from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageStat

from clients.vlr import MapScore, MatchRecord, PlayerStat, VlrClient
from render import (
    RenderBracketMatch,
    RenderBracketRound,
    RenderBracketSection,
    RenderHeadToHead,
    RenderMapScore,
    RenderMatch,
    RenderMatchReport,
    RenderPlayerStat,
    RenderSingleMapResult,
    RenderStandingGroup,
    RenderStandingRow,
    RenderStartNotice,
    RenderTournamentProgress,
    _single_map_player_rank_key,
    render_match_cards_image,
    render_match_report_image,
    render_single_map_result_image,
    render_start_notice_image,
    render_tournament_progress_image,
)

GROUP_HTML = """
<div class="event-header-thumb"><img src="//cdn.test/event.png"></div>
<h1 class="event-header-main-title">VCT Test Stage</h1>
<a class="wf-subnav-item mod-active"><div class="wf-subnav-item-title">Group Stage</div></a>
<div class="event-group-block"><table class="wf-table mod-group">
  <thead><tr><th class="mod-title">Group Alpha</th></tr></thead>
  <tbody>
    <tr class="mod-adv"><td><img class="event-group-team-logo" src="//cdn.test/a.png"></td>
      <td><a><div class="event-group-team-name">Alpha<div class="event-group-team-region">China</div></div></a></td>
      <td class="mod-stat">3<span>-</span>0</td><td class="mod-stat">6/1</td>
      <td class="mod-stat">91/70</td><td class="mod-stat"><span>+21</span></td></tr>
    <tr class="mod-elim"><td></td><td><a><div class="event-group-team-name">Beta</div></a></td>
      <td class="mod-stat">0-3</td><td class="mod-stat">1/6</td>
      <td class="mod-stat">68/90</td><td class="mod-stat">-22</td></tr>
  </tbody>
</table></div>
"""


BRACKET_HTML = """
<h1 class="event-header-main-title">VCT Test Stage</h1>
<a class="wf-subnav-item mod-active"><div class="wf-subnav-item-title">Playoffs</div></a>
<div class="event-brackets-container"><div class="bracket-container mod-upper">
  <div class="bracket-col"><div class="bracket-col-label">Semifinals</div><div class="bracket-row">
    <a class="bracket-item"><div class="bracket-item-team mod-first mod-winner">
      <div class="bracket-item-team-name"><img src="//cdn.test/a.png"><span>Alpha</span></div>
      <div class="bracket-item-team-score">2</div></div>
      <div class="bracket-item-team mod-loser"><div class="bracket-item-team-name"><span>Beta</span></div>
      <div class="bracket-item-team-score">0</div></div><div class="bracket-item-status">Jul 10</div></a>
  </div></div>
  <div class="bracket-col"><div class="bracket-col-label">Grand Final</div><div class="bracket-row">
    <a class="bracket-item"><div class="bracket-item-team mod-first"><div class="bracket-item-team-name"><span>Alpha</span></div>
      <div class="bracket-item-team-score">-</div></div><div class="bracket-item-team"><div class="bracket-item-team-name"><span>TBD</span></div>
      <div class="bracket-item-team-score">-</div></div></a>
  </div></div>
</div></div>
"""


def sample_match(schedule_name: str) -> MatchRecord:
    return MatchRecord(
        match_id="1",
        match_date="2026-07-10",
        start_time="16:00",
        status="未开始",
        team_a="Alpha",
        team_b="Beta",
        score="-",
        tournament_name="VCT Test Stage",
        schedule_name=schedule_name,
        level="S",
        best_of="Bo3",
        source="vlr",
        raw={"href": "/1/test"},
    )


