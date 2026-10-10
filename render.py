from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)

TITLE_FONT = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
TEXT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
LATIN_FONT = "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"
BROADCAST_FONT = "/usr/share/fonts/truetype/roboto/unhinted/RobotoCondensed-Regular.ttf"
BROADCAST_BOLD_FONT = (
    "/usr/share/fonts/truetype/roboto/unhinted/RobotoCondensed-Bold.ttf"
)
CJK_BOLD_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
MAP_LATIN_BOLD_FONT = "/usr/share/fonts/opentype/inter/InterDisplay-ExtraBold.otf"
MAP_LATIN_BLACK_FONT = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
MAP_CJK_MEDIUM_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
MAP_CJK_BLACK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
STAGE_BACKDROP_PATH = (
    Path(__file__).resolve().parent / "assets" / "vct_stage_backdrop.jpg"
)

AGENT_NAMES_ZH = {
    "astra": "星礈",
    "breach": "铁臂",
    "brimstone": "炼狱",
    "chamber": "钱博尔",
    "clove": "暮蝶",
    "cypher": "零",
    "deadlock": "钢锁",
    "fade": "黑梦",
    "gekko": "盖可",
    "harbor": "海神",
    "iso": "壹决",
    "jett": "捷风",
    "kayo": "K/O",
    "killjoy": "奇乐",
    "neon": "霓虹",
    "omen": "幽影",
    "phoenix": "不死鸟",
    "raze": "雷兹",
    "reyna": "芮娜",
    "sage": "贤者",
    "skye": "斯凯",
    "sova": "猎枭",
    "tejo": "钛狐",
    "viper": "蝰蛇",
    "vyse": "维斯",
    "waylay": "幻棱",
    "yoru": "夜露",
}


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


@dataclass(slots=True)
class RenderMapScore:
    map_name: str
    team_a_score: str
    team_b_score: str
    duration: str = ""
    pick: str = ""
    image_path: str | None = None


@dataclass(slots=True)
class RenderPlayerStat:
    player: str
    team: str
    agents: list[str]
    kills: str
    deaths: str
    assists: str
    acs: str = ""
    adr: str = ""
    rating: str = ""
    country_code: str = ""
    country_name: str = ""
    country_flag_path: str | None = None
    avatar_path: str | None = None
    agent_image_paths: list[str] | None = None
    kast: str = ""
    headshot_percent: str = ""
    first_kills: str = ""
    first_deaths: str = ""
    kd_diff: str = ""
    fk_diff: str = ""
    stats_available: bool = True
    agent_full_portrait_path: str | None = None


@dataclass(slots=True)
class RenderMatchReport:
    team_a: str
    team_b: str
    score: str
    tournament_name: str
    schedule_name: str
    best_of: str
    maps: list[RenderMapScore]
    players: list[RenderPlayerStat]
    comment: str
    team_a_logo_path: str | None = None
    team_b_logo_path: str | None = None
    event_logo_path: str | None = None


@dataclass(slots=True)
class RenderSingleMapResult:
    map_number: int
    map_name: str
    team_a: str
    team_b: str
    team_a_score: str
    team_b_score: str
    tournament_name: str
    schedule_name: str
    players: list[RenderPlayerStat]
    team_a_logo_path: str | None = None
    team_b_logo_path: str | None = None
    event_logo_path: str | None = None
    map_image_path: str | None = None


@dataclass(slots=True)
class RenderHeadToHead:
    date_label: str
    score: str
    event_name: str


@dataclass(slots=True)
class RenderStartNotice:
    start_time: str
    team_a: str
    team_b: str
    tournament_name: str
    schedule_name: str
    best_of: str
    betting_info: str
    head_to_head: list[RenderHeadToHead]
    team_a_odds: str = ""
    team_b_odds: str = ""
    team_a_logo_path: str | None = None
    team_b_logo_path: str | None = None
    event_logo_path: str | None = None


def _single_map_player_rank_key(player: RenderPlayerStat) -> tuple[int, float, int]:
    rating = 0.0
    acs = 0
    diff = 0
    with contextlib.suppress(ValueError, TypeError):
        rating = float(str(player.rating or "0").replace("%", ""))
    with contextlib.suppress(ValueError, TypeError):
        acs = int(float(str(player.acs or "0")))
    with contextlib.suppress(ValueError, TypeError):
        diff = int(player.kills or 0) - int(player.deaths or 0)
    return acs, rating, diff


@dataclass(slots=True)
class RenderStandingRow:
    team: str
    record: str
    maps: str
    rounds: str
    round_diff: str
    logo_path: str | None = None
    position_state: str = "neutral"


@dataclass(slots=True)
class RenderStandingGroup:
    name: str
    rows: list[RenderStandingRow]


@dataclass(slots=True)
class RenderBracketMatch:
    team_a: str
    team_b: str
    score_a: str
    score_b: str
    logo_a_path: str | None = None
    logo_b_path: str | None = None
    winner: int = 0
    status: str = ""


@dataclass(slots=True)
class RenderBracketRound:
    name: str
    matches: list[RenderBracketMatch]


@dataclass(slots=True)
class RenderBracketSection:
    name: str
    rounds: list[RenderBracketRound]


@dataclass(slots=True)
class RenderTournamentProgress:
    event_name: str
    stage_name: str
    kind: str
    groups: list[RenderStandingGroup]
    brackets: list[RenderBracketSection]
    event_logo_path: str | None = None


@dataclass(frozen=True, slots=True)
class RenderTheme:
    name: str
    bg_top: tuple[int, int, int]
    bg_bottom: tuple[int, int, int]
    haze: tuple[
        tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int]
    ]
    page_base: tuple[int, int, int, int]
    panel: tuple[int, int, int, int]
    panel_alt: tuple[int, int, int, int]
    panel_soft: tuple[int, int, int, int]
    border: tuple[int, int, int, int]
    text: tuple[int, int, int]
    text_muted: tuple[int, int, int]
    text_soft: tuple[int, int, int]
    accent: tuple[int, int, int]
    accent_2: tuple[int, int, int]
    score_box: tuple[int, int, int, int]
    metric_box: tuple[int, int, int, int]
    overlay: tuple[int, int, int, int]


THEMES: dict[str, RenderTheme] = {
    "premium_dark": RenderTheme(
        name="premium_dark",
        bg_top=(10, 10, 11),
        bg_bottom=(10, 10, 11),
        haze=((0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)),
        page_base=(10, 10, 11, 255),
        panel=(17, 17, 19, 255),
        panel_alt=(22, 22, 24, 255),
        panel_soft=(29, 29, 32, 255),
        border=(255, 255, 255, 32),
        text=(247, 247, 244),
        text_muted=(155, 155, 158),
        text_soft=(211, 211, 208),
        accent=(255, 70, 85),
        accent_2=(218, 48, 63),
        score_box=(8, 8, 9, 255),
        metric_box=(34, 34, 37, 255),
        overlay=(0, 0, 0, 96),
    ),
    "premium_light": RenderTheme(
        name="premium_light",
        bg_top=(245, 246, 248),
        bg_bottom=(245, 246, 248),
        haze=((0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)),
        page_base=(245, 246, 248, 255),
        panel=(255, 255, 255, 255),
        panel_alt=(255, 255, 255, 255),
        panel_soft=(237, 239, 242, 255),
        border=(18, 20, 24, 35),
        text=(15, 16, 18),
        text_muted=(105, 108, 114),
        text_soft=(58, 61, 66),
        accent=(222, 45, 61),
        accent_2=(197, 28, 45),
        score_box=(232, 234, 238, 255),
        metric_box=(238, 240, 243, 255),
        overlay=(255, 255, 255, 70),
    ),
    "dark": RenderTheme(
        name="dark",
        bg_top=(10, 18, 29),
        bg_bottom=(4, 10, 18),
        haze=((38, 182, 165, 60), (54, 102, 204, 52), (219, 112, 64, 34)),
        page_base=(4, 10, 18, 255),
        panel=(15, 19, 27, 220),
        panel_alt=(18, 24, 34, 255),
        panel_soft=(24, 34, 50, 238),
        border=(255, 255, 255, 18),
        text=(246, 249, 253),
        text_muted=(168, 181, 198),
        text_soft=(223, 233, 248),
        accent=(116, 225, 210),
        accent_2=(49, 94, 180),
        score_box=(37, 47, 66, 255),
        metric_box=(26, 28, 34, 255),
        overlay=(0, 0, 0, 84),
    ),
    "light": RenderTheme(
        name="light",
        bg_top=(249, 251, 255),
        bg_bottom=(232, 238, 247),
        haze=((43, 179, 165, 30), (68, 111, 211, 24), (226, 97, 80, 18)),
        page_base=(238, 243, 250, 255),
        panel=(255, 255, 255, 232),
        panel_alt=(255, 255, 255, 248),
        panel_soft=(246, 249, 253, 244),
        border=(24, 39, 64, 24),
        text=(18, 28, 45),
        text_muted=(91, 105, 128),
        text_soft=(68, 82, 105),
        accent=(0, 137, 127),
        accent_2=(47, 101, 201),
        score_box=(239, 244, 251, 255),
        metric_box=(235, 240, 248, 255),
        overlay=(255, 255, 255, 70),
    ),
}


def _resolve_theme(theme: str = "premium_dark") -> RenderTheme:
    value = str(theme or "premium_dark").strip().casefold()
    # Studio does not restyle the optional single-map card.
    value = {"studio_dark": "premium_dark", "studio_light": "premium_light"}.get(
        value, value
    )
    return THEMES.get(value, THEMES["premium_dark"])


def _load_font(
    path: str, size: int, *, index: int = 0
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size, index=index)
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


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    *,
    y_offset: int = 0,
) -> None:
    value = str(text or "")
    bbox = draw.textbbox((0, 0), value, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x0, y0, x1, y1 = box
    draw.text(
        (
            x0 + (x1 - x0 - text_width) / 2 - bbox[0],
            y0 + (y1 - y0 - text_height) / 2 - bbox[1] + y_offset,
        ),
        value,
        font=font,
        fill=fill,
    )


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and draw.textlength(lines[-1], font=font) > max_width:
        lines[-1] = _fit_text(draw, lines[-1], font, max_width)
    return lines


def _shorten_tournament_name(text: str) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return "-"

    patterns = (
        (
            re.compile(r"^Valorant\s+Masters\s+(.+?)\s+20\d{2}$", re.I),
            lambda m: f"Masters {m.group(1)}",
        ),
        (
            re.compile(r"^VCT\s+\d{4}:\s*([A-Za-z]+)\s+Stage\s+(\d+)$", re.I),
            lambda m: f"VCT {m.group(1)} S{m.group(2)}",
        ),
        (
            re.compile(r"^VCT\s+\d{4}:\s*([A-Za-z]+)\s+Ascension$", re.I),
            lambda m: f"VCT {m.group(1)} Asc.",
        ),
        (
            re.compile(
                r"^VALORANT\s+Challengers\s+\d{4}:\s*(.+?)\s+Stage\s+(\d+)$", re.I
            ),
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


def _shorten_team_display_name(text: str) -> str:
    value = " ".join(str(text or "").split())
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", value)
    if not match:
        return value
    prefix = match.group(1).strip()
    parenthetical = match.group(2).strip()
    normalized_prefix = re.sub(r"[^a-z0-9]", "", prefix.casefold())
    normalized_parenthetical = re.sub(r"[^a-z0-9]", "", parenthetical.casefold())
    if normalized_parenthetical and normalized_parenthetical in normalized_prefix:
        return prefix
    return value


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


def _draw_background(image: Image.Image, theme: RenderTheme | None = None) -> None:
    theme = theme or THEMES["dark"]
    draw = ImageDraw.Draw(image)
    width, height = image.size
    if theme.name.startswith("premium_"):
        draw.rectangle((0, 0, width, height), fill=theme.bg_top)
        grid = (255, 255, 255, 9) if theme.name == "premium_dark" else (16, 18, 22, 8)
        for x in range(40, width, 80):
            draw.line((x, 0, x, height), fill=grid, width=1)
        return
    top = theme.bg_top
    bottom = theme.bg_bottom
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)

    haze = Image.new("RGBA", image.size, (0, 0, 0, 0))
    haze_draw = ImageDraw.Draw(haze)
    haze_draw.ellipse((-200, -180, 520, 440), fill=theme.haze[0])
    haze_draw.ellipse((width - 540, -140, width + 120, 320), fill=theme.haze[1])
    haze_draw.ellipse(
        (width - 420, height - 320, width + 80, height + 100), fill=theme.haze[2]
    )
    haze = haze.filter(ImageFilter.GaussianBlur(64))
    image.alpha_composite(haze)


def _save_opaque_png(
    image: Image.Image, output: Path, theme: RenderTheme | None = None
) -> None:
    theme = theme or THEMES["dark"]
    base = Image.new("RGBA", image.size, theme.page_base)
    base.alpha_composite(image)
    base.convert("RGB").save(output, format="PNG", optimize=True)


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
    badge_draw.ellipse(
        (0, 0, size - 1, size - 1), fill=fill, outline=(255, 255, 255, 24), width=2
    )

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


def _draw_logo_badge(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    logo_path: str | None,
    fallback_text: str,
    *,
    radius: int = 999,
    background: tuple[int, int, int, int] = (255, 255, 255, 255),
    outline: tuple[int, int, int, int] = (27, 38, 59, 28),
) -> None:
    x0, y0, x1, y1 = [int(value) for value in box]
    width = max(x1 - x0, 1)
    height = max(y1 - y0, 1)
    tile = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=radius,
        fill=background,
        outline=outline,
        width=1,
    )
    loaded = False
    if logo_path and Path(logo_path).exists():
        try:
            with Image.open(logo_path) as raw:
                logo = raw.convert("RGBA")
                inset = max(2, min(width, height) // 12)
                logo.thumbnail(
                    (width - inset * 2, height - inset * 2), Image.Resampling.LANCZOS
                )
                tile.alpha_composite(
                    logo, ((width - logo.width) // 2, (height - logo.height) // 2)
                )
                loaded = True
        except OSError:
            loaded = False
    if not loaded:
        font = _load_font(TITLE_FONT, max(16, min(width, height) // 3))
        text = (fallback_text[:2] or "?").upper()
        _draw_centered_text(draw, (0, 0, width, height), text, font, (34, 48, 72))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=radius, fill=255
    )
    tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask))
    canvas.alpha_composite(tile, (x0, y0))


def _draw_right_text(
    draw: ImageDraw.ImageDraw,
    right_x: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    value = str(text or "")
    draw.text(
        (right_x - draw.textlength(value, font=font), y), value, font=font, fill=fill
    )


def _parse_decimal(value: str) -> float | None:
    with contextlib.suppress(Exception):
        number = float(str(value or "").strip())
        if number > 1:
            return number
    return None


def _odds_probabilities(left_odds: str, right_odds: str) -> tuple[float, float] | None:
    left = _parse_decimal(left_odds)
    right = _parse_decimal(right_odds)
    if left and right:
        left_implied = 1 / left
        right_implied = 1 / right
        total = left_implied + right_implied
        if total > 0:
            return left_implied / total, right_implied / total
    if left:
        left_prob = max(0.08, min(0.92, 1 / left))
        return left_prob, 1 - left_prob
    if right:
        right_prob = max(0.08, min(0.92, 1 / right))
        return 1 - right_prob, right_prob
    return None


def _draw_odds_bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    left_prob: float,
    right_prob: float,
    *,
    radius: int = 12,
) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    left_w = int(width * max(0.04, min(0.96, left_prob)))
    draw.rounded_rectangle(box, radius=radius, fill=(205, 68, 83, 255))
    draw.rounded_rectangle(
        (x0, y0, x0 + left_w, y1), radius=radius, fill=(48, 105, 214, 255)
    )
    draw.line(
        (x0 + left_w, y0 + 2, x0 + left_w, y1 - 2), fill=(255, 255, 255, 170), width=2
    )


def _draw_image_cover(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    image_path: str | None,
    *,
    radius: int = 0,
    fallback_fill: tuple[int, int, int, int] = (20, 27, 39, 255),
) -> bool:
    x0, y0, x1, y1 = [int(value) for value in box]
    width = max(x1 - x0, 1)
    height = max(y1 - y0, 1)
    tile = Image.new("RGBA", (width, height), fallback_fill)
    loaded = False
    if image_path and Path(image_path).exists():
        try:
            with Image.open(image_path) as raw:
                source = raw.convert("RGBA")
                scale = max(
                    width / max(source.width, 1), height / max(source.height, 1)
                )
                resized = source.resize(
                    (
                        max(int(source.width * scale), 1),
                        max(int(source.height * scale), 1),
                    ),
                    Image.Resampling.LANCZOS,
                )
                left = (resized.width - width) // 2
                top = (resized.height - height) // 2
                tile = resized.crop((left, top, left + width, top + height))
                loaded = True
        except OSError:
            loaded = False
    if radius > 0:
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=radius, fill=255
        )
        tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask))
        canvas.alpha_composite(tile, (x0, y0))
    else:
        canvas.alpha_composite(tile, (x0, y0))
    return loaded


