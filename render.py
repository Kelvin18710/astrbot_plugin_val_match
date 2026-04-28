from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import re


TITLE_FONT = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
TEXT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
LATIN_FONT = "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"


@dataclass(slots=True)
class RenderMatch:
    day_label: str
    start_time: str
    status: str
    score: str
    team_a: str
    team_b: str
    tournament_name: str
    schedule_name: str
    level: str
    best_of: str
    logo_a_path: str | None = None
    logo_b_path: str | None = None
    event_logo_path: str | None = None
    is_placeholder: bool = False
    placeholder_text: str = ""


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    value = text
    while value:
        value = value[:-1]
        candidate = value.rstrip() + ellipsis
        if draw.textlength(candidate, font=font) <= max_width:
            return candidate
    return ellipsis


def _shorten_tournament_name(text: str) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return "-"

    patterns = (
        (
            re.compile(r"^VCT\s+\d{4}:\s*([A-Za-z]+)\s+Stage\s+(\d+)$", re.I),
            lambda m: f"VCT {m.group(1)} S{m.group(2)}",
        ),
        (
            re.compile(r"^VCT\s+\d{4}:\s*([A-Za-z]+)\s+Ascension$", re.I),
            lambda m: f"VCT {m.group(1)} Asc.",
        ),
        (
            re.compile(r"^VALORANT\s+Challengers\s+\d{4}:\s*(.+?)\s+Stage\s+(\d+)$", re.I),
            lambda m: f"Challengers {m.group(1)} S{m.group(2)}",
        ),
    )
    for pattern, formatter in patterns:
        match = pattern.match(value)
        if match:
            return formatter(match)

    value = re.sub(r"\b20\d{2}\b", "", value)
    value = value.replace("VALORANT Challengers", "Challengers")
    value = value.replace("Stage ", "S")
    value = re.sub(r"\s+", " ", value).strip(" :-")
    return value or "-"


def _status_colors(status: str) -> dict[str, tuple[int, int, int]]:
    if status == "进行中":
        return {
            "accent": (255, 122, 74),
            "pill": (106, 41, 25),
            "pill_text": (255, 232, 224),
        }
    if status == "已结束":
        return {
            "accent": (104, 140, 186),
            "pill": (34, 56, 87),
            "pill_text": (226, 237, 248),
        }
    if status == "未开始":
        return {
            "accent": (57, 212, 151),
            "pill": (14, 82, 58),
            "pill_text": (227, 255, 241),
        }
    return {
        "accent": (148, 157, 175),
        "pill": (58, 65, 78),
        "pill_text": (235, 239, 246),
    }


