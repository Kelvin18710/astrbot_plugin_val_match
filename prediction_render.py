"""Native Studio prediction graphics; all numbers come from settled predictions."""

from datetime import datetime
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

try:
    from .render import _shorten_team_display_name, _shorten_tournament_name
    from .studio_render import Canvas
except ImportError:
    from render import _shorten_team_display_name, _shorten_tournament_name
    from studio_render import Canvas

BLUE = "#75B9F4"
ORANGE = "#FFAD69"
WINNER_FACES = [("285", "摸鱼"), ("293", "摸锦鲤")]
FACE_ROOT = Path(__file__).resolve().parent / "assets" / "qq_faces"


def dot(c, x, y, radius, color):
    c.draw.ellipse(
        tuple(round(v * 2) for v in (x - radius, y - radius, x + radius, y + radius)),
        fill=color,
    )


def prediction_card(payload, path, *, theme="studio_dark", demo=False, bot=None):
    """A narrower 720 x 300 card avoids the previous ultra-wide QQ preview."""
    c = Canvas(720, 300, theme)
    blue = "#2165A2" if c.light else BLUE
    orange = "#A55216" if c.light else ORANGE
    c.rect((0, 0, 5, 300), c.accent)
    c.text(24, 24, "VAL MATCH  /  胜负竞猜", 14, c.muted, True, width=270, minimum=12)
    event = _shorten_tournament_name(payload.get("tournament") or "胜负竞猜")
    c.text(696, 24, event, 15, c.muted, align="right", width=366, minimum=12)
    start = (
        datetime.fromisoformat(payload["start_at"]) if payload.get("start_at") else None
    )
    c.text(
        24,
        82,
        start.strftime("%H:%M") if start else "VS",
        35,
        bold=True,
        width=90,
        minimum=28,
    )
    c.text(
        24,
        132,
        start.strftime("%m月%d日") if start else "二选一",
        16,
        c.muted,
        width=92,
        minimum=13,
    )
    c.text(
        24,
        165,
        "演示 · 不计分" if demo else "猜中 +2 分",
        15,
        c.accent,
        True,
        width=94,
        minimum=13,
    )
    c.rule(128, 68, 128, 214)
    for side, center, color, face in [
        ("a", 268, blue, "285"),
        ("b", 574, orange, "293"),
    ]:
        name = payload["team_" + side]
        c.logo(payload.get("logo_" + side), center - 36, 66, 72, name)
        c.text(
            center,
            151,
            _shorten_team_display_name(name),
            24,
            bold=True,
            align="center",
            width=232,
            minimum=17,
        )
        c.text(center - 91, 197, "点", 16, color)
        c.icon(FACE_ROOT / (face + ".png"), center - 68, 184, 34)
        c.text(center - 28, 197, "预测该队获胜", 16, color, width=144, minimum=14)
    c.text(421, 108, "VS", 22, c.muted, True, align="center")
    c.rule(24, 234, 696)
    c.text(24, 256, "点对应表情参与 · 换队可改选", 15, c.muted, width=340, minimum=13)
    if demo:
        note = "明日赛程演示 · 不计分"
    else:
        cutoff = datetime.fromisoformat(payload["lock_at"])
        note = f"{cutoff:%H:%M} 封盘"
        if bot and bot.get("state") == "ready":
            winner = payload["team_a"] if bot["a"] > bot["b"] else payload["team_b"]
            note = f"{bot['name']} 选 {_shorten_team_display_name(winner)} · " + note
    c.text(696, 256, note, 14, c.accent, align="right", width=300, minimum=12)
    return c.save(path)


def names(rows):
    clean = [" ".join(str(r.get("name") or "群友").split()) for r in rows]
    return "、".join(clean[:2]) + (
        " 等 " + str(len(clean)) + " 位" if len(clean) > 2 else ""
    )


def member_avatar(c, path, x, y, size, name):
    try:
        if not path:
            raise ValueError("avatar unavailable")
        with Image.open(path) as source:
            source.load()
            picture = ImageOps.fit(
                source.convert("RGB"),
                (size * 2, size * 2),
                method=Image.Resampling.LANCZOS,
            )
        mask = Image.new("L", picture.size)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 2 - 1, size * 2 - 1), fill=255)
        c.image.paste(picture, (round(x * 2), round(y * 2)), mask)
    except (OSError, ValueError, TypeError):
        dot(c, x + size / 2, y + size / 2, size / 2, c.soft)
        initial = str(name or "?").strip()[:1].upper() or "?"
        c.text(
            x + size / 2,
            y + size * 0.23,
            initial,
            size * 0.45,
            c.accent,
            True,
            align="center",
            minimum=12,
        )