def _draw_image_contain(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    image_path: str | None,
    *,
    radius: int = 0,
    background: tuple[int, int, int, int] = (18, 24, 34, 255),
) -> bool:
    x0, y0, x1, y1 = [int(value) for value in box]
    width = max(x1 - x0, 1)
    height = max(y1 - y0, 1)
    tile = Image.new("RGBA", (width, height), background)
    loaded = False
    if image_path and Path(image_path).exists():
        try:
            with Image.open(image_path) as raw:
                source = raw.convert("RGBA")
                source.thumbnail((width - 4, height - 4), Image.Resampling.LANCZOS)
                left = (width - source.width) // 2
                top = (height - source.height) // 2
                tile.alpha_composite(source, (left, top))
                loaded = True
        except OSError:
            loaded = False
    if radius > 0:
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=radius, fill=255
        )
        tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask))
        canvas.alpha_composite(tile, (x0, y0))
    else:
        canvas.alpha_composite(tile, (x0, y0))
    return loaded


def _draw_avatar_or_initials(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    image_path: str | None,
    fallback_text: str,
    *,
    background: tuple[int, int, int, int] = (38, 44, 54, 255),
    text_fill: tuple[int, int, int] = (232, 238, 247),
) -> None:
    loaded = _draw_image_cover(
        canvas, box, image_path, radius=999, fallback_fill=background
    )
    if loaded:
        return
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = box
    size = min(x1 - x0, y1 - y0)
    font = _load_font(LATIN_FONT, max(18, size // 3))
    text = (fallback_text[:2] or "?").upper()
    _draw_centered_text(draw, (x0, y0, x1, y1), text, font, text_fill)


def _draw_metric_box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill: tuple[int, int, int, int] = (26, 28, 34, 255),
    text_fill: tuple[int, int, int] = (244, 247, 252),
    radius: int = 7,
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=fill)
    value = str(text or "-")
    _draw_centered_text(draw, (x, y, x + width, y + height), value, font, text_fill)


def _asset_background(palette: RenderTheme) -> tuple[int, int, int, int]:
    return (0, 0, 0, 0)


def _logo_background(palette: RenderTheme) -> tuple[int, int, int, int]:
    if palette.name == "premium_dark":
        return (70, 70, 74, 245)
    if palette.name == "dark":
        return (248, 250, 253, 245)
    return (255, 255, 255, 245)


def _logo_outline(palette: RenderTheme) -> tuple[int, int, int, int]:
    if palette.name in {"dark", "premium_dark"}:
        return (255, 255, 255, 46)
    return (27, 38, 59, 20)


def _asset_outline(palette: RenderTheme) -> tuple[int, int, int, int]:
    if palette.name == "dark":
        return (255, 255, 255, 34)
    return (27, 38, 59, 24)


def _signed_color(value: str, neutral: tuple[int, int, int]) -> tuple[int, int, int]:
    text = str(value or "").strip()
    if text.startswith("+"):
        return (79, 218, 127)
    if text.startswith("-"):
        return (255, 91, 94)
    return neutral


def _render_premium_match_cards_image(
    matches: list[RenderMatch],
    target_date: date,
    output_path: str | Path,
    *,
    source_name: str,
    eyebrow_text: str,
    title_text: str,
    palette: RenderTheme,
) -> str:
    width = 1280
    padding = 40
    header_height = 176
    section_header = 52
    card_height = 154
    card_gap = 10
    section_gap = 26
    sections: list[tuple[str, list[RenderMatch]]] = []
    for match in matches:
        if sections and sections[-1][0] == match.day_label:
            sections[-1][1].append(match)
        else:
            sections.append((match.day_label, [match]))
    body_height = 0
    for index, (_, items) in enumerate(sections):
        body_height += (
            section_header
            + len(items) * card_height
            + max(len(items) - 1, 0) * card_gap
        )
        if index:
            body_height += section_gap
    height = padding * 2 + header_height + max(body_height, 220)
    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    draw = ImageDraw.Draw(image)

    eyebrow_font = _load_font(LATIN_FONT, 16)
    title_font = _load_font(TITLE_FONT, 48)
    meta_font = _load_font(TEXT_FONT, 16)
    date_font = _load_font(LATIN_FONT, 34)
    section_font = _load_font(TEXT_FONT, 22)
    index_font = _load_font(LATIN_FONT, 16)
    time_font = _load_font(LATIN_FONT, 32)
    status_font = _load_font(TEXT_FONT, 15)
    team_font = _load_font(TEXT_FONT, 23)
    score_font = _load_font(LATIN_FONT, 28)
    event_font = _load_font(TEXT_FONT, 17)
    small_font = _load_font(TEXT_FONT, 14)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    draw.rectangle((padding, 32, padding + 7, 120), fill=palette.accent)
    draw.text((padding + 24, 30), eyebrow_text, font=eyebrow_font, fill=palette.accent)
    draw.text((padding + 24, 55), title_text, font=title_font, fill=palette.text)
    source_line = f"{len([m for m in matches if not m.is_placeholder])} MATCHES   /   {source_name.upper()}"
    draw.text((padding + 25, 122), source_line, font=meta_font, fill=palette.text_muted)
    date_box = (width - padding - 264, 30, width - padding, 130)
    date_fill = palette.accent if palette.name == "premium_dark" else palette.text
    draw.rectangle(date_box, fill=(*date_fill, 255))
    _draw_centered_text(
        draw,
        (date_box[0], date_box[1] + 6, date_box[2], date_box[1] + 62),
        target_date.strftime("%m.%d"),
        date_font,
        (255, 255, 255),
    )
    _draw_centered_text(
        draw,
        (date_box[0], date_box[1] + 64, date_box[2], date_box[3] - 6),
        target_date.strftime("%Y / %A").upper(),
        eyebrow_font,
        (255, 255, 255),
    )
    draw.line((padding, 153, width - padding, 153), fill=palette.border, width=2)

    cursor_y = padding + header_height
    for section_index, (label, items) in enumerate(sections):
        if section_index:
            cursor_y += section_gap
        draw.text(
            (padding, cursor_y + 8),
            f"0{section_index + 1}"[-2:],
            font=index_font,
            fill=palette.accent,
        )
        draw.text(
            (padding + 42, cursor_y + 4), label, font=section_font, fill=palette.text
        )
        draw.line(
            (padding + 370, cursor_y + 23, width - padding, cursor_y + 23),
            fill=palette.border,
            width=1,
        )
        cursor_y += section_header
        for match_index, match in enumerate(items):
            if match_index:
                cursor_y += card_gap
            y = cursor_y
            x0, x1 = padding, width - padding
            draw.rectangle(
                (x0, y, x1, y + card_height),
                fill=palette.panel_alt,
                outline=palette.border,
                width=1,
            )
            colors = _status_colors(match.status)
            accent = (
                palette.accent
                if match.status in {"进行中", "未开始"}
                else colors["accent"]
            )
            draw.rectangle((x0, y, x0 + 5, y + card_height), fill=accent)
            if match.is_placeholder:
                draw.text(
                    (x0 + 30, y + 42),
                    match.placeholder_text or "此日无关注比赛",
                    font=team_font,
                    fill=palette.text,
                )
                draw.text(
                    (x0 + 30, y + 82),
                    "NO SCHEDULED MATCHES",
                    font=eyebrow_font,
                    fill=palette.text_muted,
                )
                cursor_y += card_height
                continue

            time_right = x0 + 170
            draw.text(
                (x0 + 30, y + 34),
                match.start_time or "--:--",
                font=time_font,
                fill=palette.text,
            )
            draw.text((x0 + 31, y + 83), match.status, font=status_font, fill=accent)
            draw.line(
                (time_right, y + 22, time_right, y + card_height - 22),
                fill=palette.border,
                width=1,
            )

            team_x = time_right + 30
            score_x = x0 + 760
            for row_index, (team, logo, score) in enumerate(
                (
                    (match.team_a, match.logo_a_path, ""),
                    (match.team_b, match.logo_b_path, ""),
                )
            ):
                row_y = y + 28 + row_index * 62
                logo_box = (team_x, row_y - 4, team_x + 52, row_y + 48)
                _draw_logo_badge(
                    image,
                    logo_box,
                    logo,
                    team,
                    radius=8,
                    background=logo_bg,
                    outline=logo_outline,
                )
                draw.text(
                    (team_x + 68, row_y + 7),
                    _fit_text(draw, team, team_font, 352),
                    font=team_font,
                    fill=palette.text,
                )
            score_values = [
                part.strip()
                for part in str(match.score or "").replace(":", "-").split("-")
            ]
            if len(score_values) == 2 and all(value for value in score_values):
                left_score, right_score = score_values
            else:
                left_score, right_score = ("-", "-")
            draw.text((score_x, y + 31), left_score, font=score_font, fill=palette.text)
            draw.text(
                (score_x, y + 93), right_score, font=score_font, fill=palette.text
            )
            draw.line(
                (score_x - 18, y + 76, score_x + 36, y + 76),
                fill=palette.border,
                width=1,
            )

            event_x = x0 + 850
            draw.line(
                (event_x - 22, y + 22, event_x - 22, y + card_height - 22),
                fill=palette.border,
                width=1,
            )
            event_logo_box = (event_x, y + 28, event_x + 48, y + 76)
            _draw_logo_badge(
                image,
                event_logo_box,
                match.event_logo_path,
                match.level or "V",
                radius=7,
                background=logo_bg,
                outline=logo_outline,
            )
            event_name = _fit_text(
                draw, _shorten_tournament_name(match.tournament_name), event_font, 260
            )
            draw.text(
                (event_x + 64, y + 27), event_name, font=event_font, fill=palette.text
            )
            draw.text(
                (event_x + 64, y + 57),
                _fit_text(draw, match.schedule_name or "Main Event", small_font, 250),
                font=small_font,
                fill=palette.text_muted,
            )
            meta = f"{(match.best_of or 'BO?').upper()}   /   {(match.level or '?').upper()} TIER"
            draw.text((event_x, y + 104), meta, font=eyebrow_font, fill=palette.accent)
            cursor_y += card_height

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def render_match_cards_image(
    matches: list[RenderMatch],
    target_date: date,
    output_path: str | Path,
    *,
    source_name: str,
    eyebrow_text: str = "VALORANT S-TIER",
    title_text: str = "今日 S 级赛事",
    theme: str = "dark",
) -> str:
    if str(theme).strip().casefold() in {"studio_dark", "studio_light"}:
        try:
            from .studio_render import schedule as draw_studio
        except ImportError:
            from studio_render import schedule as draw_studio
        return draw_studio(
            matches,
            target_date,
            output_path,
            source_name=source_name,
            eyebrow_text=eyebrow_text,
            title_text=title_text,
            theme=theme,
        )
    palette = _resolve_theme(theme)
    if palette.name.startswith("premium_"):
        return _render_premium_match_cards_image(
            matches,
            target_date,
            output_path,
            source_name=source_name,
            eyebrow_text=eyebrow_text,
            title_text=title_text,
            palette=palette,
        )
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
    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
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
    _asset_background(palette)
    _asset_outline(palette)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    draw.text((padding, 30), eyebrow_text, font=eyebrow_font, fill=palette.accent)
    draw.text((padding, 52), title_text, font=title_font, fill=palette.text)
    subtitle = (
        f"{target_date.isoformat()}  |  {len(matches)} cards  |  source: {source_name}"
    )
    draw.text((padding, 110), subtitle, font=subtitle_font, fill=palette.text_muted)
    draw.line((padding, 146, width - padding, 146), fill=palette.border, width=1)

    cursor_y = padding + header_height
    if not sections:
        empty_box = (padding, cursor_y, width - padding, cursor_y + 180)
        draw.rounded_rectangle(
            empty_box, radius=26, fill=palette.panel_alt, outline=palette.border
        )
        draw.text(
            (padding + 34, cursor_y + 54),
            "当前没有可展示的比赛",
            font=placeholder_font,
            fill=palette.text,
        )
    else:
        for section_index, (section_label, section_matches) in enumerate(sections):
            if section_index > 0:
                cursor_y += section_gap
            draw.text(
                (padding, cursor_y),
                section_label,
                font=section_font,
                fill=palette.text_soft,
            )
            cursor_y += section_title_height

            for match_index, match in enumerate(section_matches):
                if match_index > 0:
                    cursor_y += card_gap
                y = cursor_y
                x0, x1 = padding, width - padding
                colors = _status_colors(match.status)
                draw.rounded_rectangle(
                    (x0, y, x1, y + card_height),
                    radius=22,
                    fill=palette.panel_alt,
                    outline=palette.border,
                )
                draw.rounded_rectangle(
                    (x0, y, x0 + 8, y + card_height), radius=22, fill=colors["accent"]
                )

                if match.is_placeholder:
                    title = match.placeholder_text or "此日无关注比赛"
                    draw.text(
                        (x0 + 34, y + 22),
                        title,
                        font=placeholder_font,
                        fill=palette.text,
                    )
                    message = "你可以调整关注赛事，或者把图片日期范围再放宽一些。"
                    draw.text(
                        (x0 + 34, y + 62),
                        message,
                        font=event_sub_font,
                        fill=palette.text_muted,
                    )
                    draw.rounded_rectangle(
                        (x1 - 268, y + 14, x1 - 18, y + 112),
                        radius=18,
                        fill=palette.panel_soft,
                    )
                    draw.line(
                        (x1 - 284, y + 22, x1 - 284, y + 104),
                        fill=palette.border,
                        width=1,
                    )
                    draw.text(
                        (x1 - 236, y + 34),
                        "NO MATCH",
                        font=eyebrow_font,
                        fill=palette.accent,
                    )
                    draw.text(
                        (x1 - 236, y + 62),
                        "Watchlist clear",
                        font=event_sub_font,
                        fill=palette.text_muted,
                    )
                    cursor_y += card_height
                    continue

                time_box = (x0 + 22, y + 18, x0 + 126, y + 104)
                time_fill = tuple(min(channel + 12, 255) for channel in colors["pill"])
                draw.rounded_rectangle(
                    time_box, radius=18, fill=time_fill, outline=colors["accent"]
                )
                _draw_centered_text(
                    draw,
                    (time_box[0], time_box[1] + 4, time_box[2], time_box[1] + 52),
                    match.start_time,
                    time_font,
                    (247, 249, 252),
                )
                status_box = (x0 + 34, y + 70, x0 + 114, y + 94)
                draw.rounded_rectangle(status_box, radius=11, fill=colors["pill"])
                _draw_centered_text(
                    draw, status_box, match.status, status_font, colors["pill_text"]
                )

                left_logo_box = (x0 + 158, y + 30, x0 + 220, y + 92)
                right_logo_box = (x0 + 628, y + 30, x0 + 690, y + 92)
                _draw_logo_badge(
                    image,
                    left_logo_box,
                    match.logo_a_path,
                    match.team_a,
                    background=logo_bg,
                    outline=logo_outline,
                )
                _draw_logo_badge(
                    image,
                    right_logo_box,
                    match.logo_b_path,
                    match.team_b,
                    background=logo_bg,
                    outline=logo_outline,
                )

                left_team_x = left_logo_box[2] + 16
                left_team_name = _fit_text(draw, match.team_a, team_font, 200)
                right_team_name = _fit_text(draw, match.team_b, team_font, 194)
                left_bbox = draw.textbbox((0, 0), left_team_name, font=team_font)
                right_bbox = draw.textbbox((0, 0), right_team_name, font=team_font)
                left_y = y + 62 - ((left_bbox[3] - left_bbox[1]) / 2)
                right_y = y + 62 - ((right_bbox[3] - right_bbox[1]) / 2)
                draw.text(
                    (left_team_x, left_y),
                    left_team_name,
                    font=team_font,
                    fill=palette.text,
                )
                draw.text(
                    (right_logo_box[2] + 16, right_y),
                    right_team_name,
                    font=team_font,
                    fill=palette.text,
                )

                score_box = (x0 + 442, y + 22, x0 + 588, y + 74)
                draw.rounded_rectangle(
                    score_box,
                    radius=18,
                    fill=palette.score_box,
                    outline=colors["accent"],
                )
                score_text = match.score if match.score != "-" else "VS"
                _draw_centered_text(
                    draw, score_box, score_text, score_font, palette.text
                )
                bo_text = match.best_of.upper() if match.best_of else "BO?"
                _draw_centered_text(
                    draw,
                    (score_box[0], y + 82, score_box[2], y + 106),
                    bo_text,
                    bo_font,
                    palette.text_muted,
                )

                separator_x = x1 - 336
                draw.line(
                    (separator_x, y + 18, separator_x, y + card_height - 18),
                    fill=palette.border,
                    width=1,
                )
                event_panel = (x1 - 322, y + 14, x1 - 18, y + card_height - 14)
                draw.rounded_rectangle(event_panel, radius=18, fill=palette.panel_soft)
                accent, accent_text = _level_colors(match.level)
                draw.polygon(
                    [
                        (event_panel[2] - 38, event_panel[1]),
                        (event_panel[2], event_panel[1]),
                        (event_panel[2], event_panel[3]),
                        (event_panel[2] - 24, event_panel[3]),
                    ],
                    fill=accent,
                )
                level_text = (match.level or "?").upper()[:1]
                _draw_centered_text(
                    draw,
                    (
                        event_panel[2] - 40,
                        event_panel[1],
                        event_panel[2],
                        event_panel[3],
                    ),
                    level_text,
                    level_font,
                    accent_text,
                )

                event_logo_box = (
                    event_panel[0] + 16,
                    y + 34,
                    event_panel[0] + 56,
                    y + 74,
                )
                _draw_logo_badge(
                    image,
                    event_logo_box,
                    match.event_logo_path,
                    match.level or "EV",
                    radius=12,
                    background=logo_bg,
                    outline=logo_outline,
                )
                event_name = _fit_text(
                    draw,
                    _shorten_tournament_name(match.tournament_name),
                    event_font,
                    194,
                )
                schedule_name = _fit_text(
                    draw, match.schedule_name or "-", event_sub_font, 194
                )
                draw.text(
                    (event_logo_box[2] + 14, y + 28),
                    event_name,
                    font=event_font,
                    fill=palette.text,
                )
                draw.text(
                    (event_logo_box[2] + 14, y + 58),
                    schedule_name,
                    font=event_sub_font,
                    fill=palette.text_muted,
                )

                cursor_y += card_height

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def _render_premium_match_report_image(
    report: RenderMatchReport,
    output_path: str | Path,
    *,
    source_name: str,
    palette: RenderTheme,
) -> str:
    width = 1600
    padding = 44
    header_height = 268
    maps_height = 132
    team_header_height = 56
    player_row_height = 70
    group_gap = 14
    comment_height = 112
    maps = report.maps[:5]
    players = report.players[:12]
    grouped: dict[str, list[RenderPlayerStat]] = {}
    for player in players:
        grouped.setdefault(player.team or "PLAYERS", []).append(player)
    grouped_players = list(grouped.items())
    if not grouped_players and players:
        grouped_players = [("PLAYERS", players)]
    stats_height = sum(
        team_header_height + len(items) * player_row_height
        for _, items in grouped_players
    )
    stats_height += max(len(grouped_players) - 1, 0) * group_gap
    if not grouped_players:
        stats_height = team_header_height + player_row_height
    height = (
        padding
        + header_height
        + 18
        + maps_height
        + 24
        + stats_height
        + 24
        + comment_height
        + padding
    )

    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    draw = ImageDraw.Draw(image)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)
    asset_bg = _asset_background(palette)
    asset_outline = _asset_outline(palette)
    team_a_display = _shorten_team_display_name(report.team_a)
    team_b_display = _shorten_team_display_name(report.team_b)

    eyebrow_font = _load_font(LATIN_FONT, 16)
    title_font = _load_font(TITLE_FONT, 40)
    subtitle_font = _load_font(TEXT_FONT, 17)
    team_font = _load_font(TEXT_FONT, 29)
    score_font = _load_font(LATIN_FONT, 78)
    result_font = _load_font(LATIN_FONT, 15)
    map_title_font = _load_font(TEXT_FONT, 18)
    map_score_font = _load_font(LATIN_FONT, 34)
    small_font = _load_font(TEXT_FONT, 14)
    player_font = _load_font(TEXT_FONT, 19)
    row_small_font = _load_font(TEXT_FONT, 13)
    metric_font = _load_font(LATIN_FONT, 20)
    metric_small_font = _load_font(LATIN_FONT, 17)
    comment_font = _load_font(TEXT_FONT, 20)

    header = (padding, 30, width - padding, padding + header_height)
    draw.rectangle(header, fill=palette.panel_alt, outline=palette.border, width=1)
    draw.rectangle(
        (padding, 30, padding + 7, padding + header_height), fill=palette.accent
    )
    draw.text(
        (padding + 26, 32),
        "VALORANT / FINAL RESULT",
        font=eyebrow_font,
        fill=palette.accent,
    )
    title = _fit_text(
        draw, _shorten_tournament_name(report.tournament_name), title_font, 980
    )
    draw.text((padding + 26, 59), title, font=title_font, fill=palette.text)
    subtitle = f"{report.schedule_name or 'Main Event'}   /   {(report.best_of or 'Bo?').upper()}   /   {source_name.upper()}"
    draw.text(
        (padding + 27, 116), subtitle, font=subtitle_font, fill=palette.text_muted
    )
    if report.event_logo_path:
        _draw_logo_badge(
            image,
            (width - padding - 78, 43, width - padding - 6, 115),
            report.event_logo_path,
            "VCT",
            radius=10,
            background=logo_bg,
            outline=logo_outline,
        )

    score_text = report.score if report.score and report.score != "-" else "VS"
    parts = [part.strip() for part in score_text.replace(":", "-").split("-")]
    left_won = right_won = False
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        left_won = int(parts[0]) > int(parts[1])
        right_won = int(parts[1]) > int(parts[0])
    center_x = width // 2
    board_y = 158
    logo_size = 92
    left_logo = (padding + 70, board_y, padding + 70 + logo_size, board_y + logo_size)
    right_logo = (
        width - padding - 70 - logo_size,
        board_y,
        width - padding - 70,
        board_y + logo_size,
    )
    _draw_logo_badge(
        image,
        left_logo,
        report.team_a_logo_path,
        team_a_display,
        radius=12,
        background=logo_bg,
        outline=logo_outline,
    )
    _draw_logo_badge(
        image,
        right_logo,
        report.team_b_logo_path,
        team_b_display,
        radius=12,
        background=logo_bg,
        outline=logo_outline,
    )
    left_name = _fit_text(draw, team_a_display, team_font, 390)
    right_name = _fit_text(draw, team_b_display, team_font, 390)
    draw.text(
        (left_logo[2] + 24, board_y + 17), left_name, font=team_font, fill=palette.text
    )
    _draw_right_text(
        draw, right_logo[0] - 24, board_y + 17, right_name, team_font, palette.text
    )
    if left_won:
        draw.text(
            (left_logo[2] + 25, board_y + 59),
            "WINNER",
            font=result_font,
            fill=palette.accent,
        )
    elif right_won:
        _draw_right_text(
            draw,
            right_logo[0] - 25,
            board_y + 59,
            "WINNER",
            result_font,
            palette.accent,
        )
    score_box = (center_x - 126, board_y - 2, center_x + 126, board_y + 94)
    score_fill = (8, 8, 9, 255) if palette.name == "premium_dark" else (20, 20, 22, 255)
    draw.rectangle(score_box, fill=score_fill, outline=palette.border, width=1)
    _draw_centered_text(draw, score_box, score_text, score_font, (250, 250, 248))

    cursor_y = padding + header_height + 18
    label_width = 194
    draw.rectangle(
        (padding, cursor_y, padding + label_width, cursor_y + maps_height),
        fill=(*palette.accent_2, 255),
    )
    draw.text(
        (padding + 24, cursor_y + 34),
        "地图比分",
        font=_load_font(TEXT_FONT, 26),
        fill=(255, 255, 255),
    )
    draw.text(
        (padding + 25, cursor_y + 76),
        "MAP RESULTS",
        font=eyebrow_font,
        fill=(255, 235, 238),
    )
    map_gap = 10
    if maps:
        card_width = int(
            (width - padding * 2 - label_width - map_gap * len(maps)) / len(maps)
        )
        for index, item in enumerate(maps):
            x0 = padding + label_width + map_gap + index * (card_width + map_gap)
            box = (x0, cursor_y, x0 + card_width, cursor_y + maps_height)
            loaded = _draw_image_cover(
                image, box, item.image_path, radius=0, fallback_fill=palette.panel_soft
            )
            if loaded:
                overlay = Image.new("RGBA", (card_width, maps_height), (0, 0, 0, 96))
                image.alpha_composite(overlay, (x0, cursor_y))
            draw = ImageDraw.Draw(image)
            draw.rectangle(box, outline=palette.border, width=1)
            map_name = _fit_text(
                draw, item.map_name or "-", map_title_font, card_width - 28
            )
            _draw_centered_text(
                draw,
                (x0 + 12, cursor_y + 10, x0 + card_width - 12, cursor_y + 43),
                map_name,
                map_title_font,
                (255, 255, 255) if loaded else palette.text,
            )
            score = f"{item.team_a_score}:{item.team_b_score}"
            _draw_centered_text(
                draw,
                (x0 + 12, cursor_y + 42, x0 + card_width - 12, cursor_y + 91),
                score,
                map_score_font,
                (255, 255, 255) if loaded else palette.text,
            )
            meta = (
                " / ".join(value for value in (item.duration, item.pick) if value)
                or "-"
            )
            _draw_centered_text(
                draw,
                (x0 + 10, cursor_y + 96, x0 + card_width - 10, cursor_y + 123),
                _fit_text(draw, meta, small_font, card_width - 22),
                small_font,
                (226, 230, 236) if loaded else palette.text_muted,
            )
    else:
        draw.rectangle(
            (
                padding + label_width + map_gap,
                cursor_y,
                width - padding,
                cursor_y + maps_height,
            ),
            fill=palette.panel_alt,
            outline=palette.border,
        )
        draw.text(
            (padding + label_width + 34, cursor_y + 50),
            "VLR 暂无地图详情",
            font=player_font,
            fill=palette.text_muted,
        )
    cursor_y += maps_height + 24

    stat_columns = [
        ("Rating", 580, 82),
        ("ACS", 672, 74),
        ("K / D / A", 756, 176),
        ("+/-", 942, 66),
        ("KAST", 1018, 82),
        ("ADR", 1110, 82),
        ("HS%", 1202, 76),
        ("FK / FD", 1288, 112),
        ("+/-", 1410, 76),
    ]
    team_names = [team_a_display, team_b_display]
    team_logos = [report.team_a_logo_path, report.team_b_logo_path]
    if grouped_players:
        for group_index, (team_code, team_players) in enumerate(grouped_players):
            if group_index:
                cursor_y += group_gap
            team_name = (
                team_names[group_index] if group_index < len(team_names) else team_code
            )
            team_logo = (
                team_logos[group_index] if group_index < len(team_logos) else None
            )
            side_color = (49, 112, 220) if group_index == 0 else palette.accent
            draw.rectangle(
                (padding, cursor_y, width - padding, cursor_y + team_header_height),
                fill=palette.panel_soft,
                outline=palette.border,
                width=1,
            )
            draw.rectangle(
                (padding, cursor_y, padding + 6, cursor_y + team_header_height),
                fill=side_color,
            )
            _draw_logo_badge(
                image,
                (padding + 18, cursor_y + 7, padding + 60, cursor_y + 49),
                team_logo,
                team_code,
                radius=7,
                background=logo_bg,
                outline=logo_outline,
            )
            draw.text(
                (padding + 76, cursor_y + 14),
                _fit_text(draw, team_name, player_font, 280),
                font=player_font,
                fill=palette.text,
            )
            draw.text(
                (padding + 370, cursor_y + 18),
                _fit_text(draw, team_code, row_small_font, 150),
                font=row_small_font,
                fill=palette.text_muted,
            )
            for label, x, col_width in stat_columns:
                _draw_centered_text(
                    draw,
                    (x, cursor_y, x + col_width, cursor_y + team_header_height),
                    label,
                    row_small_font,
                    palette.text_muted,
                )
            cursor_y += team_header_height

            for row_index, player in enumerate(team_players):
                row_y = cursor_y
                row_fill = (
                    palette.panel_alt if row_index % 2 == 0 else palette.panel_soft
                )
                draw.rectangle(
                    (padding, row_y, width - padding, row_y + player_row_height),
                    fill=row_fill,
                    outline=palette.border,
                    width=1,
                )
                avatar_box = (padding + 18, row_y + 9, padding + 70, row_y + 61)
                _draw_avatar_or_initials(
                    image,
                    avatar_box,
                    player.avatar_path,
                    player.player,
                    background=asset_bg,
                    text_fill=palette.text,
                )
                flag_box = (padding + 82, row_y + 21, padding + 118, row_y + 47)
                loaded_flag = _draw_image_cover(
                    image,
                    flag_box,
                    player.country_flag_path,
                    radius=3,
                    fallback_fill=asset_bg,
                )
                draw.rectangle(flag_box, outline=asset_outline, width=1)
                if not loaded_flag:
                    _draw_centered_text(
                        draw,
                        flag_box,
                        player.country_code or "--",
                        row_small_font,
                        palette.text_muted,
                    )
                draw.text(
                    (padding + 132, row_y + 17),
                    _fit_text(draw, player.player, player_font, 190),
                    font=player_font,
                    fill=palette.text,
                )
                if player.country_name:
                    draw.text(
                        (padding + 132, row_y + 43),
                        _fit_text(draw, player.country_name, row_small_font, 170),
                        font=row_small_font,
                        fill=palette.text_muted,
                    )
                agent_x = padding + 350
                if player.agent_image_paths:
                    for agent_index, path in enumerate(player.agent_image_paths[:4]):
                        icon_box = (
                            agent_x + agent_index * 48,
                            row_y + 12,
                            agent_x + 42 + agent_index * 48,
                            row_y + 54,
                        )
                        _draw_image_contain(
                            image, icon_box, path, radius=4, background=asset_bg
                        )
                else:
                    agents = _fit_text(
                        draw, ", ".join(player.agents) or "-", row_small_font, 190
                    )
                    draw.text(
                        (agent_x, row_y + 25),
                        agents,
                        font=row_small_font,
                        fill=palette.text_muted,
                    )
                if player.stats_available:
                    values = [
                        player.rating or "-",
                        player.acs or "-",
                        f"{player.kills}/{player.deaths}/{player.assists}",
                        player.kd_diff or "-",
                        player.kast or "-",
                        player.adr or "-",
                        player.headshot_percent or "-",
                        f"{player.first_kills or '-'}/{player.first_deaths or '-'}",
                        player.fk_diff or "-",
                    ]
                    for (label, x, col_width), value in zip(stat_columns, values):
                        fill = (
                            _signed_color(value, palette.text)
                            if label == "+/-"
                            else palette.text
                        )
                        font = (
                            metric_small_font
                            if label in {"K / D / A", "FK / FD"}
                            else metric_font
                        )
                        _draw_centered_text(
                            draw,
                            (x, row_y, x + col_width, row_y + player_row_height),
                            value,
                            font,
                            fill,
                        )
                else:
                    draw.text(
                        (580, row_y + 24),
                        "VLR 暂无选手统计",
                        font=row_small_font,
                        fill=palette.text_muted,
                    )
                cursor_y += player_row_height
    else:
        draw.rectangle(
            (padding, cursor_y, width - padding, cursor_y + stats_height),
            fill=palette.panel_alt,
            outline=palette.border,
        )
        draw.text(
            (padding + 26, cursor_y + 42),
            "VLR 暂未提供选手统计",
            font=player_font,
            fill=palette.text_muted,
        )
        cursor_y += stats_height

    cursor_y += 24
    comment_box = (padding, cursor_y, width - padding, cursor_y + comment_height)
    draw.rectangle(comment_box, fill=palette.panel_alt, outline=palette.border, width=1)
    draw.rectangle(
        (padding, cursor_y, padding + 7, cursor_y + comment_height), fill=palette.accent
    )
    insight_label_font = _load_font(TEXT_FONT, 17)
    draw.text(
        (padding + 26, cursor_y + 16),
        "赛后锐评",
        font=insight_label_font,
        fill=palette.accent,
    )
    draw.text(
        (padding + 122, cursor_y + 18),
        "MATCH INSIGHT",
        font=eyebrow_font,
        fill=palette.text_muted,
    )
    for line_index, line in enumerate(
        _wrap_text(draw, report.comment, comment_font, width - padding * 2 - 54, 2)
    ):
        draw.text(
            (padding + 26, cursor_y + 50 + line_index * 29),
            line,
            font=comment_font,
            fill=palette.text,
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def render_match_report_image(
    report: RenderMatchReport,
    output_path: str | Path,
    *,
    source_name: str = "VLR.gg",
    theme: str = "dark",
) -> str:
    if str(theme).strip().casefold() in {"studio_dark", "studio_light"}:
        try:
            from .studio_render import report as draw_studio
        except ImportError:
            from studio_render import report as draw_studio
        return draw_studio(report, output_path, source_name=source_name, theme=theme)
    palette = _resolve_theme(theme)
    if palette.name.startswith("premium_"):
        return _render_premium_match_report_image(
            report,
            output_path,
            source_name=source_name,
            palette=palette,
        )
    width = 1600
    padding = 32
    header_height = 146
    map_height = 112
    map_gap = 16
    row_height = 68
    team_header_height = 58
    group_gap = 16
    comment_height = 96
    top_gap = 18
    maps = report.maps[:5]
    players = report.players[:12]

    grouped_players: list[tuple[str, list[RenderPlayerStat]]] = []
    for player in players:
        team = player.team or "UNK"
        if grouped_players and grouped_players[-1][0] == team:
            grouped_players[-1][1].append(player)
        else:
            grouped_players.append((team, [player]))
    if not grouped_players and players:
        grouped_players = [("PLAYERS", players)]
    group_height = sum(
        team_header_height + len(items) * row_height for _, items in grouped_players
    )
    group_height += max(len(grouped_players) - 1, 0) * group_gap
    if not grouped_players:
        group_height = team_header_height + row_height

    height = (
        padding
        + header_height
        + top_gap
        + map_height
        + 24
        + group_height
        + 24
        + comment_height
        + padding
    )

    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    draw = ImageDraw.Draw(image)

    eyebrow_font = _load_font(LATIN_FONT, 17)
    title_font = _load_font(TITLE_FONT, 40)
    subtitle_font = _load_font(TEXT_FONT, 19)
    team_font = _load_font(TEXT_FONT, 25)
    score_font = _load_font(LATIN_FONT, 58)
    label_font = _load_font(TEXT_FONT, 18)
    small_font = _load_font(TEXT_FONT, 15)
    map_title_font = _load_font(LATIN_FONT, 28)
    map_score_font = _load_font(LATIN_FONT, 42)
    row_font = _load_font(TEXT_FONT, 20)
    row_small_font = _load_font(TEXT_FONT, 14)
    metric_font = _load_font(LATIN_FONT, 24)
    _load_font(LATIN_FONT, 21)
    comment_font = _load_font(TEXT_FONT, 21)
    asset_bg = _asset_background(palette)
    asset_outline = _asset_outline(palette)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    team_code_names: dict[str, str] = {}
    for index, (code, _) in enumerate(grouped_players):
        if index == 0:
            team_code_names[code] = report.team_a
        elif index == 1:
            team_code_names[code] = report.team_b
        else:
            team_code_names[code] = code

    header_box = (padding, padding, width - padding, padding + header_height)
    draw.rounded_rectangle(
        header_box, radius=16, fill=palette.panel, outline=palette.border
    )
    draw.text(
        (padding + 24, padding + 20),
        "VALORANT MATCH REPORT",
        font=eyebrow_font,
        fill=palette.accent,
    )
    title = _fit_text(
        draw, _shorten_tournament_name(report.tournament_name), title_font, 560
    )
    draw.text((padding + 24, padding + 46), title, font=title_font, fill=palette.text)
    subtitle = f"{report.schedule_name or '-'}  |  {report.best_of or 'Bo?'}  |  source: {source_name}"
    draw.text(
        (padding + 24, padding + 102),
        subtitle,
        font=subtitle_font,
        fill=palette.text_muted,
    )

    center_y = padding + 72
    logo_size = 62
    score = report.score if report.score and report.score != "-" else "VS"
    score_center_x = width - padding - 460
    score_box = (
        score_center_x - 112,
        center_y - 42,
        score_center_x + 112,
        center_y + 42,
    )
    side_gap = 42
    scoreboard_right = width - padding - 24
    side_width = min(300, scoreboard_right - score_box[2] - side_gap)
    left_team_box = (
        score_box[0] - side_gap - side_width,
        center_y - 36,
        score_box[0] - side_gap,
        center_y + 36,
    )
    right_team_box = (
        score_box[2] + side_gap,
        center_y - 36,
        score_box[2] + side_gap + side_width,
        center_y + 36,
    )
    left_logo = (
        left_team_box[0],
        center_y - 31,
        left_team_box[0] + logo_size,
        center_y + 31,
    )
    right_logo = (
        right_team_box[2] - logo_size,
        center_y - 31,
        right_team_box[2],
        center_y + 31,
    )
    _draw_logo_badge(
        image,
        left_logo,
        report.team_a_logo_path,
        report.team_a,
        background=logo_bg,
        outline=logo_outline,
    )
    _draw_logo_badge(
        image,
        right_logo,
        report.team_b_logo_path,
        report.team_b,
        background=logo_bg,
        outline=logo_outline,
    )

    left_name = _fit_text(
        draw, report.team_a, team_font, max(score_box[0] - left_logo[2] - 52, 120)
    )
    right_name = _fit_text(
        draw, report.team_b, team_font, max(right_logo[0] - score_box[2] - 52, 120)
    )
    left_name_box = (left_logo[2] + 18, center_y - 32, score_box[0] - 26, center_y + 32)
    draw.text(
        (left_name_box[0], center_y - 17), left_name, font=team_font, fill=palette.text
    )
    right_name_w = draw.textlength(right_name, font=team_font)
    draw.text(
        (right_logo[0] - 18 - right_name_w, center_y - 17),
        right_name,
        font=team_font,
        fill=palette.text,
    )
    draw.rounded_rectangle(
        score_box, radius=18, fill=palette.score_box, outline=palette.border
    )
    _draw_centered_text(draw, score_box, score, score_font, palette.text)

    cursor_y = padding + header_height + top_gap
    all_width = 210
    map_count = max(len(maps), 1)
    card_width = int(
        (width - padding * 2 - all_width - map_gap * map_count) / map_count
    )
    draw.rounded_rectangle(
        (padding, cursor_y, padding + all_width, cursor_y + map_height),
        radius=8,
        fill=(*palette.accent_2, 255),
    )
    draw.text(
        (padding + 30, cursor_y + 30),
        "全场统计",
        font=_load_font(TEXT_FONT, 30),
        fill=(248, 251, 255),
    )
    draw.text(
        (padding + 32, cursor_y + 70),
        "FULL MATCH",
        font=eyebrow_font,
        fill=(226, 237, 255),
    )

    if maps:
        for index, item in enumerate(maps):
            x0 = padding + all_width + map_gap + index * (card_width + map_gap)
            box = (x0, cursor_y, x0 + card_width, cursor_y + map_height)
            loaded = _draw_image_cover(
                image, box, item.image_path, radius=8, fallback_fill=palette.panel_alt
            )
            overlay = Image.new("RGBA", (card_width, map_height), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.rounded_rectangle(
                (0, 0, card_width - 1, map_height - 1),
                radius=8,
                fill=(0, 0, 0, 78 if loaded else 18),
            )
            overlay_draw.rectangle(
                (0, map_height - 38, card_width, map_height), fill=(0, 0, 0, 100)
            )
            image.alpha_composite(overlay, (x0, cursor_y))
            score_text = f"{item.team_a_score}:{item.team_b_score}"
            title_text = _fit_text(
                draw, item.map_name or "-", map_title_font, card_width - 36
            )
            _draw_centered_text(
                draw,
                (x0 + 12, cursor_y + 8, x0 + card_width - 12, cursor_y + 40),
                title_text,
                map_title_font,
                (255, 255, 255),
            )
            score_y = cursor_y + 43
            map_score_box = (
                int(x0 + card_width / 2 - 64),
                score_y - 1,
                int(x0 + card_width / 2 + 64),
                score_y + 42,
            )
            draw.rounded_rectangle(
                map_score_box,
                radius=8,
                fill=(0, 0, 0, 70),
                outline=(255, 255, 255, 42),
            )
            _draw_centered_text(
                draw, map_score_box, score_text, map_score_font, (255, 255, 255)
            )
            meta = item.duration or ""
            if item.pick:
                meta = f"{meta} Pick: {item.pick}".strip()
            footer = meta.strip() or "-"
            footer = _fit_text(draw, footer, small_font, card_width - 24)
            _draw_centered_text(
                draw,
                (x0 + 10, cursor_y + 86, x0 + card_width - 10, cursor_y + 108),
                footer,
                small_font,
                (226, 234, 246),
            )
    else:
        x0 = padding + all_width + map_gap
        box = (x0, cursor_y, width - padding, cursor_y + map_height)
        draw.rounded_rectangle(
            box, radius=8, fill=palette.panel_alt, outline=palette.border
        )
        draw.text(
            (x0 + 28, cursor_y + 42),
            "暂无地图详情",
            font=row_font,
            fill=palette.text_muted,
        )

    cursor_y += map_height + 24

    stat_columns = [
        ("Rating", 620, 78),
        ("ACS", 718, 78),
        ("K/D/A", 816, 190),
        ("+/-", 1016, 70),
        ("KAST", 1106, 78),
        ("ADR", 1204, 78),
        ("HS%", 1302, 78),
        ("FK/FD", 1400, 96),
        ("+/-", 1512, 56),
    ]

    def team_logo_for(index: int) -> str | None:
        return report.team_a_logo_path if index == 0 else report.team_b_logo_path

    if grouped_players:
        for group_index, (team_code, team_players) in enumerate(grouped_players):
            if group_index > 0:
                cursor_y += group_gap
            team_fill = (46, 103, 211, 245) if group_index == 0 else (198, 82, 99, 235)
            header = (padding, cursor_y, width - padding, cursor_y + team_header_height)
            draw.rounded_rectangle(header, radius=8, fill=palette.panel_alt)
            draw.rounded_rectangle(
                (padding, cursor_y, padding + 300, cursor_y + team_header_height),
                radius=8,
                fill=team_fill,
            )
            _draw_logo_badge(
                image,
                (padding + 18, cursor_y + 8, padding + 60, cursor_y + 50),
                team_logo_for(group_index),
                team_code,
                radius=999,
                background=logo_bg,
                outline=(255, 255, 255, 44),
            )
            team_label = _fit_text(
                draw, team_code_names.get(team_code, team_code), team_font, 180
            )
            draw.text(
                (padding + 74, cursor_y + 14),
                team_code,
                font=team_font,
                fill=(250, 252, 255),
            )
            draw.text(
                (padding + 144, cursor_y + 18),
                _fit_text(draw, team_label, small_font, 150),
                font=small_font,
                fill=(223, 233, 248),
            )
            for label, x, col_width in stat_columns:
                _draw_centered_text(
                    draw,
                    (x, cursor_y + 8, x + col_width, cursor_y + team_header_height - 8),
                    label,
                    label_font,
                    palette.text_soft,
                )
            cursor_y += team_header_height

            for row_index, player in enumerate(team_players):
                row_y = cursor_y
                fill = palette.panel_alt if row_index % 2 == 0 else palette.panel_soft
                draw.rounded_rectangle(
                    (padding, row_y + 5, width - padding, row_y + row_height - 5),
                    radius=8,
                    fill=fill,
                )
                flag = player.country_code or "--"
                flag_box = (padding + 18, row_y + 21, padding + 62, row_y + 49)
                flag_loaded = _draw_image_cover(
                    image,
                    flag_box,
                    player.country_flag_path,
                    radius=4,
                    fallback_fill=asset_bg,
                )
                draw.rounded_rectangle(
                    flag_box, radius=4, outline=asset_outline, width=1
                )
                if not flag_loaded:
                    _draw_centered_text(
                        draw, flag_box, flag, row_small_font, palette.text
                    )
                _draw_avatar_or_initials(
                    image,
                    (padding + 76, row_y + 10, padding + 124, row_y + 58),
                    player.avatar_path,
                    player.player,
                    background=asset_bg,
                    text_fill=palette.text,
                )
                name = _fit_text(draw, player.player, row_font, 170)
                draw.text(
                    (padding + 140, row_y + 20), name, font=row_font, fill=palette.text
                )
                if player.country_name:
                    draw.text(
                        (padding + 140, row_y + 43),
                        _fit_text(draw, player.country_name, row_small_font, 150),
                        font=row_small_font,
                        fill=palette.text_muted,
                    )

                agent_x = padding + 340
                agent_paths = player.agent_image_paths or []
                if agent_paths:
                    for agent_index, path in enumerate(agent_paths[:4]):
                        icon_box = (
                            agent_x + agent_index * 48,
                            row_y + 12,
                            agent_x + 40 + agent_index * 48,
                            row_y + 52,
                        )
                        _draw_image_contain(
                            image, icon_box, path, radius=5, background=asset_bg
                        )
                else:
                    agents = _fit_text(
                        draw, ", ".join(player.agents) or "-", row_small_font, 190
                    )
                    draw.text(
                        (agent_x, row_y + 25),
                        agents,
                        font=row_small_font,
                        fill=palette.text_muted,
                    )

                if player.stats_available:
                    kda = f"{player.kills}/{player.deaths}/{player.assists}"
                    fkfd = f"{player.first_kills or '-'}/{player.first_deaths or '-'}"
                    metrics = [
                        player.rating or "-",
                        player.acs or "-",
                        kda,
                        player.kd_diff or "-",
                        player.kast or "-",
                        player.adr or "-",
                        player.headshot_percent or "-",
                        fkfd,
                        player.fk_diff or "-",
                    ]
                    for (label, x, col_width), value in zip(stat_columns, metrics):
                        text_fill = (
                            _signed_color(value, palette.text)
                            if label == "+/-"
                            else palette.text
                        )
                        font = metric_font
                        _draw_metric_box(
                            draw,
                            x,
                            row_y + 12,
                            col_width,
                            44,
                            value,
                            font,
                            fill=palette.metric_box,
                            text_fill=text_fill,
                        )
                else:
                    missing_box = (620, row_y + 12, width - padding - 20, row_y + 56)
                    draw.rounded_rectangle(
                        missing_box, radius=7, fill=palette.metric_box
                    )
                    draw.text(
                        (missing_box[0] + 18, row_y + 24),
                        "VLR 暂无选手统计",
                        font=row_small_font,
                        fill=palette.text_muted,
                    )
                cursor_y += row_height
    else:
        draw.rounded_rectangle(
            (
                padding,
                cursor_y,
                width - padding,
                cursor_y + team_header_height + row_height,
            ),
            radius=8,
            fill=palette.panel_alt,
        )
        draw.text(
            (padding + 24, cursor_y + 34),
            "VLR 暂未提供选手统计",
            font=row_font,
            fill=palette.text,
        )
        draw.text(
            (padding + 24, cursor_y + 66),
            "已保留地图比分；英雄、KDA、ACS 等数据等待数据源更新。",
            font=small_font,
            fill=palette.text_muted,
        )
        cursor_y += team_header_height + row_height

    cursor_y += 24
    comment_box = (padding, cursor_y, width - padding, cursor_y + comment_height)
    draw.rounded_rectangle(
        comment_box, radius=14, fill=palette.panel_soft, outline=palette.border
    )
    draw.text(
        (comment_box[0] + 24, cursor_y + 16),
        "锐评",
        font=label_font,
        fill=palette.accent,
    )
    for line_index, line in enumerate(
        _wrap_text(draw, report.comment, comment_font, width - padding * 2 - 48, 2)
    ):
        draw.text(
            (comment_box[0] + 24, cursor_y + 46 + line_index * 28),
            line,
            font=comment_font,
            fill=palette.text,
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def render_single_map_result_image(
    result: RenderSingleMapResult,
    output_path: str | Path,
    *,
    source_name: str = "VLR.gg",
    theme: str = "premium_dark",
) -> str:
    palette = _resolve_theme(theme)
    width, height = 1440, 790
    is_light = palette.name in {"light", "premium_light"}
    image = Image.new(
        "RGBA", (width, height), (238, 242, 245, 255) if is_light else (3, 19, 31, 255)
    )
    background_path = (
        STAGE_BACKDROP_PATH
        if STAGE_BACKDROP_PATH.exists()
        else Path(result.map_image_path or "")
    )
    if background_path.is_file():
        try:
            with Image.open(background_path) as raw:
                source = raw.convert("RGB")
                scale = max(
                    width / max(source.width, 1), height / max(source.height, 1)
                )
                resized = source.resize(
                    (
                        max(int(source.width * scale), 1),
                        max(int(source.height * scale), 1),
                    ),
                    Image.Resampling.LANCZOS,
                )
                left = (resized.width - width) // 2
                top = (resized.height - height) // 2
                background = resized.crop((left, top, left + width, top + height))
                if is_light:
                    background = ImageEnhance.Color(background).enhance(0.35)
                elif background_path == STAGE_BACKDROP_PATH:
                    stage_luma = ImageEnhance.Brightness(
                        ImageOps.grayscale(background)
                    ).enhance(2.15)
                    background = ImageOps.colorize(
                        stage_luma,
                        black=(0, 6, 15),
                        white=(24, 121, 151),
                    )
                else:
                    background = ImageOps.colorize(
                        ImageOps.grayscale(background),
                        black=(0, 7, 16),
                        white=(22, 124, 154),
                    )
                background = ImageEnhance.Contrast(background).enhance(1.08)
                background = background.filter(ImageFilter.GaussianBlur(15)).convert(
                    "RGBA"
                )
                image.alpha_composite(background)
        except OSError:
            pass
    image.alpha_composite(
        Image.new(
            "RGBA", image.size, (246, 248, 250, 213) if is_light else (0, 20, 34, 96)
        )
    )
    atmosphere = Image.new("RGBA", image.size, (0, 0, 0, 0))
    atmosphere_draw = ImageDraw.Draw(atmosphere)
    if is_light:
        atmosphere_draw.rectangle((0, 0, width, 154), fill=(255, 255, 255, 34))
        atmosphere_draw.rectangle((0, 438, width, height), fill=(255, 255, 255, 28))
    else:
        atmosphere_draw.polygon(
            ((90, 438), (245, 154), (330, 154), (245, 438)), fill=(0, 151, 194, 22)
        )
        atmosphere_draw.polygon(
            ((1190, 438), (1110, 154), (1195, 154), (1340, 438)),
            fill=(22, 119, 219, 24),
        )
        atmosphere_draw.rectangle((0, 438, width, height), fill=(0, 8, 16, 46))
    image.alpha_composite(atmosphere)
    draw = ImageDraw.Draw(image)
    text = (17, 23, 29) if is_light else (250, 252, 253)
    text_soft = (49, 61, 72) if is_light else (237, 244, 248)
    text_muted = (89, 105, 117) if is_light else (170, 195, 208)
    stat_accent = (10, 128, 151) if is_light else (75, 204, 230)
    line_color = (11, 34, 48, 70) if is_light else (190, 224, 235, 92)
    icon_bg = (248, 250, 251, 228) if is_light else (5, 35, 51, 218)
    icon_outline = (12, 37, 51, 58) if is_light else (120, 220, 238, 92)

    team_font = _load_font(MAP_LATIN_BOLD_FONT, 62)
    score_font = _load_font(MAP_LATIN_BLACK_FONT, 72)
    state_font = _load_font(MAP_CJK_BLACK_FONT, 22, index=2)
    top_stat_font = _load_font(MAP_LATIN_BOLD_FONT, 35)
    stat_label_font = _load_font(CJK_BOLD_FONT, 16, index=2)
    top_name_font = _load_font(MAP_LATIN_BOLD_FONT, 28)
    player_font = _load_font(MAP_LATIN_BOLD_FONT, 20)
    small_font = _load_font(MAP_CJK_MEDIUM_FONT, 14, index=2)
    bottom_stat_font = _load_font(MAP_LATIN_BOLD_FONT, 22)
    bottom_acs_font = _load_font(MAP_LATIN_BOLD_FONT, 23)
    map_name_font = _load_font(MAP_LATIN_BOLD_FONT, 23)

    team_codes: list[str] = []
    grouped: dict[str, list[RenderPlayerStat]] = {}
    for player in result.players:
        code = player.team or "TEAM"
        if code not in grouped:
            grouped[code] = []
            team_codes.append(code)
        grouped[code].append(player)
    left_players = grouped.get(team_codes[0], []) if team_codes else []
    right_players = grouped.get(team_codes[1], []) if len(team_codes) > 1 else []

    left_players = sorted(left_players, key=_single_map_player_rank_key, reverse=True)
    right_players = sorted(right_players, key=_single_map_player_rank_key, reverse=True)
    left_top = left_players[0] if left_players else None
    right_top = right_players[0] if right_players else None

    def acs_key(player: RenderPlayerStat) -> float:
        with contextlib.suppress(ValueError, TypeError):
            return float(str(player.acs or "0"))
        return 0.0

    left_support = sorted(left_players[1:], key=acs_key)
    right_support = sorted(right_players[1:], key=acs_key, reverse=True)

    def agent_display_name(agent: str) -> str:
        key = re.sub(r"[^a-z0-9]", "", str(agent or "").casefold())
        return AGENT_NAMES_ZH.get(key, str(agent or "-").strip() or "-")

    left_score: int | None = None
    with contextlib.suppress(ValueError):
        left_score = int(result.team_a_score)
    right_score: int | None = None
    with contextlib.suppress(ValueError):
        right_score = int(result.team_b_score)
    left_won = (
        left_score is not None and right_score is not None and left_score > right_score
    )
    right_won = (
        left_score is not None and right_score is not None and right_score > left_score
    )

    left_name = (
        team_codes[0]
        if team_codes and len(team_codes[0]) <= 8
        else _shorten_team_display_name(result.team_a)
    )
    right_name = (
        team_codes[1]
        if len(team_codes) > 1 and len(team_codes[1]) <= 8
        else _shorten_team_display_name(result.team_b)
    )
    left_logo = (82, 24, 178, 120)
    right_logo = (1222, 24, 1342, 120)

    def draw_team_logo(
        box: tuple[int, int, int, int], path: str | None, fallback: str
    ) -> None:
        if _draw_image_contain(image, box, path, background=(0, 0, 0, 0)):
            return
        local_draw = ImageDraw.Draw(image)
        _draw_centered_text(
            local_draw,
            box,
            fallback[:3].upper(),
            _load_font(BROADCAST_BOLD_FONT, 25),
            text,
        )

    draw_team_logo(left_logo, result.team_a_logo_path, left_name)
    draw_team_logo(right_logo, result.team_b_logo_path, right_name)
    draw = ImageDraw.Draw(image)
    draw.text(
        (218, 31), _fit_text(draw, left_name, team_font, 220), font=team_font, fill=text
    )
    draw.text(
        (1060, 31),
        _fit_text(draw, right_name, team_font, 150),
        font=team_font,
        fill=text,
    )
    draw.text(
        (455, 53),
        "胜利" if left_won else "失败",
        font=state_font,
        fill=(66, 223, 151) if left_won else text_soft,
    )
    draw.text(
        (900, 53),
        "胜利" if right_won else "失败",
        font=state_font,
        fill=(66, 223, 151) if right_won else text_soft,
    )

    _draw_centered_text(
        draw, (558, 20, 674, 127), result.team_a_score, score_font, text
    )
    _draw_centered_text(
        draw, (766, 20, 882, 127), result.team_b_score, score_font, text
    )

    def draw_event_mark(box: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = box
        if result.event_logo_path and Path(result.event_logo_path).exists():
            try:
                with Image.open(result.event_logo_path) as raw:
                    mark = raw.convert("RGBA")
                    content_box = mark.getchannel("A").getbbox()
                    if content_box:
                        mark = mark.crop(content_box)
                    mark.thumbnail((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
                    recolored = Image.new("RGBA", mark.size, (*stat_accent, 0))
                    recolored.putalpha(mark.getchannel("A"))
                    image.alpha_composite(
                        recolored,
                        (
                            x0 + (x1 - x0 - recolored.width) // 2,
                            y0 + (y1 - y0 - recolored.height) // 2,
                        ),
                    )
                    return
            except OSError:
                pass
        local_draw = ImageDraw.Draw(image)
        _draw_centered_text(
            local_draw, box, "VS", _load_font(BROADCAST_BOLD_FONT, 24), stat_accent
        )

    draw_event_mark((699, 56, 741, 102))
    draw = ImageDraw.Draw(image)
    draw.line((90, 154, width - 80, 154), fill=line_color, width=1)

    def draw_feature_portrait(
        box: tuple[int, int, int, int], portrait_path: str | None
    ) -> None:
        x0, y0, x1, y1 = box
        if not portrait_path or not Path(portrait_path).exists():
            _draw_image_contain(image, box, portrait_path, background=(0, 0, 0, 0))
            return
        try:
            with Image.open(portrait_path) as raw:
                portrait = raw.convert("RGBA")
                content_box = portrait.getchannel("A").getbbox()
                if content_box:
                    portrait = portrait.crop(content_box)
                upper_body_height = max(int(portrait.height * 0.62), 1)
                portrait = portrait.crop((0, 0, portrait.width, upper_body_height))
                box_width = x1 - x0
                box_height = y1 - y0
                scale = (
                    min(
                        box_width / max(portrait.width, 1),
                        box_height / max(portrait.height, 1),
                    )
                    * 1.4
                )
                portrait = portrait.resize(
                    (
                        max(int(portrait.width * scale), 1),
                        max(int(portrait.height * scale), 1),
                    ),
                    Image.Resampling.LANCZOS,
                )
                tile = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
                tile.alpha_composite(
                    portrait,
                    ((box_width - portrait.width) // 2, 0),
                )
                image.alpha_composite(tile, (x0, y0))
        except OSError:
            _draw_image_contain(image, box, portrait_path, background=(0, 0, 0, 0))

    if left_top:
        portrait = (
            left_top.agent_full_portrait_path
            or ((left_top.agent_image_paths or [None])[0])
        )
        draw_feature_portrait((70, 170, 500, 452), portrait)
    if right_top:
        portrait = (
            right_top.agent_full_portrait_path
            or ((right_top.agent_image_paths or [None])[0])
        )
        draw_feature_portrait((1010, 170, 1370, 452), portrait)
    draw = ImageDraw.Draw(image)

    def draw_top_player(player: RenderPlayerStat | None, side: str) -> None:
        if player is None:
            return
        if side == "left":
            x0, x1 = 438, 650
            align_right = False
        else:
            x0, x1 = 790, 1002
            align_right = True
        name = _fit_text(draw, player.player, top_name_font, x1 - x0)
        agent = (
            " / ".join(agent_display_name(item) for item in player.agents[:2]) or "-"
        )
        kda = f"{player.kills}/{player.deaths}/{player.assists}"
        if align_right:
            _draw_right_text(draw, x1, 181, kda, top_stat_font, text)
            _draw_right_text(draw, x1, 239, player.acs or "-", top_stat_font, text)
            _draw_right_text(draw, x1, 325, name, top_name_font, text_soft)
            _draw_right_text(draw, x1, 357, agent, small_font, text_muted)
        else:
            draw.text((x0, 181), kda, font=top_stat_font, fill=text)
            draw.text((x0, 239), player.acs or "-", font=top_stat_font, fill=text)
            draw.text((x0, 325), name, font=top_name_font, fill=text_soft)
            draw.text((x0, 357), agent, font=small_font, fill=text_muted)

    draw_top_player(left_top, "left")
    draw_top_player(right_top, "right")
    _draw_centered_text(draw, (680, 187, 760, 221), "KDA", stat_label_font, stat_accent)
    _draw_centered_text(
        draw, (670, 245, 770, 279), "平均战斗评分", stat_label_font, stat_accent
    )
    draw.line((42, 438, width - 42, 438), fill=line_color, width=1)

    center_box = (634, 454, 806, 584)
    _draw_image_cover(
        image,
        center_box,
        result.map_image_path,
        radius=0,
        fallback_fill=(18, 28, 40, 255),
    )
    draw = ImageDraw.Draw(image)
    draw.rectangle(center_box, outline=icon_outline, width=1)
    _draw_centered_text(
        draw,
        (center_box[0], 590, center_box[2], 628),
        result.map_name or "-",
        map_name_font,
        text,
    )
    _draw_centered_text(
        draw,
        (center_box[0], 666, center_box[2], 694),
        "KDA",
        stat_label_font,
        stat_accent,
    )
    _draw_centered_text(
        draw,
        (center_box[0], 724, center_box[2], 752),
        "平均战斗评分",
        stat_label_font,
        stat_accent,
    )

    def draw_support_players(players: list[RenderPlayerStat], start_x: int) -> None:
        items = players[:4]
        card_width = 139
        for index, player in enumerate(items):
            x = start_x + index * card_width
            agent_path = (player.agent_image_paths or [None])[0]
            icon_box = (x + 4, 454, x + 132, 582)
            _draw_image_contain(
                image, icon_box, agent_path, radius=0, background=icon_bg
            )
            local_draw = ImageDraw.Draw(image)
            local_draw.rectangle(icon_box, outline=icon_outline, width=1)
            _draw_centered_text(
                local_draw,
                (x, 590, x + 136, 620),
                _fit_text(local_draw, player.player, player_font, 128),
                player_font,
                text,
            )
            agent_name = agent_display_name(player.agents[0]) if player.agents else "-"
            _draw_centered_text(
                local_draw, (x, 624, x + 136, 649), agent_name, small_font, text_muted
            )
            _draw_centered_text(
                local_draw,
                (x, 660, x + 136, 696),
                f"{player.kills}/{player.deaths}/{player.assists}",
                bottom_stat_font,
                text,
            )
            _draw_centered_text(
                local_draw,
                (x, 718, x + 136, 752),
                player.acs or "-",
                bottom_acs_font,
                stat_accent,
            )

    draw_support_players(left_support, 40)
    draw_support_players(right_support, 820)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return str(output)


def _render_premium_start_notice_image(
    notice: RenderStartNotice,
    output_path: str | Path,
    *,
    source_name: str,
    palette: RenderTheme,
) -> str:
    width = 1280
    padding = 44
    rows = notice.head_to_head[:3]
    header_y = 30
    header_height = 160
    match_y = 208
    match_height = 246
    odds_y = 472
    odds_height = 140
    h2h_y = 630
    h2h_height = 124 if not rows else 66 + len(rows) * 70
    height = h2h_y + h2h_height + padding
    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    draw = ImageDraw.Draw(image)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    eyebrow_font = _load_font(LATIN_FONT, 16)
    title_font = _load_font(TITLE_FONT, 40)
    subtitle_font = _load_font(TEXT_FONT, 16)
    team_font = _load_font(TEXT_FONT, 28)
    small_font = _load_font(TEXT_FONT, 14)
    label_font = _load_font(TEXT_FONT, 18)
    time_font = _load_font(LATIN_FONT, 38)
    vs_font = _load_font(LATIN_FONT, 48)
    score_font = _load_font(LATIN_FONT, 27)

    header = (padding, header_y, width - padding, header_y + header_height)
    draw.rectangle(header, fill=palette.panel_alt, outline=palette.border, width=1)
    draw.rectangle(
        (padding, header_y, padding + 7, header_y + header_height), fill=palette.accent
    )
    draw.text(
        (padding + 26, header_y + 16),
        "VALORANT / MATCH START",
        font=eyebrow_font,
        fill=palette.accent,
    )
    title = _fit_text(
        draw, _shorten_tournament_name(notice.tournament_name), title_font, 760
    )
    draw.text((padding + 26, header_y + 44), title, font=title_font, fill=palette.text)
    meta = f"{notice.schedule_name or 'Main Event'}   /   {(notice.best_of or 'Bo?').upper()}   /   {source_name.upper()}"
    draw.text(
        (padding + 27, header_y + 104),
        _fit_text(draw, meta, subtitle_font, 760),
        font=subtitle_font,
        fill=palette.text_muted,
    )
    time_box = (
        width - padding - 286,
        header_y + 20,
        width - padding - 98,
        header_y + 132,
    )
    time_fill = (8, 8, 9, 255) if palette.name == "premium_dark" else (20, 20, 22, 255)
    draw.rectangle(time_box, fill=time_fill, outline=palette.border, width=1)
    _draw_centered_text(
        draw,
        (time_box[0], time_box[1] + 8, time_box[2], time_box[1] + 68),
        notice.start_time or "LIVE",
        time_font,
        (250, 250, 248),
    )
    _draw_centered_text(
        draw,
        (time_box[0], time_box[1] + 70, time_box[2], time_box[3] - 6),
        "即将开赛",
        small_font,
        (220, 222, 226),
    )
    _draw_logo_badge(
        image,
        (width - padding - 82, header_y + 38, width - padding - 14, header_y + 106),
        notice.event_logo_path,
        "VCT",
        radius=9,
        background=logo_bg,
        outline=logo_outline,
    )

    draw = ImageDraw.Draw(image)
    match_box = (padding, match_y, width - padding, match_y + match_height)
    draw.rectangle(match_box, fill=palette.panel_alt, outline=palette.border, width=1)
    left_name = _shorten_team_display_name(notice.team_a)
    right_name = _shorten_team_display_name(notice.team_b)
    logo_size = 104
    left_logo = (
        padding + 54,
        match_y + 66,
        padding + 54 + logo_size,
        match_y + 66 + logo_size,
    )
    right_logo = (
        width - padding - 54 - logo_size,
        match_y + 66,
        width - padding - 54,
        match_y + 66 + logo_size,
    )
    _draw_logo_badge(
        image,
        left_logo,
        notice.team_a_logo_path,
        left_name,
        radius=13,
        background=logo_bg,
        outline=logo_outline,
    )
    _draw_logo_badge(
        image,
        right_logo,
        notice.team_b_logo_path,
        right_name,
        radius=13,
        background=logo_bg,
        outline=logo_outline,
    )
    draw = ImageDraw.Draw(image)
    draw.text(
        (left_logo[2] + 24, match_y + 87),
        _fit_text(draw, left_name, team_font, 330),
        font=team_font,
        fill=palette.text,
    )
    _draw_right_text(
        draw,
        right_logo[0] - 24,
        match_y + 87,
        _fit_text(draw, right_name, team_font, 330),
        team_font,
        palette.text,
    )
    draw.text(
        (left_logo[2] + 25, match_y + 130),
        "BLUE SIDE",
        font=eyebrow_font,
        fill=(70, 132, 232),
    )
    _draw_right_text(
        draw,
        right_logo[0] - 25,
        match_y + 130,
        "RED SIDE",
        eyebrow_font,
        palette.accent,
    )
    vs_box = (width // 2 - 96, match_y + 58, width // 2 + 96, match_y + 178)
    draw.rectangle(vs_box, fill=time_fill, outline=palette.border, width=1)
    _draw_centered_text(
        draw,
        (vs_box[0], vs_box[1] + 4, vs_box[2], vs_box[1] + 72),
        "VS",
        vs_font,
        (250, 250, 248),
    )
    _draw_centered_text(
        draw,
        (vs_box[0], vs_box[1] + 74, vs_box[2], vs_box[3] - 8),
        (notice.best_of or "BO?").upper(),
        small_font,
        (205, 208, 214),
    )

    odds_box = (padding, odds_y, width - padding, odds_y + odds_height)
    draw.rectangle(odds_box, fill=palette.panel_alt, outline=palette.border, width=1)
    draw.rectangle(
        (padding, odds_y, padding + 176, odds_y + odds_height),
        fill=(*palette.accent_2, 255),
    )
    draw.text(
        (padding + 22, odds_y + 30),
        "赛前指数",
        font=_load_font(TEXT_FONT, 25),
        fill=(255, 255, 255),
    )
    draw.text(
        (padding + 23, odds_y + 70),
        "MARKET ODDS",
        font=eyebrow_font,
        fill=(255, 233, 237),
    )
    content_x0 = padding + 204
    content_x1 = width - padding - 26
    probabilities = _odds_probabilities(notice.team_a_odds, notice.team_b_odds)
    if probabilities:
        left_prob, right_prob = probabilities
        draw.text(
            (content_x0, odds_y + 22),
            f"{left_name}  {notice.team_a_odds}",
            font=subtitle_font,
            fill=palette.text,
        )
        _draw_right_text(
            draw,
            content_x1,
            odds_y + 22,
            f"{notice.team_b_odds}  {right_name}",
            subtitle_font,
            palette.text,
        )
        bar = (content_x0, odds_y + 64, content_x1, odds_y + 94)
        _draw_odds_bar(draw, bar, left_prob, right_prob, radius=0)
        _draw_centered_text(
            draw,
            (bar[0] + 8, bar[1], bar[0] + 76, bar[3]),
            f"{round(left_prob * 100)}%",
            small_font,
            (255, 255, 255),
        )
        _draw_centered_text(
            draw,
            (bar[2] - 76, bar[1], bar[2] - 8, bar[3]),
            f"{round(right_prob * 100)}%",
            small_font,
            (255, 255, 255),
        )
        if notice.betting_info:
            draw.text(
                (content_x0, odds_y + 108),
                _fit_text(
                    draw, notice.betting_info, small_font, content_x1 - content_x0
                ),
                font=small_font,
                fill=palette.text_muted,
            )
    else:
        message = notice.betting_info or "VLR 暂未提供赛前指数"
        draw.text(
            (content_x0, odds_y + 50),
            _fit_text(draw, message, label_font, content_x1 - content_x0),
            font=label_font,
            fill=palette.text,
        )
        draw.text(
            (content_x0, odds_y + 84),
            "市场数据缺失时不会推算或伪造概率",
            font=small_font,
            fill=palette.text_muted,
        )

    h2h_box = (padding, h2h_y, width - padding, h2h_y + h2h_height)
    draw.rectangle(h2h_box, fill=palette.panel_alt, outline=palette.border, width=1)
    draw.rectangle(
        (padding, h2h_y, padding + 7, h2h_y + h2h_height), fill=palette.accent
    )
    draw.text(
        (padding + 24, h2h_y + 18), "历史交手", font=label_font, fill=palette.text
    )
    draw.text(
        (padding + 126, h2h_y + 21),
        "HEAD TO HEAD",
        font=eyebrow_font,
        fill=palette.text_muted,
    )
    if not rows:
        draw.text(
            (padding + 24, h2h_y + 72),
            "双方暂无可用交手记录",
            font=subtitle_font,
            fill=palette.text_muted,
        )
    else:
        row_y = h2h_y + 58
        for index, item in enumerate(rows):
            y = row_y + index * 70
            if index % 2:
                draw.rectangle(
                    (padding + 10, y, width - padding - 10, y + 62),
                    fill=palette.panel_soft,
                )
            draw.text(
                (padding + 24, y + 20),
                _fit_text(draw, item.date_label or "-", subtitle_font, 140),
                font=subtitle_font,
                fill=palette.text_muted,
            )
            left_small = (padding + 200, y + 10, padding + 242, y + 52)
            right_small = (padding + 390, y + 10, padding + 432, y + 52)
            _draw_logo_badge(
                image,
                left_small,
                notice.team_a_logo_path,
                left_name,
                radius=7,
                background=logo_bg,
                outline=logo_outline,
            )
            _draw_logo_badge(
                image,
                right_small,
                notice.team_b_logo_path,
                right_name,
                radius=7,
                background=logo_bg,
                outline=logo_outline,
            )
            draw = ImageDraw.Draw(image)
            _draw_centered_text(
                draw,
                (padding + 252, y + 4, padding + 380, y + 58),
                item.score or "-",
                score_font,
                palette.text,
            )
            draw.text(
                (padding + 478, y + 20),
                _fit_text(
                    draw,
                    item.event_name or "-",
                    subtitle_font,
                    width - padding * 2 - 520,
                ),
                font=subtitle_font,
                fill=palette.text_muted,
            )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def render_start_notice_image(
    notice: RenderStartNotice,
    output_path: str | Path,
    *,
    source_name: str = "VLR.gg",
    theme: str = "dark",
) -> str:
    if str(theme).strip().casefold() in {"studio_dark", "studio_light"}:
        try:
            from .studio_render import notice as draw_studio
        except ImportError:
            from studio_render import notice as draw_studio
        return draw_studio(notice, output_path, source_name=source_name, theme=theme)
    palette = _resolve_theme(theme)
    if palette.name.startswith("premium_"):
        return _render_premium_start_notice_image(
            notice,
            output_path,
            source_name=source_name,
            palette=palette,
        )
    width = 1280
    padding = 40
    rows = notice.head_to_head[:3]
    h2h_row_count = max(len(rows), 1)
    header_bottom = 334
    info_top = header_bottom + 26
    info_h = 150
    h2h_height = (
        76 if not rows else 82 + h2h_row_count * 62 + max(h2h_row_count - 1, 0) * 10
    )
    height = info_top + info_h + 24 + h2h_height + padding
    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    draw = ImageDraw.Draw(image)

    eyebrow_font = _load_font(LATIN_FONT, 17)
    title_font = _load_font(TITLE_FONT, 40)
    team_font = _load_font(TEXT_FONT, 30)
    team_small_font = _load_font(TEXT_FONT, 18)
    score_font = _load_font(LATIN_FONT, 40)
    label_font = _load_font(TEXT_FONT, 18)
    text_font = _load_font(TEXT_FONT, 20)
    small_font = _load_font(TEXT_FONT, 16)
    _load_font(LATIN_FONT, 26)
    row_score_font = _load_font(LATIN_FONT, 32)
    _asset_background(palette)
    _asset_outline(palette)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    header = (padding, padding, width - padding, header_bottom)
    draw.rounded_rectangle(
        header, radius=16, fill=palette.panel, outline=palette.border
    )
    draw.text(
        (padding + 24, padding + 22),
        "VALORANT START NOTICE",
        font=eyebrow_font,
        fill=palette.accent,
    )
    title = _fit_text(
        draw, _shorten_tournament_name(notice.tournament_name), title_font, 680
    )
    draw.text((padding + 24, padding + 50), title, font=title_font, fill=palette.text)
    subtitle = _fit_text(
        draw,
        f"{notice.schedule_name or '-'}  |  {notice.best_of or 'Bo?'}  |  source: {source_name}",
        small_font,
        760,
    )
    draw.text(
        (padding + 24, padding + 106),
        subtitle,
        font=small_font,
        fill=palette.text_muted,
    )

    logo_size = 90
    center_x = width // 2
    center_y = 236
    left_logo = (
        padding + 64,
        center_y - logo_size // 2,
        padding + 64 + logo_size,
        center_y + logo_size // 2,
    )
    right_logo = (
        width - padding - 64 - logo_size,
        center_y - logo_size // 2,
        width - padding - 64,
        center_y + logo_size // 2,
    )
    _draw_logo_badge(
        image,
        left_logo,
        notice.team_a_logo_path,
        notice.team_a,
        background=logo_bg,
        outline=logo_outline,
    )
    _draw_logo_badge(
        image,
        right_logo,
        notice.team_b_logo_path,
        notice.team_b,
        background=logo_bg,
        outline=logo_outline,
    )
    left_name = _fit_text(draw, notice.team_a, team_font, 330)
    right_name = _fit_text(draw, notice.team_b, team_font, 330)
    draw.text(
        (left_logo[2] + 24, center_y - 24), left_name, font=team_font, fill=palette.text
    )
    draw.text(
        (left_logo[2] + 25, center_y + 14),
        "BLUE SIDE",
        font=team_small_font,
        fill=(72, 126, 224),
    )
    _draw_right_text(
        draw, right_logo[0] - 24, center_y - 24, right_name, team_font, palette.text
    )
    _draw_right_text(
        draw,
        right_logo[0] - 25,
        center_y + 14,
        "RED SIDE",
        team_small_font,
        (210, 76, 93),
    )

    vs_box = (center_x - 88, center_y - 54, center_x + 88, center_y + 54)
    draw.rounded_rectangle(
        vs_box, radius=20, fill=palette.score_box, outline=palette.border
    )
    start_text = notice.start_time or "即将开始"
    _draw_centered_text(
        draw,
        (vs_box[0], vs_box[1] + 12, vs_box[2], vs_box[1] + 68),
        "VS",
        score_font,
        palette.text,
    )
    _draw_centered_text(
        draw,
        (vs_box[0], vs_box[1] + 70, vs_box[2], vs_box[3] - 10),
        start_text,
        small_font,
        palette.text_muted,
    )

    bet_box = (padding, info_top, width - padding, info_top + info_h)
    draw.rounded_rectangle(
        bet_box, radius=16, fill=palette.panel_alt, outline=palette.border
    )
    draw.text(
        (bet_box[0] + 24, bet_box[1] + 18),
        "赛前赔率",
        font=label_font,
        fill=palette.accent,
    )
    left_odds = _parse_decimal(notice.team_a_odds)
    right_odds = _parse_decimal(notice.team_b_odds)
    probs = (
        _odds_probabilities(notice.team_a_odds, notice.team_b_odds)
        if left_odds and right_odds
        else None
    )
    bar = (bet_box[0] + 24, bet_box[1] + 76, bet_box[2] - 24, bet_box[1] + 106)
    if probs:
        left_prob, right_prob = probs
        _draw_odds_bar(draw, bar, left_prob, right_prob)
        left_pct = f"{round(left_prob * 100):d}%"
        right_pct = f"{round(right_prob * 100):d}%"
        draw.text(
            (bar[0], bet_box[1] + 46),
            f"{_fit_text(draw, notice.team_a, small_font, 280)}  {notice.team_a_odds}",
            font=small_font,
            fill=palette.text,
        )
        _draw_right_text(
            draw,
            bar[2],
            bet_box[1] + 46,
            f"{notice.team_b_odds}  {_fit_text(draw, notice.team_b, small_font, 280)}",
            small_font,
            palette.text,
        )
        _draw_centered_text(
            draw,
            (bar[0] + 8, bar[1], bar[0] + 74, bar[3]),
            left_pct,
            small_font,
            (255, 255, 255),
        )
        _draw_centered_text(
            draw,
            (bar[2] - 74, bar[1], bar[2] - 8, bar[3]),
            right_pct,
            small_font,
            (255, 255, 255),
        )
    elif left_odds or right_odds:
        draw.rounded_rectangle(bar, radius=12, fill=palette.metric_box)
        known_team = notice.team_a if left_odds else notice.team_b
        known_odds = notice.team_a_odds if left_odds else notice.team_b_odds
        missing_team = notice.team_b if left_odds else notice.team_a
        text = f"VLR 页面仅公开 {known_team} 赔率 {known_odds}，{missing_team} 暂无公开赔率"
        text = _fit_text(draw, text, text_font, bar[2] - bar[0] - 32)
        _draw_centered_text(draw, bar, text, text_font, palette.text_muted)
    else:
        draw.rounded_rectangle(bar, radius=12, fill=palette.metric_box)
        text = "暂无 betting / 预测信息"
        _draw_centered_text(draw, bar, text, text_font, palette.text_muted)
    if notice.betting_info:
        info = _fit_text(
            draw, notice.betting_info, small_font, bet_box[2] - bet_box[0] - 48
        )
        draw.text(
            (bet_box[0] + 24, bet_box[1] + 122),
            info,
            font=small_font,
            fill=palette.text_muted,
        )

    h2h_top = info_top + info_h + 24
    h2h_box = (padding, h2h_top, width - padding, height - padding)
    draw.rounded_rectangle(
        h2h_box, radius=14, fill=palette.panel_soft, outline=palette.border
    )
    draw.text(
        (h2h_box[0] + 22, h2h_box[1] + 18),
        "历史交手",
        font=label_font,
        fill=palette.accent,
    )
    if not rows:
        draw.text(
            (h2h_box[0] + 22, h2h_box[1] + 68),
            "暂无可用交手记录",
            font=text_font,
            fill=palette.text_muted,
        )
    else:
        row_y = h2h_box[1] + 58
        for index, item in enumerate(rows, start=1):
            row_box = (h2h_box[0] + 18, row_y, h2h_box[2] - 18, row_y + 62)
            draw.rounded_rectangle(row_box, radius=12, fill=palette.metric_box)
            number_box = (row_box[0] + 12, row_y + 12, row_box[0] + 42, row_y + 50)
            _draw_centered_text(
                draw, number_box, f"{index}", label_font, palette.accent
            )
            date_box = (row_box[0] + 54, row_y + 8, row_box[0] + 180, row_y + 54)
            _draw_centered_text(
                draw,
                date_box,
                _fit_text(draw, item.date_label or "-", text_font, 120),
                text_font,
                palette.text,
            )
            score_center = row_box[0] + 356
            logo_gap = 68
            left_small = (
                score_center - logo_gap - 38,
                row_y + 12,
                score_center - logo_gap,
                row_y + 50,
            )
            right_small = (
                score_center + logo_gap,
                row_y + 12,
                score_center + logo_gap + 38,
                row_y + 50,
            )
            _draw_logo_badge(
                image,
                left_small,
                notice.team_a_logo_path,
                notice.team_a,
                background=logo_bg,
                outline=logo_outline,
            )
            _draw_logo_badge(
                image,
                right_small,
                notice.team_b_logo_path,
                notice.team_b,
                background=logo_bg,
                outline=logo_outline,
            )
            score_text = item.score or "-"
            _draw_centered_text(
                draw,
                (score_center - 58, row_y + 6, score_center + 58, row_y + 56),
                score_text,
                row_score_font,
                palette.text,
            )
            event_name = _fit_text(
                draw, item.event_name or "-", small_font, row_box[2] - row_box[0] - 536
            )
            draw.text(
                (row_box[0] + 520, row_y + 21),
                event_name,
                font=small_font,
                fill=palette.text_muted,
            )
            row_y += 72

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def render_tournament_progress_image(
    progress: RenderTournamentProgress,
    output_path: str | Path,
    *,
    source_name: str = "VLR.gg",
    theme: str = "premium_dark",
) -> str:
    if str(theme).strip().casefold() in {"studio_dark", "studio_light"}:
        try:
            from .studio_render import progress as draw_studio
        except ImportError:
            from studio_render import progress as draw_studio
        return draw_studio(progress, output_path, source_name=source_name, theme=theme)
    palette = _resolve_theme(theme)
    if progress.kind == "bracket" and progress.brackets:
        return _render_bracket_progress(
            progress, output_path, source_name=source_name, palette=palette
        )
    return _render_standings_progress(
        progress, output_path, source_name=source_name, palette=palette
    )


def _draw_progress_header(
    image: Image.Image,
    progress: RenderTournamentProgress,
    *,
    source_name: str,
    palette: RenderTheme,
) -> int:
    draw = ImageDraw.Draw(image)
    width = image.width
    padding = 44
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)
    eyebrow_font = _load_font(LATIN_FONT, 16)
    title_font = _load_font(TITLE_FONT, 42)
    subtitle_font = _load_font(TEXT_FONT, 18)
    kind_label = "PLAYOFF BRACKET" if progress.kind == "bracket" else "GROUP STANDINGS"
    draw.rectangle((padding, 32, padding + 7, 126), fill=palette.accent)
    draw.text(
        (padding + 24, 32),
        f"VALORANT / {kind_label}",
        font=eyebrow_font,
        fill=palette.accent,
    )
    title = _fit_text(draw, progress.event_name, title_font, width - 420)
    draw.text((padding + 24, 58), title, font=title_font, fill=palette.text)
    subtitle = f"{progress.stage_name or 'Main Event'}   /   UPDATED FROM {source_name.upper()}"
    draw.text(
        (padding + 25, 118), subtitle, font=subtitle_font, fill=palette.text_muted
    )
    logo_box = (width - padding - 92, 38, width - padding, 130)
    _draw_logo_badge(
        image,
        logo_box,
        progress.event_logo_path,
        "VCT",
        radius=12,
        background=logo_bg,
        outline=logo_outline,
    )
    draw.line((padding, 158, width - padding, 158), fill=palette.border, width=2)
    return 188


def _render_standings_progress(
    progress: RenderTournamentProgress,
    output_path: str | Path,
    *,
    source_name: str,
    palette: RenderTheme,
) -> str:
    width = 1440
    padding = 44
    gap = 22
    groups = progress.groups[:8]
    columns = 2 if len(groups) > 1 else 1
    card_width = (width - padding * 2 - gap * (columns - 1)) // columns
    row_height = 62
    group_header_height = 86
    grid_rows: list[list[RenderStandingGroup]] = [
        groups[index : index + columns] for index in range(0, len(groups), columns)
    ]
    body_height = 0
    for row_groups in grid_rows:
        body_height += (
            group_header_height
            + max(len(group.rows) for group in row_groups) * row_height
            + 20
        )
    body_height += max(len(grid_rows) - 1, 0) * gap
    height = 188 + body_height + padding
    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    cursor_y = _draw_progress_header(
        image, progress, source_name=source_name, palette=palette
    )
    draw = ImageDraw.Draw(image)
    group_font = _load_font(TEXT_FONT, 22)
    header_font = _load_font(LATIN_FONT, 14)
    rank_font = _load_font(LATIN_FONT, 18)
    team_font = _load_font(TEXT_FONT, 19)
    stat_font = _load_font(LATIN_FONT, 19)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    for grid_row in grid_rows:
        row_card_height = (
            group_header_height
            + max(len(group.rows) for group in grid_row) * row_height
            + 20
        )
        for col_index, group in enumerate(grid_row):
            x0 = padding + col_index * (card_width + gap)
            x1 = x0 + card_width
            draw.rectangle(
                (x0, cursor_y, x1, cursor_y + row_card_height),
                fill=palette.panel_alt,
                outline=palette.border,
                width=1,
            )
            draw.rectangle(
                (x0, cursor_y, x0 + 5, cursor_y + row_card_height), fill=palette.accent
            )
            draw.text(
                (x0 + 24, cursor_y + 16), group.name, font=group_font, fill=palette.text
            )
            headers = (
                ("TEAM", x0 + 84),
                ("REC", x1 - 280),
                ("MAP", x1 - 202),
                ("RND", x1 - 126),
                ("+/-", x1 - 54),
            )
            for label, center_x in headers:
                bbox = draw.textbbox((0, 0), label, font=header_font)
                draw.text(
                    (center_x - (bbox[2] - bbox[0]) / 2, cursor_y + 57),
                    label,
                    font=header_font,
                    fill=palette.text_muted,
                )
            y = cursor_y + group_header_height
            for rank, row in enumerate(group.rows, start=1):
                row_fill = palette.panel_soft if rank % 2 == 0 else palette.panel_alt
                draw.rectangle((x0 + 8, y, x1 - 8, y + row_height - 2), fill=row_fill)
                state_color = palette.accent
                if row.position_state == "advance":
                    state_color = (51, 190, 123)
                elif row.position_state == "eliminated":
                    state_color = (121, 124, 130)
                draw.rectangle(
                    (x0 + 8, y, x0 + 12, y + row_height - 2), fill=state_color
                )
                _draw_centered_text(
                    draw,
                    (x0 + 18, y, x0 + 54, y + row_height - 2),
                    str(rank),
                    rank_font,
                    palette.text_muted,
                )
                logo_box = (x0 + 54, y + 7, x0 + 102, y + 55)
                _draw_logo_badge(
                    image,
                    logo_box,
                    row.logo_path,
                    row.team,
                    radius=7,
                    background=logo_bg,
                    outline=logo_outline,
                )
                team_max = max(card_width - 410, 120)
                draw.text(
                    (x0 + 116, y + 17),
                    _fit_text(draw, row.team, team_font, team_max - 4),
                    font=team_font,
                    fill=palette.text,
                )
                values = (
                    (row.record, x1 - 280),
                    (row.maps, x1 - 202),
                    (row.rounds, x1 - 126),
                    (row.round_diff, x1 - 54),
                )
                for value, center_x in values:
                    fill = _signed_color(value, palette.text)
                    _draw_centered_text(
                        draw,
                        (center_x - 34, y, center_x + 34, y + row_height - 2),
                        value or "-",
                        stat_font,
                        fill,
                    )
                y += row_height
        cursor_y += row_card_height + gap

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)


def _render_bracket_progress(
    progress: RenderTournamentProgress,
    output_path: str | Path,
    *,
    source_name: str,
    palette: RenderTheme,
) -> str:
    padding = 44
    col_width = 270
    col_gap = 52
    match_height = 100
    match_stride = 122
    # Four double-elimination groups produce eight sections; keep all groups.
    sections = progress.brackets
    max_rounds = max((len(section.rounds) for section in sections), default=1)
    width = max(
        1440, padding * 2 + max_rounds * col_width + max(max_rounds - 1, 0) * col_gap
    )
    section_heights: list[int] = []
    for section in sections:
        max_matches = max(
            (len(round_item.matches) for round_item in section.rounds), default=1
        )
        section_heights.append(92 + max_matches * match_stride + 24)
    height = (
        188 + sum(section_heights) + max(len(section_heights) - 1, 0) * 20 + padding
    )
    image = Image.new("RGBA", (width, height), palette.page_base)
    _draw_background(image, palette)
    cursor_y = _draw_progress_header(
        image, progress, source_name=source_name, palette=palette
    )
    draw = ImageDraw.Draw(image)
    section_font = _load_font(LATIN_FONT, 17)
    round_font = _load_font(TEXT_FONT, 16)
    team_font = _load_font(TEXT_FONT, 15)
    score_font = _load_font(LATIN_FONT, 20)
    small_font = _load_font(TEXT_FONT, 12)
    logo_bg = _logo_background(palette)
    logo_outline = _logo_outline(palette)

    for section_index, section in enumerate(sections):
        if section_index:
            cursor_y += 20
        section_height = section_heights[section_index]
        draw.rectangle(
            (padding, cursor_y, width - padding, cursor_y + section_height),
            fill=palette.panel_alt,
            outline=palette.border,
            width=1,
        )
        draw.rectangle(
            (padding, cursor_y, padding + 5, cursor_y + section_height),
            fill=palette.accent,
        )
        draw.text(
            (padding + 20, cursor_y + 14),
            section.name.upper(),
            font=section_font,
            fill=palette.accent,
        )
        round_top = cursor_y + 82
        max_matches = max(
            (len(round_item.matches) for round_item in section.rounds), default=1
        )
        available_height = max_matches * match_stride
        positions_by_round: list[list[int]] = []
        for round_item in section.rounds:
            count = max(len(round_item.matches), 1)
            slot = available_height / count
            positions_by_round.append(
                [
                    int(round_top + slot * (index + 0.5) - match_height / 2)
                    for index in range(count)
                ]
            )

        line_color = (
            palette.accent
            if palette.name.startswith("premium_")
            else palette.text_muted
        )
        for round_index in range(len(section.rounds) - 1):
            current_positions = positions_by_round[round_index]
            next_positions = positions_by_round[round_index + 1]
            x_right = padding + round_index * (col_width + col_gap) + col_width
            x_left = padding + (round_index + 1) * (col_width + col_gap)
            mid_x = (x_right + x_left) // 2
            for item_index, item_y in enumerate(current_positions):
                target_index = min(
                    int(
                        item_index
                        * len(next_positions)
                        / max(len(current_positions), 1)
                    ),
                    len(next_positions) - 1,
                )
                y0 = item_y + match_height // 2
                y1 = next_positions[target_index] + match_height // 2
                draw.line((x_right, y0, mid_x, y0), fill=(*line_color, 100), width=2)
                draw.line((mid_x, y0, mid_x, y1), fill=(*line_color, 100), width=2)
                draw.line((mid_x, y1, x_left, y1), fill=(*line_color, 100), width=2)

        for round_index, round_item in enumerate(section.rounds):
            x0 = padding + round_index * (col_width + col_gap)
            draw.text(
                (x0 + 10, cursor_y + 48),
                _fit_text(draw, round_item.name, round_font, col_width - 20),
                font=round_font,
                fill=palette.text,
            )
            for match_index, match in enumerate(round_item.matches):
                y = positions_by_round[round_index][match_index]
                draw.rectangle(
                    (x0, y, x0 + col_width, y + match_height),
                    fill=palette.metric_box,
                    outline=palette.border,
                    width=1,
                )
                for team_index, (team, score, logo_path) in enumerate(
                    (
                        (match.team_a, match.score_a, match.logo_a_path),
                        (match.team_b, match.score_b, match.logo_b_path),
                    )
                ):
                    team_y = y + 4 + team_index * 38
                    is_winner = match.winner == team_index + 1
                    if is_winner:
                        draw.rectangle(
                            (x0, team_y - 1, x0 + col_width, team_y + 35),
                            fill=(*palette.accent, 32),
                        )
                        draw.rectangle(
                            (x0, team_y - 1, x0 + 4, team_y + 35), fill=palette.accent
                        )
                    logo_box = (x0 + 10, team_y, x0 + 44, team_y + 34)
                    _draw_logo_badge(
                        image,
                        logo_box,
                        logo_path,
                        team,
                        radius=5,
                        background=logo_bg,
                        outline=logo_outline,
                    )
                    text_fill = (
                        palette.text
                        if is_winner or match.winner == 0
                        else palette.text_muted
                    )
                    draw.text(
                        (x0 + 52, team_y + 7),
                        _fit_text(draw, team, team_font, 163),
                        font=team_font,
                        fill=text_fill,
                    )
                    _draw_right_text(
                        draw,
                        x0 + col_width - 14,
                        team_y + 5,
                        score or "-",
                        score_font,
                        text_fill,
                    )
                if match.status:
                    draw.text(
                        (x0 + 12, y + 81),
                        _fit_text(draw, match.status, small_font, col_width - 24),
                        font=small_font,
                        fill=palette.text_muted,
                    )
        cursor_y += section_height

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_opaque_png(image, output, palette)
    return str(output)
