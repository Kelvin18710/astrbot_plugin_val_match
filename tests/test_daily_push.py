import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_progress import sample_match

from main import ValMatchPlugin


class DailyPushTests(unittest.IsolatedAsyncioTestCase):
    async def test_window_empty_and_partial_and_filtering(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = object.__new__(ValMatchPlugin)
            p.config = {
                "image_day_offsets": "-1,0,1",
                "preferred_tournaments": ["VCT Test Stage"],
                "push_targets": "default:GroupMessage:42",
            }
            p.rendered_dir = Path(tmp)
            p._today_in_display_timezone = lambda: date(2026, 9, 21)
            p._display_source_name = lambda _: "VLR"
            p._prepare_visual_matches = AsyncMock()
            p._build_render_matches = AsyncMock(return_value=["real-match"])
            p._push_image_to_targets = AsyncMock(return_value=(1, 0))
            p._render_daily_progress_image = AsyncMock(return_value="progress.png")
            for mode in ("empty", "unrelated", "last-day"):

                async def query(day):
                    m = sample_match("Group Stage")
                    if mode == "unrelated":
                        m.tournament_name = "Unrelated Event"
                    rows = (
                        []
                        if mode == "empty" or (mode == "last-day" and day.day != 22)
                        else [m]
                    )
                    return rows, None

                p._query_matches = AsyncMock(side_effect=query)
                p._push_image_to_targets.reset_mock()
                p._render_daily_progress_image.reset_mock()
                with patch(
                    "main.render_match_cards_image", return_value="schedule.png"
                ) as render:
                    await p._push_today_matches()
                    self.assertEqual(p._query_matches.await_count, 3)
                    self.assertEqual(
                        p._push_image_to_targets.await_count,
                        2 if mode == "last-day" else 0,
                    )
                    self.assertEqual(render.call_count, 1 if mode == "last-day" else 0)
                    self.assertEqual(
                        p._render_daily_progress_image.await_count,
                        1 if mode == "last-day" else 0,
                    )
            p._query_matches = AsyncMock(return_value=([], None))
            with patch(
                "main.render_match_cards_image", return_value="empty-manual.png"
            ):
                self.assertEqual(
                    await p._render_daily_s_tier_image(date(2026, 9, 21)),
                    "empty-manual.png",
                )
