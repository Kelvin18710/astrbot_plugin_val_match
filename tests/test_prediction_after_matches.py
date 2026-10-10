import asyncio
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_predictions import NOW

from main import ValMatchPlugin
from predictions import PredictionStore

A = "default:GroupMessage:42"
B = "default:GroupMessage:43"


class AfterMatchRankTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "p.db"
        p = self.p = object.__new__(ValMatchPlugin)
        p.config = {
            "prediction_enabled": True,
            "prediction_targets": f"{A}\n{B}",
            "prediction_rank_enabled": True,
            "prediction_rank_after_matches_enabled": True,
            "prediction_rank_after_matches_targets": A,
            "display_timezone": "Asia/Shanghai",
        }
        p.prediction_store = PredictionStore(self.path)
        p._prediction_delivery_lock = asyncio.Lock()
        p._prediction_lock = asyncio.Lock()
        self.now = NOW
        p._now_in_display_timezone = lambda: self.now
        p._today_in_display_timezone = lambda: self.now.date()
        p._prediction_groups = {A: "测试群"}
        p._sync_prediction_members = AsyncMock()
        p.context = SimpleNamespace(send_message=AsyncMock(return_value=True))
        p.prediction_store.member(A, "user", "群友")
        for mid in ["123456", "123457"]:
            p.prediction_store.sync_match(
                mid, "EDward Gaming", "Paper Rex", 3, NOW + timedelta(hours=1), "未开始"
            )
        p.prediction_store.submit(A, "user", "123456", 2, 0, NOW)
        p.prediction_store.submit(A, "user", "123457", 0, 2, NOW)

    def tearDown(self):
        self.p.prediction_store.close()
        self.temp.cleanup()

    def settle_all(self):
        self.p.prediction_store.settle("123456", 2, 1)
        self.p.prediction_store.settle("123457", 1, 2)

    async def test_waits_for_all_matches_and_settlement_then_sends_final_accuracy(self):
        p = self.p
        p._watch_rank_days()
        p.prediction_store.settle("123456", 2, 1)
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_not_awaited()
        p.prediction_store.settle("123457", 1, 2)
        with p.prediction_store.db:
            p.prediction_store.db.execute(
                "UPDATE predictions SET points=NULL WHERE group_id=? AND match_id='123457'",
                (A,),
            )
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_not_awaited()
        with p.prediction_store.db:
            p.prediction_store.db.execute(
                "UPDATE predictions SET points=2 WHERE group_id=? AND match_id='123457'",
                (A,),
            )
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_awaited_once()
        message = p.context.send_message.call_args.args[1].chain[0].text
        self.assertIn("10月01日的比赛已结束，竞猜已结算", message)
        self.assertIn("100.0%（猜中 2/2 场）", message)
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))

    async def test_concurrent_retry_and_restart_do_not_duplicate_success(self):
        p = self.p
        p._watch_rank_days()
        self.settle_all()
        await asyncio.gather(
            p._deliver_after_match_rank(A, "2026-10-01"),
            p._deliver_after_match_rank(A, "2026-10-01"),
        )
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        p._watch_rank_days()
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_awaited_once()

    async def test_failure_is_not_marked_and_other_groups_can_complete(self):
        p = self.p
        p.config["prediction_rank_after_matches_targets"] = f"{A}\n{B}"
        p._watch_rank_days()
        self.settle_all()

        async def send(group, chain):
            return group != A

        p.context.send_message.side_effect = send
        await p._deliver_after_match_ranks()
        self.assertFalse(p.prediction_store.delivered("2026-10-01", "赛后积分", A))
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", B))
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        p.context.send_message.side_effect = None
        await p._deliver_after_match_ranks()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))
        self.assertEqual(
            sum(c.args[0] == B for c in p.context.send_message.call_args_list), 1
        )

    async def test_cross_midnight_retains_original_day_even_if_match_is_postponed(self):
        p = self.p
        p._watch_rank_days()
        p.prediction_store.settle("123456", 2, 1)
        self.now = NOW + timedelta(days=1)
        p.prediction_store.sync_match(
            "123457",
            "EDward Gaming",
            "Paper Rex",
            3,
            self.now + timedelta(hours=1),
            "未开始",
        )
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_not_awaited()
        p.prediction_store.settle("123457", 1, 2)
        await p._deliver_after_match_ranks()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))
        self.assertFalse(p.prediction_store.delivered("2026-10-02", "赛后积分", A))
        self.assertIn(
            "10月01日", p.context.send_message.call_args.args[1].chain[0].text
        )

    async def test_selected_group_skips_clock_schedule_others_keep_it(self):
        p = self.p
        await p._deliver_scheduled_prediction(A, "积分")
        p.context.send_message.assert_not_awaited()
        await p._deliver_scheduled_prediction(B, "积分")
        self.assertEqual(p.context.send_message.call_args.args[0], B)
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "积分", B))
        p.config["prediction_rank_after_matches_enabled"] = False
        await p._deliver_scheduled_prediction(A, "积分")
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "积分", A))

    async def test_prior_fixed_rank_does_not_suppress_final_rank_when_mode_changes(
        self,
    ):
        p = self.p
        p.prediction_store.mark_delivered("2026-10-01", "积分", A)
        p._watch_rank_days()
        self.settle_all()
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_awaited_once()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))

    async def test_no_matches_and_historical_days_do_not_generate_backlog(self):
        p = self.p
        self.settle_all()
        self.now = NOW + timedelta(days=1)
        p._watch_rank_days()
        await p._deliver_after_match_ranks()
        self.assertEqual(p.prediction_store.pending_rank_days(A), [])
        p.context.send_message.assert_not_awaited()

    async def test_newly_discovered_today_match_is_added_before_delivery(self):
        p = self.p
        p._watch_rank_days()
        self.settle_all()
        p.prediction_store.sync_match(
            "123458", "FNATIC", "DRX", 3, NOW + timedelta(hours=3), "未开始"
        )
        p._watch_rank_days()
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_not_awaited()
        p.prediction_store.settle("123458", 2, 0)
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_awaited_once()

    async def test_cross_midnight_refresh_watches_matches_without_any_predictions(self):
        p = self.p
        with p.prediction_store.db:
            p.prediction_store.db.execute("DELETE FROM predictions")
        p._watch_rank_days()
        self.now = NOW + timedelta(days=1)
        p._query_matches = AsyncMock(return_value=([], None))
        p._apply_preferred_filters = lambda matches, *args: (matches, None)
        p._special_state = {}
        await p._refresh_predictions()
        self.assertEqual(
            {c.args[0] for c in p._query_matches.call_args_list},
            {date(2026, 10, 1), date(2026, 10, 2)},
        )

    async def test_refresh_failure_cannot_send_a_partially_synchronized_rank(self):
        p = self.p
        p._watch_rank_days()
        self.settle_all()
        p.config.update(
            {"prediction_daily_enabled": False, "prediction_rank_enabled": False}
        )
        p._refresh_predictions = AsyncMock(side_effect=RuntimeError("offline"))
        p._ensure_bot_predictions = AsyncMock()
        with patch(
            "prediction_feature.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await p._prediction_loop()
        p.context.send_message.assert_not_awaited()

    async def test_successful_loop_tick_settles_then_sends_even_with_fixed_timer_disabled(
        self,
    ):
        p = self.p
        p.config.update(
            {"prediction_daily_enabled": False, "prediction_rank_enabled": False}
        )
        p._refresh_predictions = AsyncMock(side_effect=self.settle_all)
        p._ensure_bot_predictions = AsyncMock()
        with patch(
            "prediction_feature.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await p._prediction_loop()
        p.context.send_message.assert_awaited_once()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))

    async def test_disabling_predictions_stops_pending_after_match_delivery(self):
        p = self.p
        p._watch_rank_days()
        self.settle_all()
        p.config["prediction_enabled"] = False
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_not_awaited()

    def test_settings_reject_non_prediction_or_non_group_target(self):
        p = self.p
        p.plugin_root = Path(__file__).resolve().parent.parent
        for payload in [
            {"prediction_rank_after_matches_targets": "default:GroupMessage:99"},
            {"prediction_rank_after_matches_targets": "default:FriendMessage:42"},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                p._validate_page_settings(payload)
        self.assertEqual(
            p._validate_page_settings(
                {
                    "prediction_rank_after_matches_enabled": True,
                    "prediction_rank_after_matches_targets": A,
                }
            )["prediction_rank_after_matches_targets"],
            A,
        )
