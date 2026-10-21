"""QQ reaction choices reuse the same validated, locked prediction write path."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

try:
    from .prediction_render import WINNER_FACES
    from .prediction_text import name_text, short_team
    from .predictions import best_of, validate_score
except ImportError:
    from prediction_render import WINNER_FACES
    from prediction_text import name_text, short_team
    from predictions import best_of, validate_score


REACTIONS = [
    ("128077", "👍"),
    ("10084", "❤️"),
    ("128293", "🔥"),
    ("127881", "🎉"),
    ("128079", "👏"),
    ("128514", "😂"),
]


def score_choices(bo):
    bo = best_of(str(bo))
    win = bo // 2 + 1
    scores = [(win, n) for n in range(win)] + [(n, win) for n in range(win)]
    return {
        emoji_id: {"emoji": emoji, "a": a, "b": b}
        for (emoji_id, emoji), (a, b) in zip(REACTIONS, scores)
    }


def winner_choices():
    return {
        face: {"emoji": name, "a": int(i == 0), "b": int(i == 1)}
        for i, (face, name) in enumerate(WINNER_FACES)
    }


class ClickPredictionFeature:
    @property
    def click_prediction_targets(self):
        if not self._safe_bool(self.config.get("prediction_click_enabled")):
            return []
        return self._normalize_push_targets(
            self._split_csv_text(self.config.get("prediction_click_targets"))
        )

    def _click_bot(self, group):
        platform_id, kind, _ = group.split(":", 2)
        platform = self.context.get_platform_inst(platform_id)
        bot = getattr(platform, "bot", None)
        if (
            kind != "GroupMessage"
            or not bot
            or getattr(platform.meta(), "name", "") != "aiocqhttp"
        ):
            raise ValueError("点选竞猜需要 QQ 的 OneBot / NapCat 接入。")
        return bot

    def _click_card(self, group, message_id):
        row = self.prediction_store.db.execute(
            "SELECT * FROM click_cards WHERE group_id=? AND message_id=?",
            (group, str(message_id)),
        ).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    async def _send_click_card(self, group, match=None, *, demo=False):
        if group not in self.click_prediction_targets:
            raise ValueError("请先把此群加入点选竞猜群。")
        bot = self._click_bot(group)
        version = await asyncio.wait_for(bot.call_action("get_version_info"), 10)
        if "napcat" not in str(version.get("app_name", "")).casefold():
            raise ValueError("当前接入端未确认支持 NapCat 表情回应，未发送点选卡片。")
        now = self._now_in_display_timezone()
        if demo:
            payload = (
                {k: match[k] for k in ("team_a", "team_b", "bo", "start_at")}
                if match
                else {"team_a": "红队", "team_b": "蓝队", "bo": 3}
            )
            payload["lock_at"] = (now + timedelta(minutes=30)).isoformat()
            match_id = ""
        else:
            if group not in self.prediction_targets or not self._safe_bool(
                self.config.get("prediction_enabled")
            ):
                raise ValueError("此群尚未启用正式竞猜。")
            await self._verify_prediction_match(match)
            match = next(
                m
                for m in self.prediction_store.matches()
                if m["match_id"] == match["match_id"]
            )
            if (
                match["day"] != now.date().isoformat()
                or match["status"] != "未开始"
                or now >= datetime.fromisoformat(match["lock_at"])
            ):
                return None
            payload = {
                k: match[k] for k in ("team_a", "team_b", "bo", "lock_at", "start_at")
            }
            match_id = match["match_id"]
        payload["mode"] = "winner"
        payload["choices"] = winner_choices()
        metadata = (
            self.prediction_store.match_metadata(match.get("match_id", ""))
            if match
            else {}
        )
        for key in ("tournament", "logo_a", "logo_b"):
            if metadata.get(key):
                payload[key] = metadata[key]
            elif match and match.get(key):
                payload[key] = match[key]
        info = self._bot_match_info(group, match_id) if not demo else None
        image_path = await self._render_click_image(payload, demo=demo, bot=info)
        payload["image_path"] = image_path
        file = "base64://" + base64.b64encode(Path(image_path).read_bytes()).decode(
            "ascii"
        )
        result = await asyncio.wait_for(
            bot.call_action(
                "send_group_msg",
                group_id=group.split(":", 2)[2],
                message=[{"type": "image", "data": {"file": file}}],
            ),
            25,
        )
        message_id = (
            str(result.get("message_id", "")) if isinstance(result, dict) else ""
        )
        if not message_id:
            raise RuntimeError(
                "QQ 未返回消息编号，不能确认点选卡片已发送；请勿盲目重发。"
            )
        with self.prediction_store.db:
            self.prediction_store.db.execute(
                "INSERT INTO click_cards VALUES(?,?,?,?,?,?)",
                (
                    group,
                    message_id,
                    match_id,
                    int(demo),
                    json.dumps(payload, ensure_ascii=False),
                    now.isoformat(),
                ),
            )
        for emoji_id in payload["choices"]:
            await asyncio.wait_for(
                bot.call_action(
                    "set_msg_emoji_like",
                    message_id=message_id,
                    emoji_id=emoji_id,
                    set=True,
                ),
                15,
            )
        with self.prediction_store.db:
            self.prediction_store.event(
                "点选测试已发送" if demo else "点选竞猜已发送",
                group,
                f"消息 {message_id} · {match_id or '交互演示，不计分'}",
            )
        return message_id

    async def _send_click_cards(self, group, *, force=False):
        if (
            group not in self.click_prediction_targets
            or group not in self.prediction_targets
        ):
            return []
        if not hasattr(self, "_click_send_lock"):
            self._click_send_lock = asyncio.Lock()
        async with self._click_send_lock:
            ids = []
            for match in self.prediction_store.matches(
                self._today_in_display_timezone().isoformat()
            ):
                old = self.prediction_store.db.execute(
                    "SELECT message_id FROM click_cards WHERE group_id=? AND match_id=? AND demo=0 ORDER BY created_at DESC LIMIT 1",
                    (group, match["match_id"]),
                ).fetchone()
                if not force and old:
                    ids.append(old["message_id"])
                    continue
                if (
                    match["status"] == "未开始"
                    and self._now_in_display_timezone()
                    < datetime.fromisoformat(match["lock_at"])
                ):
                    mid = await self._send_click_card(group, match)
                    if mid:
                        ids.append(mid)
            return ids

    async def _handle_click_prediction(self, event):
        raw = getattr(event.message_obj, "raw_message", None)
        if (
            not isinstance(raw, Mapping)
            or raw.get("notice_type") != "group_msg_emoji_like"
        ):
            return
        group = event.unified_msg_origin
        if group not in self.click_prediction_targets:
            return
        card = self._click_card(group, raw.get("message_id", ""))
        if not card or str(raw.get("group_id", "")) != group.split(":", 2)[2]:
            return
        event.stop_event()
        user = str(raw.get("user_id") or raw.get("operator_id") or "")
        if user in {"", "0", str(event.message_obj.self_id)}:
            return  # Bot-seeded shortcuts are never votes or bot predictions.
        if raw.get("is_add") not in (True, 1, "true"):
            return  # Removing an emoji does not cancel a saved prediction.
        payload = card["payload"]
        likes = raw.get("likes", [])
        chosen = [
            str(like.get("emoji_id"))
            for like in likes
            if isinstance(like, dict)
            and str(like.get("emoji_id")) in payload["choices"]
        ]
        if len(chosen) != 1:
            return
        emoji_id = chosen[0]
        now = self._now_in_display_timezone()
        try:
            event_at = float(raw["time"])
        except (ValueError, TypeError, KeyError):
            return
        if (
            event_at < datetime.fromisoformat(card["created_at"]).timestamp() - 5
            or event_at > now.timestamp() + 60
        ):
            return
        key = hashlib.sha256(
            json.dumps(
                [group, card["message_id"], user, emoji_id, event_at],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        with self.prediction_store.db:
            claimed = self.prediction_store.db.execute(
                "INSERT OR IGNORE INTO click_notices VALUES(?,?,?)",
                (key, group, now.isoformat()),
            ).rowcount
        if not claimed:
            return
        if not hasattr(self, "_click_user_locks"):
            self._click_user_locks = {}
        lock = self._click_user_locks.setdefault((group, user), asyncio.Lock())
        async with lock:
            now = self._now_in_display_timezone()
            choice = payload["choices"][emoji_id]
            try:
                if now >= datetime.fromisoformat(payload["lock_at"]):
                    raise ValueError(
                        "这条测试已结束。"
                        if card["demo"]
                        else "这场已封盘，开赛前 10 分钟起不能竞猜或修改。"
                    )
                if now.timestamp() - event_at > 120:
                    raise ValueError(
                        "这次点击通知延迟过久，我没有修改记录；请重新点一下。"
                    )
                previous = self.prediction_store.db.execute(
                    "SELECT * FROM click_selections WHERE group_id=? AND message_id=? AND user_id=?",
                    (group, card["message_id"], user),
                ).fetchone()
                if previous and previous["event_at"] > event_at:
                    return
                if not card["demo"]:
                    latest = self.prediction_store.db.execute(
                        "SELECT MAX(s.event_at) FROM click_selections s JOIN click_cards c ON c.group_id=s.group_id AND c.message_id=s.message_id WHERE s.group_id=? AND s.user_id=? AND c.match_id=? AND c.demo=0",
                        (group, user, card["match_id"]),
                    ).fetchone()[0]
                    if latest is not None and latest > event_at:
                        return
                bot = self._click_bot(group)
                member = await asyncio.wait_for(
                    bot.call_action(
                        "get_group_member_info",
                        group_id=group.split(":", 2)[2],
                        user_id=user,
                    ),
                    15,
                )
                name = member.get("card") or member.get("nickname") or user
                if payload.get("mode") == "winner":
                    if (choice["a"], choice["b"]) not in {(1, 0), (0, 1)}:
                        raise ValueError("胜队选项无效。")
                else:
                    validate_score(payload["bo"], choice["a"], choice["b"])
                if card["demo"]:
                    changed = previous is not None
                else:
                    if (
                        not self._safe_bool(self.config.get("prediction_enabled"))
                        or group not in self.prediction_targets
                    ):
                        raise ValueError("本群当前未启用正式竞猜，我没有保存这次选择。")
                    match = next(
                        (
                            m
                            for m in self.prediction_store.matches()
                            if m["match_id"] == card["match_id"]
                        ),
                        None,
                    )
                    if not match:
                        raise ValueError("比赛记录不可用，我没有保存这次选择。")
                    self.prediction_store.member(group, user, name)
                    changed, _ = await self._save_member_prediction(
                        group,
                        user,
                        match,
                        int(choice["a"] > choice["b"]),
                        int(choice["b"] > choice["a"]),
                    )
                with self.prediction_store.db:
                    self.prediction_store.db.execute(
                        "INSERT INTO click_selections VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(group_id,message_id,user_id) DO UPDATE SET name=excluded.name,emoji_id=excluded.emoji_id,a=excluded.a,b=excluded.b,event_at=excluded.event_at,updated_at=excluded.updated_at",
                        (
                            group,
                            card["message_id"],
                            user,
                            name,
                            emoji_id,
                            choice["a"],
                            choice["b"],
                            event_at,
                            now.isoformat(),
                        ),
                    )
                    self.prediction_store.event(
                        "点选测试" if card["demo"] else "点选竞猜",
                        group,
                        f"{user} · {card['match_id'] or '演示'} · {choice['a']}:{choice['b']} · {'修改' if changed else '提交'}",
                    )
                winner = (
                    payload["team_a"]
                    if choice["a"] > choice["b"]
                    else payload["team_b"]
                )
                message = f"{'🧪 测试' if card['demo'] else '✅ 竞猜'}{'已修改' if changed else '已记录'} · {name_text(name)}\n已选：{short_team(winner)} 胜"
                message += "\n本次仅测试交互，不计积分。" if card["demo"] else ""
                if not self._safe_bool(
                    self.config.get("prediction_click_feedback_enabled", True)
                ):
                    return  # Keep rejection replies visible even in quiet mode.
            except ValueError as exc:
                message = "🔒 未保存 · " + str(exc)
            except Exception as exc:
                logger.warning("VAL 点选竞猜处理失败: %s", exc)
                message = "⚠️ 暂时无法核实本次选择，请稍后重试或 @我带上队名和比分。"
        yield event.plain_result(message)

    async def page_click_demo(self):
        try:
            body = await request.json(default={})
            group = body.get("group", "")
            if body.get("day"):
                day = datetime.fromisoformat(body["day"]).date()
                if day != self._today_in_display_timezone() + timedelta(days=1):
                    raise ValueError("赛程演示仅支持明天，不开放未来正式竞猜。")
                # Use the already synced official schedule, never invent fixtures.
                rows = self._build_monitor_snapshot().get("match_states", [])
                matches = [
                    m
                    for m in rows
                    if m.get("match_date") == day.isoformat() and m.get("start_at")
                ]
                if not matches or len(matches) > 10:
                    raise ValueError("没有可用于演示的明日赛程，或场数超过 10 场。")
                ids = []
                for m in sorted(matches, key=lambda m: m["start_at"]):
                    fixture = {
                        k: m[k]
                        for k in (
                            "team_a",
                            "team_b",
                            "start_at",
                            "match_id",
                            "tournament",
                        )
                        if k in m
                    }
                    fixture["bo"] = best_of(m["best_of"])
                    ids.append(await self._send_click_card(group, fixture, demo=True))
                return json_response(
                    {
                        "sent": True,
                        "message_ids": ids,
                        "demo": True,
                        "day": day.isoformat(),
                    }
                )
            message_id = await self._send_click_card(group, demo=True)
            return json_response({"sent": True, "message_id": message_id, "demo": True})
        except Exception as exc:
            return error_response(str(exc))

    async def page_click_status(self):
        group = request.query.get("group", "")
        if group not in self.click_prediction_targets:
            return error_response("请选择已启用点选竞猜的群。")
        cards = [
            {**dict(r), "payload": json.loads(r["payload"])}
            for r in self.prediction_store.db.execute(
                "SELECT * FROM click_cards WHERE group_id=? ORDER BY created_at DESC LIMIT 10",
                (group,),
            )
        ]
        selections = [
            dict(r)
            for r in self.prediction_store.db.execute(
                "SELECT * FROM click_selections WHERE group_id=? ORDER BY updated_at DESC LIMIT 30",
                (group,),
            )
        ]
        return json_response({"cards": cards, "selections": selections})
