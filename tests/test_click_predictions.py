import asyncio
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import test_prediction_feature as fixture
from test_predictions import NOW

from click_predictions import score_choices, winner_choices
from predictions import PredictionStore, validate_score

GROUP = "default:GroupMessage:42"


class ClickPredictionTests(unittest.IsolatedAsyncioTestCase):
    tearDown = fixture.FeatureTests.tearDown

    def setUp(self):
        fixture.FeatureTests.setUp(self)
        self.p.config.update(
            prediction_click_enabled=True, prediction_click_targets=GROUP
        )
        self.counter = 0

        async def api(action, **params):
            if action == "get_version_info":
                return {"app_name": "NapCat.Onebot", "app_version": "4.18.1"}
            if action == "send_group_msg":
                self.counter += 1
                return {"message_id": str(100 + self.counter)}
            if action == "get_group_member_info":
                return {"user_id": params["user_id"], "nickname": "群友"}
            return {"result": 0}

        self.bot = SimpleNamespace(call_action=AsyncMock(side_effect=api))
        platform = SimpleNamespace(
            bot=self.bot, meta=lambda: SimpleNamespace(name="aiocqhttp")
        )
        self.p.context = SimpleNamespace(get_platform_inst=lambda name: platform)

    async def card(self, demo=False):
        match = self.p.prediction_store.matches()[0]
        return await self.p._send_click_card(GROUP, match, demo=demo)

    def event(self, mid, emoji="285", user="user", is_add=True, at=None, group=GROUP):
        raw = {
            "post_type": "notice",
            "notice_type": "group_msg_emoji_like",
            "group_id": group.split(":")[-1],
            "message_id": mid,
            "user_id": user,
            "self_id": "bot",
            "is_add": is_add,
            "time": at or NOW.timestamp(),
            "likes": [{"emoji_id": emoji, "count": 1}],
        }
        stop = Mock()
        return SimpleNamespace(
            message_str="",
            unified_msg_origin=group,
            message_obj=SimpleNamespace(raw_message=raw, self_id="bot", message=[]),
            stop_event=stop,
            is_stopped=lambda: stop.call_count > 0,
            get_sender_id=lambda: user,
            get_sender_name=lambda: user,
            plain_result=lambda s: s,
        )

    async def call(self, event):
        return [r async for r in self.p.prediction_message(event)]

    def picks(self):
        return self.p.prediction_store.predictions(GROUP)

    def test_legal_choices_for_each_series(self):
        for bo, expected in [(1, 2), (3, 4), (5, 6)]:
            choices = score_choices(bo)
            self.assertEqual(len(choices), expected)
            for c in choices.values():
                validate_score(bo, c["a"], c["b"])

    async def test_card_has_real_message_id_and_bot_shortcuts_never_vote(self):
        mid = await self.card()
        self.assertTrue(self.p._click_card(GROUP, mid))
        for emoji in winner_choices():
            self.assertEqual(await self.call(self.event(mid, emoji, user="bot")), [])
        self.assertEqual(self.picks(), [])
        seeds = [
            c
            for c in self.bot.call_action.call_args_list
            if c.args[0] == "set_msg_emoji_like"
        ]
        self.assertEqual(len(seeds), 2)

    async def test_click_and_modification_work_without_text_or_mention(self):
        mid = await self.card()
        response = await self.call(self.event(mid))
        self.assertIn("竞猜已记录", response[0])
        self.assertIn("群友", response[0])
        self.assertEqual((self.picks()[0]["a"], self.picks()[0]["b"]), (1, 0))
        response = await self.call(self.event(mid, "293", at=NOW.timestamp() + 1))
        self.assertIn("竞猜已修改", response[0])
        self.assertEqual((self.picks()[0]["a"], self.picks()[0]["b"]), (0, 1))
        self.p._verify_prediction_match.assert_awaited()

    async def test_duplicate_and_removed_reaction_do_not_resubmit_or_cancel(self):
        mid = await self.card()
        event = self.event(mid)
        await self.call(event)
        before = self.picks()
        self.assertEqual(await self.call(event), [])
        self.assertEqual(
            await self.call(self.event(mid, is_add=False, at=NOW.timestamp() + 1)), []
        )
        self.assertEqual(before, self.picks())

    async def test_demo_records_click_and_modification_without_any_real_prediction(
        self,
    ):
        self.p.prediction_store.member(GROUP, "user", "群友")
        mid = await self.card(demo=True)
        await self.call(self.event(mid))
        reply = await self.call(self.event(mid, "293", at=NOW.timestamp() + 1))
        self.assertIn("测试已修改", reply[0])
        self.assertIn("不计积分", reply[0])
        self.assertEqual(self.picks(), [])
        row = self.p.prediction_store.db.execute(
            "SELECT * FROM click_selections"
        ).fetchone()
        self.assertEqual((row["a"], row["b"]), (0, 1))
        self.assertEqual(self.p.prediction_store.leaderboard(GROUP)[0]["points"], 0)

    async def test_cutoff_and_early_live_are_enforced(self):
        mid = await self.card()
        self.p._now_in_display_timezone = lambda: NOW + timedelta(minutes=50)
        reply = await self.call(
            self.event(mid, at=(NOW + timedelta(minutes=50)).timestamp())
        )
        self.assertIn("已封盘", reply[0])
        self.assertEqual(self.picks(), [])
        self.p._now_in_display_timezone = lambda: NOW

        async def live(match):
            self.p.prediction_store.sync_match(
                "123456",
                "EDward Gaming",
                "Paper Rex",
                3,
                NOW + timedelta(hours=1),
                "进行中",
            )

        self.p._verify_prediction_match.side_effect = live
        reply = await self.call(self.event(mid, "293", at=NOW.timestamp() + 1))
        self.assertIn("已封盘", reply[0])
        self.assertEqual(self.picks(), [])

    async def test_moved_to_tomorrow_cannot_be_predicted(self):
        mid = await self.card()

        async def moved(match):
            self.p.prediction_store.sync_match(
                "123456",
                "EDward Gaming",
                "Paper Rex",
                3,
                NOW + timedelta(days=1),
                "未开始",
            )

        self.p._verify_prediction_match.side_effect = moved
        reply = await self.call(self.event(mid))
        self.assertIn("只支持今天", reply[0])
        self.assertEqual(self.picks(), [])

    async def test_unrelated_wrong_group_unknown_actor_and_emoji_are_ignored(self):
        mid = await self.card()
        for event in [
            self.event("999"),
            self.event(mid, "unknown"),
            self.event(mid, user="0"),
            self.event(mid, group="default:GroupMessage:43"),
        ]:
            self.assertEqual(await self.call(event), [])
        event = self.event(mid)
        event.message_obj.raw_message["likes"].append({"emoji_id": "293", "count": 1})
        self.assertEqual(await self.call(event), [])
        self.assertEqual(self.picks(), [])

    async def test_identity_protection_and_source_failure_do_not_create_prediction(
        self,
    ):
        mid = await self.card()
        self.p.prediction_store.register_bot(GROUP, "user", "Mira")
        response = await self.call(self.event(mid))
        self.assertIn("群成员不能代为修改", response[0])
        self.assertEqual(self.picks(), [])
        self.p._verify_prediction_match.side_effect = RuntimeError("offline")
        response = await self.call(self.event(mid, at=NOW.timestamp() + 1))
        self.assertIn("暂时无法核实", response[0])
        self.assertEqual(self.picks(), [])

    async def test_card_and_notice_deduplication_survive_reload(self):
        mid = await self.card()
        await self.call(self.event(mid))
        path = self.p.prediction_store.db.execute("PRAGMA database_list").fetchone()[2]
        self.p.prediction_store.close()
        self.p.prediction_store = PredictionStore(__import__("pathlib").Path(path))
        self.assertEqual(await self.call(self.event(mid)), [])
        self.assertEqual(len(self.picks()), 1)

    async def test_concurrent_changes_finish_with_the_newer_choice(self):
        mid = await self.card()
        await asyncio.gather(
            self.call(self.event(mid)),
            self.call(self.event(mid, "293", at=NOW.timestamp() + 1)),
        )
        self.assertEqual((self.picks()[0]["a"], self.picks()[0]["b"]), (0, 1))

    async def test_automatic_cards_are_deduplicated_but_explicit_list_can_resend(self):
        await self.p._send_click_cards(GROUP)
        await self.p._send_click_cards(GROUP)
        self.assertEqual(self.counter, 1)
        await self.p._send_click_cards(GROUP, force=True)
        self.assertEqual(self.counter, 2)

    async def test_older_click_on_another_card_cannot_overwrite_newer_choice(self):
        first, second = await self.card(), await self.card()
        await self.call(self.event(second, "293", at=NOW.timestamp() + 2))
        self.assertEqual(await self.call(self.event(first, at=NOW.timestamp() + 1)), [])
        self.assertEqual((self.picks()[0]["a"], self.picks()[0]["b"]), (0, 1))

    async def test_missing_time_or_unsupported_platform_never_writes_or_sends(self):
        mid = await self.card()
        event = self.event(mid)
        del event.message_obj.raw_message["time"]
        self.assertEqual(await self.call(event), [])
        self.assertEqual(self.picks(), [])
        self.bot.call_action = AsyncMock(return_value={"app_name": "Other.Onebot"})
        with self.assertRaisesRegex(ValueError, "未发送"):
            await self.card()
        self.assertEqual(self.counter, 1)
