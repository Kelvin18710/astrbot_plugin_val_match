import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from test_progress import sample_match

from main import ValMatchPlugin


class SpecialDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def make_plugin(self):
        p = object.__new__(ValMatchPlugin)
        p.config = {
            "special_report_enabled": True,
            "special_map_report_enabled": False,
            "special_push_targets": "default:GroupMessage:42",
        }
        p.context = SimpleNamespace(send_message=AsyncMock(return_value=True))
        p._now_in_display_timezone = lambda: datetime(2026, 9, 21)
        p._record_special_timeline = Mock()
        p._render_match_report_image_from_report = AsyncMock(
            return_value="/tmp/report.png"
        )
        return p

    async def test_completed_report_dedup_and_failed_send_retry(self):
        p = self.make_plugin()
        p._report_has_player_stats = lambda _: True
        match = sample_match("Final")
        state = {}
        report = SimpleNamespace()
        p.context.send_message.side_effect = RuntimeError("test failure")
        await p._maybe_send_special_report(match, state, report=report)
        self.assertFalse(state.get("report_complete", False))
        p.context.send_message.side_effect = None
        await p._maybe_send_special_report(match, state, report=report)
        self.assertTrue(state["report_complete"])
        count = p.context.send_message.await_count
        await p._maybe_send_special_report(match, state, report=report)
        self.assertEqual(p.context.send_message.await_count, count)

    async def test_missing_stats_waits_without_sending(self):
        p = self.make_plugin()
        p._report_has_player_stats = lambda _: False
        state = {}
        await p._maybe_send_special_report(
            sample_match("Final"), state, report=SimpleNamespace()
        )
        p.context.send_message.assert_not_awaited()
        self.assertIn("next_result_check", state)

    async def test_map_result_dedup(self):
        p = self.make_plugin()
        p._is_completed_report_map = lambda _: True
        p._render_single_map_result_image = AsyncMock(return_value="/tmp/map.png")
        report = SimpleNamespace(
            team_a="A",
            team_b="B",
            maps=[
                SimpleNamespace(
                    game_id="map1",
                    map_name="Ascent",
                    team_a_score="13",
                    team_b_score="8",
                )
            ],
        )
        state = {}
        match = sample_match("Final")
        await p._maybe_send_special_map_reports(match, state, report)
        await p._maybe_send_special_map_reports(match, state, report)
        self.assertEqual(p.context.send_message.await_count, 1)
