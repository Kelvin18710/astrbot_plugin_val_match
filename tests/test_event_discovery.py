import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import httpx
from test_progress import sample_match

from clients.vlr import MatchSourceError, VlrClient

EVENT = "VCT China 2026: Threshold"
CATALOG = """<a class="wf-card event-item" href="/event/3166/vct-china-2026-threshold">
<div class="event-item-title">VCT China 2026: Threshold</div>
<span class="mod-upcoming">upcoming</span></a>"""


def match_html(match_id, team_a, team_b, start):
    return f"""<a href="/{match_id}/match" class="wf-module-item match-item">
<div class="match-item-time">{start}</div>
<div class="match-item-vs-team-name"><div class="text-of">{team_a}</div></div>
<div class="match-item-vs-team-name"><div class="text-of">{team_b}</div></div>
<div class="ml-status">Upcoming</div><div class="match-item-note">Bo3</div>
<div class="match-item-event text-of"><div class="match-item-event-series text-of">Round of 12</div>Week 1</div></a>"""


SCHEDULE = (
    '<div class="wf-label mod-large">Wed, October 21, 2026</div>'
    + match_html("777944", "Wolves Esports", "A Team", "12:00 PM")
    + '<div class="wf-label mod-large">Thu, October 22, 2026</div>'
    + match_html("777948", "KeepBest Gaming", "TBD", "1:00 PM")
)


class EventDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = VlrClient(
            {
                "special_tournaments": [EVENT],
                "vlr_schedule_pages": 1,
                "vlr_results_pages": 1,
                "display_timezone": "Asia/Shanghai",
            }
        )
        self.client._get_vlr_page = AsyncMock(return_value="")

        async def request(method, url, **kwargs):
            html = SCHEDULE if "/event/matches/" in url else CATALOG
            return httpx.Response(200, text=html)

        self.client._request = AsyncMock(side_effect=request)

        async def detail(href):
            day, hour = (21, 4) if "777944" in href else (22, 5)
            return {
                "utc_dt": datetime(2026, 10, day, hour, tzinfo=timezone.utc),
                "best_of": "Bo3",
            }

        self.client._get_vlr_match_detail_info = AsyncMock(side_effect=detail)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_upcoming_catalog_event_is_discovered_without_global_matches(self):
        self.assertEqual(await self.client.discover_tournaments(), [EVENT])
        self.client._get_vlr_page.assert_any_await("schedule", 1)
        self.client._get_vlr_page.assert_any_await("results", 1)

    async def test_catalog_survives_global_page_outage_and_refreshes_on_demand(self):
        self.client._get_vlr_page.side_effect = MatchSourceError(
            "global page unavailable"
        )
        self.assertEqual(await self.client.discover_tournaments(), [EVENT])
        self.assertEqual(await self.client.discover_tournaments(), [EVENT])
        self.assertEqual(self.client._request.await_count, 2)

    async def test_global_matches_remain_available_when_catalog_fails(self):
        self.client._request.side_effect = MatchSourceError("event catalog unavailable")
        self.client._parse_vlr_match_list_html = lambda *a, **k: [sample_match("Stage")]
        self.assertEqual(await self.client.discover_tournaments(), ["VCT Test Stage"])

    async def test_total_discovery_failure_is_reported(self):
        self.client._request.side_effect = MatchSourceError("unavailable")
        self.client._get_vlr_page.side_effect = MatchSourceError("unavailable")
        with self.assertRaisesRegex(MatchSourceError, "无法更新赛事列表"):
            await self.client.discover_tournaments()

    async def test_selected_event_supplies_missing_global_fixture_and_canonical_name(
        self,
    ):
        self.client._load_from_vlr_html = AsyncMock(return_value=[])
        self.client._load_from_vlr_api = AsyncMock(return_value=[])
        rows = await self.client.get_matches_by_date(date(2026, 10, 21))
        self.assertEqual(len(rows), 1)
        m = rows[0]
        self.assertEqual(
            (m.match_id, m.tournament_name, m.match_date, m.start_time),
            ("777944", EVENT, "2026-10-21", "12:00"),
        )
        self.assertEqual(m.schedule_name, "Week 1: Round of 12")
        self.assertEqual(m.raw["event_href"], "/event/3166/vct-china-2026-threshold")
        self.assertEqual(m.best_of, "Bo3")
        self.client._load_from_vlr_api.assert_not_awaited()

    async def test_api_preference_still_includes_selected_event_and_deduplicates(self):
        self.client.config["vlr_prefer_api"] = True
        global_match = sample_match("Stage")
        global_match.match_id = "777944"
        self.client._load_from_vlr_api = AsyncMock(return_value=[global_match])
        rows = await self.client.get_matches_by_date(date(2026, 10, 21))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tournament_name, EVENT)

    async def test_selection_change_invalidates_previously_empty_date_cache(self):
        self.client.config["special_tournaments"] = []
        self.client._load_from_vlr_html = AsyncMock(return_value=[])
        self.client._load_from_vlr_api = AsyncMock(return_value=[])
        self.assertEqual(await self.client.get_matches_by_date(date(2026, 10, 21)), [])
        self.client._request.assert_not_awaited()
        self.client.config["special_tournaments"] = [EVENT]
        rows = await self.client.get_matches_by_date(date(2026, 10, 21))
        self.assertEqual(len(rows), 1)

    async def test_event_timezone_normalization_keeps_cross_midnight_match(self):
        self.client.config["display_timezone"] = "America/Los_Angeles"
        rows = await self.client._load_selected_event_matches(date(2026, 10, 20))
        self.assertEqual(
            [(m.match_id, m.match_date, m.start_time) for m in rows],
            [("777944", "2026-10-20", "21:00")],
        )

    def test_catalog_ignores_unrelated_links_and_invalid_event_targets(self):
        html = (
            CATALOG
            + """<a href="/event/100/other">navigation</a>
<a class="event-item" href="https://outside.test/event/10/other"><div class="event-item-title">Other</div></a>"""
        )
        self.assertEqual(
            self.client._parse_vlr_events_html(html),
            [{"name": EVENT, "href": "/event/3166/vct-china-2026-threshold"}],
        )
