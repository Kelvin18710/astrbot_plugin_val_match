import unittest
from datetime import timedelta

import test_prediction_feature as feature_fixture
from test_predictions import NOW

from predictions import resolve_prediction, split_prediction_requests


class BatchFeatureTests(unittest.IsolatedAsyncioTestCase):
    event = feature_fixture.FeatureTests.event
    call = feature_fixture.FeatureTests.call
    tearDown = feature_fixture.FeatureTests.tearDown

    def setUp(self):
        feature_fixture.FeatureTests.setUp(self)
        self.group = "default:GroupMessage:42"
        self.p.prediction_store.sync_match(
            "123457", "FNATIC", "DRX", 3, NOW + timedelta(hours=2), "未开始"
        )

    def picks(self, user="user"):
        return {
            r["match_id"]: (r["a"], r["b"])
            for r in self.p.prediction_store.predictions(self.group, user)
        }

    async def test_batch_submit_and_modify_with_natural_separators(self):
        for separator in ["，", ",", "；", "\n", "然后", "和", " ", "，另外"]:
            with self.subTest(separator=separator):
                reply = await self.call(
                    self.event("我猜EDG二比一赢PRX" + separator + "FNC二比零赢DRX")
                )
                self.assertIn("成功 2 场 · 未保存 0 场", reply[0])
                self.assertIn("👤 群友", reply[0])
                self.assertEqual(self.picks(), {"123456": (1, 0), "123457": (1, 0)})
        reply = await self.call(self.event("把EDG那场改成2:0，然后把FNC那场改成1:2"))
        self.assertEqual(reply[0].count("✏️ 已修改"), 2)
        self.assertEqual(self.picks(), {"123456": (1, 0), "123457": (0, 1)})

    async def test_reverse_team_order_and_mixed_submit_modify(self):
        await self.call(self.event("竞猜EDG2:1"))
        reply = await self.call(self.event("把PRX那场改成2:0，DRX2:1赢FNC"))
        self.assertIn("✏️ 已修改", reply[0])
        self.assertIn("✅ 已提交", reply[0])
        self.assertEqual(self.picks(), {"123456": (0, 1), "123457": (0, 1)})

    async def test_invalid_score_or_contradiction_does_not_block_other_match(self):
        await self.call(self.event("竞猜EDG2:1"))
        for clause in [
            "把EDG改成13:11",
            "把EDG改成1:1",
            "我猜EDG1:2赢PRX",
            "把EDG改成10000:0",
            "把EDG改成十比零",
            "把EDG改成2:-1",
        ]:
            with self.subTest(clause=clause):
                reply = await self.call(self.event(clause + "，FNC2:0赢DRX"))
                self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
                self.assertEqual(self.picks()["123456"], (1, 0))
                self.assertEqual(self.picks()["123457"], (1, 0))

    async def test_locked_match_and_detail_failure_leave_old_pick_unchanged(self):
        await self.call(self.event("竞猜EDG2:1"))
        self.p.prediction_store.sync_match(
            "123456",
            "EDward Gaming",
            "Paper Rex",
            3,
            NOW + timedelta(minutes=10),
            "未开始",
        )
        reply = await self.call(self.event("把EDG改成2:0，FNC2:0赢DRX"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertIn("已封盘", reply[0])
        self.assertEqual(self.picks()["123456"], (1, 0))

        async def verify(match):
            if match["match_id"] == "123456":
                raise RuntimeError("offline")

        self.p._verify_prediction_match.side_effect = verify
        reply = await self.call(self.event("把EDG改成2:0，FNC1:2输给DRX"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertIn("暂时无法核实", reply[0])
        self.assertEqual(self.picks(), {"123456": (1, 0), "123457": (0, 1)})

    async def test_duplicates_including_illegal_score_are_all_rejected(self):
        await self.call(self.event("竞猜EDG2:1"))
        for text in [
            "把EDG改成2:0，PRX2:1赢EDG，FNC2:0",
            "把EDG改成2:0，EDG99:0，FNC2:0",
        ]:
            with self.subTest(text=text):
                reply = await self.call(self.event(text))
                self.assertIn("成功 1 场 · 未保存 2 场", reply[0])
                self.assertIn("多次提到这场比赛", reply[0])
                self.assertEqual(self.picks()["123456"], (1, 0))

    async def test_uncertainty_and_future_scope_never_write_any_pick(self):
        for text in [
            "我猜EDG2:1或者2:0，FNC2:0",
            "我猜EDG2:1，或者FNC2:0",
            "如果竞猜EDG2:1，FNC2:0",
            "不要竞猜EDG2:1，FNC2:0",
            "我猜明天EDG2:1，FNC2:0",
            "我猜EDG2:1，明天FNC2:0",
            "我猜EDG2:1，FNC2:0吗",
            "我猜EDG2:1，FNC2:0，不要提交",
        ]:
            with self.subTest(text=text):
                await self.call(self.event(text))
                self.assertEqual(self.picks(), {})
        reply = await self.call(self.event("我猜明天EDG2:1"))
        self.assertIn("只支持今天", reply[0])

    async def test_no_implicit_previous_match_in_batch_and_unknown_team_is_local_error(
        self,
    ):
        await self.call(self.event("竞猜EDG2:1"))
        reply = await self.call(self.event("改成2:0，FNC2:0"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertEqual(self.picks(), {"123456": (1, 0), "123457": (1, 0)})
        reply = await self.call(self.event("我猜UNKNOWN2:0，FNC1:2"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])

    async def test_bot_protection_and_explicit_personal_entry(self):
        self.p.prediction_store.register_bot(self.group, "bot", "Mira")
        for match_id in ["123456", "123457"]:
            self.p.prediction_store.save_bot_analysis(
                match_id, "ready", {"a": 2, "b": 1, "basis": "limited_info"}, NOW, 1
            )
        self.p.prediction_store.submit_bot(self.group, "123456", 2, 1, NOW)
        self.p.prediction_store.submit_bot(self.group, "123457", 2, 1, NOW)
        reply = await self.call(self.event("把你的EDG竞猜改成2:0，FNC改成2:0"))
        self.assertIn("成功 0 场", reply[0])
        self.assertEqual(self.picks(), {})
        reply = await self.call(self.event("把你的EDG竞猜改成2:0，我猜FNC2:0赢DRX"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertEqual(self.picks(), {"123457": (1, 0)})
        self.assertEqual(self.picks("bot"), {"123456": (2, 1), "123457": (2, 1)})
        reply = await self.call(self.event("我猜EDG2:0，把你的FNC竞猜改成2:0"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertEqual(self.picks("bot"), {"123456": (2, 1), "123457": (2, 1)})

    async def test_tomorrow_rows_are_not_candidates_and_rescheduled_match_is_not_saved(
        self,
    ):
        self.p.prediction_store.sync_match(
            "123457", "FNATIC", "DRX", 3, NOW + timedelta(days=1), "未开始"
        )
        reply = await self.call(self.event("我猜EDG2:1，FNC2:0"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertEqual(self.picks(), {"123456": (1, 0)})

        async def reschedule(match):
            self.p.prediction_store.sync_match(
                match["match_id"],
                match["team_a"],
                match["team_b"],
                match["bo"],
                NOW + timedelta(days=1),
                "未开始",
            )

        self.p._verify_prediction_match.side_effect = reschedule
        reply = await self.call(self.event("把EDG改成2:0"))
        self.assertIn("日期已变更", reply[0])
        self.assertEqual(self.picks()["123456"], (1, 0))

    async def test_each_write_rechecks_time_when_a_batch_crosses_cutoff(self):
        self.p.prediction_store.sync_match(
            "123457", "FNATIC", "DRX", 3, NOW + timedelta(minutes=11), "未开始"
        )
        self.p._now_in_display_timezone = lambda: NOW

        async def verify(match):
            if match["match_id"] == "123457":
                self.p._now_in_display_timezone = lambda: NOW + timedelta(minutes=1)

        self.p._verify_prediction_match.side_effect = verify
        reply = await self.call(self.event("我猜EDG2:1，FNC2:0"))
        self.assertIn("成功 1 场 · 未保存 1 场", reply[0])
        self.assertEqual(self.picks(), {"123456": (1, 0)})

    async def test_batch_requires_at_and_configured_group_and_preserves_other_group(
        self,
    ):
        self.assertEqual(
            await self.call(self.event("我猜EDG2:1，FNC2:0", at="someone-else")), []
        )
        self.assertEqual(
            await self.call(
                self.event("我猜EDG2:1，FNC2:0", group="default:GroupMessage:43")
            ),
            [],
        )
        self.assertEqual(self.picks(), {})
        self.p.prediction_store.member("other", "user", "群友")
        self.p.prediction_store.submit("other", "user", "123456", 0, 2, NOW)
        await self.call(self.event("我猜EDG2:1，FNC2:0"))
        self.assertEqual(self.p.prediction_store.predictions("other")[0]["a"], 0)


class BatchParserTests(unittest.TestCase):
    def test_clause_context_and_unsplit_alternatives(self):
        teams = ["EDward Gaming", "Paper Rex", "FNATIC", "DRX"]
        self.assertEqual(
            split_prediction_requests(
                "把EDG那场，改成2:0，然后把FNC那场，改成2:1", teams
            ),
            ["把EDG那场，改成2:0", "把FNC那场，改成2:1"],
        )
        self.assertEqual(
            split_prediction_requests("竞猜EDG2:1或者2:0", teams), ["竞猜EDG2:1或者2:0"]
        )
        self.assertEqual(
            split_prediction_requests("我要改一下，2比0吧", teams),
            ["我要改一下，2比0吧"],
        )

    def test_both_teams_disambiguate_multiple_matches_sharing_one_team(self):
        rows = [
            {
                "match_id": "a",
                "team_a": "EDward Gaming",
                "team_b": "Paper Rex",
                "bo": 3,
            },
            {"match_id": "b", "team_a": "EDward Gaming", "team_b": "FNATIC", "bo": 3},
        ]
        self.assertEqual(
            resolve_prediction("我猜EDG2:1赢PRX", rows)[0]["match_id"], "a"
        )
        with self.assertRaises(ValueError):
            resolve_prediction("我猜EDG2:1", rows)