def _level_colors(level: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    normalized = (level or "").strip().upper()
    if normalized == "S":
        return (41, 100, 196), (236, 244, 255)
    if normalized == "A":
        return (12, 116, 127), (224, 249, 250)
    if normalized == "B":
        return (103, 85, 42), (251, 243, 219)
    return (82, 88, 103), (240, 243, 249)


def _draw_background(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    top = (10, 18, 29)
    bottom = (4, 10, 18)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)

    haze = Image.new("RGBA", image.size, (0, 0, 0, 0))
    haze_draw = ImageDraw.Draw(haze)
    haze_draw.ellipse((-200, -180, 520, 440), fill=(38, 182, 165, 60))
    haze_draw.ellipse((width - 540, -140, width + 120, 320), fill=(54, 102, 204, 52))
    haze_draw.ellipse((width - 420, height - 320, width + 80, height + 100), fill=(219, 112, 64, 34))
    haze = haze.filter(ImageFilter.GaussianBlur(64))
    image.alpha_composite(haze)


def _draw_logo_or_placeholder(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    logo_path: str | None,
    fallback_text: str,
    fill: tuple[int, int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    size = min(x1 - x0, y1 - y0)
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge)
    badge_draw.ellipse((0, 0, size - 1, size - 1), fill=fill, outline=(255, 255, 255, 24), width=2)

    if logo_path and Path(logo_path).exists():
        with Image.open(logo_path) as raw:
            logo = raw.convert("RGBA")
            logo.thumbnail((size - 14, size - 14))
            lx = (size - logo.width) // 2
            ly = (size - logo.height) // 2
            badge.alpha_composite(logo, (lx, ly))
    else:
        font = _load_font(TITLE_FONT, max(18, size // 3))
        text = (fallback_text[:2] or "?").upper()
        bbox = badge_draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        badge_draw.text(
            ((size - tw) / 2, (size - th) / 2 - 4),
            text,
            font=font,
            fill=(243, 247, 252, 255),
        )
    canvas.alpha_composite(badge, (x0, y0))


def render_match_cards_image(
    matches: list[RenderMatch],
    target_date: date,
    output_path: str | Path,
    *,
    source_name: str,
    eyebrow_text: str = "VALORANT S-TIER",
    title_text: str = "今日 S 级赛事",
) -> str:
    width = 1280
    padding = 40
    header_height = 168
    card_height = 126
    card_gap = 14
    section_gap = 28
    section_title_height = 36

    sections: list[tuple[str, list[RenderMatch]]] = []
    for match in matches:
        if sections and sections[-1][0] == match.day_label:
            sections[-1][1].append(match)
        else:
            sections.append((match.day_label, [match]))

    body_height = 0
    for section_index, (_, section_matches) in enumerate(sections):
        if section_index > 0:
            body_height += section_gap
        body_height += section_title_height
        body_height += len(section_matches) * card_height
        body_height += max(len(section_matches) - 1, 0) * card_gap
    if not sections:
        body_height = 220

    height = padding * 2 + header_height + body_height
    image = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    _draw_background(image)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(TITLE_FONT, 44)
    subtitle_font = _load_font(TEXT_FONT, 20)
    eyebrow_font = _load_font(LATIN_FONT, 17)
    section_font = _load_font(TEXT_FONT, 23)
    time_font = _load_font(LATIN_FONT, 26)
    status_font = _load_font(TEXT_FONT, 15)
    team_font = _load_font(TEXT_FONT, 21)
    score_font = _load_font(LATIN_FONT, 29)
    bo_font = _load_font(LATIN_FONT, 15)
    event_font = _load_font(TEXT_FONT, 18)
    event_sub_font = _load_font(TEXT_FONT, 16)
    level_font = _load_font(LATIN_FONT, 18)
    placeholder_font = _load_font(TEXT_FONT, 22)

    draw.text((padding, 30), eyebrow_text, font=eyebrow_font, fill=(112, 224, 207))
    draw.text((padding, 52), title_text, font=title_font, fill=(245, 248, 252))
    subtitle = f"{target_date.isoformat()}  |  {len(matches)} cards  |  source: {source_name}"
    draw.text((padding, 110), subtitle, font=subtitle_font, fill=(170, 181, 198))
    draw.line((padding, 146, width - padding, 146), fill=(255, 255, 255, 26), width=1)

    cursor_y = padding + header_height
    if not sections:
        empty_box = (padding, cursor_y, width - padding, cursor_y + 180)
        draw.rounded_rectangle(empty_box, radius=26, fill=(14, 23, 35), outline=(255, 255, 255, 20))
        draw.text((padding + 34, cursor_y + 54), "当前没有可展示的比赛", font=placeholder_font, fill=(240, 245, 252))
    else:
        for section_index, (section_label, section_matches) in enumerate(sections):
            if section_index > 0:
                cursor_y += section_gap
            draw.text((padding, cursor_y), section_label, font=section_font, fill=(228, 235, 245))
            cursor_y += section_title_height

            for match_index, match in enumerate(section_matches):
                if match_index > 0:
                    cursor_y += card_gap
                y = cursor_y
                x0, x1 = padding, width - padding
                colors = _status_colors(match.status)
                draw.rounded_rectangle((x0, y, x1, y + card_height), radius=22, fill=(18, 24, 34), outline=(255, 255, 255, 16))
                draw.rounded_rectangle((x0, y, x0 + 8, y + card_height), radius=22, fill=colors["accent"])

                if match.is_placeholder:
                    title = match.placeholder_text or "此日无关注比赛"
                    draw.text((x0 + 34, y + 22), title, font=placeholder_font, fill=(242, 246, 252))
                    message = "你可以调整关注赛事，或者把图片日期范围再放宽一些。"
                    draw.text((x0 + 34, y + 62), message, font=event_sub_font, fill=(163, 176, 195))
                    draw.rounded_rectangle((x1 - 268, y + 14, x1 - 18, y + 112), radius=18, fill=(22, 33, 49))
                    draw.line((x1 - 284, y + 22, x1 - 284, y + 104), fill=(255, 255, 255, 20), width=1)
                    draw.text((x1 - 236, y + 34), "NO MATCH", font=eyebrow_font, fill=(116, 206, 192))
                    draw.text((x1 - 236, y + 62), "Watchlist clear", font=event_sub_font, fill=(171, 183, 199))
                    cursor_y += card_height
                    continue

                time_box = (x0 + 22, y + 18, x0 + 126, y + 104)
                time_fill = tuple(min(channel + 12, 255) for channel in colors["pill"])
                draw.rounded_rectangle(time_box, radius=18, fill=time_fill, outline=colors["accent"])
                draw.text((x0 + 42, y + 28), match.start_time, font=time_font, fill=(247, 249, 252))
                status_box = (x0 + 34, y + 70, x0 + 114, y + 94)
                draw.rounded_rectangle(status_box, radius=11, fill=colors["pill"])
                bbox = draw.textbbox((0, 0), match.status, font=status_font)
                draw.text(
                    (status_box[0] + (status_box[2] - status_box[0] - (bbox[2] - bbox[0])) / 2, status_box[1] + 3),
                    match.status,
                    font=status_font,
                    fill=colors["pill_text"],
                )

                left_logo_box = (x0 + 160, y + 32, x0 + 216, y + 88)
                right_logo_box = (x0 + 608, y + 32, x0 + 664, y + 88)
                _draw_logo_or_placeholder(image, left_logo_box, match.logo_a_path, match.team_a, (18, 72, 85, 255))
                _draw_logo_or_placeholder(image, right_logo_box, match.logo_b_path, match.team_b, (78, 44, 39, 255))

                left_team_x = left_logo_box[2] + 16
                left_team_name = _fit_text(draw, match.team_a, team_font, 214)
                right_team_name = _fit_text(draw, match.team_b, team_font, 182)
                left_bbox = draw.textbbox((0, 0), left_team_name, font=team_font)
                right_bbox = draw.textbbox((0, 0), right_team_name, font=team_font)
                left_y = y + 62 - ((left_bbox[3] - left_bbox[1]) / 2)
                right_y = y + 62 - ((right_bbox[3] - right_bbox[1]) / 2)
                draw.text((left_team_x, left_y), left_team_name, font=team_font, fill=(243, 246, 252))
                draw.text((x0 + 680, right_y), right_team_name, font=team_font, fill=(243, 246, 252))

                score_box = (x0 + 442, y + 22, x0 + 588, y + 74)
                draw.rounded_rectangle(score_box, radius=18, fill=(31, 44, 61), outline=colors["accent"])
                score_text = match.score if match.score != "-" else "VS"
                score_w = draw.textlength(score_text, font=score_font)
                draw.text((score_box[0] + (score_box[2] - score_box[0] - score_w) / 2, y + 31), score_text, font=score_font, fill=(246, 249, 252))
                bo_text = match.best_of.upper() if match.best_of else "BO?"
                bo_w = draw.textlength(bo_text, font=bo_font)
                draw.text((score_box[0] + (score_box[2] - score_box[0] - bo_w) / 2, y + 86), bo_text, font=bo_font, fill=(172, 185, 203))

                separator_x = x1 - 300
                draw.line((separator_x, y + 18, separator_x, y + card_height - 18), fill=(255, 255, 255, 18), width=1)
                event_panel = (x1 - 286, y + 14, x1 - 18, y + card_height - 14)
                draw.rounded_rectangle(event_panel, radius=18, fill=(24, 34, 50))
                accent, accent_text = _level_colors(match.level)
                draw.polygon(
                    [
                        (event_panel[2] - 46, event_panel[1]),
                        (event_panel[2], event_panel[1]),
                        (event_panel[2], event_panel[3]),
                        (event_panel[2] - 30, event_panel[3]),
                    ],
                    fill=accent,
                )
                level_text = (match.level or "?").upper()[:1]
                level_bbox = draw.textbbox((0, 0), level_text, font=level_font)
                level_x = event_panel[2] - 24 - (level_bbox[2] - level_bbox[0]) / 2
                draw.text((level_x, y + 48), level_text, font=level_font, fill=accent_text)

                event_logo_box = (event_panel[0] + 16, y + 34, event_panel[0] + 56, y + 74)
                _draw_logo_or_placeholder(image, event_logo_box, match.event_logo_path, match.level or "EV", (26, 50, 73, 255))
                event_name = _fit_text(draw, _shorten_tournament_name(match.tournament_name), event_font, 158)
                schedule_name = _fit_text(draw, match.schedule_name or "-", event_sub_font, 158)
                draw.text((event_logo_box[2] + 14, y + 28), event_name, font=event_font, fill=(245, 247, 251))
                draw.text((event_logo_box[2] + 14, y + 58), schedule_name, font=event_sub_font, fill=(176, 188, 205))

                cursor_y += card_height

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return str(output)