def new_vlr_stats_row(index: int) -> str:
    team = "ALP" if index < 5 else "BET"
    return f"""
    <div class="ovw-row">
      <div class="ovw-cell mod-player"><div class="ovw-player">
        <i class="flag mod-cn" title="China"></i>
        <a href="/player/{index + 1}/player-{index + 1}">
          <div class="ovw-player-name text-of">Player {index + 1}</div>
          <div class="ovw-player-tag ge-text-light">{team}</div>
        </a></div><div class="ovw-agents"><img src="/agents/jett.png" title="Jett"></div>
      </div>
      <div class="ovw-cell" data-col="rating2"><span class="side mod-both">1.{30 - index:02d}</span></div>
      <div class="ovw-cell" data-col="acs"><span class="side mod-both">{280 - index}</span></div>
      <div class="ovw-cell mod-kda">
        <span data-col="kills"><span class="side mod-both">{20 - index}</span></span>
        <span data-col="deaths"><span class="side mod-both">12</span></span>
        <span data-col="assists"><span class="side mod-both">6</span></span>
      </div>
      <div class="ovw-cell" data-col="kd-diff"><span class="side mod-both">+8</span></div>
      <div class="ovw-cell" data-col="kast"><span class="side mod-both">75%</span></div>
      <div class="ovw-cell" data-col="adr"><span class="side mod-both">165</span></div>
      <div class="ovw-cell" data-col="hsp"><span class="side mod-both">30%</span></div>
      <div class="ovw-cell" data-col="fb"><span class="side mod-both">4</span></div>
      <div class="ovw-cell" data-col="fd"><span class="side mod-both">2</span></div>
      <div class="ovw-cell" data-col="fk-diff"><span class="side mod-both">+2</span></div>
    </div>
    """


NEW_VLR_REPORT_HTML = f"""
<div class="vm-stats-game" data-game-id="98765">
  <div class="vm-stats-game-header">
    <div class="team"><div class="score">13</div><div class="team-name">Alpha</div></div>
    <div class="map"><div>Haven <span class="picked mod-1">PICK</span></div>
      <div class="map-duration">42:10</div></div>
    <div class="team mod-right"><div class="team-name">Beta</div><div class="score">8</div></div>
  </div>
  <div class="ovw-table">{"".join(new_vlr_stats_row(index) for index in range(10))}</div>
</div>
"""


class ProgressParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = VlrClient({"vlr_web_base_url": "https://www.vlr.gg"})

    def test_parses_group_standings(self) -> None:
        progress = self.client._parse_tournament_progress_html(
            GROUP_HTML,
            "https://www.vlr.gg/event/1/test/group-stage",
            sample_match("Group Stage-Week 1"),
        )
        self.assertIsNotNone(progress)
        self.assertEqual(progress.kind, "standings")
        self.assertEqual(progress.groups[0].rows[0].record, "3-0")
        self.assertEqual(progress.groups[0].rows[0].position_state, "advance")
        self.assertEqual(progress.groups[0].rows[1].round_diff, "-22")

    def test_parses_playoff_bracket(self) -> None:
        progress = self.client._parse_tournament_progress_html(
            BRACKET_HTML,
            "https://www.vlr.gg/event/1/test/playoffs",
            sample_match("Playoffs-Semifinals"),
        )
        self.assertIsNotNone(progress)
        self.assertEqual(progress.kind, "bracket")
        self.assertEqual(progress.brackets[0].rounds[0].name, "Semifinals")
        self.assertEqual(progress.brackets[0].rounds[0].matches[0].winner, 1)

    def test_only_marks_finished_maps_with_complete_player_stats(self) -> None:
        players = [
            PlayerStat(
                f"Player {index}",
                "ALP" if index < 5 else "BET",
                ["Jett"],
                "20",
                "15",
                "6",
                acs="240",
            )
            for index in range(10)
        ]
        self.assertTrue(
            self.client.is_completed_report_map(
                MapScore("Haven", "13", "11", players=players)
            )
        )
        self.assertFalse(
            self.client.is_completed_report_map(
                MapScore("Haven", "13", "12", players=players)
            )
        )
        self.assertFalse(
            self.client.is_completed_report_map(
                MapScore("Haven", "12", "10", players=players)
            )
        )
        self.assertTrue(
            self.client.is_completed_report_map(
                MapScore("Haven", "14", "12", players=players)
            )
        )
        self.assertFalse(
            self.client.is_completed_report_map(
                MapScore("Haven", "13", "8", players=players[:9])
            )
        )
        partial_players = [
            PlayerStat(
                f"Player {index}",
                "ALP" if index < 5 else "BET",
                ["Jett"],
                "20",
                "15",
                "6",
                acs="" if index == 0 else "240",
            )
            for index in range(10)
        ]
        self.assertFalse(
            self.client.is_completed_report_map(
                MapScore("Haven", "13", "8", players=partial_players)
            )
        )

    def test_includes_summit_map_splash(self) -> None:
        self.assertEqual(
            self.client._map_image_url("Summit"),
            "https://media.valorant-api.com/maps/756da597-416b-c0f2-f47b-afbdf28670bc/splash.png",
        )

    def test_parses_new_vlr_overview_rows_including_rating(self) -> None:
        report = self.client._parse_match_report_html(
            NEW_VLR_REPORT_HTML,
            sample_match("Group Stage"),
            "/1/test",
            {},
        )

        self.assertEqual(len(report.maps), 1)
        self.assertEqual(len(report.maps[0].players), 10)
        self.assertEqual(len(report.players), 10)
        self.assertEqual(report.players[0].rating, "1.30")
        self.assertEqual(report.players[0].kills, "20")
        self.assertEqual(report.players[0].acs, "280")
        self.assertTrue(self.client.is_completed_report_map(report.maps[0]))

    def test_builds_current_vlr_report_url(self) -> None:
        url = self.client._match_report_url("/701031/example/?tab=performance")
        self.assertEqual(
            url,
            "https://www.vlr.gg/701031/example/?tab=performance&map=all",
        )

    def test_single_map_player_ranking_prioritizes_acs(self) -> None:
        higher_rating = RenderPlayerStat(
            "Rating", "ALP", ["Jett"], "20", "10", "4", acs="210", rating="1.50"
        )
        higher_acs = RenderPlayerStat(
            "ACS", "ALP", ["Raze"], "18", "12", "5", acs="280", rating="1.10"
        )
        ranked = sorted(
            (higher_rating, higher_acs), key=_single_map_player_rank_key, reverse=True
        )
        self.assertEqual(ranked[0].player, "ACS")


class ReportPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_always_prefers_map_all_page_over_partial_detail_rows(
        self,
    ) -> None:
        client = VlrClient({"vlr_web_base_url": "https://www.vlr.gg"})
        requested_urls: list[str] = []

        async def detail(*args, **kwargs):
            return {"html": '<div class="ovw-row"><div class="mod-player"></div></div>'}

        async def request(method, url, **kwargs):
            requested_urls.append(url)
            return SimpleNamespace(text=NEW_VLR_REPORT_HTML)

        client._get_vlr_match_detail_info = detail
        client._request = request
        try:
            report = await client.get_match_report(
                sample_match("Group Stage"), enrich_players=False
            )
        finally:
            await client.close()

        self.assertIsNotNone(report)
        self.assertEqual(len(report.maps), 1)
        self.assertEqual(len(report.maps[0].players), 10)
        self.assertEqual(len(requested_urls), 1)
        self.assertIn("map=all", requested_urls[0])

    async def test_report_uses_map_page_when_completed_map_acs_is_partial(self) -> None:
        client = VlrClient({"vlr_web_base_url": "https://www.vlr.gg"})
        requested_urls: list[str] = []
        partial_html = NEW_VLR_REPORT_HTML.replace(
            '<div class="ovw-cell" data-col="acs"><span class="side mod-both">280</span></div>',
            '<div class="ovw-cell" data-col="acs"><span class="side mod-both"></span></div>',
            1,
        )

        async def detail(*args, **kwargs):
            return {"html": '<div class="ovw-row"><div class="mod-player"></div></div>'}

        async def request(method, url, **kwargs):
            requested_urls.append(url)
            return SimpleNamespace(
                text=partial_html if "map=all" in url else NEW_VLR_REPORT_HTML
            )

        client._get_vlr_match_detail_info = detail
        client._request = request
        try:
            report = await client.get_match_report(
                sample_match("Group Stage"), enrich_players=False
            )
        finally:
            await client.close()

        self.assertIsNotNone(report)
        self.assertTrue(client.is_completed_report_map(report.maps[0]))
        self.assertEqual(report.maps[0].players[0].acs, "280")
        self.assertEqual(len(requested_urls), 2)
        self.assertIn("map=all", requested_urls[0])
        self.assertIn("map=1", requested_urls[1])


