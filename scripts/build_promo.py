"""Render a self-contained VAL Match promotion kit from native product graphics.

Requires Pillow, numpy, qrcode and ffmpeg. No real group/member data is loaded.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import wave
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prediction_render import prediction_card, prediction_leaderboard  # noqa: E402

OUT = ROOT / "docs" / "promo"
ASSETS = OUT / "source-assets"
WORK = ROOT / "artifacts" / "promo-090"
MARKET = "https://cloud.astrbot.app/plugin/Kelvin18710/astrbot_plugin_val_match"
BG = "#101713"
PANEL = "#1A241E"
LIME = "#D4EE8A"
WHITE = "#F2F5EB"
MUTED = "#A1B0A3"
LINE = "#35443A"
BLUE = "#75B9F4"
ORANGE = "#FFAD69"
TIMES = [0, 3.2, 6.4, 14.4, 19.2, 24.0, 28.8]
TITLES = [
    "谁比机器人更懂瓦",
    "赛前自动发赛程",
    "点表情选胜队，也能改选",
    "全场战报，一张图复盘",
    "赛后看榜，机器人也参赛",
    "AstrBot 插件市场搜索 VAL Match",
]


@lru_cache(maxsize=160)
def font(size, bold=False, latin=False):
    if latin:
        name = "InterDisplay-ExtraBold.otf" if bold else "InterDisplay-Medium.otf"
        path = Path("/usr/share/fonts/opentype/inter") / name
    else:
        path = Path("/usr/share/fonts/opentype/noto") / (
            "NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc"
        )
    return ImageFont.truetype(str(path), round(size))


def text(im, xy, value, size=32, color=WHITE, bold=False, anchor="lt", latin=False):
    ImageDraw.Draw(im).text(
        xy, str(value), font=font(size, bold, latin), fill=color, anchor=anchor
    )


def rect(im, box, fill=PANEL, radius=24, outline=None, width=1):
    ImageDraw.Draw(im).rounded_rectangle(
        box, radius=radius, fill=fill, outline=outline, width=width
    )


def fit(im, width, height=None):
    if height is None:
        height = round(im.height * width / im.width)
    return im.resize((round(width), round(height)), Image.Resampling.LANCZOS)


def paste(im, asset, xy, opacity=1.0):
    asset = asset.convert("RGBA")
    if opacity < 1:
        asset = asset.copy()
        asset.putalpha(asset.getchannel("A").point(lambda a: round(a * opacity)))
    im.paste(asset, tuple(round(v) for v in xy), asset)


def chip(im, xy, label, *, color=LIME, size=25):
    x, y = xy
    w = round(ImageDraw.Draw(im).textlength(label, font=font(size)) + 38)
    rect(im, (x, y, x + w, y + size + 26), "#273629", (size + 26) // 2)
    text(im, (x + 19, y + 11), label, size, color)
    return w


@lru_cache(maxsize=4)
def background(portrait=False):
    w, h = (1080, 1920) if portrait else (1920, 1080)
    yy, xx = np.mgrid[0:h, 0:w]
    glow = np.exp(
        -(((xx - w * 0.82) / (w * 0.6)) ** 2 + ((yy - h * 0.3) / (h * 0.7)) ** 2) * 2
    )
    base = np.array([16, 23, 19], dtype=np.float32)
    rgb = np.clip(base + glow[:, :, None] * np.array([7, 12, 5]), 0, 255).astype(
        np.uint8
    )
    im = Image.fromarray(rgb).convert("RGBA")
    d = ImageDraw.Draw(im)
    for x in range(0, w, 96):
        d.line((x, 0, x, h), fill="#1B251E", width=1)
    for y in range(0, h, 96):
        d.line((0, y, w, y), fill="#1B251E", width=1)
    for x in [int(w * 0.7), int(w * 0.9), int(w * 1.1)]:
        d.line((x, 0, x - 330, h), fill="#273325", width=1)
    margin = 64 if portrait else 96
    rect(im, (margin, 55, margin + 10, 87), LIME, 3)
    text(im, (margin + 28, 51), "VAL MATCH", 34, bold=True, latin=True)
    text(im, (w - margin, 59), "FOR ASTRBOT", 21, MUTED, anchor="rt", latin=True)
    return im


def footer(im, portrait=False):
    w, h = im.size
    x = 64 if portrait else 96
    s = 20 if portrait else 17
    text(
        im,
        (x, h - (93 if portrait else 69)),
        "功能演示 · 竞猜与成员数据为虚构样例",
        s,
        MUTED,
    )
    text(
        im,
        (w - x, h - (62 if portrait else 69)),
        "开源 / v0.9.0",
        s,
        MUTED,
        anchor="rt",
    )


def qr_image(size=300):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=8
    )
    qr.add_data(MARKET)
    qr.make(fit=True)
    im = qr.make_image(fill_color="#101713", back_color="white").convert("RGB")
    return im.resize((size, size), Image.Resampling.NEAREST).convert("RGBA")


def avatar(name, color, dest, bot=False):
    im = Image.new("RGB", (200, 200), color)
    d = ImageDraw.Draw(im)
    if bot:
        d.rounded_rectangle((43, 61, 157, 151), 24, fill="#E5ECD7")
        d.line((100, 45, 100, 61), fill=LIME, width=8)
        d.ellipse((88, 25, 112, 49), fill=LIME)
        for x in (77, 123):
            d.ellipse((x - 9, 89, x + 9, 107), fill="#33463A")
        d.line((79, 129, 121, 129), fill="#33463A", width=6)
    else:
        d.ellipse((65, 30, 135, 104), fill="#EBD5B7")
        d.rounded_rectangle((35, 112, 165, 225), 55, fill="#D5E3D0")
        d.pieslice((63, 22, 141, 92), 180, 355, fill="#26342B")
        d.rounded_rectangle((68, 150, 132, 184), 12, fill=color)
        text(im, (100, 156), name[:1], 22, WHITE, bold=True, anchor="mt")
    im.save(dest)


def product_assets():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    now = datetime.fromisoformat("2026-10-21T23:40:00+08:00")
    payload = {
        "team_a": "EDward Gaming",
        "team_b": "Paper Rex",
        "tournament": "VCT · 功能演示",
        "start_at": now.replace(hour=20, minute=0).isoformat(),
        "lock_at": now.replace(hour=19, minute=50).isoformat(),
        "logo_a": str(ASSETS / "edg.png"),
        "logo_b": str(ASSETS / "prx.png"),
    }
    prediction_card(
        payload,
        OUT / "prediction-demo.png",
        bot={"name": "Mira", "state": "ready", "a": 0, "b": 1},
    )
    people = [
        ("观赛搭子", 7, 9, 4, "#476D73"),
        ("Mira", 6, 9, 3, "#66664D"),
        ("早起看比赛", 5, 8, 3, "#90634C"),
        ("最后一图", 4, 7, 2, "#62577A"),
    ]
    rows = []
    for i, (name, hit, settled, streak, color) in enumerate(people):
        path = ASSETS / f"avatar-{i}.png"
        avatar(name, color, path, bot=name == "Mira")
        rows.append(
            {
                "name": name,
                "user_id": f"fictional-{i}",
                "points": hit * 2,
                "predictions": settled,
                "settled_predictions": settled,
                "correct_winners": hit,
                "winner_accuracy": hit / settled * 100,
                "longest_streak": streak,
                "recent_results": [
                    [True, False, True, True, True],
                    [True, False, True, True, True],
                    [True, True, True, False, True],
                    [False, True, True, False, False],
                ][i],
                "is_bot": name == "Mira",
                "avatar_path": str(path),
            }
        )
    results = []
    for i, (a, b, key_a, key_b, sa, sb) in enumerate(
        [
            ("EDward Gaming", "Paper Rex", "edg", "prx", 1, 2),
            ("FNATIC", "NRG", "fnc", "nrg", 0, 2),
        ]
    ):
        results.append(
            {
                "team_a": a,
                "team_b": b,
                "logo_a": str(ASSETS / f"{key_a}.png"),
                "logo_b": str(ASSETS / f"{key_b}.png"),
                "result_a": sa,
                "result_b": sb,
                "status": "已结束",
                "start_at": now.replace(hour=20, minute=0).isoformat(),
                "winners": [dict(r) for r in rows[: 2 + i]],
            }
        )
    prediction_leaderboard(
        "一起看瓦 · 演示群",
        "VCT 功能展示赛",
        rows,
        now,
        OUT / "leaderboard-demo.png",
        results=results,
        demo=True,
    )
    # A calendar illustration uses the same logo adaptation and typography as production.
    from studio_render import Canvas

    c = Canvas(960, 670)
    c.header(
        "MATCH DAY",
        "今晚，一起看瓦。",
        "赛程示意 / 时间与对阵为虚构样例",
        source="VAL Match",
    )
    for i, (hour, a, b, ka, kb) in enumerate(
        [
            ("20:00", "EDward Gaming", "Paper Rex", "edg", "prx"),
            ("22:00", "FNATIC", "NRG", "fnc", "nrg"),
        ]
    ):
        y = 245 + i * 156
        c.rect((48, y, 912, y + 138), c.panel, 12)
        c.text(72, y + 40, hour, 32, bold=True)
        c.text(72, y + 88, "BO3", 16, c.muted)
        c.logo(ASSETS / f"{ka}.png", 341, y + 23, 58, a)
        c.logo(ASSETS / f"{kb}.png", 691, y + 23, 58, b)
        c.text(370, y + 83, a, 22, bold=True, align="center", width=300, minimum=18)
        c.text(720, y + 83, b, 22, bold=True, align="center", width=250, minimum=18)
        c.text(565, y + 49, "VS", 24, c.muted, align="center")
    c.text(48, 611, "首场赛前自动推送 · 提前多久由你设置", 20, c.accent)
    c.save(OUT / "schedule-demo.png")
    qr_image(512).save(OUT / "market-qr.png")
    return rows


@lru_cache(maxsize=20)
def asset(name):
    if name == "report":
        return Image.open(ROOT / "docs/examples/report.png").convert("RGBA")
    if name == "card":
        return Image.open(OUT / "prediction-demo.png").convert("RGBA")
    if name == "rank":
        return Image.open(OUT / "leaderboard-demo.png").convert("RGBA")
    if name == "schedule":
        return Image.open(OUT / "schedule-demo.png").convert("RGBA")
    if name.startswith("face"):
        return Image.open(ROOT / "assets/qq_faces" / f"{name[4:]}.png").convert("RGBA")
    return Image.open(ASSETS / name).convert("RGBA")


def card_panel(im, source, xy, width, *, height=None, border=True):
    source = fit(source, width)
    if height is not None:
        source = source.crop((0, 0, source.width, min(round(height), source.height)))
    x, y = map(round, xy)
    rect(im, (x - 2, y - 2, x + source.width + 2, y + source.height + 2), LINE, 18)
    mask = Image.new("L", source.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, source.width - 1, source.height - 1), 16, fill=255
    )
    im.paste(source, (x, y), mask)


def headline(im, lines, portrait, *, kicker, subtitle=None, last_accent=True):
    x = 64 if portrait else 96
    y = 192 if portrait else 224
    text(im, (x, y), kicker, 25 if portrait else 23, LIME)
    size = 89 if portrait else 83
    if len(lines) == 1:
        size = 104 if portrait else 97
    y += 69
    for i, line in enumerate(lines):
        text(
            im,
            (x, y + i * (size + 26)),
            line,
            size,
            LIME if last_accent and i == len(lines) - 1 else WHITE,
            True,
        )
    if subtitle:
        text(
            im,
            (x, y + len(lines) * (size + 26) + 33),
            subtitle,
            29 if portrait else 29,
            MUTED,
        )


def reactions(im, portrait, selected):
    if portrait:
        x, y, gap, width = 164, 1315, 350, 310
    else:
        x, y, gap, width = 972, 710, 352, 310
    for i, (face, name) in enumerate([("face285", "EDG"), ("face293", "PRX")]):
        xx = x + i * gap
        is_selected = selected == i
        rect(
            im,
            (xx, y, xx + width, y + 74),
            "#344731" if is_selected else "#24322B",
            37,
            LIME if is_selected else LINE,
            2,
        )
        paste(im, fit(asset(face), 47), (xx + 18, y + 12))
        text(im, (xx + 86, y + 19), name, 27, WHITE, True, latin=True)
        text(
            im,
            (xx + width - 33, y + 20),
            "2" if is_selected else "1",
            26,
            LIME if is_selected else MUTED,
            anchor="rt",
            latin=True,
        )


@lru_cache(maxsize=50)
def scene_base(index, portrait=False, state=-1):
    im = background(portrait).copy()
    w, h = im.size
    if index == 0:
        headline(
            im,
            ["谁比机器人", "更懂瓦？"],
            portrait,
            kicker="让观赛群，多一点参与感。",
            subtitle="点表情选胜队，赛后一起看榜。",
        )
        if portrait:
            card_panel(im, asset("card"), (64, 735), 952)
            chip(im, (64, 1250), "点一下，就参与")
            chip(im, (390, 1250), "Mira 也参赛")
            text(im, (64, 1430), "赛程  /  战报  /  竞猜  /  积分榜", 31, MUTED)
            rect(im, (64, 1530, 1016, 1660), "#273A26", 22)
            text(im, (540, 1577), "把观赛，带进群聊。", 39, LIME, True, anchor="mt")
        else:
            card_panel(im, asset("card"), (1055, 245), 775)
            card_panel(
                im,
                asset("rank").crop((0, 570, 1200, 1080)),
                (1100, 615),
                680,
                height=260,
            )
            x = 96
            for label in ["点选竞猜", "完整战报", "机器人同榜"]:
                x += chip(im, (x, 688), label, size=25) + 14
    elif index == 1:
        headline(
            im,
            ["比赛之前，", "群里已经热闹。"],
            portrait,
            kicker="01 / 赛前",
            subtitle="赛程自动发，竞猜紧随其后。",
        )
        if portrait:
            card_panel(im, asset("schedule"), (64, 740), 952)
            chip(im, (64, 1510), "首场赛前推送")
            text(im, (64, 1610), "提前分钟数可以自由设置。", 30, MUTED)
        else:
            card_panel(im, asset("schedule"), (925, 195), 900)
            chip(im, (96, 696), "赛前多久发，由你设置")
    elif index == 2:
        if state == 1:
            lines = ["改主意？", "再点另一边。"]
            sub = "每场以最后一次有效选择为准。"
        else:
            lines = ["想赢哪队，", "点一下。"]
            sub = "只猜输赢，不用填写比分。"
        headline(im, lines, portrait, kicker="02 / 竞猜", subtitle=sub)
        if portrait:
            x, y, pw, ph = 64, 735, 952, 780
            cx, cy, cw = 112, 920, 856
        else:
            x, y, pw, ph = 880, 160, 960, 760
            cx, cy, cw = 928, 310, 864
        rect(im, (x, y, x + pw, y + ph), "#18231D", 30, LINE, 2)
        text(im, (x + 32, y + 29), "一起看瓦 · 演示群", 28, bold=True)
        text(im, (x + pw - 32, y + 37), "群聊交互示意", 19, MUTED, anchor="rt")
        ImageDraw.Draw(im).line(
            (x + 24, y + 92, x + pw - 24, y + 92), fill=LINE, width=1
        )
        a = fit(asset("avatar-1.png"), 44)
        paste(im, a, (x + 36, y + 112))
        text(im, (x + 94, y + 119), "Mira", 24, MUTED)
        card_panel(im, asset("card"), (cx, cy), cw)
        reactions(im, portrait, state)
        if portrait:
            text(im, (112, 1450), "点选确认可关闭，群里保持清爽。", 26, MUTED)
            text(im, (64, 1610), "机器人独立预测，也参与积分榜。", 31, LIME)
        else:
            text(im, (928, 850), "点选确认可关闭，群里保持清爽。", 24, MUTED)
            text(im, (96, 716), "机器人独立预测，也参与积分榜。", 28, LIME)
    elif index == 3:
        headline(
            im,
            ["一场比赛，", "一张图复盘。"],
            portrait,
            kicker="03 / 全场战报",
            subtitle="比分、地图，十名选手完整表现。",
        )
        if portrait:
            card_panel(im, asset("report"), (64, 725), 952, height=975)
            text(im, (64, 1734), "历史比赛样例 · NRG 3:2 FNATIC", 23, MUTED)
        else:
            card_panel(im, asset("report"), (1000, 160), 750, height=780)
            chip(im, (96, 690), "总比分 / 逐图比分")
            chip(im, (96, 775), "头像 / 国家 / 完整选手数据")
            text(im, (1000, 964), "历史比赛样例 · NRG 3:2 FNATIC", 21, MUTED)
    elif index == 4:
        headline(
            im,
            ["赛后看榜，", "机器人也参赛。"],
            portrait,
            kicker="04 / 竞猜积分榜",
            subtitle="每项赛事单独计分。",
        )
        if portrait:
            card_panel(im, asset("rank"), (64, 704), 952)
        else:
            card_panel(im, asset("rank"), (1045, 145), 780, height=818)
            for i, (key, value) in enumerate(
                [
                    ("胜负正确率", "只统计本人已参与、已结算场次"),
                    ("竞猜荣誉榜", "连准纪录、命中率和参与达人"),
                ]
            ):
                text(im, (96, 680 + i * 113), key, 32, LIME, True)
                text(im, (96, 730 + i * 113), value, 24, MUTED)
    else:
        headline(
            im,
            ["下一场，", "一起猜。"],
            portrait,
            kicker="给你的观赛群，留一个席位。",
            subtitle="开源免费 · 现已上架 AstrBot 插件市场",
        )
        if portrait:
            rect(im, (64, 761, 1016, 981), LIME, 24)
            text(im, (104, 801), "插件市场搜索", 30, "#314421")
            text(im, (104, 857), "VAL Match", 67, "#182512", True, latin=True)
            paste(im, qr_image(302), (389, 1090))
            text(im, (540, 1430), "扫码查看效果与安装", 29, MUTED, anchor="mt")
            text(im, (540, 1570), "QQ / NapCat 支持表情点选", 28, WHITE, anchor="mt")
        else:
            rect(im, (96, 690, 826, 835), LIME, 22)
            text(im, (130, 711), "AstrBot 插件市场 · 搜索", 27, "#314421")
            text(im, (130, 753), "VAL Match", 49, "#182512", True, latin=True)
            paste(im, qr_image(338), (1216, 280))
            text(im, (1385, 660), "扫码查看效果与安装", 29, MUTED, anchor="mt")
            text(im, (1385, 744), "QQ / NapCat 支持表情点选", 24, MUTED, anchor="mt")
    footer(im, portrait)
    return im


def ease(x):
    x = max(0, min(1, x))
    return x * x * (3 - 2 * x)


def cursor(im, x, y, press=0):
    overlay = Image.new("RGBA", im.size)
    d = ImageDraw.Draw(overlay)
    if press > 0:
        radius = 22 + press * 38
        d.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=(212, 238, 138, round(200 * (1 - press))),
            width=5,
        )
    points = [
        (x, y),
        (x + 8, y + 38),
        (x + 19, y + 28),
        (x + 29, y + 44),
        (x + 38, y + 38),
        (x + 27, y + 22),
        (x + 41, y + 16),
    ]
    d.polygon(points, fill="#F4F6EB", outline="#0C130E", width=3)
    im.alpha_composite(overlay)


def moving_frame(t, portrait=False):
    index = next((i for i in range(6) if TIMES[i] <= t < TIMES[i + 1]), 5)
    local = t - TIMES[index]
    duration = TIMES[index + 1] - TIMES[index]
    state = -1
    if index == 2:
        state = 1 if local >= 5.0 else 0 if local >= 2.45 else -1
    im = scene_base(index, portrait, state).copy()
    if index == 2:
        if portrait:
            cx, cy, gap = 296, 1347, 350
        else:
            cx, cy, gap = 1104, 742, 352
        if local < 2.45:
            k = ease((local - 1.1) / 1.25)
            x = cx + 260 * (1 - k)
            y = cy + 180 * (1 - k)
            cursor(im, x, y)
        elif local < 3.0:
            cursor(im, cx, cy, (local - 2.45) / 0.55)
        elif local < 5.0:
            k = ease((local - 3.8) / 1.1)
            cursor(im, cx + gap * k, cy - 35 * math.sin(math.pi * k))
        elif local < 5.65:
            cursor(im, cx + gap, cy, (local - 5.0) / 0.65)
    if index == 3:
        # A slow real image pan reveals both the full-series score and player rows.
        if portrait:
            x, y, width, height = 64, 725, 952, 975
        else:
            x, y, width, height = 1000, 160, 750, 780
        report = fit(asset("report"), width)
        max_pan = max(0, report.height - height)
        offset = round(max_pan * ease((local - 1.2) / 2.8))
        cropped = report.crop((0, offset, width, offset + height))
        card_panel(im, cropped, (x, y), width, height=height)
    d = ImageDraw.Draw(im)
    w, h = im.size
    m = 64 if portrait else 96
    rail_y = h - 25
    d.line((m, rail_y, w - m, rail_y), fill=LINE, width=3)
    d.line(
        (m, rail_y, m + (w - 2 * m) * min(1, t / TIMES[-1]), rail_y), fill=LIME, width=3
    )
    # Short crossfades keep the graphics readable between scenes.
    if index < 5 and duration - local < 0.24:
        amount = ease((local - duration + 0.24) / 0.24)
        nxt = scene_base(index + 1, portrait, -1)
        im = Image.blend(im, nxt, amount)
    return im.convert("RGB")


def audio():
    sr = 48000
    n = round(TIMES[-1] * sr)
    t = np.arange(n) / sr
    data = np.zeros(n)
    chords = [(45, 52, 57, 60), (41, 48, 53, 57), (48, 55, 60, 64), (43, 50, 55, 59)]
    for start in np.arange(0, TIMES[-1], 3.6):
        idx = int(start / 3.6) % 4
        mask = (t >= start) & (t < start + 4.0)
        tt = t[mask] - start
        env = (1 - np.exp(-tt * 2)) * np.exp(-tt * 0.5)
        for midi in chords[idx]:
            hz = 440 * 2 ** ((midi - 69) / 12)
            data[mask] += 0.011 * np.sin(2 * np.pi * hz * tt) * env
    # Quiet, original plucks and two short UI taps; no sampled music or voice.
    for k, start in enumerate(np.arange(0.6, TIMES[-1] - 0.7, 0.9)):
        mask = (t >= start) & (t < start + 0.6)
        tt = t[mask] - start
        hz = 440 * 2 ** (([69, 72, 76, 79][k % 4] - 69) / 12)
        data[mask] += (
            0.018
            * np.sin(2 * np.pi * hz * tt)
            * np.exp(-tt * 12)
            * (1 - np.exp(-tt * 100))
        )
    for start in [TIMES[2] + 2.45, TIMES[2] + 5.0]:
        mask = (t >= start) & (t < start + 0.09)
        tt = t[mask] - start
        data[mask] += (
            0.12 * np.sin(2 * np.pi * (1100 * tt - 4400 * tt**2)) * np.exp(-tt * 70)
        )
    data *= np.minimum(1, t / 1.2) * np.minimum(1, (TIMES[-1] - t) / 1.8)
    stereo = np.stack([data, data * 0.96], axis=1)
    path = WORK / "original-score.wav"
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def encode(portrait=False):
    w, h = (1080, 1920) if portrait else (1920, 1080)
    name = "val-match-vertical.mp4" if portrait else "val-match-demo.mp4"
    path = OUT / name
    fps = 30
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(WORK / "original-score.wav"),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-threads",
        "4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-metadata",
        "title=VAL Match — 谁比机器人更懂瓦",
        "-metadata",
        "comment=Product illustration; fictional prediction/member data; historical VLR match report. Original synthesized music.",
        "-shortest",
        str(path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(round(TIMES[-1] * fps)):
            proc.stdin.write(moving_frame(i / fps, portrait).tobytes())
            if i % 180 == 0:
                print(name, f"{i / fps:.0f}/{TIMES[-1]}s", flush=True)
        proc.stdin.close()
        code = proc.wait()
        assert code == 0, code
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    print("VIDEO", path.name, path.stat().st_size, flush=True)


def posters():
    # One clear hero cover, one mobile share card; neither is a raw collage.
    cover = scene_base(0, False).convert("RGB")
    cover.save(OUT / "cover.png", optimize=True)
    cover.save(OUT / "cover.jpg", quality=94, subsampling=0)
    im = background(True).crop((0, 0, 1080, 1440))
    headline(
        im,
        ["谁比机器人", "更懂瓦？"],
        True,
        kicker="VAL MATCH / 无畏契约群聊插件",
        subtitle="点一下选胜队，赛后一起看榜。",
    )
    card_panel(im, asset("card"), (64, 675), 952)
    x = 64
    for label in ["点选竞猜", "自动战报", "机器人同榜"]:
        x += chip(im, (x, 1125), label, size=25) + 12
    rect(im, (64, 1236, 798, 1367), LIME, 22)
    text(im, (94, 1262), "AstrBot 插件市场", 25, "#314421")
    text(im, (94, 1304), "搜索 VAL Match", 36, "#182512", True)
    paste(im, qr_image(184), (832, 1220))
    text(im, (64, 1402), "画面为功能演示，竞猜数据非真实赛事结算。", 17, MUTED)
    im.convert("RGB").save(OUT / "share-poster.png", optimize=True)
    square = background(False).crop((0, 0, 1200, 1080))
    text(square, (96, 195), "谁比机器人", 91, bold=True)
    text(square, (96, 315), "更懂瓦？", 112, LIME, True)
    text(square, (96, 484), "点表情选胜队，赛后一起看榜。", 34, MUTED)
    card_panel(square, asset("card"), (96, 585), 1008)
    text(square, (96, 1040), "AstrBot 插件市场 · 搜索 VAL Match", 30, LIME)
    square.convert("RGB").save(OUT / "community-cover.png", optimize=True)
    # A 6-frame review sheet from both aspect ratios is for quality control.
    sheet = Image.new("RGB", (1440, 1320), "#09100B")
    for i, t in enumerate([1.6, 4.8, 8.0, 12.0, 17.0, 21.0]):
        frame = fit(moving_frame(t, False), 700)
        sheet.paste(frame, (10 + (i % 2) * 720, 10 + (i // 2) * 435))
        text(
            sheet,
            (22 + (i % 2) * 720, 415 + (i // 2) * 435),
            f"{t:.1f}s / {TITLES[next(j for j in range(6) if TIMES[j] <= t < TIMES[j + 1])]}",
            18,
            MUTED,
        )
    sheet.save(WORK / "contact-sheet.png")
    for name, t, portrait in [
        ("hero", 1.6, False),
        ("interaction", 9.0, False),
        ("change", 12.0, False),
        ("cta", 26.4, False),
        ("portrait-interaction", 9.0, True),
        ("portrait-ranking", 21.0, True),
    ]:
        moving_frame(t, portrait).save(WORK / (name + ".png"))


def captions():
    lines = []
    for i, (a, b, s) in enumerate(zip(TIMES, TIMES[1:], TITLES), 1):

        def stamp(x):
            sec = int(x)
            return f"00:{sec // 60:02}:{sec % 60:02},{round((x - sec) * 1000):03}"

        lines += [str(i), stamp(a) + " --> " + stamp(b), s, ""]
    (OUT / "captions-zh.srt").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "storyboard.json").write_text(
        json.dumps(
            {
                "duration_seconds": TIMES[-1],
                "fps": 30,
                "market_url": MARKET,
                "scenes": [
                    {"from": a, "to": b, "title": title}
                    for a, b, title in zip(TIMES, TIMES[1:], TITLES)
                ],
                "data": "All member names, avatars and predictions are fictional. Full match report is an actual historical sample.",
                "audio": "Original synthesized ambient music and UI taps, generated by this script.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--video", choices=["all", "landscape", "portrait", "none"], default="all"
    )
    args = parser.parse_args()
    product_assets()
    captions()
    posters()
    audio()
    if args.video in ["all", "landscape"]:
        encode(False)
    if args.video in ["all", "portrait"]:
        encode(True)
    print("Completed promotion kit in", OUT, flush=True)


if __name__ == "__main__":
    main()
