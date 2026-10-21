import asyncio
import unittest
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import test_prediction_after_matches as rank_fixture
import test_prediction_schedule as schedule_fixture
from test_predictions import NOW
from test_progress import sample_match

from predictions import PredictionStore

A = rank_fixture.A
B = rank_fixture.B


class FirstMatchPushTests(unittest.IsolatedAsyncioTestCase):
    setUp = schedule_fixture.ScheduleOrderTests.setUp
    tearDown = schedule_fixture.ScheduleOrderTests.tearDown

    def setup_schedule(self, start="15:00"):
        p = self.p
        p.config.update(daily_push_mode="首场赛前", daily_push_lead_minutes=120)
        p._apply_preferred_filters = lambda rows, *args: (
            [m for m in rows if m.tournament_name == "Cup"],
            None,
        )
        self.first = replace(
            sample_match("Group"),
            match_id="1",
            match_date=NOW.date().isoformat(),
            start_time=start,
            tournament_name="Cup",
        )

        async def query(day):
            return (
                [
                    self.first,
                    replace(self.first, match_id="2", start_time="18:00"),
                    replace(
                        self.first,
                        match_id="unrelated",
                        start_time="08:00",
                        tournament_name="Other",
                    ),
                ]
                if day == NOW.date()
                else []
            ), None

        p._query_matches = AsyncMock(side_effect=query)

    async def test_first_followed_match_defines_trigger_and_reschedule_recomputes(self):
        self.setup_schedule()
        p = self.p
        await p._refresh_daily_first_trigger()
        self.assertEqual(p._daily_first_trigger, NOW + timedelta(hours=1))
        self.assertFalse(p._daily_schedule_due())
        p._now_in_display_timezone = lambda: NOW + timedelta(hours=1)
        self.assertTrue(p._daily_schedule_due())
        self.first.start_time = "17:00"
        await p._refresh_daily_first_trigger()
        self.assertEqual(p._daily_first_trigger, NOW + timedelta(hours=3))
        self.assertFalse(p._daily_schedule_due())

    async def test_no_confirmed_schedule_no_push_and_midnight_does_not_open_future_day(
        self,
    ):
        self.setup_schedule(start="00:30")
        p = self.p
        await p._refresh_daily_first_trigger()
        self.assertEqual(p._daily_first_trigger.hour, 0)
        self.assertEqual(p._daily_first_trigger.date(), NOW.date())
        p._query_matches = AsyncMock(return_value=([], None))
        await p._refresh_daily_first_trigger()
        self.assertIsNone(p._daily_first_trigger)
        self.assertFalse(p._daily_schedule_due())
        p._query_matches = AsyncMock(side_effect=RuntimeError("source unavailable"))
        with self.assertRaises(RuntimeError):
            await p._refresh_daily_first_trigger()
        self.assertFalse(p._daily_schedule_due())

    async def test_early_schedule_failed_prediction_retries_before_standalone_timer(
        self,
    ):
        p = self.p
        p.config.update(prediction_push_time="23:59", prediction_rank_enabled=False)
        self.fail_prediction.add(A)
        await p._push_today_matches()
        self.fail_prediction.clear()
        with patch(
            "prediction_feature.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await p._prediction_loop()
        self.assertTrue(
            p.prediction_store.delivered(NOW.date().isoformat(), "赛程后竞猜", A)
        )
        self.assertEqual(sum(g == A and step == "竞猜" for g, step in self.calls), 2)
        self.assertEqual(
            sum(g == A and step == "schedule.png" for g, step in self.calls), 1
        )


class ReportBeforeRankTests(unittest.IsolatedAsyncioTestCase):
    tearDown = rank_fixture.AfterMatchRankTests.tearDown
    settle_all = rank_fixture.AfterMatchRankTests.settle_all

    def setUp(self):
        rank_fixture.AfterMatchRankTests.setUp(self)
        p = self.p
        p.config.update(
            special_report_enabled=True,
            special_map_report_enabled=False,
            special_push_targets=A,
        )
        p._query_matches = AsyncMock(return_value=([], None))
        p._fetch_match_report = AsyncMock(return_value=SimpleNamespace())
        p._report_has_player_stats = lambda report: True
        p._record_special_timeline = Mock()
        p._render_match_report_image_from_report = AsyncMock(
            return_value="/tmp/report.png"
        )
        p._watch_rank_days()
        self.settle_all()

    async def test_both_reports_confirmed_before_image_rank_and_survive_reload(self):
        p = self.p
        await p._deliver_after_match_ranks()
        messages = [call.args[1] for call in p.context.send_message.call_args_list]
        self.assertEqual(
            [[part.type for part in chain.chain] for chain in messages],
            [["Plain", "Image"], ["Plain", "Image"], ["Image"]],
        )
        for mid in ["123456", "123457"]:
            self.assertTrue(p.prediction_store.report_delivered(A, mid))
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        p._special_state = {}
        await p._deliver_after_match_ranks()
        self.assertEqual(p.context.send_message.await_count, 3)

    async def test_missing_stats_and_false_ack_hold_rank_then_retry_without_duplicate_report(
        self,
    ):
        p = self.p
        p._report_has_player_stats = lambda report: False
        await p._deliver_after_match_ranks()
        p.context.send_message.assert_not_awaited()
        p._report_has_player_stats = lambda report: True
        calls = 0

        async def send(group, chain):
            nonlocal calls
            calls += 1
            return calls != 2

        p.context.send_message.side_effect = send
        await p._deliver_after_match_ranks()
        self.assertTrue(p.prediction_store.report_delivered(A, "123456"))
        self.assertFalse(p.prediction_store.report_delivered(A, "123457"))
        self.assertFalse(p.prediction_store.delivered("2026-10-01", "赛后积分", A))
        await p._deliver_after_match_ranks()
        self.assertEqual(p.context.send_message.await_count, 4)
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))

    async def test_partial_group_failure_does_not_block_successful_group_or_resend_its_reports(
        self,
    ):
        p = self.p
        p.config.update(
            special_push_targets=A + "\n" + B,
            prediction_rank_after_matches_targets=A + "\n" + B,
        )
        p._watch_rank_days()
        failed = True

        async def send(group, chain):
            return not (group == B and failed)

        p.context.send_message.side_effect = send
        await p._deliver_after_match_ranks()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", A))
        self.assertFalse(p.prediction_store.delivered("2026-10-01", "赛后积分", B))
        a_count = sum(c.args[0] == A for c in p.context.send_message.call_args_list)
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        p._special_state = {}
        failed = False
        await p._deliver_after_match_ranks()
        self.assertTrue(p.prediction_store.delivered("2026-10-01", "赛后积分", B))
        self.assertEqual(
            sum(c.args[0] == A for c in p.context.send_message.call_args_list), a_count
        )

    async def test_concurrent_report_and_rank_check_send_each_report_once(self):
        p = self.p
        from clients.vlr import MatchRecord

        record = MatchRecord(
            "123456",
            "2026-10-01",
            "13:00",
            "已结束",
            "EDward Gaming",
            "Paper Rex",
            "2:1",
            "",
            "",
            "",
            "Bo3",
            "VLR",
            {},
        )
        await asyncio.gather(
            p._maybe_send_special_report(record, {}, report=SimpleNamespace()),
            p._deliver_after_match_ranks(),
        )
        reports = [
            c.args[1].chain[0].text
            for c in p.context.send_message.call_args_list
            if c.args[1].chain[0].type == "Plain"
        ]
        self.assertEqual(len(reports), 2)
        self.assertEqual(
            p.context.send_message.call_args.args[1].chain[0].type, "Image"
        )