class ProgressRenderTests(unittest.TestCase):
    def assert_nonblank_png(self, path: Path, minimum_width: int) -> None:
        with Image.open(path) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertGreaterEqual(image.width, minimum_width)
            self.assertGreaterEqual(image.height, 400)
            self.assertGreater(max(ImageStat.Stat(image).var), 20)

    def test_renders_both_new_schedule_styles(self) -> None:
        match = RenderMatch(
            day_label="今天 · 2026-07-10 · 周五",
            start_time="16:00",
            status="未开始",
            score="-",
            team_a="Alpha",
            team_b="Beta",
            tournament_name="VCT Test Stage",
            schedule_name="Group Stage",
            level="S",
            best_of="Bo3",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for theme in ("premium_dark", "premium_light"):
                output = Path(temp_dir) / f"schedule_{theme}.png"
                render_match_cards_image(
                    [match],
                    date(2026, 7, 10),
                    output,
                    source_name="VLR.gg",
                    theme=theme,
                )
                self.assert_nonblank_png(output, 1280)

    def test_renders_standings_and_bracket(self) -> None:
        standings = RenderTournamentProgress(
            event_name="VCT Test Stage",
            stage_name="Group Stage",
            kind="standings",
            groups=[
                RenderStandingGroup(
                    "Group Alpha",
                    [RenderStandingRow("Alpha", "3-0", "6/1", "91/70", "+21")],
                )
            ],
            brackets=[],
        )
        bracket = RenderTournamentProgress(
            event_name="VCT Test Stage",
            stage_name="Playoffs",
            kind="bracket",
            groups=[],
            brackets=[
                RenderBracketSection(
                    "Upper Bracket",
                    [
                        RenderBracketRound(
                            "Grand Final",
                            [RenderBracketMatch("Alpha", "Beta", "3", "1", winner=1)],
                        )
                    ],
                )
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, progress in (("standings", standings), ("bracket", bracket)):
                output = Path(temp_dir) / f"{name}.png"
                render_tournament_progress_image(progress, output, theme="premium_dark")
                self.assert_nonblank_png(output, 1440)

    def test_renders_both_new_match_report_styles(self) -> None:
        report = RenderMatchReport(
            team_a="Alpha Esports",
            team_b="Beta Gaming",
            score="2:1",
            tournament_name="VCT Test Stage",
            schedule_name="Playoffs-Grand Final",
            best_of="Bo3",
            maps=[RenderMapScore("Haven", "13", "9")],
            players=[
                RenderPlayerStat(
                    "Player A", "ALP", ["Jett"], "40", "30", "12", rating="1.30"
                ),
                RenderPlayerStat(
                    "Player B", "BET", ["Sova"], "30", "40", "14", rating="0.88"
                ),
            ],
            comment="关键回合处理决定了整场系列赛的走势。",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for theme in ("premium_dark", "premium_light"):
                output = Path(temp_dir) / f"report_{theme}.png"
                render_match_report_image(report, output, theme=theme)
                self.assert_nonblank_png(output, 1600)

    def test_renders_both_new_start_notice_styles(self) -> None:
        notice = RenderStartNotice(
            start_time="19:00",
            team_a="Alpha Esports",
            team_b="Beta Gaming",
            tournament_name="VCT Test Stage",
            schedule_name="Playoffs-Grand Final",
            best_of="Bo5",
            betting_info="VLR market preview",
            team_a_odds="1.72",
            team_b_odds="2.15",
            head_to_head=[RenderHeadToHead("2026-05-01", "2:1", "VCT Test Stage")],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for theme in ("premium_dark", "premium_light"):
                output = Path(temp_dir) / f"notice_{theme}.png"
                render_start_notice_image(notice, output, theme=theme)
                self.assert_nonblank_png(output, 1280)

    def test_renders_single_map_result_in_both_themes(self) -> None:
        players = [
            RenderPlayerStat(
                player=f"Player {index + 1}",
                team="ALP" if index < 5 else "BET",
                agents=["Jett" if index % 2 == 0 else "Sova"],
                kills=str(28 - index),
                deaths=str(11 + index),
                assists=str(4 + index),
                acs=str(320 - index * 12),
                rating=f"{1.35 - index * 0.05:.2f}",
            )
            for index in range(10)
        ]
        result = RenderSingleMapResult(
            map_number=1,
            map_name="Haven",
            team_a="Alpha Esports",
            team_b="Beta Gaming",
            team_a_score="13",
            team_b_score="8",
            tournament_name="VCT Test Stage",
            schedule_name="Playoffs",
            players=players,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = []
            for theme in ("premium_dark", "premium_light"):
                output = Path(temp_dir) / f"map_{theme}.png"
                render_single_map_result_image(result, output, theme=theme)
                self.assert_nonblank_png(output, 1400)
                outputs.append(Image.open(output).convert("RGB"))
            try:
                dark_mean = sum(ImageStat.Stat(outputs[0]).mean) / 3
                light_mean = sum(ImageStat.Stat(outputs[1]).mean) / 3
                self.assertGreater(light_mean - dark_mean, 80)
            finally:
                for image in outputs:
                    image.close()


if __name__ == "__main__":
    unittest.main()
