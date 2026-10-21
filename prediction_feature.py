from __future__ import annotations

import asyncio
import contextlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

try:
    from .bot_predictions import BotPredictionFeature
    from .click_predictions import ClickPredictionFeature
    from .prediction_images import PredictionImages
    from .prediction_intent import prediction_intent
    from .prediction_text import (
        RULE,
        VIEW,
        leaderboard,
        my_predictions,
        name_text,
        short_team,
    )
    from .predictions import (
        PredictionStore,
        best_of,
        parse_score,
        resolve_prediction_match,
        resolve_winner_prediction,
        split_winner_requests,
        validate_batch_request,
    )
except ImportError:
    from bot_predictions import BotPredictionFeature
    from click_predictions import ClickPredictionFeature
    from prediction_images import PredictionImages
    from prediction_intent import prediction_intent
    from prediction_text import (
        RULE,
        VIEW,
        leaderboard,
        my_predictions,
        name_text,
        short_team,
    )
    from predictions import (
        PredictionStore,
        best_of,
        parse_score,
        resolve_prediction_match,
        resolve_winner_prediction,
        split_winner_requests,
        validate_batch_request,
    )

PLUGIN = "astrbot_plugin_val_match"
HELP = (
    "🎮 胜负竞猜 · 选一队就行\n\n"
    "点比赛消息下方的表情选胜队，点另一个可改选。\n"
    "也可 @我说‘我猜 EDG 赢’或‘把 EDG 那场改成 PRX 赢’。\n\n"
    "🏅 猜中 +2 分，猜错 0 分；只猜胜负，不用填比分。\n"
    "🔒 只开放今日比赛，开赛前 10 分钟封盘，提前开赛也会封盘。\n"
    "📖 @我说‘我的竞猜’或‘积分榜’查看。各群、各赛事独立计分，历史成绩保留。\n"
    "🧾 多场可一起说：‘我猜 EDG 赢，FNC 赢’；修改也可带上各场队名。\n"
    "以最后一次保存为准；取消表情不撤销竞猜。"
)


