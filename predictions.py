"""Durable, group-scoped predictions. Scores are derived from settled rows."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ALIASES = {
    "EDward Gaming": ["EDG", "EDward Gaming", "EDward", "国电"],
    "Paper Rex": ["PRX", "Paper Rex", "纸男"],
    "Bilibili Gaming": ["BLG", "Bilibili Gaming", "哔哩哔哩"],
    "FunPlus Phoenix": ["FPX", "FunPlus Phoenix"],
    "Trace Esports": ["TE", "Trace Esports"],
    "Dragon Ranger Gaming": ["DRG", "Dragon Ranger Gaming"],
    "Team Heretics": ["TH", "Team Heretics"],
    "Team Liquid": ["TL", "Team Liquid", "液体"],
    "Team Vitality": ["VIT", "Team Vitality"],
    "Gen.G": ["GEN", "Gen.G", "GEN.G"],
    "Sentinels": ["SEN", "Sentinels"],
    "G2 Esports": ["G2", "G2 Esports"],
    "Nongshim RedForce": ["NS", "Nongshim RedForce", "农心"],
    "Rex Regum Qeon": ["RRQ", "Rex Regum Qeon"],
    "TYLOO": ["TYLOO", "天禄"],
    "Xi Lai Gaming": ["XLG", "Xi Lai Gaming"],
    "FNATIC": ["FNC", "FNATIC"],
}


def best_of(value: str) -> int:
    m = re.fullmatch(r"\s*(?:bo\s*)?([135])\s*", str(value), re.I)
    if not m:
        raise ValueError("这场比赛的赛制尚未确认，暂时不能竞猜。")
    return int(m[1])


def validate_score(bo: int, a: int, b: int) -> None:
    win = bo // 2 + 1
    if (
        type(a) is not int
        or type(b) is not int
        or not ((a == win and 0 <= b < win) or (b == win and 0 <= a < win))
    ):
        examples = "、".join(f"{win}:{n}" for n in range(win))
        raise ValueError(
            f"BO{bo} 的胜队必须拿到 {win} 张地图，负队少于 {win} 张。例如 {examples}，也可以反过来；不能填平局或单图回合比分。"
        )


def parse_score(text: str) -> tuple[int, int] | None:
    translated = text.translate(
        str.maketrans(
            {
                "零": "0",
                "一": "1",
                "二": "2",
                "两": "2",
                "三": "3",
                "四": "4",
                "五": "5",
                "：": ":",
                "－": "-",
            }
        )
    )
    found = re.findall(
        r"(?<![\d.\-−])([0-9]+)\s*(?:比|:|\-|∶)\s*([0-9]+)(?![\d.])", translated
    )
    if len(found) > 1:
        raise ValueError(
            "每场请只说一个确定的比分；多场请带上各场队名，用逗号或“然后”分开，例如“我猜 EDG 2:1 赢 PRX，FNC 2:0 赢 DRX”。"
        )
    if not found:
        return None
    if len(found[0][0]) > 3 or len(found[0][1]) > 3:
        raise ValueError("比分太大了，请预测整场地图比分，例如 2:1。")
    return tuple(map(int, found[0]))


def split_prediction_requests(text: str, teams=()) -> list[str]:
    """Split independent requests, keeping score alternatives in the same clause.

    A scoreless fragment is context for the next score (e.g. “把 FNC 那场，
    改成 2:0”). A lone request retains its original punctuation and wording.
    """
    score = r"[-−]?[零一二两三四五六七八九十百0-9]+\s*(?:比|:|：|－|-|∶)\s*[-−]?[零一二两三四五六七八九十百0-9]+"
    if len(re.findall(score, text)) <= 1:
        return [text]
    aliases = sorted(
        {team_pattern(n) for t in teams for n in team_names(t)}, key=len, reverse=True
    )
    boundary = r"[,，;；。\n、]+|(?:然后|另外|以及|同时|还有)|(?=再把|再将)"
    if aliases:
        next_request = (
            r"(?:(?:再|把|将|我猜|竞猜)\s*)?(?:"
            + "|".join(aliases)
            + r")\s*(?:那场|这场|的比赛|比赛)?\s*(?:改成|改为|会|将|以)?\s*"
            + score
        )
        boundary += r"|(?:\s+|和|再)(?=" + next_request + r")"
    parts = re.split(boundary, text, flags=re.I)
    requests, pending = [], []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.search(score, part):
            requests.append("，".join([*pending, part]))
            pending = []
        else:
            pending.append(part)
    if pending and requests:
        requests[-1] += "，" + "，".join(pending)
    return requests or [text]


def validate_batch_request(text: str) -> None:
    text = re.sub(r"\[CQ:at,[^\]]+\]|\[At:[^\]]+\]", "", text).strip()
    if re.search(r"明天|后天|明日|后日|未来|下周|下星期|下个月", text):
        raise ValueError(
            "目前只支持今天的比赛，不能提前竞猜或修改未来赛程。请只发送今天各场的队名和比分。"
        )
    # These words can scope over all following clauses; do not turn a discussion
    # or an alternative into several independent confirmed writes.
    if re.search(
        r"如果|假如|或者|还是|可能|能不能|可以吗|怎么样|吗|么|[?？]|(?:不要|别|不)(?:提交|保存|登记|记录)|(?:都|全部|统统)(?:不要|不|取消|撤销)",
        text,
    ) or re.match(r"\s*(?:不要|别|不想|不准备|不改|不竞猜|不预测|取消|撤销)", text):
        raise ValueError(
            "这句话还不够确定，我没有修改竞猜。多场请明确说“我猜 EDG 2:1 赢 PRX，FNC 2:0 赢 DRX”。"
        )


def team_names(team: str) -> list[str]:
    names = [team]
    for full, aliases in ALIASES.items():
        if full.casefold() == team.casefold():
            names.extend(aliases)
    return list(dict.fromkeys(names))


def team_pattern(name: str) -> str:
    pattern = re.escape(name.casefold())
    if name.isascii():
        pattern = r"(?<![a-z])" + pattern + r"(?![a-z])"
    return pattern


def team_position(text: str, team: str) -> int | None:
    positions = []
    for name in team_names(team):
        match = re.search(team_pattern(name), text.casefold())
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def explicit_outcome(text: str, team: str) -> set[str]:
    score = r"(?:[零一二两三四五0-9]+\s*(?:比|:|：|\-)\s*[零一二两三四五0-9]+)?"
    outcomes = set()
    for name in team_names(team):
        prefix = (
            team_pattern(name) + r"\s*(?:会|将|能|要)?\s*(?:以)?\s*" + score + r"\s*"
        )
        if re.search(prefix + r"(?:赢|胜|获胜|拿下|击败|战胜)", text.casefold()):
            outcomes.add("win")
        if re.search(prefix + r"(?:输|负|落败)", text.casefold()):
            outcomes.add("lose")
    return outcomes


def refers_to_previous(text: str) -> bool:
    if not re.search(r"改|修改", text):
        return False
    remainder = re.sub(
        r"[零一二两三四五0-9]+\s*(?:比|:|：|\-)\s*[零一二两三四五0-9]+", "", text
    )
    return bool(
        re.fullmatch(
            r"(?:我|想|要|改|修改|一下|刚才|那场|这场|上一场|的|我的|竞猜|预测|比分|成|为|吧|呀|啊|哦|呢|了|请|帮|把|[,，。!！\s])*",
            remainder,
        )
    )


def resolve_prediction_match(
    text: str, matches: list[dict], previous_id: str | None = None
):
    explicit = re.search(r"#\s*(\d+)|(?:比赛|场次)\s*(\d{4,})", text)
    candidates = []
    for match in matches:
        pa = team_position(text, match["team_a"])
        pb = team_position(text, match["team_b"])
        if explicit:
            if match["match_id"] != (explicit[1] or explicit[2]):
                continue
        elif pa is None and pb is None:
            continue
        candidates.append((match, pa, pb))
    if not candidates and not explicit and previous_id and refers_to_previous(text):
        candidates = [(m, None, None) for m in matches if m["match_id"] == previous_id]
    both_teams = [c for c in candidates if c[1] is not None and c[2] is not None]
    if not explicit and both_teams:
        candidates = both_teams
    if len(candidates) != 1:
        raise ValueError(
            "这场比赛还不够明确。请先 @我说“今日竞猜”查看对阵，再带上队名和比分告诉我，例如“我猜 EDG 2比1 赢 PRX”。"
        )
    return candidates[0]


def resolve_prediction(
    text: str, matches: list[dict], previous_id: str | None = None
) -> tuple[dict, int, int]:
    if re.search(r"明天|后天|明日|后日|未来|下周|下星期|下个月", text):
        raise ValueError(
            "目前只支持今天的比赛，不能提前竞猜或修改未来赛程。请 @我说“今日竞猜”查看可参与比赛。"
        )
    score = parse_score(text)
    if score is None:
        raise ValueError("请 @我带上队名和比分，例如“我猜 EDG 2比1 赢 PRX”。")
    match, pa, pb = resolve_prediction_match(text, matches, previous_id)
    a, b = score
    # Explicit IDs with no team use the advertised left/right order.
    if pb is not None and (pa is None or pb < pa):
        a, b = b, a
    # “A 输给 B 1:2” describes A's score; other negated/conditional utterances are not writes.
    if re.search(
        r"不要|别|不想|不准备|没(?:有)?(?:猜|押|预测|竞猜)|不(?:要|想|是)?(?:竞猜|预测)|如果|假如|可能|或者|还是|取消|撤销|不是|不改|别改|不要改|能不能|可以吗|怎么样|吗|么|[?？]|不变|保持",
        text,
    ):
        raise ValueError(
            "这句话还不够确定，我没有修改竞猜。请明确说“竞猜/修改 队名 比分”，例如“竞猜 EDG 2:1 赢 PRX”。"
        )
    validate_score(match["bo"], a, b)
    for team, won in [(match["team_a"], a > b), (match["team_b"], b > a)]:
        stated = explicit_outcome(text, team)
        if (won and "lose" in stated) or (not won and "win" in stated):
            raise ValueError(
                "你说的胜队和比分不一致，请按“胜队 2:1 赢 负队”的形式再说一次。"
            )
    return match, a, b


class PredictionStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS groups(group_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE IF NOT EXISTS members(group_id TEXT,user_id TEXT,name TEXT,PRIMARY KEY(group_id,user_id));
        CREATE TABLE IF NOT EXISTS matches(match_id TEXT PRIMARY KEY,team_a TEXT,team_b TEXT,bo INTEGER,start_at TEXT,lock_at TEXT,status TEXT,day TEXT,result_a INTEGER,result_b INTEGER);
        CREATE TABLE IF NOT EXISTS predictions(group_id TEXT,user_id TEXT,match_id TEXT,a INTEGER,b INTEGER,updated_at TEXT,points INTEGER,PRIMARY KEY(group_id,user_id,match_id));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,group_id TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS match_metadata(match_id TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE IF NOT EXISTS bot_accounts(group_id TEXT PRIMARY KEY,user_id TEXT,name TEXT);
        CREATE TABLE IF NOT EXISTS bot_analyses(match_id TEXT PRIMARY KEY,state TEXT,payload TEXT,attempted_at TEXT,attempts INTEGER);
        CREATE TABLE IF NOT EXISTS deliveries(day TEXT,kind TEXT,group_id TEXT,PRIMARY KEY(day,kind,group_id));
        CREATE TABLE IF NOT EXISTS rank_days(day TEXT,group_id TEXT,match_ids TEXT,PRIMARY KEY(day,group_id));
        """)

    def group_names(self):
        return {r[0]: r[1] for r in self.db.execute("SELECT group_id,name FROM groups")}

    def set_group_name(self, group, name):
        with self.db:
            self.db.execute(
                "INSERT INTO groups VALUES(?,?) ON CONFLICT(group_id) DO UPDATE SET name=excluded.name",
                (group, name),
            )

    def close(self):
        self.db.close()

    def event(self, kind: str, group: str, detail: str):
        self.db.execute(
            "INSERT INTO events(at,kind,group_id,detail) VALUES(?,?,?,?)",
            (datetime.now().astimezone().isoformat(), kind, group, detail),
        )
        self.db.execute(
            "DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-1000 FROM events)"
        )

    def member(self, group: str, user: str, name: str):
        with self.db:
            self.db.execute(
                "INSERT INTO members VALUES(?,?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET name=excluded.name",
                (group, user, name or user),
            )

    def sync_match(
        self,
        match_id: str,
        team_a: str,
        team_b: str,
        bo: int,
        start: datetime,
        status: str,
    ):
        lock = (start - timedelta(minutes=10)).isoformat()
        with self.db:
            old = self.db.execute(
                "SELECT * FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()
            if old:
                if old["result_a"] is not None:
                    return
                if (old["team_a"], old["team_b"], old["bo"]) != (team_a, team_b, bo):
                    self.db.execute(
                        "UPDATE matches SET status='赛制或队伍变更，暂停' WHERE match_id=?",
                        (match_id,),
                    )
                    return
                # Never reopen an elapsed cutoff after postponement / restart.
                lock = min(
                    datetime.fromisoformat(lock), datetime.fromisoformat(old["lock_at"])
                ).isoformat()
                if old["status"] != "未开始":
                    status = old["status"]
            self.db.execute(
                "INSERT INTO matches(match_id,team_a,team_b,bo,start_at,lock_at,status,day) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET start_at=excluded.start_at,lock_at=excluded.lock_at,status=excluded.status,day=excluded.day",
                (
                    match_id,
                    team_a,
                    team_b,
                    bo,
                    start.isoformat(),
                    lock,
                    status,
                    start.date().isoformat(),
                ),
            )

    def matches(self, day: str | None = None):
        rows = self.db.execute(
            "SELECT * FROM matches"
            + (" WHERE day=?" if day else "")
            + " ORDER BY start_at,match_id",
            (day,) if day else (),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_match_metadata(self, match_id, payload):
        previous = self.match_metadata(match_id)
        previous.update({k: v for k, v in payload.items() if v is not None})
        with self.db:
            self.db.execute(
                "INSERT INTO match_metadata VALUES(?,?) ON CONFLICT(match_id) DO UPDATE SET payload=excluded.payload",
                (match_id, json.dumps(previous, ensure_ascii=False)),
            )

    def match_metadata(self, match_id):
        row = self.db.execute(
            "SELECT payload FROM match_metadata WHERE match_id=?", (match_id,)
        ).fetchone()
        return json.loads(row[0]) if row else {}

    def bot_account(self, group):
        row = self.db.execute(
            "SELECT * FROM bot_accounts WHERE group_id=?", (group,)
        ).fetchone()
        return dict(row) if row else None

    def register_bot(self, group, user, name):
        with self.db:
            self.db.execute(
                "INSERT INTO bot_accounts VALUES(?,?,?) ON CONFLICT(group_id) DO UPDATE SET user_id=excluded.user_id,name=excluded.name",
                (group, user, name),
            )
            self.member(group, user, name)

    def bot_analysis(self, match_id):
        row = self.db.execute(
            "SELECT * FROM bot_analyses WHERE match_id=?", (match_id,)
        ).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def save_bot_analysis(self, match_id, state, payload, now, attempts):
        with self.db:
            self.db.execute(
                "INSERT INTO bot_analyses VALUES(?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET state=excluded.state,payload=excluded.payload,attempted_at=excluded.attempted_at,attempts=excluded.attempts",
                (
                    match_id,
                    state,
                    json.dumps(payload, ensure_ascii=False),
                    now.isoformat(),
                    attempts,
                ),
            )

    def submit_bot(self, group, match_id, a, b, now):
        account = self.bot_account(group)
        if not account:
            raise ValueError("机器人身份尚未确认。")
        with self.db:
            m = self.db.execute(
                "SELECT * FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()
            if (
                not m
                or m["status"] != "未开始"
                or m["result_a"] is not None
                or now >= datetime.fromisoformat(m["lock_at"])
            ):
                raise ValueError("机器人也必须在封盘前完成预测。")
            analysis = self.bot_analysis(match_id)
            if (
                not analysis
                or analysis["state"] != "ready"
                or not (
                    analysis["payload"].get("history")
                    or analysis["payload"].get("basis")
                    in {"recent_form", "limited_info"}
                )
                or (analysis["payload"].get("a"), analysis["payload"].get("b"))
                != (a, b)
                or datetime.fromisoformat(analysis["attempted_at"])
                >= datetime.fromisoformat(m["lock_at"])
            ):
                raise ValueError("缺少有效的赛前独立预测。")
            validate_score(m["bo"], a, b)
            if self.db.execute(
                "SELECT 1 FROM predictions WHERE group_id=? AND user_id=? AND match_id=?",
                (group, account["user_id"], match_id),
            ).fetchone():
                return False
            self.db.execute(
                "INSERT INTO predictions VALUES(?,?,?,?,?,?,NULL)",
                (group, account["user_id"], match_id, a, b, now.isoformat()),
            )
            self.event(
                "机器人预测",
                group,
                f"{account['name']} · {m['team_a']} {a}:{b} {m['team_b']}",
            )
        return True

    def submit(
        self, group: str, user: str, match_id: str, a: int, b: int, now: datetime
    ):
        account = self.bot_account(group)
        if account and user == account["user_id"]:
            raise ValueError("机器人的预测由比赛资料分析独立生成，群成员不能代为修改。")
        with self.db:
            m = self.db.execute(
                "SELECT * FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()
            if (
                not m
                or m["status"] != "未开始"
                or m["result_a"] is not None
                or now >= datetime.fromisoformat(m["lock_at"])
            ):
                raise ValueError(
                    "这场比赛已封盘：开赛前 10 分钟起不能竞猜或修改。请选其他未封盘比赛。"
                )
            validate_score(m["bo"], a, b)
            old = self.db.execute(
                "SELECT * FROM predictions WHERE group_id=? AND user_id=? AND match_id=?",
                (group, user, match_id),
            ).fetchone()
            self.db.execute(
                "INSERT INTO predictions VALUES(?,?,?,?,?,?,NULL) ON CONFLICT(group_id,user_id,match_id) DO UPDATE SET a=excluded.a,b=excluded.b,updated_at=excluded.updated_at",
                (group, user, match_id, a, b, now.isoformat()),
            )
            self.event(
                "修改竞猜" if old else "提交竞猜",
                group,
                f"{user} · #{match_id} · {a}:{b}",
            )
        return bool(old)

    def settle(self, match_id: str, a: int, b: int):
        with self.db:
            m = self.db.execute(
                "SELECT * FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()
            if (
                not m
                or m["result_a"] is not None
                or m["status"] == "赛制或队伍变更，暂停"
            ):
                return False
            validate_score(m["bo"], a, b)
            self.db.execute(
                "UPDATE matches SET result_a=?,result_b=?,status='已结束' WHERE match_id=?",
                (a, b, match_id),
            )
            self.db.execute(
                "UPDATE predictions SET points=CASE WHEN (a>b)=? THEN 2+CASE WHEN a=? AND b=? THEN 3 ELSE 0 END ELSE 0 END WHERE match_id=? AND points IS NULL",
                (a > b, a, b, match_id),
            )
            self.event("自动结算", "", f"#{match_id} · {a}:{b}")
        return True

    def leaderboard(self, group: str):
        rows = [
            dict(r)
            for r in self.db.execute(
                """
            SELECT m.user_id,m.name,
                CASE WHEN ba.user_id IS NULL THEN 0 ELSE 1 END AS is_bot,
                COALESCE(SUM(p.points),0) AS points,
                COUNT(p.match_id) AS predictions,
                SUM(CASE WHEN p.points IS NOT NULL AND game.result_a IS NOT NULL
                    AND game.result_b IS NOT NULL THEN 1 ELSE 0 END) AS settled_predictions,
                SUM(CASE WHEN p.points IS NOT NULL AND game.result_a IS NOT NULL
                    AND game.result_b IS NOT NULL
                    AND (p.a > p.b) = (game.result_a > game.result_b)
                    THEN 1 ELSE 0 END) AS correct_winners
            FROM members m
            LEFT JOIN bot_accounts ba ON ba.group_id=m.group_id AND ba.user_id=m.user_id
            LEFT JOIN predictions p ON p.group_id=m.group_id AND p.user_id=m.user_id
            LEFT JOIN matches game ON game.match_id=p.match_id
            WHERE m.group_id=?
            GROUP BY m.user_id,m.name ORDER BY points DESC,m.user_id
            """,
                (group,),
            )
        ]
        for row in rows:
            row["winner_accuracy"] = (
                round(100 * row["correct_winners"] / row["settled_predictions"], 1)
                if row["settled_predictions"]
                else None
            )
        return rows

    def predictions(self, group: str, user: str | None = None):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT p.*,m.team_a,m.team_b,m.start_at,m.lock_at,m.status,m.result_a,m.result_b,n.name,CASE WHEN ba.user_id IS NULL THEN 0 ELSE 1 END AS is_bot FROM predictions p JOIN matches m USING(match_id) LEFT JOIN bot_accounts ba ON ba.group_id=p.group_id AND ba.user_id=p.user_id LEFT JOIN members n ON n.group_id=p.group_id AND n.user_id=p.user_id WHERE p.group_id=?"
                + (" AND p.user_id=?" if user else "")
                + " ORDER BY p.updated_at DESC",
                (group, user) if user else (group,),
            )
        ]

    def last_match(self, group: str, user: str):
        rows = self.predictions(group, user)
        return rows[0]["match_id"] if rows else None

    def delivered(self, day: str, kind: str, group: str):
        return bool(
            self.db.execute(
                "SELECT 1 FROM deliveries WHERE day=? AND kind=? AND group_id=?",
                (day, kind, group),
            ).fetchone()
        )

    def watch_rank_day(self, day: str, group: str, match_ids):
        if self.delivered(day, "赛后积分", group):
            return
        old = self.db.execute(
            "SELECT match_ids FROM rank_days WHERE day=? AND group_id=?", (day, group)
        ).fetchone()
        ids = sorted(set(match_ids) | set(json.loads(old[0]) if old else []))
        if not ids:
            return
        with self.db:
            self.db.execute(
                "INSERT INTO rank_days VALUES(?,?,?) ON CONFLICT(day,group_id) DO UPDATE SET match_ids=excluded.match_ids",
                (day, group, json.dumps(ids)),
            )

    def pending_rank_days(self, group: str):
        return [
            {**dict(r), "match_ids": json.loads(r["match_ids"])}
            for r in self.db.execute(
                """
            SELECT r.* FROM rank_days r WHERE r.group_id=? AND NOT EXISTS
            (SELECT 1 FROM deliveries d WHERE d.day=r.day AND d.group_id=r.group_id AND d.kind='赛后积分')
            ORDER BY r.day
            """,
                (group,),
            )
        ]

    def rank_day_ready(self, day: str, group: str):
        row = self.db.execute(
            "SELECT match_ids FROM rank_days WHERE day=? AND group_id=?", (day, group)
        ).fetchone()
        if not row:
            return False
        ids = json.loads(row[0])
        if not ids:
            return False
        for match_id in ids:
            match = self.db.execute(
                "SELECT result_a,result_b FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()
            if not match or match["result_a"] is None or match["result_b"] is None:
                return False
            if self.db.execute(
                "SELECT 1 FROM predictions WHERE group_id=? AND match_id=? AND points IS NULL",
                (group, match_id),
            ).fetchone():
                return False
        return True

    def mark_delivered(self, day: str, kind: str, group: str):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO deliveries VALUES(?,?,?)", (day, kind, group)
            )
            self.event("定时播报", group, kind)

    def events(self):
        return [
            dict(r)
            for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100")
        ]