def honors(rows):
    """Preserve all ties and compare exact fractions, never rounded percentages."""
    settled = [r for r in rows if r.get("settled_predictions", 0) > 0]
    streak = max((r.get("longest_streak", 0) for r in settled), default=0)
    run = [r for r in settled if r.get("longest_streak", 0) == streak] if streak else []
    rate = max(
        (Fraction(r["correct_winners"], r["settled_predictions"]) for r in settled),
        default=None,
    )
    accurate = (
        [
            r
            for r in settled
            if Fraction(r["correct_winners"], r["settled_predictions"]) == rate
        ]
        if rate is not None
        else []
    )
    participation = max((r.get("predictions", 0) for r in rows), default=0)
    active = (
        [r for r in rows if r.get("predictions", 0) == participation]
        if participation
        else []
    )
    return [
        {
            "title": "连准纪录",
            "value": str(streak) + " 连准" if run else "等待首位命中",
            "names": names(run),
            "members": run,
            "note": "本赛事最长连续命中",
        },
        {
            "title": "命中率之星",
            "value": f"{float(rate) * 100:.1f}%" if accurate else "等待首位命中",
            "names": names(accurate),
            "members": accurate,
            "note": " · ".join(
                f"{r['correct_winners']}/{r['settled_predictions']} 场"
                for r in accurate[:2]
            )
            if accurate
            else "已结算竞猜的胜负正确率",
        },
        {
            "title": "参与达人",
            "value": str(participation) + " 场" if active else "虚位以待",
            "names": names(active),
            "members": active,
            "note": "本赛事参与场次最多",
        },
    ]