class PredictionFeature(ClickPredictionFeature, BotPredictionFeature, PredictionImages):
    def _init_predictions(self):
        self.prediction_store = PredictionStore(
            Path(get_astrbot_plugin_data_path()) / PLUGIN / "predictions.sqlite3"
        )
        self._prediction_task = None
        self._prediction_lock = asyncio.Lock()
        self._settings_lock = asyncio.Lock()
        self._bot_prediction_lock = asyncio.Lock()
        self._prediction_delivery_lock = asyncio.Lock()
        self._prediction_last_refresh = None
        self._prediction_last_error = ""
        self._prediction_groups = self.prediction_store.group_names()
        for endpoint, handler, methods in [
            ("status", self.page_status, ["GET"]),
            ("settings", self.page_settings, ["GET"]),
            ("settings", self.page_save_settings, ["POST"]),
            ("groups", self.page_groups, ["GET"]),
            ("refresh", self.page_refresh, ["POST"]),
            ("broadcast", self.page_broadcast, ["POST"]),
            ("events/sync", self.page_sync_events, ["POST"]),
            ("click/demo", self.page_click_demo, ["POST"]),
            ("click/status", self.page_click_status, ["GET"]),
        ]:
            self.context.register_web_api(
                f"/{PLUGIN}/{endpoint}", handler, methods, endpoint
            )

    @property
    def prediction_targets(self):
        return self._normalize_push_targets(
            self._split_csv_text(self.config.get("prediction_targets"))
        )

    async def _restart_prediction_task(self):
        if self._prediction_task:
            self._prediction_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prediction_task
        self._prediction_task = None
        if (
            self._safe_bool(self.config.get("prediction_enabled"))
            and self.prediction_targets
        ):
            self._prediction_task = asyncio.create_task(self._prediction_loop())

    async def _stop_predictions(self):
        if self._prediction_task:
            self._prediction_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prediction_task
            self._prediction_task = None
        self.prediction_store.close()

    async def _prediction_loop(self):
        while True:
            refreshed = False
            try:
                self._watch_rank_days()
                await self._refresh_predictions()
                refreshed = True
                self._watch_rank_days()
                await self._ensure_bot_predictions()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record_prediction_error("赛程同步异常", "", exc)
            now = self._now_in_display_timezone()
            for kind, key, enabled in [
                ("竞猜", "prediction_push_time", "prediction_daily_enabled"),
                ("积分", "prediction_rank_time", "prediction_rank_enabled"),
            ]:
                if not self._safe_bool(self.config.get(enabled)) or (
                    kind == "竞猜" and not refreshed
                ):
                    continue
                scheduled = datetime.combine(
                    now.date(),
                    self._parse_push_time(self.config.get(key)),
                    tzinfo=now.tzinfo,
                )
                for group in self.prediction_targets:
                    if now < scheduled and not (
                        kind == "竞猜" and self._prediction_follows_schedule(group)
                    ):
                        continue
                    try:
                        await self._deliver_scheduled_prediction(group, kind)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._record_prediction_error("播报异常", group, exc)
            if refreshed:
                await self._deliver_after_match_ranks()
            await asyncio.sleep(60)

    @property
    def rank_after_matches_targets(self):
        if not self._safe_bool(
            self.config.get("prediction_enabled")
        ) or not self._safe_bool(
            self.config.get("prediction_rank_after_matches_enabled")
        ):
            return []
        selected = self._normalize_push_targets(
            self._split_csv_text(
                self.config.get("prediction_rank_after_matches_targets")
            )
        )
        return [group for group in selected if group in self.prediction_targets]

    def _watch_rank_days(self):
        today = self._today_in_display_timezone().isoformat()
        ids = [m["match_id"] for m in self.prediction_store.matches(today)]
        for group in self.rank_after_matches_targets:
            self.prediction_store.watch_rank_day(today, group, ids)

    async def _deliver_after_match_ranks(self):
        for group in self.rank_after_matches_targets:
            for batch in self.prediction_store.pending_rank_days(group):
                try:
                    await self._deliver_after_match_rank(group, batch["day"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._record_prediction_error("赛后积分榜发送暂不可用", group, exc)

    async def _deliver_after_match_rank(self, group, day):
        async with self._prediction_delivery_lock:
            if group not in self.rank_after_matches_targets:
                return
            if self.prediction_store.delivered(
                day, "赛后积分", group
            ) or not self.prediction_store.rank_day_ready(day, group):
                return
            if not await self._rank_reports_ready(group, day):
                return
            return await self._broadcast_prediction(
                group,
                "积分",
                scheduled=True,
                delivery_key="赛后积分",
                delivery_day=day,
                rank_day=day,
            )

    async def _rank_reports_ready(self, group, day):
        if not self.special_report_enabled or group not in self.special_push_targets:
            return True
        try:
            from .clients.vlr import MatchRecord
        except ImportError:
            from clients.vlr import MatchRecord
        batch = next(
            (
                b
                for b in self.prediction_store.pending_rank_days(group)
                if b["day"] == day
            ),
            None,
        )
        if not batch:
            return False
        if not hasattr(self, "_special_state"):
            self._special_state = {}
        for row in self.prediction_store.matches():
            if row["match_id"] not in batch[
                "match_ids"
            ] or self.prediction_store.report_delivered(group, row["match_id"]):
                continue
            metadata = self.prediction_store.match_metadata(row["match_id"])
            record = MatchRecord(
                row["match_id"],
                row["day"],
                datetime.fromisoformat(row["start_at"]).strftime("%H:%M"),
                "已结束",
                row["team_a"],
                row["team_b"],
                f"{row['result_a']}:{row['result_b']}",
                metadata.get("tournament", ""),
                metadata.get("schedule", ""),
                "",
                f"Bo{row['bo']}",
                "VLR",
                {},
            )
            key = self._match_state_key(record)
            state = self._special_state.setdefault(
                key, {"created_at": self._now_in_display_timezone()}
            )
            state.update(match=record, start_sent=True)
            await self._check_special_match_result(record, state)
        return all(
            self.prediction_store.report_delivered(group, mid)
            for mid in batch["match_ids"]
        )

    def _prediction_follows_schedule(self, group):
        return (
            self._safe_bool(self.config.get("prediction_after_schedule"))
            and self._safe_bool(self.config.get("enable_daily_push"))
            and group in self.push_targets
        )

    async def _deliver_scheduled_prediction(self, group, kind):
        async with self._prediction_delivery_lock:
            if kind == "积分" and group in self.rank_after_matches_targets:
                return
            day = self._today_in_display_timezone().isoformat()
            follows = kind == "竞猜" and self._prediction_follows_schedule(group)
            key = "赛程后竞猜" if follows else kind
            if self.prediction_store.delivered(day, key, group):
                return
            if follows and not self.prediction_store.delivered(day, "赛程完成", group):
                return
            return await self._broadcast_prediction(
                group, kind, scheduled=True, delivery_key=key, delivery_day=day
            )

    async def _after_daily_schedule(self, group):
        self.prediction_store.mark_delivered(
            self._today_in_display_timezone().isoformat(), "赛程完成", group
        )
        if (
            not self._safe_bool(self.config.get("prediction_enabled"))
            or not self._safe_bool(self.config.get("prediction_daily_enabled"))
            or group not in self.prediction_targets
            or not self._prediction_follows_schedule(group)
        ):
            return
        try:
            await self._refresh_predictions()
            await self._deliver_scheduled_prediction(group, "竞猜")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_prediction_error("赛程后竞猜发送暂不可用", group, exc)

    def _record_prediction_error(self, kind, group, exc):
        self._prediction_last_error = str(exc)
        with self.prediction_store.db:
            self.prediction_store.event(kind, group, str(exc))
        logger.warning("VAL %s: %s", kind, exc)

    async def _refresh_predictions(self):
        async with self._prediction_lock:
            today = self._today_in_display_timezone()
            days = {today}
            watched_ids = set()
            for group in self.rank_after_matches_targets:
                for batch in self.prediction_store.pending_rank_days(group):
                    days.add(date.fromisoformat(batch["day"]))
                    watched_ids.update(batch["match_ids"])
            for m in self.prediction_store.matches():
                if m["result_a"] is None and (
                    m["match_id"] in watched_ids
                    or self.prediction_store.db.execute(
                        "SELECT 1 FROM predictions WHERE match_id=?", (m["match_id"],)
                    ).fetchone()
                ):
                    days.add(date.fromisoformat(m["day"]))
            errors = []
            for day in sorted(days):
                try:
                    matches, _ = await self._query_matches(day)
                    filtered, _ = self._apply_preferred_filters(
                        matches, self.default_levels, False
                    )
                    # Continue settling stored predictions even after changing followed events.
                    known = {m["match_id"] for m in self.prediction_store.matches()}
                    for m in matches:
                        if m not in filtered and m.match_id not in known:
                            continue
                        self._remember_prediction_match(m)
                        await self._enrich_prediction_match(m)
                        if m.status == "已结束":
                            score = parse_score(m.score)
                            if score:
                                self.prediction_store.settle(m.match_id, *score)
                except Exception as exc:
                    errors.append(f"{day}: {exc}")
            for state in getattr(self, "_special_state", {}).values():
                match = state.get("match")
                if match is not None:
                    await self._enrich_prediction_match(match)
            self._prediction_last_refresh = self._now_in_display_timezone().isoformat()
            self._prediction_last_error = "; ".join(errors)
            if errors:
                raise RuntimeError(self._prediction_last_error)

    def _remember_prediction_match(self, match):
        start = self._match_start_datetime(match)
        if (
            not start
            or not match.match_id
            or any(
                t.strip().casefold() in {"", "tbd", "tba", "待定", "未知"}
                for t in [match.team_a, match.team_b]
            )
        ):
            return
        try:
            bo = best_of(match.best_of)
        except ValueError:
            return
        self.prediction_store.sync_match(
            match.match_id, match.team_a, match.team_b, bo, start, match.status
        )
        self.prediction_store.set_match_metadata(
            match.match_id,
            {
                "tournament": match.tournament_name,
                "schedule": match.schedule_name,
                "event_href": (match.raw or {}).get("event_href") or None,
            },
        )

    async def _verify_prediction_match(self, row):
        """Refresh detail before every write: early LIVE and changed schedules close safely."""
        try:
            from .clients.vlr import MatchRecord
        except ImportError:
            from clients.vlr import MatchRecord
        record = MatchRecord(
            row["match_id"],
            row["day"],
            datetime.fromisoformat(row["start_at"]).strftime("%H:%M"),
            "未开始",
            row["team_a"],
            row["team_b"],
            "-",
            "",
            "",
            "",
            f"Bo{row['bo']}",
            "VLR",
            {},
        )
        detail = await self.vlr_client._get_vlr_match_detail_info(
            self.vlr_client._match_href(record), force_refresh=True
        )
        html = detail.get("html", "")
        soup = __import__("bs4", fromlist=["BeautifulSoup"]).BeautifulSoup(
            html, "html.parser"
        )
        header = soup.select_one(".match-header-vs-score")
        text = header.get_text(" ", strip=True).casefold() if header else ""
        if header and (
            header.select_one(".mod-live") or re.search(r"\b(live|in progress)\b", text)
        ):
            status = "进行中"
        elif header and (
            header.select_one(".mod-final")
            or re.search(r"\b(final|completed|cancelled|canceled|forfeit)\b", text)
        ):
            status = "已封盘"
        elif header and header.select_one(".mod-upcoming"):
            status = "未开始"
        else:
            raise ValueError("暂时无法核实比赛状态，我没有更改竞猜，请稍后重试。")
        bo = best_of(detail.get("best_of", ""))
        start = detail.get("utc_dt")
        if not isinstance(start, datetime) or start.tzinfo is None:
            raise ValueError("暂时无法核实开赛时间，我没有更改竞猜，请稍后重试。")
        self.prediction_store.sync_match(
            row["match_id"],
            detail.get("team_a_display_name") or row["team_a"],
            detail.get("team_b_display_name") or row["team_b"],
            bo,
            start.astimezone(self._get_display_tz()),
            status,
        )

    def _prediction_list_text(self, group=None):
        now = self._now_in_display_timezone()
        lines = [f"🎮 今日竞猜 · {now:%m月%d日}", "🎯 " + RULE]
        rows = self.prediction_store.matches(now.date().isoformat())
        for i, m in enumerate(rows, 1):
            cutoff = datetime.fromisoformat(m["lock_at"]).astimezone(now.tzinfo)
            if m["result_a"] is not None:
                state = f"✅ 已结束 · 赛果 {m['result_a']}:{m['result_b']}"
            elif m["status"] == "进行中":
                state = "🔴 比赛进行中 · 已封盘"
            elif m["status"] != "未开始" or now >= cutoff:
                state = "🔒 已封盘"
            else:
                state = f"🟢 可竞猜 · {cutoff:%H:%M} 截止"
            text = f"{i}. {m['team_a']} vs {m['team_b']} · BO{m['bo']}\n🕒 开赛 {datetime.fromisoformat(m['start_at']).astimezone(now.tzinfo):%H:%M}\n{state}"
            bot = self._bot_match_info(group, m["match_id"])
            if bot:
                if bot["state"] == "ready":
                    text += f"\n🤖 {bot['name']} 选 {short_team(m['team_a'] if bot['a'] > bot['b'] else m['team_b'])} 胜"
            lines.append(text)
        if not rows:
            lines.append("今日暂无已确认赛制和时间的特别关心比赛。")
        available = next(
            (
                m
                for m in rows
                if m["status"] == "未开始"
                and now < datetime.fromisoformat(m["lock_at"])
            ),
            None,
        )
        if available:
            a, b = short_team(available["team_a"]), short_team(available["team_b"])
            lines.append(
                f"💬 参与：@我说“我猜 {a} 赢”。\n✏️ 修改：@我说“把 {a} 那场改成 {b} 赢”。"
            )
        if group in self.click_prediction_targets:
            lines.append(
                "🖱️ 本群也支持点选：直接点比赛消息下方的表情选胜队，点另一个即可改选，无需打字或 @。"
            )
        lines.append(
            "🧾 多场可一起说：带上各场队名和胜队，用逗号或“然后”分开；修改也支持。\n🔒 开赛前 10 分钟封盘，之后不能竞猜或修改。\n"
            + VIEW
        )
        return "\n\n".join(lines)

    def _prediction_tournaments(self):
        selected = [
            self.prediction_store.ensure_tournament(n)["tournament_id"]
            for n in self.preferred_tournaments
        ]
        rows = self.prediction_store.tournaments()
        rows = [r for r in rows if r["match_count"] or r["tournament_id"] in selected]
        if not rows:
            rows = [{**self.prediction_store.tournament("legacy"), "match_count": 0}]
        for row in rows:
            row["current"] = row["tournament_id"] in selected
        return sorted(rows, key=lambda r: not r["current"])

    def _view_tournament_ids(self, text=""):
        options = self._prediction_tournaments()
        cleaned = re.sub(r"\[CQ:at,[^\]]+\]|\[At:[^\]]+\]", "", text)
        cleaned = re.sub(
            r"我的竞猜|我的预测|你的竞猜|你的预测|机器人的?竞猜|机器人的?预测|竞猜积分榜|竞猜排行榜|积分排行榜|积分排名|积分排行|积分情况|积分多少|积分榜|排行榜|我的积分|查看|看看|查一下|查询|显示|帮我|给我|请|我想|我猜了什么|我押了什么|当前|本赛事|本群|赛事",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"群里的?|群内的?|群成员|我们群的?|咱们群的?|记录|情况|一下", "", cleaned
        )

        def normalize(s):
            return re.sub(r"[\W_]+", "", s).casefold()

        keyword = normalize(cleaned).strip("呢啊吧")
        if keyword in {"积分", "排名", "排行", "群积分"}:
            keyword = ""
        if keyword == "历史":
            archived = [
                r["tournament_id"]
                for r in options
                if not r["current"] and r["match_count"]
            ]
            return archived or [r["tournament_id"] for r in options]
        if keyword:
            candidates = []
            for row in options:
                aliases = [normalize(row["name"])]
                if "champions" in row["name"].casefold():
                    year = "".join(re.findall(r"20\d\d", row["name"]))
                    aliases += [
                        "冠军赛",
                        "全球冠军赛",
                        "冠军赛" + year,
                        year + "冠军赛",
                    ]
                if any(s in row["name"].casefold() for s in ("threshold", "ascension")):
                    aliases += ["晋升赛", "晋级赛"]
                if any(
                    keyword == a or (len(keyword) >= 2 and keyword in a)
                    for a in aliases
                ):
                    candidates.append(row["tournament_id"])
            if len(candidates) == 1:
                return candidates
            hint = "、".join(r["name"] for r in options)
            raise ValueError(
                ("赛事不够明确" if candidates else "没有找到这项赛事的竞猜榜单")
                + "。请带上完整赛事名，例如“VCT China 2026: Threshold 积分榜”。可查看："
                + hint
            )
        current = [r["tournament_id"] for r in options if r["current"]]
        if current:
            return current
        today = {
            m["tournament_id"]
            for m in self.prediction_store.matches(
                self._today_in_display_timezone().isoformat()
            )
        }
        return [r["tournament_id"] for r in options if r["tournament_id"] in today] or [
            options[0]["tournament_id"]
        ]

    def _rank_text(self, group, tournament_id=None, day=None, text=""):
        if tournament_id:
            event = self.prediction_store.tournament(tournament_id)
            if not event:
                raise ValueError("请选择有效的赛事。")
            ids = [event["tournament_id"]]
        else:
            ids = (
                self.prediction_store.rank_day_tournaments(day, group)
                if day
                else self._view_tournament_ids(text)
            )
        name = getattr(self, "_prediction_groups", {}).get(group, "本群")
        return "\n\n──────────\n\n".join(
            leaderboard(
                name,
                self.prediction_store.leaderboard(group, tid),
                self._now_in_display_timezone(),
                self.prediction_store.tournament(tid)["name"],
            )
            for tid in ids
        )

    def _my_prediction_text(self, group, user, name, text):
        boards = []
        for tid in self._view_tournament_ids(text):
            rows = self.prediction_store.predictions(group, user, tid)
            points = next(
                (
                    r["points"]
                    for r in self.prediction_store.leaderboard(group, tid)
                    if r["user_id"] == user
                ),
                0,
            )
            boards.append(
                my_predictions(
                    name,
                    rows,
                    points,
                    self._now_in_display_timezone(),
                    self._get_display_tz(),
                    self.prediction_store.tournament(tid)["name"],
                )
            )
        return "\n\n──────────\n\n".join(boards)

    async def _save_member_prediction(self, group, user, match, a, b):
        async with self._prediction_lock:
            await self._verify_prediction_match(match)
            updated = next(
                m
                for m in self.prediction_store.matches()
                if m["match_id"] == match["match_id"]
            )
            if updated["day"] != self._today_in_display_timezone().isoformat():
                raise ValueError("这场比赛的日期已变更，目前只支持今天的比赛。")
            changed = self.prediction_store.submit(
                group,
                user,
                match["match_id"],
                a,
                b,
                self._now_in_display_timezone(),
                mode="winner",
            )
        return changed, updated

    async def _batch_prediction_message(self, text, requests, group, user, name, teams):
        validate_batch_request(text)
        if len(requests) > 20:
            raise ValueError("一次最多处理 20 场竞猜，请分几条消息发送。")
        await self._refresh_predictions()
        rows = self.prediction_store.matches(
            self._today_in_display_timezone().isoformat()
        )
        entries = []
        bot_scope = prediction_intent(requests[0], True, teams) == "bot_change"
        for clause in requests:
            entry = {"clause": clause}
            try:
                if prediction_intent(clause, True, teams) == "bot_change" or (
                    bot_scope
                    and not re.search(r"我(?:的|猜|竞猜|预测)|帮我|给我", clause)
                ):
                    raise ValueError("机器人的预测独立生成，不能由群成员修改。")
                # Each batch entry needs its own match, never the user's last pick.
                entry["match"] = resolve_prediction_match(clause, rows)[0]
                match, a, b = resolve_winner_prediction(clause, rows)
                entry.update(match=match, a=a, b=b)
            except ValueError as exc:
                entry["error"] = str(exc)
            entries.append(entry)
        ids = [e["match"]["match_id"] for e in entries if "match" in e]
        for e in entries:
            if "match" in e and ids.count(e["match"]["match_id"]) > 1:
                e["error"] = (
                    "同一句里多次提到这场比赛，请只保留一个确定的胜队；本场没有修改。"
                )
        lines, saved = [], 0
        for i, e in enumerate(entries, 1):
            if "error" not in e:
                try:
                    changed, updated = await self._save_member_prediction(
                        group, user, e["match"], e["a"], e["b"]
                    )
                    saved += 1
                    m = e["match"]
                    cutoff = datetime.fromisoformat(updated["lock_at"]).astimezone(
                        self._get_display_tz()
                    )
                    lines.append(
                        f"{i}. {'✏️ 已修改' if changed else '✅ 已提交'}\n{m['team_a']} vs {m['team_b']}\n🏁 预测胜队：{m['team_a'] if e['a'] > e['b'] else m['team_b']}\n🔒 截止 {cutoff:%m-%d %H:%M}（{self.display_timezone}）"
                    )
                except ValueError as exc:
                    e["error"] = str(exc)
                except Exception as exc:
                    logger.warning("VAL 批量竞猜单场请求失败: %s", exc)
                    e["error"] = "暂时无法核实比赛状态，本场没有修改，请稍后重试。"
            if "error" in e:
                lines.append(f"{i}. ⚠️ 未保存 · {name_text(e['clause'])}\n{e['error']}")
        return "\n\n".join(
            [
                f"🧾 批量竞猜结果\n👤 {name_text(name)}\n成功 {saved} 场 · 未保存 {len(entries) - saved} 场",
                *lines,
                "✏️ 截止前可再次 @我，带上各场队名和新胜队一起修改。\n🎯 "
                + RULE
                + "\n"
                + VIEW,
            ]
        )

    async def _handle_prediction_message(self, event):
        if (
            not self._safe_bool(self.config.get("prediction_enabled"))
            or event.unified_msg_origin not in self.prediction_targets
        ):
            return
        # Require a real @bot component, not generic wake words / @other users.
        if not any(
            isinstance(c, At) and str(c.qq) == str(event.message_obj.self_id)
            for c in event.message_obj.message
        ):
            return
        text = event.message_str.strip()
        if text.startswith(("/val", "val ")):
            return
        try:
            has_score = parse_score(text) is not None
        except ValueError:
            has_score = True
        teams = [
            m[side]
            for m in self.prediction_store.matches()
            for side in ("team_a", "team_b")
        ]
        requests = split_winner_requests(text, teams)
        intent = prediction_intent(text, has_score, teams)
        if intent == "bot_change" and len(requests) > 1:
            intent = "submit"
        if intent is None:
            return
        event.stop_event()
        group, user, name = (
            event.unified_msg_origin,
            event.get_sender_id(),
            event.get_sender_name(),
        )
        self.prediction_store.member(group, user, name)
        if intent == "bot_change":
            yield event.plain_result(
                "🤖 我的预测会综合交手记录、近期表现和赛制独立生成，不能由群成员修改。\n✏️ 修改自己的竞猜：@我说“把 EDG 那场改成 PRX 赢”。"
            )
            return
        try:
            if intent == "rank":
                await self._sync_prediction_members(group)
                for path in await self._rank_images(group, text=text):
                    yield event.image_result(path)
                return
            elif intent == "bot":
                account = self.prediction_store.bot_account(group)
                if account:
                    message = self._my_prediction_text(
                        group, account["user_id"], "🤖 " + account["name"], text
                    )
                    message = (
                        re.sub(
                            r"✏️ 修改：.*?(?=\n\n──────────|$)", "", message, flags=re.S
                        ).rstrip()
                        + "\n🤖 我的预测根据比赛资料独立生成，群成员不能修改。"
                    )
                else:
                    message = "🤖 机器人参与竞猜尚未开启，可在赛事控制台的设置中开启。"
            elif intent == "mine":
                message = self._my_prediction_text(group, user, name, text)
            elif intent == "help":
                message = HELP
            elif intent == "list":
                await self._refresh_predictions()
                if group in self.click_prediction_targets:
                    ids = await self._send_click_cards(group, force=True)
                    if ids:
                        return
                message = self._prediction_list_text(group)
            elif len(requests) > 1:
                message = await self._batch_prediction_message(
                    text, requests, group, user, name, teams
                )
            else:
                await self._refresh_predictions()
                previous = self.prediction_store.last_match(group, user)
                today = self._today_in_display_timezone().isoformat()
                rows = self.prediction_store.matches(today)
                match, a, b = resolve_winner_prediction(text, rows, previous)
                changed, updated = await self._save_member_prediction(
                    group, user, match, a, b
                )
                message = f"{'✏️ 已修改竞猜' if changed else '✅ 竞猜成功'}\n👤 {name_text(name)}\n\n{match['team_a']} vs {match['team_b']}\n🏁 预测胜队：{match['team_a'] if a > b else match['team_b']}\n🔒 截止：{datetime.fromisoformat(updated['lock_at']).astimezone(self._get_display_tz()):%m-%d %H:%M}（{self.display_timezone}）\n\n截止前可 @我说“把 {short_team(match['team_a'])} 那场改成 {short_team(match['team_b'] if a > b else match['team_a'])} 赢”。\n🎯 {RULE}\n{VIEW}"
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.warning("VAL 竞猜请求失败: %s", exc)
            message = "赛程服务暂时不可用，我没有修改你的竞猜。请稍后重试；仍可 @我说“我的竞猜”或者“积分榜”查看已保存的信息。"
        yield event.plain_result(message)
        if intent == "list":
            try:
                await self._send_click_cards(group, force=True)
            except Exception as exc:
                self._record_prediction_error("点选卡片发送失败", group, exc)

    async def _sync_prediction_members(self, group):
        platform_id, _, group_id = group.split(":", 2)
        platform = self.context.get_platform_inst(platform_id)
        bot = getattr(platform, "bot", None)
        if not bot:
            return
        try:
            members = await asyncio.wait_for(
                bot.call_action(
                    "get_group_member_list",
                    group_id=int(group_id) if group_id.isdigit() else group_id,
                ),
                timeout=15,
            )
            for m in members if isinstance(members, list) else []:
                self.prediction_store.member(
                    group,
                    str(m["user_id"]),
                    m.get("card") or m.get("nickname") or str(m["user_id"]),
                )
        except Exception as exc:
            logger.info("VAL 群成员同步暂不可用: %s", exc)

    async def _broadcast_prediction(
        self,
        group,
        kind,
        scheduled=False,
        delivery_key=None,
        delivery_day=None,
        rank_day=None,
        tournament_id=None,
    ):
        if group not in self.prediction_targets:
            raise ValueError("请先将此群加入竞猜目标。")
        if kind == "积分":
            await self._sync_prediction_members(group)
            message = self._rank_text(group, tournament_id=tournament_id, day=rank_day)
            if rank_day:
                message = (
                    f"🏁 {date.fromisoformat(rank_day):%m月%d日}的比赛已结束，竞猜已结算。\n\n"
                    + message
                )
        elif kind == "竞猜":
            await self._ensure_bot_predictions()
            message = self._prediction_list_text(group)
        else:
            raise ValueError("未知播报类型。")
        if kind == "竞猜" and group in self.click_prediction_targets:
            ids = await self._send_click_cards(group, force=not scheduled)
            message = f"已发送 {len(ids)} 场胜负竞猜，每场两个选项。"
            if not ids:
                message = "🎯 今日暂无开放竞猜的比赛。"
                ok = await self.context.send_message(
                    group, MessageChain().message(message)
                )
                if not ok:
                    raise RuntimeError("平台未确认发送成功。")
        else:
            chain = MessageChain()
            if kind == "积分":
                for path in await self._rank_images(
                    group, tournament_id=tournament_id, day=rank_day
                ):
                    chain.file_image(path)
            else:
                chain.message(message)
            ok = await self.context.send_message(group, chain)
            if not ok:
                raise RuntimeError("平台未确认发送成功。")
        if scheduled:
            self.prediction_store.mark_delivered(
                delivery_day or self._today_in_display_timezone().isoformat(),
                delivery_key or kind,
                group,
            )
        else:
            with self.prediction_store.db:
                self.prediction_store.event("手动播报", group, kind)
        return message

    async def page_status(self):
        group = request.query.get("group", "")
        if group and group not in self.prediction_targets:
            return error_response("请选择已配置的竞猜群。")
        tournaments = self._prediction_tournaments()
        requested = request.query.get("tournament", "")
        event = (
            self.prediction_store.tournament(requested)
            if requested
            else self.prediction_store.tournament(self._view_tournament_ids()[0])
        )
        if not event:
            return error_response("请选择有效的赛事。")
        tournament_id = event["tournament_id"]
        snapshot = self._build_monitor_snapshot()
        for m in snapshot["match_states"]:
            m.update(self.prediction_store.match_metadata(m["match_id"]))
        snapshot["schedule"] = snapshot["match_states"]
        snapshot["predictions"] = {
            "enabled": self._safe_bool(self.config.get("prediction_enabled")),
            "running": bool(self._prediction_task and not self._prediction_task.done()),
            "targets": [
                {
                    "id": g,
                    "name": self._prediction_groups.get(g, "群 " + g.split(":")[-1]),
                }
                for g in self.prediction_targets
            ],
            "last_refresh": self._prediction_last_refresh,
            "last_error": self._prediction_last_error,
            "bot_enabled": self._safe_bool(self.config.get("prediction_bot_enabled")),
            "rank_after_matches": group in self.rank_after_matches_targets,
            "tournaments": tournaments,
            "tournament_id": tournament_id,
            "tournament_name": event["name"],
            "rank_batches": [
                {
                    "day": b["day"],
                    "match_count": len(b["match_ids"]),
                    "ready": self.prediction_store.rank_day_ready(b["day"], group),
                }
                for b in self.prediction_store.pending_rank_days(group)
            ]
            if group in self.rank_after_matches_targets
            else [],
            "matches": [
                {
                    **m,
                    **self.prediction_store.match_metadata(m["match_id"]),
                    "bot": self._bot_match_info(group, m["match_id"]),
                }
                for m in self.prediction_store.matches(
                    self._today_in_display_timezone().isoformat()
                )
                if m["tournament_id"] == tournament_id
            ],
            "leaderboard": self.prediction_store.leaderboard(group, tournament_id)
            if group
            else [],
            "entries": self.prediction_store.predictions(
                group, tournament_id=tournament_id
            )[:200]
            if group
            else [],
            "events": self.prediction_store.events(),
        }
        return json_response(snapshot)

    async def page_settings(self):
        schema = json.loads((self.plugin_root / "_conf_schema.json").read_text())
        return json_response(
            {
                "schema": schema,
                "values": {
                    k: self.config.get(k, v.get("default")) for k, v in schema.items()
                },
            }
        )

    def _validate_page_settings(self, payload):
        schema = json.loads((self.plugin_root / "_conf_schema.json").read_text())
        if not isinstance(payload, dict) or any(k not in schema for k in payload):
            raise ValueError("设置包含未知字段。")
        for key, value in payload.items():
            spec = schema[key]
            typ = spec["type"]
            if (
                (typ == "bool" and type(value) is not bool)
                or (typ == "int" and type(value) is not int)
                or (typ in {"string", "text"} and not isinstance(value, str))
                or (
                    typ == "list"
                    and (
                        not isinstance(value, list)
                        or any(not isinstance(x, str) for x in value)
                    )
                )
            ):
                raise ValueError(f"{spec['description']}格式错误。")
            if key.endswith("_time") and not re.fullmatch(
                r"(?:[01]\d|2[0-3]):[0-5]\d", value
            ):
                raise ValueError(f"{spec['description']}请填 HH:MM。")
            if typ == "int" and not 0 <= value <= 100000:
                raise ValueError(f"{spec['description']}超出范围。")
            if key == "daily_push_lead_minutes" and not 1 <= value <= 1440:
                raise ValueError("首场赛前提前分钟数请填写 1–1440。")
            if typ in {"string", "text"} and len(value) > 10000:
                raise ValueError("设置内容过长。")
            if spec.get("options") and typ == "string" and value not in spec["options"]:
                raise ValueError("请选择有效选项。")
            if key == "display_timezone":
                from zoneinfo import ZoneInfo

                try:
                    ZoneInfo(value)
                except Exception:
                    raise ValueError("时区无效。")
            if key.endswith("_targets"):
                raw = self._split_csv_text(value)
                normalized = self._normalize_push_targets(raw)
                if len(raw) != len(normalized) or (
                    key
                    in {"prediction_targets", "prediction_rank_after_matches_targets"}
                    and any(":GroupMessage:" not in g for g in normalized)
                ):
                    raise ValueError("推送目标格式错误，竞猜目标必须为群会话。")
        if (
            "prediction_targets" in payload
            or "prediction_rank_after_matches_targets" in payload
        ):
            targets = self._normalize_push_targets(
                self._split_csv_text(
                    payload.get(
                        "prediction_targets", self.config.get("prediction_targets")
                    )
                )
            )
            rank_targets = self._normalize_push_targets(
                self._split_csv_text(
                    payload.get(
                        "prediction_rank_after_matches_targets",
                        self.config.get("prediction_rank_after_matches_targets"),
                    )
                )
            )
            if any(g not in targets for g in rank_targets):
                raise ValueError("赛后积分榜群必须先加入竞猜目标群。")
        return payload

    async def page_save_settings(self):
        try:
            payload = self._validate_page_settings(await request.json(default={}))
            async with self._settings_lock:
                previous = dict(self.config)
                try:
                    self.config.update(payload)
                    self.config.save_config()
                except Exception:
                    self.config.clear()
                    self.config.update(previous)
                    raise
                await self._restart_push_task()
                await self._restart_special_task()
                await self._restart_prediction_task()
                with self.prediction_store.db:
                    self.prediction_store.event(
                        "设置保存", "", f"已调整 {len(payload)} 项设置"
                    )
            return json_response({"saved": True})
        except ValueError as exc:
            return error_response(str(exc))

    async def page_groups(self):
        groups = []
        errors = []
        for platform in self.context.platform_manager.platform_insts:
            bot = getattr(platform, "bot", None)
            if not bot:
                continue
            try:
                rows = await asyncio.wait_for(
                    bot.call_action("get_group_list"), timeout=10
                )
                for g in rows if isinstance(rows, list) else []:
                    origin = f"{platform.meta().id}:GroupMessage:{g['group_id']}"
                    name = g.get("group_name") or str(g["group_id"])
                    groups.append({"id": origin, "name": name})
                    self._prediction_groups[origin] = name
                    self.prediction_store.set_group_name(origin, name)
            except Exception as exc:
                errors.append(f"{platform.meta().id}: {str(exc) or type(exc).__name__}")
        return json_response({"groups": groups, "errors": errors})

    async def page_sync_events(self):
        try:
            names = await self.vlr_client.discover_tournaments()
            self._update_tournament_options(names)
            return json_response({"options": names})
        except Exception as exc:
            return error_response(str(exc), status_code=503)

    async def page_refresh(self):
        try:
            await self._refresh_predictions()
            return json_response({"refreshed": True})
        except Exception as exc:
            return error_response(str(exc), status_code=503)

    async def page_broadcast(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求格式错误。")
        try:
            if not self._safe_bool(self.config.get("prediction_enabled")):
                raise ValueError("请先启用竞猜。")
            if payload.get("group") not in self.prediction_targets:
                raise ValueError("请先选择竞猜目标群。")
            if payload.get("kind") == "竞猜":
                await self._refresh_predictions()
            message = await self._broadcast_prediction(
                payload.get("group"),
                payload.get("kind"),
                tournament_id=payload.get("tournament") or None,
            )
            return json_response({"sent": True, "preview": message})
        except Exception as exc:
            return error_response(str(exc))
