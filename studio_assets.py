"""Theme-aware transparent logos; portraits and flags deliberately bypass this."""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def _luminance(rgb):
    values = [v / 255 for v in rgb]
    linear = [
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _remove_edge_matte(image):
    """Remove only a neutral, uniform, opaque background connected to the edges."""
    if image.getchannel("A").getextrema()[0] < 240:
        return image
    corners = [
        (0, 0),
        (image.width - 1, 0),
        (0, image.height - 1),
        (image.width - 1, image.height - 1),
    ]
    colors = [image.getpixel(p)[:3] for p in corners]
    base = colors[0]
    if max(base) - min(base) > 12 or not (max(base) < 30 or min(base) > 225):
        return image
    if any(max(abs(a - b) for a, b in zip(base, color)) > 12 for color in colors):
        return image
    candidate = image.copy()
    for corner in corners:
        if candidate.getpixel(corner)[3]:
            ImageDraw.floodfill(candidate, corner, (0, 0, 0, 0), thresh=40)
    # Avoid replacing an almost entirely blank or entirely solid asset.
    visible = sum(alpha > 64 for alpha in candidate.getchannel("A").getdata())
    if 0.01 < visible / (candidate.width * candidate.height) < 0.95:
        return candidate
    return image


@lru_cache(maxsize=128)
def _prepared_logo(path, modified, size, light, name):
    with Image.open(path) as source:
        image = source.convert("RGBA")
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    image = _remove_edge_matte(image)
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        raise ValueError("empty logo")
    image = image.crop(bbox)
    pixels = [pixel[:3] for pixel in image.getdata() if pixel[3] > 128]
    if not pixels:
        raise ValueError("empty logo")
    neutral = sum(max(pixel) - min(pixel) < 24 for pixel in pixels) / len(pixels) > 0.95
    background = _luminance((252, 252, 247) if light else (27, 35, 32))
    low_contrast_fraction = sum(
        (max(_luminance(pixel), background) + 0.05)
        / (min(_luminance(pixel), background) + 0.05)
        < 2.8
        for pixel in pixels
    ) / len(pixels)
    low_contrast = low_contrast_fraction > (0.55 if neutral else 0.25)
    if low_contrast and neutral:
        # Vitality supplies a monochrome bee: use its familiar yellow on dark surfaces.
        normalized = "".join(ch for ch in name.casefold() if ch.isalnum())
        color = (
            "#FFE234"
            if not light and normalized in {"teamvitality", "vitality", "vit"}
            else "#17201B"
            if light
            else "#F0F3E9"
        )
        dark_fraction = sum(_luminance(pixel) < 0.04 for pixel in pixels) / len(pixels)
        bright_fraction = sum(_luminance(pixel) > 0.65 for pixel in pixels) / len(
            pixels
        )
        alpha = image.getchannel("A")
        if dark_fraction > 0.08 and bright_fraction > 0.08:
            # Badges such as EDG contain lettering inside the mark. Invert both tones
            # together so adapting contrast never fills in their internal detail.
            image = ImageOps.invert(image.convert("RGB")).convert("RGBA")
        else:
            image = Image.new("RGBA", image.size, color)
        image.putalpha(alpha)
    image.thumbnail((round(size * 1.88), round(size * 1.88)), Image.Resampling.LANCZOS)
    if low_contrast and not neutral:
        # Preserve colored marks and add only a fine silhouette, never a rectangular plate.
        image = ImageOps.expand(image, border=2, fill=(0, 0, 0, 0))
        alpha = image.getchannel("A")
        edge = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(5)), alpha)
        edge = edge.point(lambda value: round(value * 0.65))
        outline = Image.new("RGBA", image.size, "#17201B" if light else "#F0F3E9")
        outline.putalpha(edge)
        image = Image.alpha_composite(outline, image)
    return image


def prepared_logo(path, size, light, name):
    path = Path(path)
    return _prepared_logo(str(path), path.stat().st_mtime_ns, size, light, name).copy()
