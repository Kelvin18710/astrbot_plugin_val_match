"""Plain-text presentation shared by scheduled and conversational replies."""

from datetime import datetime

try:
    from .predictions import team_names
except ImportError:
    from predictions import team_names

RULE = "猜中胜队得 2 分；同时猜中比分，额外得 3 分，合计 5 分。"
VIEW = "📖 查看：@我说“我的竞猜”或者“积分榜”。"


def short_team(team):
    names = team_names(team)
    return next((n for n in names if n.isascii() and len(n) <= 4), team)


def name_text(value):
    return " ".join(str(value or "群友").split())[:50]


def my_predictions(name, rows, points, now, tz):
    lines = [
        f"👤 {name_text(name)} · 我的竞猜",
        f"🏅 当前积分：{points} 分\n🎲 共参与 {len(rows)} 场比赛",
    ]
    if not rows:
        lines.append(
            "还没有竞猜记录，第一场预测从这里开始吧。\n@我说“今日竞猜”查看今天的比赛。"
        )
    for i, r in enumerate(rows[:20], 1):
        state = ""
        if r["points"] is not None:
            state = {
                5: "✅ 胜队和比分均命中 · 获得 5 分",
                2: "🎯 胜队命中 · 获得 2 分",
                0: "🌱 未猜中胜队 · 本场 0 分",
            }.get(r["points"], f"获得 {r['points']} 分")
            result = (
                f"\n赛果：{r['team_a']} {r['result_a']} : {r['result_b']} {r['team_b']}"
            )
        else:
            result = ""
            if r["status"] == "进行中":
                state = "🔴 比赛进行中 · 等待结算"
            elif now >= datetime.fromisoformat(r["lock_at"]) or r["status"] != "未开始":
                state = "🔒 已封盘 · 等待赛果"
            else:
                state = f"🟢 截止 {datetime.fromisoformat(r['lock_at']).astimezone(tz):%m-%d %H:%M}，仍可修改"
        lines.append(
            f"{i}. {short_team(r['team_a'])} vs {short_team(r['team_b'])}\n你的预测：{r['team_a']} {r['a']} : {r['b']} {r['team_b']}\n{state}{result}"
        )
    if len(rows) > 20:
        lines.append("以上为最近 20 场竞猜。")
    lines.append(
        "✏️ 修改：@我说“把队名那场改成 2:0”。\n多场修改可带上各场队名和新比分，用逗号或“然后”分开。\n比分需要符合该场赛制；开赛前 10 分钟封盘。"
    )
    return "\n\n".join(lines)


def leaderboard(group_name, rows, now):
    lines = [f"🏆 {group_name} · 竞猜积分榜", f"📅 {now:%m月%d日 %H:%M}"]
    for i, r in enumerate(rows[:50]):
        rank = 1 + sum(x["points"] > r["points"] for x in rows)
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        tied = sum(x["points"] == r["points"] for x in rows) > 1
        who = ("🤖 " if r.get("is_bot") else "") + name_text(r["name"])
        settled = r.get("settled_predictions", 0)
        accuracy = (
            f"{r['winner_accuracy']:.1f}%（猜中 {r['correct_winners']}/{settled} 场）"
            if settled
            else "暂无（尚无已结算竞猜）"
        )
        lines.append(
            f"{medal} {'并列第 ' + str(rank) + ' · ' if tied else ''}{who}  ·  {r['points']} 分\n    已参与 {r['predictions']} 场 · 已结算 {settled} 场\n    🎯 胜负正确率：{accuracy}"
        )
    if not rows:
        lines.append(
            "还没有参与记录，每位群成员都从 0 分开始。\n@我说“今日竞猜”开启第一场预测。"
        )
    lines.append(
        f"共 {len(rows)} 位已同步成员 · 同分并列。"
        + ("\n完整排名可在赛事控制台查看。" if len(rows) > 50 else "")
        + "\n尚未参与的成员初始积分为 0 分。"
    )
    lines.append(
        "📊 正确率仅统计已结算竞猜，猜中胜队即算正确，无需比分完全一致。\n🎯 "
        + RULE
        + "\n"
        + VIEW
    )
    return "\n\n".join(lines)
