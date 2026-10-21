import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import test_click_predictions as click_fixture
import test_prediction_feature as fixture
from test_predictions import NOW

from predictions import PredictionStore, resolve_winner_prediction

GROUP = click_fixture.GROUP


class WinnerStoreTests(unittest.TestCase):
    def test_winner_only_always_scores_two_even_for_bo1_exact_result(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predictions.db"
            store = PredictionStore(path)
            store.sync_match(
                "bo1", "Left", "Right", 1, NOW + timedelta(hours=1), "未开始"
            )
            for user in ["winner", "legacy", "wrong"]:
                store.member(GROUP, user, user)
            store.submit(GROUP, "winner", "bo1", 1, 0, NOW, mode="winner")
            store.submit(GROUP, "wrong", "bo1", 0, 1, NOW, mode="winner")
            store.submit(GROUP, "legacy", "bo1", 1, 0, NOW)
            store.close()
            store = PredictionStore(path)
            store.settle("bo1", 1, 0)
            entries = {r["user_id"]: r for r in store.predictions(GROUP)}
            self.assertEqual(
                {u: r["points"] for u, r in entries.items()},
                {"winner": 2, "legacy": 5, "wrong": 0},
            )
            self.assertEqual(entries["winner"]["mode"], "winner")
            self.assertEqual(entries["legacy"]["mode"], "score")
            self.assertFalse(store.settle("bo1", 1, 0))
            store.close()


class WinnerFeatureTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.FeatureTests.setUp
    tearDown = fixture.FeatureTests.tearDown
    event = fixture.FeatureTests.event
    call = fixture.FeatureTests.call

    async def test_scoreless_submit_modify_batch_and_personal_view(self):
        reply = await self.call(self.event("我猜 EDG 赢"))
        self.assertIn("竞猜成功", reply[0])
        self.assertNotIn("1 : 0", reply[0])
        reply = await self.call(self.event("把 EDG 那场改成 PRX 赢"))
        self.assertIn("已修改", reply[0])
        self.p.prediction_store.sync_match(
            "other", "FNATIC", "DRX", 3, NOW + timedelta(hours=2), "未开始"
        )
        reply = await self.call(self.event("我猜 EDG 赢，FNC 赢"))
        self.assertIn("成功 2 场", reply[0])
        rows = self.p.prediction_store.predictions(GROUP)
        self.assertEqual({r["mode"] for r in rows}, {"winner"})
        self.assertEqual({(r["a"], r["b"]) for r in rows}, {(1, 0)})
        reply = await self.call(self.event("我的竞猜"))
        self.assertIn("你的预测：EDward Gaming 胜", reply[0])
        self.assertNotIn("1 : 0", reply[0])

    async def test_speculation_bot_changes_and_future_requests_do_not_write(self):
        for text in [
            "预测今年冠军",
            "你觉得 EDG 赢吗？",
            "EDG 今天赢了吗",
            "我的竞猜 EDG",
            "我猜 EDG 或者 PRX 赢",
            "我猜明天 EDG 赢",
            "把你的竞猜改成 EDG 赢",
        ]:
            await self.call(self.event(text))
            self.assertEqual(self.p.prediction_store.predictions(GROUP), [], text)

    def test_conflicting_sides_and_malformed_legacy_scores_rejected(self):
        rows = self.p.prediction_store.matches()
        for text in [
            "我猜 EDG 赢 PRX 赢",
            "我猜 EDG 赢又输",
            "我猜 EDG 十比零",
            "把 EDG 改成 2:-1",
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                resolve_winner_prediction(text, rows)


class WinnerClickTests(unittest.IsolatedAsyncioTestCase):
    setUp = click_fixture.ClickPredictionTests.setUp
    tearDown = click_fixture.ClickPredictionTests.tearDown
    card = click_fixture.ClickPredictionTests.card
    event = click_fixture.ClickPredictionTests.event
    call = click_fixture.ClickPredictionTests.call
    picks = click_fixture.ClickPredictionTests.picks

    async def test_quiet_mode_saves_and_modifies_but_still_reports_lock_errors(self):
        self.p.config["prediction_click_feedback_enabled"] = False
        mid = await self.card()
        self.assertEqual(await self.call(self.event(mid)), [])
        self.assertEqual(
            await self.call(self.event(mid, "293", at=NOW.timestamp() + 1)), []
        )
        pick = self.picks()[0]
        self.assertEqual((pick["a"], pick["b"], pick["mode"]), (0, 1, "winner"))
        self.p._now_in_display_timezone = lambda: NOW + timedelta(minutes=50)
        reply = await self.call(
            self.event(mid, at=(NOW + timedelta(minutes=50)).timestamp())
        )
        self.assertIn("已封盘", reply[0])
        self.assertEqual((self.picks()[0]["a"], self.picks()[0]["b"]), (0, 1))

    async def test_four_fixtures_send_exactly_four_compact_cards_and_two_choices_each(
        self,
    ):
        for i in range(3):
            self.p.prediction_store.sync_match(
                str(i),
                "Left " + str(i),
                "Right " + str(i),
                5,
                NOW + timedelta(hours=2),
                "未开始",
            )
        self.p.context.send_message = AsyncMock(return_value=True)
        await self.p._broadcast_prediction(GROUP, "竞猜")
        sends = [
            c
            for c in self.bot.call_action.call_args_list
            if c.args[0] == "send_group_msg"
        ]
        self.assertEqual(len(sends), 4)
        self.p.context.send_message.assert_not_awaited()
        import base64
        import io

        from PIL import Image

        for send in sends:
            segments = send.kwargs["message"]
            self.assertEqual([part["type"] for part in segments], ["image"])
            with Image.open(
                io.BytesIO(
                    base64.b64decode(segments[0]["data"]["file"].split("base64://")[1])
                )
            ) as image:
                self.assertEqual(image.size, (720, 300))
        self.assertEqual(
            len(
                [
                    c
                    for c in self.bot.call_action.call_args_list
                    if c.args[0] == "set_msg_emoji_like"
                ]
            ),
            8,
        )

    async def test_tomorrow_demo_uses_real_fixture_without_opening_future_predictions(
        self,
    ):
        day = (NOW + timedelta(days=1)).date().isoformat()
        match = {
            "team_a": "Tomorrow Left",
            "team_b": "Tomorrow Right",
            "bo": 3,
            "start_at": (NOW + timedelta(days=1)).isoformat(),
        }
        mid = await self.p._send_click_card(GROUP, match, demo=True)
        payload = self.p._click_card(GROUP, mid)["payload"]
        self.assertEqual(payload["team_a"], "Tomorrow Left")
        self.assertEqual(len(payload["choices"]), 2)
        reply = await self.call(self.event(mid))
        self.assertIn("不计积分", reply[0])
        self.assertEqual(self.picks(), [])
        self.assertEqual(len(self.p.prediction_store.matches(day)), 0)
