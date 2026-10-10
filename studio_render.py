"""Studio: restrained sports typography, clear hierarchy, native 2x rendering."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from .render import (
        CJK_BOLD_FONT,
        TEXT_FONT,
        _shorten_team_display_name,
        _shorten_tournament_name,
    )
    from .studio_assets import prepared_logo
except ImportError:
    from render import (
        CJK_BOLD_FONT,
        TEXT_FONT,
        _shorten_team_display_name,
        _shorten_tournament_name,
    )
    from studio_assets import prepared_logo

LATIN = "/usr/share/fonts/opentype/inter/InterDisplay-Regular.otf"
BOLD = "/usr/share/fonts/opentype/inter/InterDisplay-SemiBold.otf"
BLACK = "/usr/share/fonts/opentype/inter/InterDisplay-ExtraBold.otf"


@lru_cache(maxsize=160)
def font(text, size, bold=False):
    path = (
        (BOLD if bold else LATIN)
        if text.isascii()
        else (CJK_BOLD_FONT if bold else TEXT_FONT)
    )
    try:
        return ImageFont.truetype(path, round(size * 2))
    except OSError:
        return ImageFont.truetype(TEXT_FONT, round(size * 2))


class Canvas:
    def __init__(self, width, height, theme="studio_dark"):
        self.width = width
        self.height = height
        self.light = theme == "studio_light"
        self.bg = "#F3F2EB" if self.light else "#131917"
        self.panel = "#FCFCF7" if self.light else "#1B2320"
        self.ink = "#17201B" if self.light else "#F0F3E9"
        self.muted = "#687569" if self.light else "#A4B2A6"
        self.line = "#D4DBCF" if self.light else "#344039"
        self.accent = "#4E681D" if self.light else "#D4EE8A"
        self.soft = "#E5ECD7" if self.light else "#293925"
        self.red = "#A63739" if self.light else "#FF9B8F"
        self.image = Image.new("RGB", (width * 2, height * 2), self.bg)
        self.draw = ImageDraw.Draw(self.image)

    def rect(self, box, color=None, radius=0, outline=None):
        box = tuple(round(v * 2) for v in box)
        self.draw.rounded_rectangle(
            box, radius=round(radius * 2), fill=color, outline=outline, width=2
        )

    def rule(self, x, y, x2, y2=None, color=None, width=1):
        self.draw.line(
            (
                round(x * 2),
                round(y * 2),
                round(x2 * 2),
                round((y if y2 is None else y2) * 2),
            ),
            fill=color or self.line,
            width=max(1, round(width * 2)),
        )

    def text(
        self,
        x,
        y,
        value,
        size=24,
        color=None,
        bold=False,
        width=None,
        align="left",
        minimum=18,
    ):
        value = "—" if value is None or value == "" else str(value)
        f = font(value, size, bold)
        while (
            width and self.draw.textlength(value, font=f) > width * 2 and size > minimum
        ):
            size -= 1
            f = font(value, size, bold)
        if width and self.draw.textlength(value, font=f) > width * 2:
            while value and self.draw.textlength(value + "…", font=f) > width * 2:
                value = value[:-1]
            value += "…"
        anchor = {"left": "lt", "center": "mt", "right": "rt"}[align]
        self.draw.text(
            (round(x * 2), round(y * 2)),
            value,
            font=f,
            fill=color or self.ink,
            anchor=anchor,
        )

    def lines(self, text, width, size=25):
        f = font(str(text), size)
        rows = []
        for paragraph in str(text).splitlines():
            line = ""
            for ch in paragraph:
                if line and self.draw.textlength(line + ch, font=f) > width * 2:
                    rows.append(line)
                    line = ch
                else:
                    line += ch
            rows.append(line)
        return rows

    def logo(self, path, x, y, size, name="V"):
        box = (round(x * 2), round(y * 2), round((x + size) * 2), round((y + size) * 2))
        try:
            if not path:
                raise ValueError("asset unavailable")
            rgba = prepared_logo(path, size, self.light, name)
            offset = (
                box[0] + round((size * 2 - rgba.width) / 2),
                box[1] + round((size * 2 - rgba.height) / 2),
            )
            self.image.paste(rgba, offset, rgba)
        except (OSError, TypeError, ValueError):
            initials = (
                "".join(part[0] for part in re.findall(r"[\w]+", name))[:3] or "V"
            )
            self.text(
                x + size / 2,
                y + size * 0.29,
                initials,
                size * 0.34,
                self.accent,
                True,
                align="center",
                minimum=10,
            )

    def portrait(self, path, x, y, size, name):
        try:
            if not path:
                raise ValueError("asset unavailable")
            with Image.open(path) as source:
                image = ImageOps.fit(
                    source.convert("RGBA"),
                    (size * 2, size * 2),
                    method=Image.Resampling.LANCZOS,
                )
            mask = Image.new("L", image.size)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, size * 2 - 1, size * 2 - 1), radius=12, fill=255
            )
            from PIL import ImageChops

            mask = ImageChops.multiply(mask, image.getchannel("A"))
            self.image.paste(image, (round(x * 2), round(y * 2)), mask)
        except (OSError, TypeError, ValueError):
            self.logo(None, x, y, size, name)

    def flag(self, path, x, y, code):
        try:
            if not path:
                raise ValueError("asset unavailable")
            with Image.open(path) as source:
                flag = ImageOps.contain(
                    source.convert("RGBA"), (48, 32), method=Image.Resampling.LANCZOS
                )
            self.image.paste(
                flag, (round(x * 2), round(y * 2) + (32 - flag.height) // 2), flag
            )
        except (OSError, TypeError, ValueError):
            pass
        if code:
            self.text(x + 33, y + 1, code.upper(), 14, self.muted, width=90, minimum=12)

    def icon(self, path, x, y, size):
        try:
            if not path:
                return
            with Image.open(path) as source:
                asset = source.convert("RGBA")
            asset.thumbnail(
                (round(size * 2), round(size * 2)), Image.Resampling.LANCZOS
            )
            self.image.paste(
                asset,
                (
                    round(x * 2) + (round(size * 2) - asset.width) // 2,
                    round(y * 2) + (round(size * 2) - asset.height) // 2,
                ),
                asset,
            )
        except (OSError, TypeError, ValueError):
            pass

    def photo(self, path, box):
        try:
            if not path:
                raise ValueError("asset unavailable")
            with Image.open(path) as asset:
                fitted = ImageOps.fit(
                    asset.convert("RGB"),
                    (round((box[2] - box[0]) * 2), round((box[3] - box[1]) * 2)),
                    method=Image.Resampling.LANCZOS,
                )
                dark = Image.new("RGB", fitted.size, "#111815")
                fitted = Image.blend(fitted, dark, 0.64)
                self.image.paste(fitted, (round(box[0] * 2), round(box[1] * 2)))
                return True
        except (OSError, TypeError, ValueError):
            return False

    def header(self, section, title, subtitle="", source="VLR.gg", logo=None):
        p = 64
        right = self.width - p
        self.rect((p, 45, p + 12, 57), self.accent, 2)
        self.text(p + 25, 42, "VAL MATCH  /  " + section, 18, self.muted, True)
        self.text(p, 92, title, 62, bold=True, width=self.width - 280, minimum=40)
        if logo:
            self.logo(logo, right - 58, 92, 58, "VCT")
        self.text(p, 177, subtitle, 22, self.muted, width=self.width - 128)
        self.rule(p, 225, right)

    def footer(self, source="VLR.gg", note=""):
        y = self.height - 61
        self.rule(64, y - 17, self.width - 64)
        self.text(64, y, "VAL MATCH   /   " + source.upper(), 15, self.muted, True)
        if note:
            self.text(
                self.width - 64,
                y,
                note,
                16,
                self.muted,
                align="right",
                width=self.width - 460,
                minimum=13,
            )

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize((self.width, self.height), Image.Resampling.LANCZOS).save(
            path, format="PNG", optimize=True
        )
        return str(path)


def stage_label(value):
    text = str(value or "")
    for old, new in [
        ("Group Stage", "小组赛"),
        ("Upper Bracket", "胜者组"),
        ("Lower Bracket", "败者组"),
        ("Winner's", "胜者组对决"),
        ("Elimination", "淘汰战"),
        ("Decider", "出线决定战"),
        ("Opening", "首轮对决"),
        ("Grand Final", "总决赛"),
        ("Upper Final", "胜者组决赛"),
        ("Lower Final", "败者组决赛"),
        ("Semifinals", "半决赛"),
        ("Quarterfinals", "四分之一决赛"),
        ("Playoffs", "淘汰赛"),
    ]:
        text = text.replace(old, new)
    return (
        re.sub(r"\s*[–—]\s*", " · ", text)
        .replace("Stage-", "Stage · ")
        .replace("赛-", "赛 · ")
    )


def state_color(c, status):
    return c.red if status == "进行中" else c.accent if status == "已结束" else c.muted


def scores(value):
    found = re.fullmatch(r"\s*(\d+)\s*[:：\-]\s*(\d+)\s*", str(value))
    return (int(found[1]), int(found[2])) if found else (None, None)


def schedule(
    matches, target_date, path, *, source_name, eyebrow_text, title_text, theme
):
    sections = []
    for m in matches:
        if sections and sections[-1][0] == m.day_label:
            sections[-1][1].append(m)
        else:
            sections.append((m.day_label, [m]))
    if not sections:
        sections = [(target_date.isoformat(), [])]
    heights = [
        max(212, len(items) * 212 + max(0, len(items) - 1) * 14)
        for _, items in sections
    ]
    height = 278 + sum(heights) + len(sections) * 34 + 86
    c = Canvas(1440, height, theme)
    count = sum(not m.is_placeholder for m in matches)
    c.header(
        "MATCHDAY",
        "赛事日历",
        f"{title_text}  /  {count} 场比赛  /  {target_date.year}",
        source_name,
    )
    c.text(1376, 110, target_date.strftime("%m.%d"), 50, c.accent, True, align="right")
    y = 268
    for (label, items), block_h in zip(sections, heights):
        found = re.search(r"(\d{4})-(\d{2})-(\d{2})", label)
        day = f"{found[2]}.{found[3]}" if found else label[:8]
        prefix = label.split("·")[0].strip() if "·" in label else "赛程"
        today = found and f"{found[1]}-{found[2]}-{found[3]}" == target_date.isoformat()
        c.text(64, y + 9, prefix, 24, c.accent if today else c.muted, True, width=168)
        c.text(64, y + 54, day, 48, bold=True, width=178)
        c.text(
            64,
            y + 119,
            label.split("·")[-1].strip() if "·" in label else "",
            20,
            c.muted,
            width=176,
        )
        c.rect((251, y + 5, 254, y + block_h - 5), c.accent if today else c.line)
        if not items:
            c.text(289, y + 66, "暂无已确认的比赛", 30, c.muted)
        for i, m in enumerate(items):
            top = y + i * 226
            x = 284
            right = 1376
            center = (x + 199 + right) / 2
            c.rect((x, top, right, top + 212), c.panel, 10)
            if m.is_placeholder:
                c.text(
                    x + 28, top + 53, m.placeholder_text or "此日暂无比赛", 29, c.muted
                )
                continue
            color = state_color(c, m.status)
            c.text(
                x + 209,
                top + 20,
                _shorten_tournament_name(m.tournament_name)
                + "  /  "
                + stage_label(m.schedule_name),
                18,
                c.muted,
                width=right - x - 312,
                minimum=14,
            )
            c.text(
                right - 24,
                top + 20,
                (m.best_of or "BO?").upper(),
                18,
                c.muted,
                True,
                align="right",
            )
            c.text(x + 24, top + 56, "开赛", 16, c.muted)
            c.text(
                x + 24,
                top + 88,
                m.start_time or "--:--",
                40,
                bold=True,
                width=132,
                minimum=25,
            )
            c.text(x + 24, top + 147, m.status, 18, color, width=132)
            c.rule(x + 176, top + 53, x + 176, top + 183)
            a, b = scores(m.score)
            c.logo(m.logo_a_path, x + 199, top + 78, 88, m.team_a)
            c.logo(m.logo_b_path, right - 114, top + 78, 88, m.team_b)
            c.text(
                x + 306,
                top + 107,
                _shorten_team_display_name(m.team_a),
                29,
                c.accent if a is not None and a > b else c.ink,
                True,
                width=214,
                minimum=20,
            )
            c.text(
                right - 133,
                top + 107,
                _shorten_team_display_name(m.team_b),
                29,
                c.accent if b is not None and b > a else c.ink,
                True,
                width=214,
                minimum=20,
                align="right",
            )
            if a is None:
                c.text(center, top + 113, "VS", 35, c.muted, True, align="center")
            else:
                c.text(
                    center - 24,
                    top + 104,
                    a,
                    49,
                    c.accent if a > b else c.ink,
                    True,
                    align="right",
                    width=55,
                )
                c.text(center, top + 114, ":", 30, c.muted, align="center")
                c.text(
                    center + 24,
                    top + 104,
                    b,
                    49,
                    c.accent if b > a else c.ink,
                    True,
                    width=55,
                )
        y += block_h + 34
    c.footer(source_name, "时间按展示时区 · 高亮为已确认胜队")
    return c.save(path)


def report(result, path, *, source_name, theme):
    groups = {}
    for player in result.players:
        groups.setdefault(player.team or "选手", []).append(player)
    grouped = list(groups.items())
    row_height = 76
    group_header_height = 80
    probe = Canvas(1600, 500, theme)
    comment_lines = (
        probe.lines(result.comment, 1396, 26) if result.comment.strip() else []
    )
    table_h = (
        sum(group_header_height + len(rows) * row_height for _, rows in grouped)
        + max(0, len(grouped) - 1) * 24
        if grouped
        else 156
    )
    comment_h = 32 + 44 + len(comment_lines) * 38 + 24 if comment_lines else 0
    map_columns = 2 if len(result.maps) == 4 else max(1, min(3, len(result.maps)))
    map_rows = max(1, math.ceil(len(result.maps) / map_columns))
    extra_map_height = (map_rows - 1) * 154
    height = 696 + extra_map_height + table_h + comment_h + 100
    c = Canvas(1600, height, theme)
    event = _shorten_tournament_name(result.tournament_name)
    c.header(
        "FULL TIME",
        "全场战报",
        event + "  /  " + stage_label(result.schedule_name or "全场赛果"),
        source_name,
        result.event_logo_path,
    )
    a, b = scores(result.score)
    winner = 0 if a is None or a == b else 1 if a > b else 2
    c.text(
        800,
        253,
        (result.best_of or "BO?").upper() + "  /  FINAL",
        18,
        c.muted,
        True,
        align="center",
    )
    for side, name, logo, center in [
        (1, result.team_a, result.team_a_logo_path, 335),
        (2, result.team_b, result.team_b_logo_path, 1265),
    ]:
        c.logo(logo, center - 44, 287, 88, name)
        c.text(
            center,
            393,
            _shorten_team_display_name(name),
            37,
            bold=True,
            align="center",
            width=415,
            minimum=23,
        )
        if winner == side:
            c.rect((center - 62, 447, center + 62, 477), c.soft, 5)
            c.text(center, 453, "胜出", 18, c.accent, True, align="center")
    c.text(
        747,
        304,
        "—" if a is None else a,
        140,
        c.accent if winner == 1 else c.ink,
        True,
        align="right",
    )
    c.text(800, 349, ":", 66, c.muted, align="center")
    c.text(
        853, 304, "—" if b is None else b, 140, c.accent if winner == 2 else c.ink, True
    )
    c.rule(64, 502, 1536)
    maps = result.maps
    if maps:
        gap = 16
        card_width = (1472 - gap * (map_columns - 1)) / map_columns
        for i, m in enumerate(maps):
            row, col = divmod(i, map_columns)
            row_items = min(map_columns, len(maps) - row * map_columns)
            offset = (1472 - (row_items * card_width + (row_items - 1) * gap)) / 2
            x = 64 + offset + col * (card_width + gap)
            y = 526 + row * 154
            c.rect((x, y, x + card_width, y + 138), c.panel, 8)
            photo = c.photo(m.image_path, (x, y, x + card_width, y + 138))
            ink = "#F0F3E9" if photo else c.ink
            muted = "#B5C2B6" if photo else c.muted
            c.text(x + 19, y + 16, f"MAP {i + 1:02}", 14, muted, True)
            if m.pick:
                c.text(
                    x + card_width - 19,
                    y + 16,
                    "选图 · " + _shorten_team_display_name(m.pick),
                    14,
                    muted,
                    align="right",
                    width=card_width - 122,
                    minimum=11,
                )
            c.text(x + 19, y + 44, m.map_name, 23, ink, True, width=card_width - 38)
            c.text(
                x + 19,
                y + 83,
                f"{m.team_a_score}  :  {m.team_b_score}",
                34,
                ink,
                True,
                width=card_width - 100,
            )
            if m.duration:
                c.text(
                    x + card_width - 19, y + 96, m.duration, 14, muted, align="right"
                )
    else:
        c.text(64, 552, "地图明细暂不可用", 25, c.muted)
    y = 696 + extra_map_height
    if not grouped:
        c.text(64, y + 24, "选手统计暂不可用", 27, c.muted)
        y += table_h
    top_acs = max(
        (
            float(p.acs)
            for p in result.players
            if str(p.acs).replace(".", "", 1).isdigit()
        ),
        default=None,
    )
    stat_columns = [
        ("Rating", 621, 76),
        ("ACS", 709, 76),
        ("K / D / A", 842, 164),
        ("K/D ±", 975, 68),
        ("KAST", 1063, 80),
        ("ADR", 1155, 80),
        ("HS%", 1247, 76),
        ("FK / FD", 1351, 110),
        ("FK/FD ±", 1462, 74),
    ]
    for index, (team, rows) in enumerate(grouped):
        if index:
            y += 24
        name = [result.team_a, result.team_b][index] if index < 2 else team
        logo = (
            [result.team_a_logo_path, result.team_b_logo_path][index]
            if index < 2
            else None
        )
        c.rect((64, y, 1536, y + group_header_height - 8), c.panel, 8)
        c.logo(logo, 82, y + 17, 38, name)
        c.text(
            138,
            y + 14,
            _shorten_team_display_name(name),
            25,
            bold=True,
            width=360,
            minimum=18,
        )
        c.text(138, y + 45, team + "  /  整场选手数据", 15, c.muted, width=400)
        for title, cx, col_width in stat_columns:
            c.text(
                cx,
                y + 30,
                title,
                16,
                c.muted,
                True,
                align="center",
                width=col_width,
                minimum=12,
            )
        y += group_header_height
        for r, p in enumerate(rows):
            yy = y + r * row_height
            highlighted = (
                p.stats_available
                and top_acs is not None
                and str(p.acs).replace(".", "", 1).isdigit()
                and float(p.acs) == top_acs
            )
            if highlighted:
                c.rect((64, yy - 2, 1536, yy + 68), c.soft, 5)
            elif r % 2 == 0:
                c.rect((64, yy - 2, 1536, yy + 68), c.panel, 5)
            c.portrait(p.avatar_path, 82, yy + 4, 52, p.player)
            c.text(148, yy + 6, p.player, 23, bold=True, width=224, minimum=16)
            c.flag(p.country_flag_path, 148, yy + 39, "")
            nationality = (
                " · ".join(
                    str(value) for value in [p.country_code, p.country_name] if value
                )
                or "—"
            )
            c.text(181, yy + 40, nationality, 14, c.muted, width=193, minimum=11)
            agent_paths = p.agent_image_paths or []
            if agent_paths:
                icon_size = min(
                    42, (174 - max(0, len(agent_paths) - 1) * 5) / len(agent_paths)
                )
                for i, agent_path in enumerate(agent_paths):
                    c.icon(agent_path, 388 + i * (icon_size + 5), yy + 6, icon_size)
                c.text(
                    388,
                    yy + 55,
                    ", ".join(p.agents),
                    12,
                    c.muted,
                    width=174,
                    minimum=10,
                )
            else:
                c.text(
                    388,
                    yy + 27,
                    ", ".join(p.agents) or "—",
                    15,
                    c.muted,
                    width=174,
                    minimum=11,
                )

            def value(v):
                return "—" if v is None or v == "" else str(v)

            values = [
                value(p.rating),
                value(p.acs),
                f"{value(p.kills)}/{value(p.deaths)}/{value(p.assists)}",
                value(p.kd_diff),
                value(p.kast),
                value(p.adr),
                value(p.headshot_percent),
                f"{value(p.first_kills)}/{value(p.first_deaths)}",
                value(p.fk_diff),
            ]
            for (title, cx, col_width), metric in zip(stat_columns, values):
                if not p.stats_available:
                    metric = "—"
                color = (
                    c.accent
                    if title == "ACS" and highlighted
                    else c.accent
                    if metric.startswith("+")
                    else c.red
                    if metric.startswith("-") and metric != "—"
                    else c.ink
                )
                c.text(
                    cx,
                    yy + 24,
                    metric,
                    23,
                    color,
                    title in ["Rating", "ACS"],
                    align="center",
                    width=col_width - 6,
                    minimum=15,
                )
            c.rule(64, yy + 71, 1536)
        y += len(rows) * row_height
    if comment_lines:
        y += 32
        c.rect((64, y, 69, y + 35 + len(comment_lines) * 38), c.accent)
        c.text(91, y, "赛后锐评", 23, c.accent, True)
        for i, line in enumerate(comment_lines):
            c.text(91, y + 44 + i * 38, line, 26, width=1396)
    c.footer(source_name, "整场统计 · 高亮为 ACS 领跑 · — 为数据暂缺")
    return c.save(path)


def market_support(left_odds, right_odds):
    """Normalized implied shares; require two finite, valid decimal odds."""
    try:
        left, right = float(left_odds), float(right_odds)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 1 for v in (left, right)):
        return None
    a, b = 1 / left, 1 / right
    return a / (a + b), b / (a + b)


def support_bar(c, box, left_share, left_color, right_color):
    x0, y0, x1, y1 = (round(v * 2) for v in box)
    width, height = x1 - x0, y1 - y0
    bar = Image.new("RGB", (width, height), right_color)
    split = round(width * left_share)
    if split > 0:
        ImageDraw.Draw(bar).rectangle((0, 0, split - 1, height - 1), fill=left_color)
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=height // 2, fill=255
    )
    c.image.paste(bar, (x0, y0), mask)
    if 0 < split < width:
        c.rule(
            (x0 + split) / 2, y0 / 2 + 4, (x0 + split) / 2, y1 / 2 - 4, c.panel, width=2
        )


def notice(data, path, *, source_name, theme):
    rows = data.head_to_head
    has_odds = bool(data.team_a_odds or data.team_b_odds)
    has_reference = has_odds or bool(data.betting_info)
    support = market_support(data.team_a_odds, data.team_b_odds)
    reference_height = (
        300 if support else 170 if has_odds else 140 if has_reference else 0
    )
    height = 830 + max(1, len(rows)) * 63 + reference_height
    c = Canvas(1440, height, theme)
    c.header(
        "STARTING SOON",
        "比赛即将开始",
        _shorten_tournament_name(data.tournament_name)
        + "  /  "
        + stage_label(data.schedule_name),
        source_name,
        data.event_logo_path,
    )
    c.text(
        720,
        263,
        "开赛时间  /  " + (data.best_of or "BO?").upper(),
        22,
        c.muted,
        align="center",
    )
    c.text(720, 312, data.start_time, 116, c.accent, True, align="center")
    for team, logo, center in [
        (data.team_a, data.team_a_logo_path, 365),
        (data.team_b, data.team_b_logo_path, 1075),
    ]:
        c.logo(logo, center - 53, 462, 106, team)
        c.text(
            center,
            600,
            _shorten_team_display_name(team),
            41,
            bold=True,
            align="center",
            width=500,
            minimum=24,
        )
    c.text(720, 508, "VS", 35, c.muted, True, align="center")
    c.rule(64, 678, 1376)
    if has_reference:
        if support:
            blue = "#35749E" if c.light else "#83B8E2"
            c.text(64, 704, "赛前支持率", 25, bold=True)
            c.text(
                1376, 710, "来源：双方赔率换算", 18, c.muted, align="right", width=700
            )
            left_percent = round(support[0] * 100, 1)
            right_percent = round(100 - left_percent, 1)
            for name, value, percent, x, align, color in [
                (data.team_a, data.team_a_odds, left_percent, 64, "left", c.accent),
                (data.team_b, data.team_b_odds, right_percent, 1376, "right", blue),
            ]:
                c.text(
                    x,
                    754,
                    _shorten_team_display_name(name),
                    23,
                    c.muted,
                    align=align,
                    width=580,
                )
                c.text(
                    x, 792, f"{percent:.1f}%", 44, color, True, align=align, width=400
                )
                c.text(x, 846, f"赔率 {value}", 20, c.muted, align=align, width=580)
            support_bar(c, (64, 885, 1376, 917), support[0], c.accent, blue)
            c.text(64, 944, "按双方赔率折算，仅作赛前参考", 18, c.muted, width=1312)
        elif has_odds:
            c.text(64, 704, "赛前指数", 25, bold=True)
            for name, value, x in [
                (data.team_a, data.team_a_odds, 64),
                (data.team_b, data.team_b_odds, 748),
            ]:
                c.text(x, 759, _shorten_team_display_name(name), 23, c.muted, width=410)
                c.text(
                    x + 580,
                    752,
                    value or "暂无",
                    34,
                    bold=True,
                    align="right",
                    width=156,
                )
            c.text(64, 807, "支持率暂缺 · 双方有效赔率未齐", 18, c.muted, width=1312)
        else:
            c.text(64, 704, "赛前指数", 25, bold=True)
            c.text(64, 759, data.betting_info, 23, c.muted, width=1312)
        c.rule(64, 678 + reference_height, 1376)
    c.text(64, 704 + reference_height, "过往交手", 25, bold=True)
    if not rows:
        c.text(64, 759 + reference_height, "暂无双方直接交手记录", 25, c.muted)
    for i, r in enumerate(rows):
        y = 760 + i * 63 + reference_height
        c.text(64, y, r.date_label, 22, c.muted)
        c.text(320, y, r.score, 26, bold=True)
        c.text(472, y, r.event_name, 23, c.muted, width=904)
        c.rule(64, y + 45, 1376)
    c.footer(source_name, "双方历史比分按上方对阵顺序展示")
    return c.save(path)


def standings(data, path, *, source_name, theme):
    height = 276 + sum(104 + max(1, len(g.rows)) * 72 for g in data.groups) + 94
    c = Canvas(1440, max(480, height), theme)
    c.header(
        "STANDINGS",
        "赛事积分榜",
        _shorten_tournament_name(data.event_name)
        + "  /  "
        + stage_label(data.stage_name),
        source_name,
        data.event_logo_path,
    )
    y = 263
    for group in data.groups:
        c.text(64, y, group.name, 29, bold=True)
        labels = [
            ("排名", 64),
            ("战队", 152),
            ("战绩", 772),
            ("地图", 944),
            ("回合", 1110),
            ("净胜回合", 1323),
        ]
        for label, x in labels:
            c.text(x, y + 52, label, 19, c.muted, align="center" if x > 700 else "left")
        y += 95
        if not group.rows:
            c.text(152, y + 17, "暂无积分数据", 26, c.muted)
            y += 72
        for rank, row in enumerate(group.rows, 1):
            color = (
                c.accent
                if row.position_state == "advance"
                else c.red
                if row.position_state == "eliminated"
                else c.ink
            )
            if rank % 2:
                c.rect((64, y - 2, 1376, y + 63), c.panel, 5)
            c.text(86, y + 17, f"{rank:02}", 25, color, True, align="center")
            c.logo(row.logo_path, 151, y + 8, 46, row.team)
            c.text(217, y + 19, row.team, 26, bold=True, width=457)
            for text, x in [
                (row.record, 772),
                (row.maps, 944),
                (row.rounds, 1110),
                (row.round_diff, 1323),
            ]:
                c.text(
                    x,
                    y + 18,
                    text,
                    25,
                    color if x == 1323 else c.ink,
                    True,
                    align="center",
                )
            y += 72
        y += 9
    c.footer(source_name, "青柠 / 晋级  ·  珊瑚 / 淘汰  ·  其余状态以赛事规则为准")
    return c.save(path)


def group_bracket(data, path, *, source_name, theme):
    pairs = [data.brackets[i : i + 2] for i in range(0, len(data.brackets), 2)]
    cell_h = 602
    rows = math.ceil(len(pairs) / 2)
    c = Canvas(1600, 270 + rows * (cell_h + 24) + 80, theme)
    c.header(
        "GROUP STAGE",
        "小组赛出线图",
        _shorten_tournament_name(data.event_name)
        + "  /  "
        + stage_label(data.stage_name),
        source_name,
        data.event_logo_path,
    )
    cell_w = 722
    for index, pair in enumerate(pairs):
        x = 64 + (index % 2) * (cell_w + 28)
        y = 266 + (index // 2) * (cell_h + 24)
        c.rect((x, y, x + cell_w, y + cell_h), c.panel, 12, outline=c.line)
        c.text(x + 22, y + 22, f"小组 {index + 1:02}", 28, bold=True)
        sy = y + 74
        for section in pair:
            body = max(120, max(len(r.matches) for r in section.rounds) * 112)
            c.text(x + 22, sy, stage_label(section.name), 18, c.muted, True)
            top = sy + 53
            positions = []
            col_w = (cell_w - 66) / 2
            for col, r in enumerate(section.rounds):
                cx = x + 22 + col * (col_w + 22)
                c.text(cx, sy + 25, stage_label(r.name), 17, c.muted, width=col_w)
                positions.append(
                    (
                        cx,
                        [
                            top + body * (i + 0.5) / len(r.matches)
                            for i in range(len(r.matches))
                        ],
                    )
                )
            if len(positions) > 1:
                cx, centers = positions[0]
                nx, following = positions[1]
                for i, center in enumerate(centers):
                    if following:
                        end = following[
                            min(
                                len(following) - 1,
                                int(i * len(following) / max(1, len(centers))),
                            )
                        ]
                        middle = cx + col_w + 11
                        c.rule(cx + col_w, center, middle)
                        c.rule(middle, center, middle, end)
                        c.rule(middle, end, nx)
            for r, (cx, centers) in zip(section.rounds, positions):
                for m, center in zip(r.matches, centers):
                    yy = center - 43
                    c.rect((cx, yy, cx + col_w, yy + 86), c.bg, 7)
                    for side, team, logo, score_value in [
                        (1, m.team_a, m.logo_a_path, m.score_a),
                        (2, m.team_b, m.logo_b_path, m.score_b),
                    ]:
                        ry = yy + 8 + (side - 1) * 42
                        won = m.winner == side
                        c.logo(logo, cx + 10, ry, 27, team)
                        c.text(
                            cx + 47,
                            ry + 4,
                            team,
                            19,
                            c.accent if won else c.ink,
                            won,
                            width=col_w - 88,
                            minimum=13,
                        )
                        c.text(
                            cx + col_w - 14,
                            ry + 3,
                            score_value,
                            22,
                            c.accent if won else c.muted,
                            True,
                            align="right",
                        )
            sy = top + body + 22
    c.footer(source_name, "高亮为已确认胜队 · 各组按数据源顺序排列")
    return c.save(path)


def bracket(data, path, *, source_name, theme):
    is_group = "Group Stage" in data.stage_name or "小组" in data.stage_name
    if (
        is_group
        and len(data.brackets) >= 4
        and len(data.brackets) % 2 == 0
        and all(
            s.rounds
            and len(s.rounds) <= 2
            and all(len(r.matches) <= 2 for r in s.rounds)
            for s in data.brackets
        )
    ):
        return group_bracket(data, path, source_name=source_name, theme=theme)
    pages = []
    for section in data.brackets:
        for first in range(0, len(section.rounds), 5):
            rounds = section.rounds[first : first + 5]
            body = max(220, max((len(r.matches) for r in rounds), default=1) * 126)
            pages.append((section.name, first, rounds, body))
    height = 266 + sum(body + 132 for _, _, _, body in pages) + 84
    width = max(
        1440, 128 + max((len(rounds) for _, _, rounds, _ in pages), default=1) * 266
    )
    c = Canvas(width, max(480, height), theme)
    c.header(
        "GROUP STAGE" if is_group else "PLAYOFFS",
        "小组赛出线图" if is_group else "淘汰赛晋级图",
        _shorten_tournament_name(data.event_name)
        + "  /  "
        + stage_label(data.stage_name),
        source_name,
        data.event_logo_path,
    )
    y = 265
    for section, first, rounds, body in pages:
        c.text(64, y, stage_label(section) + (" · 续" if first else ""), 27, bold=True)
        top = y + 96
        positions = []
        col_width = (width - 128 - (len(rounds) - 1) * 26) / max(1, len(rounds))
        for col, r in enumerate(rounds):
            x = 64 + col * (col_width + 26)
            c.text(x, y + 48, stage_label(r.name), 20, c.muted, True, width=col_width)
            centers = [
                top + body * (i + 0.5) / len(r.matches) for i in range(len(r.matches))
            ]
            positions.append((x, centers))
        for col in range(len(rounds) - 1):
            x, centers = positions[col]
            next_x, next_centers = positions[col + 1]
            for i, cy in enumerate(centers):
                if not next_centers:
                    continue
                j = min(
                    len(next_centers) - 1,
                    int(i * len(next_centers) / max(1, len(centers))),
                )
                ny = next_centers[j]
                middle = x + col_width + 13
                c.rule(x + col_width, cy, middle)
                c.rule(middle, cy, middle, ny)
                c.rule(middle, ny, next_x)
        for col, r in enumerate(rounds):
            x, centers = positions[col]
            for m, cy in zip(r.matches, centers):
                yy = cy - 49
                c.rect((x, yy, x + col_width, yy + 98), c.panel, 7, outline=c.line)
                for side, team, logo, score_value in [
                    (1, m.team_a, m.logo_a_path, m.score_a),
                    (2, m.team_b, m.logo_b_path, m.score_b),
                ]:
                    ry = yy + 11 + (side - 1) * 43
                    won = m.winner == side
                    c.logo(logo, x + 12, ry, 30, team)
                    c.text(
                        x + 52,
                        ry + 5,
                        team,
                        19,
                        c.accent if won else c.ink,
                        won,
                        width=col_width - 100,
                        minimum=13,
                    )
                    c.text(
                        x + col_width - 17,
                        ry + 4,
                        score_value,
                        23,
                        c.accent if won else c.muted,
                        True,
                        align="right",
                    )
                c.rule(x + 12, yy + 49, x + col_width - 12)
        y = top + body + 36
    c.footer(source_name, "高亮为已确认胜队 · 完整轮次按赛事结构展示")
    return c.save(path)


def progress(data, path, *, source_name, theme):
    return (
        bracket(data, path, source_name=source_name, theme=theme)
        if data.kind == "bracket" and data.brackets
        else standings(data, path, source_name=source_name, theme=theme)
    )
