"""Route explicit group guessing requests without intercepting ordinary discussion."""

import re

try:
    from .predictions import parse_score, team_names, team_pattern
except ImportError:
    from predictions import parse_score, team_names, team_pattern


SCORE = (
    r"[零一二两三四五六七八九十百\d]+\s*(?:比|:|：|-)\s*[零一二两三四五六七八九十百\d]+"
)
BOT_REFERENCE = r"你的|机器人(?:的)?(?:竞猜|预测)|替你|帮你改|给你改|你自己的|把机器人"


def prediction_intent(text, has_score=False, teams=()):
    text = re.sub(r"\[CQ:at,[^\]]+\]|\[At:[^\]]+\]", "", text).strip()
    # Predicting an event winner or discussing a hypothetical result is ordinary chat.
    if re.search(
        r"冠军|夺冠|谁会赢|谁能赢|你觉得|你认为|你怎么看|分析|概率|可能性|会不会|有没有可能|为什么|是不是|[?？]",
        text,
    ):
        # A direct request to participate may be phrased as a polite question.
        explicit = re.search(
            r"(?:帮我|给我|我要|我想)(?:提交|参加|参与|竞猜|押)|(?:把|将).*(?:改成|改为)",
            text,
        )
        view = re.search(
            r"我的(?:竞猜|预测|积分)|你的(?:竞猜|预测)|竞猜.*(?:规则|玩法)|竞猜怎么玩|积分榜",
            text,
        )
        if not explicit and not view:
            return None
        if re.search(r"冠军|夺冠|赛区排名|世界排名", text) and not explicit:
            return None
    if (
        re.search(r"竞猜", text)
        and re.search(r"规则|怎么|帮助|玩法|如何", text)
        and not has_score
    ):
        return "help"
    if not has_score:
        if re.search(r"我的(?:竞猜|预测)|我(?:猜|押)了什么", text):
            return "mine"
        if re.search(r"(?:你的|你自己的|机器人的?)(?:竞猜|预测)", text):
            return "bot"
        if re.search(
            r"积分榜|积分(?:排名|排行|情况|多少)|我的积分|群.*积分", text
        ) or re.fullmatch(r"(?:积分|排名|排行|排行榜)[呢啊吧?？。！!]*", text):
            return "rank"
        if re.search(
            r"(?:今日|今天|今日的|今天的|当前|查看|看看|查一下|显示|有哪些|可参与的|可参加的|可)(?:比赛)?(?:竞猜|预测)",
            text,
        ) or re.fullmatch(r"竞猜[呢啊吧?？。！!]*", text):
            return "list"
        if re.search(r"(?:我要|我想|帮我|给我|参加|参与).*竞猜", text):
            return "help"
        return None
    if re.search(BOT_REFERENCE, text) and re.search(r"改|修改|更改|调整", text):
        return "bot_change"
    if re.search(
        r"^(?:(?:请|帮我|给我)\s*)?(?:我)?(?:要|想|打算|准备|决定)?(?:参与|参加)?(?:提交|登记|记录)?(?:竞猜|猜|押|预测|觉得|看好)",
        text,
    ):
        return "submit"
    if re.search(r"^(?:请|帮我|给我|我|把|将|改|修改|更改|调整)", text) and re.search(
        r"改成|改为|改一下|修改|更改|调整", text
    ):
        return "submit"
    if re.fullmatch(SCORE + r"[吧。！!]*", text):
        if re.fullmatch(r"\d{1,2}:[0-5]\d", text):
            return None
        try:
            score = parse_score(text)
        except ValueError:
            return None
        if score and max(score) in {1, 2, 3} and min(score) < max(score):
            return "submit"
        return None
    # Keep the short "EDG 2:1 PRX" form, but require a known team at the start.
    for team in teams:
        for alias in team_names(team):
            if re.match(
                team_pattern(alias) + r"\s*(?:会|将|以)?\s*" + SCORE, text.casefold()
            ):
                return "submit"
    return None