def result_height(result):
    return 211 + max(1, (len(result.get("winners", [])) + 2) // 3) * 44


def draw_result(c, result, x, y, width, height):
    c.rect((x, y, x + width, y + height), c.panel, 10)
    complete = result.get("result_a") is not None and result.get("result_b") is not None
    state = (
        "已结束"
        if complete
        else {"已结束": "赛果待确认", "赛制或队伍变更，暂停": "暂停"}.get(
            result.get("status"), result.get("status") or "未开始"
        )
    )
    color = c.accent if complete else c.red if state == "进行中" else c.muted
    start = datetime.fromisoformat(result["start_at"])
    c.text(x + 20, y + 17, start.strftime("%H:%M"), 17, c.muted, True)
    c.text(x + width - 20, y + 17, state, 16, color, align="right")
    for side, center in [("a", 122), ("b", width - 122)]:
        c.logo(
            result.get("logo_" + side),
            x + center - 27,
            y + 47,
            54,
            result["team_" + side],
        )
        c.text(
            x + center,
            y + 115,
            _shorten_team_display_name(result["team_" + side]),
            19,
            bold=True,
            align="center",
            width=218,
            minimum=14,
        )
    score = f"{result['result_a']} : {result['result_b']}" if complete else "— : —"
    c.text(
        x + width / 2,
        y + 61,
        score,
        34,
        c.accent if complete else c.muted,
        True,
        align="center",
    )
    c.rule(x + 20, y + 151, x + width - 20)
    winners = result.get("winners", [])
    c.text(
        x + 20,
        y + 166,
        f"预测正确 · {len(winners)} 人" if complete else "等待赛果",
        15,
        c.muted,
        True,
    )
    if not winners:
        c.text(
            x + 20,
            y + 205,
            "本群暂无成员猜中" if complete else "赛果确认后展示猜中成员",
            17,
            c.muted,
            width=width - 40,
            minimum=14,
        )
    for index, member in enumerate(winners):
        left = x + 20 + (index % 3) * ((width - 40) / 3)
        top = y + 198 + (index // 3) * 44
        member_avatar(c, member.get("avatar_path"), left, top, 32, member.get("name"))
        c.text(
            left + 40,
            top + 8,
            member.get("name") or member["user_id"],
            15,
            width=(width - 40) / 3 - 45,
            minimum=12,
        )


def prediction_leaderboard(
    group,
    tournament,
    rows,
    now,
    path,
    *,
    theme="studio_dark",
    page=1,
    pages=1,
    offset=0,
    all_rows=None,
    rank_day=None,
    demo=False,
    results=None,
    result_day=None,
):
    all_rows = all_rows if all_rows is not None else rows
    results = results or []
    result_day = result_day or rank_day or now.date().isoformat()
    grid = []
    cursor = 294
    for index in range(0, len(results), 2):
        pair = results[index : index + 2]
        height = max(result_height(r) for r in pair)
        grid.append((cursor, height, pair))
        cursor += height + 18
    result_end = cursor if results else 332
    table_header = result_end + 23
    table_top = table_header + 36
    bottom = table_top + max(1, len(rows)) * 64
    awards = honors(all_rows)
    award_rows = max(1, max(((len(a["members"]) + 1) // 2 for a in awards), default=1))
    award_height = 164 + award_rows * 44
    award_top = bottom + 72
    c = Canvas(1200, award_top + award_height + 92, theme)
    subtitle = group + "  /  " + tournament + ("  /  样例" if demo else "")
    c.header("PREDICTIONS", "竞猜积分榜", subtitle, source="群内竞猜")
    c.text(1136, 106, now.strftime("%m.%d"), 36, c.accent, True, align="right")
    c.text(1136, 156, now.strftime("%H:%M"), 18, c.muted, align="right")
    heading = (
        "今日赛果"
        if result_day == now.date().isoformat() and not rank_day
        else datetime.fromisoformat(result_day).strftime("%m月%d日赛果")
    )
    c.text(64, 253, heading, 24, bold=True)
    c.text(
        1136,
        257,
        "赛后结算榜" if rank_day else "本赛事 · 本群预测",
        16,
        c.muted,
        align="right",
    )
    for top, height, pair in grid:
        for column, result in enumerate(pair):
            draw_result(c, result, 64 + column * 548, top, 524, height)
    if not results:
        c.text(64, 297, "当日暂无已登记比赛", 18, c.muted)
    for x, label, align in [
        (87, "排名", "left"),
        (176, "群友", "left"),
        (611, "近 5 场", "left"),
        (818, "胜负命中", "right"),
        (969, "参与 / 已结算", "right"),
        (1114, "积分", "right"),
    ]:
        c.text(x, table_header, label, 16, c.muted, True, align=align)
    for i, r in enumerate(rows):
        y = table_top + i * 64
        rank = 1 + sum(p["points"] > r["points"] for p in all_rows)
        if i % 2 == 0:
            c.rect((64, y - 2, 1136, y + 60), c.panel, 8)
        color = (
            {1: "#E4C36D", 2: "#BECBD0", 3: "#C6926D"}.get(rank, c.muted)
            if r["points"]
            else c.muted
        )
        dot(c, 103, y + 28, 20, c.soft if rank <= 3 and r["points"] else c.panel)
        c.text(103, y + 13, f"{rank:02}", 23, color, True, align="center")
        member = ("BOT · " if r.get("is_bot") else "") + str(
            r.get("name") or r.get("user_id") or "群友"
        )
        member_avatar(c, r.get("avatar_path"), 176, y + 5, 48, r.get("name"))
        c.text(239, y + 19, member, 23, bold=True, width=342, minimum=18)
        recent = r.get("recent_results", [])
        for j in range(5):
            value = recent[j] if j < len(recent) else None
            dot(
                c,
                621 + j * 22,
                y + 28,
                6,
                c.line if value is None else c.accent if value else c.red,
            )
        settled = r.get("settled_predictions", 0)
        c.text(
            818,
            y + 6,
            f"{r['winner_accuracy']:.1f}%" if settled else "—",
            23,
            bold=True,
            align="right",
        )
        c.text(
            818,
            y + 38,
            f"{r['correct_winners']}/{settled} 场"
            if settled
            else ("待结算" if r["predictions"] else "未参与"),
            14,
            c.muted,
            align="right",
        )
        c.text(
            969, y + 20, f"{r['predictions']} / {settled}", 21, c.muted, align="right"
        )
        c.text(
            1114,
            y + 8,
            r["points"],
            34,
            c.accent if r["points"] else c.muted,
            True,
            align="right",
        )
    if not rows:
        c.text(
            600,
            table_top + 20,
            "还没有成员记录，等你来开局。",
            25,
            c.muted,
            align="center",
        )
    c.text(64, bottom + 28, "竞猜荣誉榜", 23, bold=True)
    c.text(
        1136,
        bottom + 32,
        "近况：亮色命中 · 红色未中 · 从左到右由旧到新",
        14,
        c.muted,
        align="right",
    )
    for i, award in enumerate(awards):
        x = 64 + i * 364
        c.rect((x, award_top, x + 344, award_top + award_height), c.panel, 10)
        c.text(x + 20, award_top + 20, award["title"], 17, c.muted, True)
        c.text(
            x + 20,
            award_top + 51,
            award["value"],
            29,
            c.accent,
            True,
            width=304,
            minimum=21,
        )
        for index, member in enumerate(award["members"]):
            left = x + 20 + (index % 2) * 156
            top = award_top + 99 + (index // 2) * 44
            member_avatar(
                c, member.get("avatar_path"), left, top, 32, member.get("name")
            )
            c.text(
                left + 40,
                top + 8,
                member.get("name") or member.get("user_id", "群友"),
                16,
                width=108,
                minimum=12,
            )
        if not award["members"]:
            c.text(x + 20, award_top + 108, "暂无获得者", 17, c.muted)
        c.text(
            x + 20,
            award_top + award_height - 31,
            award["note"],
            14,
            c.muted,
            width=304,
            minimum=12,
        )
    c.footer(
        "群内竞猜",
        f"仅统计本赛事参与且已结算场次 · 未参与不计入正确率 · {page}/{pages}",
    )
    return c.save(path)
