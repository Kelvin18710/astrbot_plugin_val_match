import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_predictions import NOW

from main import ValMatchPlugin
from predictions import PredictionStore

A = "default:GroupMessage:42"
B = "default:GroupMessage:43"
ONLY = "default:GroupMessage:44"


class ScheduleOrderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "p.db"
        p = self.p = object.__new__(ValMatchPlugin)
        p.config = {
            "prediction_enabled": True,
            "prediction_daily_enabled": True,
            "prediction_after_schedule": True,
            "prediction_targets": f"{A}\n{B}\n{ONLY}",
            "enable_daily_push": True,
            "push_targets": f"{A}\n{B}",
            "push_time": "11:00",
            "display_timezone": "Asia/Shanghai",
        }
        p.prediction_store = PredictionStore(self.path)
        p._prediction_delivery_lock = asyncio.Lock()
        p._today_in_display_timezone = lambda: NOW.date()
        p._now_in_display_timezone = lambda: NOW
        p._render_daily_s_tier_image = AsyncMock(return_value="schedule.png")
        p._render_daily_progress_image = AsyncMock(return_value="progress.png")
        p._refresh_predictions = AsyncMock()
        p._ensure_bot_predictions = AsyncMock()
        p._prediction_last_error = ""
        p._prediction_list_text = lambda group: "竞猜 " + group
        p._prediction_groups = {}
        self.calls = []
        self.failed = set()
        self.fail_prediction = set()

        async def image(path, *, targets):
            group = targets[0]
            self.calls.append((group, path))
            return (0, 1) if (group, path) in self.failed else (1, 0)

        async def message(group, chain):
            self.calls.append((group, "竞猜"))
            return group not in self.fail_prediction

        p._push_image_to_targets = AsyncMock(side_effect=image)
        p.context = SimpleNamespace(send_message=AsyncMock(side_effect=message))

    def tearDown(self):
        self.p.prediction_store.close()
        self.temp.cleanup()

    async def test_schedule_then_progress_then_prediction_and_concurrent_dedup(self):
        p = self.p
        await p._deliver_scheduled_prediction(A, "竞猜")
        self.assertEqual(self.calls, [])
        await p._push_today_matches()
        for group in [A, B]:
            self.assertEqual(
                [step for g, step in self.calls if g == group],
                ["schedule.png", "progress.png", "竞猜"],
            )
        await asyncio.gather(
            p._deliver_scheduled_prediction(A, "竞猜"),
            p._deliver_scheduled_prediction(A, "竞猜"),
            p._push_today_matches(),
        )
        self.assertEqual(sum(g == A and step == "竞猜" for g, step in self.calls), 1)
        self.assertEqual(p._daily_schedule_pending(), [])
        self.assertFalse(p._daily_schedule_due())

    async def test_independent_prediction_group_not_blocked_and_disabled_follow_uses_old_key(
        self,
    ):
        p = self.p
        await p._deliver_scheduled_prediction(ONLY, "竞猜")
        self.assertEqual(self.calls, [(ONLY, "竞猜")])
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "竞猜", ONLY))
        p.config["prediction_after_schedule"] = False
        await p._deliver_scheduled_prediction(A, "竞猜")
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "竞猜", A))

    async def test_schedule_failed_one_group_other_completes_and_retry_only_pending(
        self,
    ):
        p = self.p
        self.failed.add((A, "schedule.png"))
        await p._push_today_matches()
        self.assertNotIn((A, "竞猜"), self.calls)
        self.assertIn((B, "竞猜"), self.calls)
        self.assertEqual(p._daily_schedule_pending(), [A])
        self.assertTrue(p._daily_schedule_due())
        self.failed.clear()
        await p._push_today_matches()
        self.assertEqual(sum(g == B for g, _ in self.calls), 3)
        self.assertEqual(
            [step for g, step in self.calls if g == A],
            ["schedule.png", "schedule.png", "progress.png", "竞猜"],
        )

    async def test_prediction_failed_retries_without_resending_schedule_even_after_restart(
        self,
    ):
        p = self.p
        self.fail_prediction.add(A)
        await p._push_today_matches()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛程完成", A))
        self.assertFalse(p.prediction_store.delivered("2026-10-01", "赛程后竞猜", A))
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        self.fail_prediction.clear()
        await p._deliver_scheduled_prediction(A, "竞猜")
        self.assertEqual(
            sum(g == A and step == "schedule.png" for g, step in self.calls), 1
        )
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛程后竞猜", A))

    async def test_old_standalone_delivery_does_not_suppress_new_follow_schedule_batch(
        self,
    ):
        p = self.p
        p.prediction_store.mark_delivered("2026-10-01", "竞猜", A)
        await p._push_today_matches()
        self.assertIn((A, "竞猜"), self.calls)
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛程后竞猜", A))

    async def test_missing_or_failed_progress_does_not_block_prediction(self):
        p = self.p
        p._render_daily_progress_image.side_effect = RuntimeError(
            "progress unavailable"
        )
        await p._push_today_matches()
        self.assertEqual(
            [step for g, step in self.calls if g == A], ["schedule.png", "竞猜"]
        )

    async def test_empty_schedule_completes_job_and_sends_empty_today_prediction(self):
        p = self.p
        p._render_daily_s_tier_image.return_value = None
        await p._push_today_matches()
        self.assertEqual(self.calls, [(A, "竞猜"), (B, "竞猜")])
        self.assertFalse(p._daily_schedule_due())
