import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from main import ValMatchPlugin
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
    render_match_cards_image,
    render_match_report_image,
    render_single_map_result_image,
    render_start_notice_image,
    render_tournament_progress_image,
)
from studio_assets import prepared_logo
from studio_render import Canvas, market_support


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name)
        self.players = [
            RenderPlayerStat(
                "选手" + str(i),
                "ALP" if i < 5 else "BET",
                ["Jett"],
                "20",
                "12",
                "6",
                acs=str(200 + i),
                rating="1.10",
            )
            for i in range(10)
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_new_styles_render_real_zero_scores_and_all_text_stays_inside_canvas(self):
        match = RenderMatch(
            "今天 · 2026-10-01 · 周四",
            "19:00",
            "已结束",
            "2:0",
            "超长中文战队名称 Alpha International Esports",
            "Beta",
            "VCT 2026: China Stage 2",
            "Group Stage-Winner's (A)",
            "S",
            "Bo3",
        )
        report = RenderMatchReport(
            match.team_a,
            match.team_b,
            "2:0",
            match.tournament_name,
            match.schedule_name,
            "Bo3",
            [
                RenderMapScore("很长的地图名字长廊", "13", "0"),
                RenderMapScore("Haven", "13", "7"),
            ],
            self.players,
            "这是用于验证自动换行的赛后观察。" * 17,
        )
        notice = RenderStartNotice(
            "19:00",
            match.team_a,
            match.team_b,
            match.tournament_name,
            match.schedule_name,
            "Bo3",
            "",
            [RenderHeadToHead("2026-09-01", "2:0", "VCT")],
            team_a_odds="4.20",
            team_b_odds="1.21",
        )
        progress = RenderTournamentProgress(
            "VCT",
            "Group Stage",
            "standings",
            [
                RenderStandingGroup(
                    "小组 A",
                    [
                        RenderStandingRow("Alpha", "0-0", "0/0", "0/0", "0"),
                        RenderStandingRow(
                            "Beta",
                            "1-0",
                            "2/0",
                            "26/14",
                            "+12",
                            position_state="advance",
                        ),
                    ],
                )
            ],
            [],
        )
        texts = []
        draw_text = ImageDraw.ImageDraw.text

        def checked(draw, xy, text, *args, **kwargs):
            bbox = draw.textbbox(
                xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor")
            )
            width, height = draw._image.size
            self.assertGreaterEqual(bbox[0], -2, (text, bbox))
            self.assertGreaterEqual(bbox[1], -2, (text, bbox))
            self.assertLessEqual(bbox[2], width + 2, (text, bbox, width))
            self.assertLessEqual(bbox[3], height + 2, (text, bbox, height))
            texts.append(str(text))
            return draw_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=checked):
            for style in ["studio_dark", "studio_light"]:
                for label, call in [
                    (
                        "schedule",
                        lambda path: render_match_cards_image(
                            [match],
                            date(2026, 10, 1),
                            path,
                            source_name="VLR.gg",
                            theme=style,
                        ),
                    ),
                    (
                        "report",
                        lambda path: render_match_report_image(
                            report, path, theme=style
                        ),
                    ),
                    (
                        "notice",
                        lambda path: render_start_notice_image(
                            notice, path, theme=style
                        ),
                    ),
                    (
                        "standings",
                        lambda path: render_tournament_progress_image(
                            progress, path, theme=style
                        ),
                    ),
                ]:
                    output = self.out / f"{label}-{style}.png"
                    call(output)
                    with Image.open(output) as image:
                        self.assertEqual(image.mode, "RGB")
                        self.assertGreaterEqual(image.width, 1280)
        self.assertIn("0", texts)
        self.assertIn("13  :  0", texts)
        self.assertIn("选手9", texts)
        self.assertIn("赔率 4.20", texts)
        self.assertIn("赔率 1.21", texts)

    def test_all_bracket_rounds_and_teams_retained_over_five_rounds(self):
        rounds = [
            RenderBracketRound(
                f"ROUND {i}",
                [RenderBracketMatch(f"Alpha-{i}", "Beta", "0", "2", winner=2)],
            )
            for i in range(8)
        ]
        data = RenderTournamentProgress(
            "VCT",
            "Playoffs",
            "bracket",
            [],
            [RenderBracketSection("Upper Bracket", rounds)],
        )
        texts = []
        original = ImageDraw.ImageDraw.text

        def capture(draw, xy, text, *args, **kwargs):
            texts.append(str(text))
            return original(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=capture):
            render_tournament_progress_image(
                data, self.out / "bracket.png", theme="studio_dark"
            )
        for i in range(8):
            self.assertIn(f"ROUND {i}", texts)
            self.assertIn(f"Alpha-{i}", texts)

    def test_single_map_styles_are_pixel_identical_to_existing_styles(self):
        data = RenderSingleMapResult(
            1, "Haven", "Alpha", "Beta", "13", "0", "VCT", "Playoffs", self.players
        )
        for suffix in ["dark", "light"]:
            a = self.out / f"old-{suffix}.png"
            b = self.out / f"new-{suffix}.png"
            render_single_map_result_image(data, a, theme="premium_" + suffix)
            render_single_map_result_image(data, b, theme="studio_" + suffix)
            with Image.open(a) as old, Image.open(b) as new:
                self.assertIsNone(ImageChops.difference(old, new).getbbox())

    def test_plugin_accepts_new_theme_options(self):
        plugin = object.__new__(ValMatchPlugin)
        for theme in ["studio_dark", "studio_light", "premium_dark", "premium_light"]:
            plugin.config = {"image_theme": theme}
            self.assertEqual(plugin.image_theme, theme)

    def test_market_support_requires_both_valid_odds(self):
        self.assertEqual(market_support("2.00", "2.00"), (0.5, 0.5))
        left, right = market_support("4.20", "1.21")
        self.assertAlmostEqual(left, 0.2236598890942699)
        self.assertAlmostEqual(left + right, 1)
        for a, b in [
            ("4.20", ""),
            ("", "1.21"),
            ("nan", "1.21"),
            ("inf", "1.21"),
            ("0", "1.21"),
            ("1", "1.21"),
            ("bad", "1.21"),
        ]:
            with self.subTest(a=a, b=b):
                self.assertIsNone(market_support(a, b))

    def test_notice_support_percentages_and_bar_follow_the_team_order(self):
        notice = RenderStartNotice(
            "19:00",
            "Alpha",
            "Beta",
            "VCT",
            "Playoffs",
            "Bo3",
            "",
            [],
            team_a_odds="4.20",
            team_b_odds="1.21",
        )
        original = ImageDraw.ImageDraw.text
        for theme in ["studio_dark", "studio_light"]:
            for reverse in [False, True]:
                texts = []

                def capture(draw, xy, text, *args, **kwargs):
                    texts.append(str(text))
                    return original(draw, xy, text, *args, **kwargs)

                data = (
                    replace(notice, team_a_odds="1.21", team_b_odds="4.20")
                    if reverse
                    else notice
                )
                output = self.out / f"support-{theme}-{reverse}.png"
                with patch.object(ImageDraw.ImageDraw, "text", new=capture):
                    render_start_notice_image(data, output, theme=theme)
                self.assertIn("22.4%", texts)
                self.assertIn("77.6%", texts)
                self.assertIn("赔率 4.20", texts)
                self.assertIn("赔率 1.21", texts)
                canvas = Canvas(1, 1, theme)
                with Image.open(output) as image:
                    # The centre changes sides when the team odds are reversed.
                    expected = (
                        canvas.accent
                        if reverse
                        else "#35749E"
                        if canvas.light
                        else "#83B8E2"
                    )
                    self.assertEqual(
                        image.getpixel((720, 901)),
                        Image.new("RGB", (1, 1), expected).getpixel((0, 0)),
                    )
            texts = []
            with patch.object(ImageDraw.ImageDraw, "text", new=capture):
                render_start_notice_image(
                    replace(notice, team_b_odds=""),
                    self.out / f"missing-{theme}.png",
                    theme=theme,
                )
            self.assertFalse(any("%" in t for t in texts))
            self.assertIn("支持率暂缺 · 双方有效赔率未齐", texts)

    def test_empty_schedule_and_missing_assets_render(self):
        for style in ["studio_dark", "studio_light"]:
            render_match_cards_image(
                [],
                date(2026, 10, 1),
                self.out / f"empty-{style}.png",
                source_name="VLR.gg",
                theme=style,
            )
            with Image.open(self.out / f"empty-{style}.png") as image:
                self.assertGreaterEqual(image.height, 400)
        empty = RenderTournamentProgress(
            "VCT",
            "Group Stage",
            "bracket",
            [],
            [RenderBracketSection("Upper Bracket", []) for _ in range(4)],
        )
        render_tournament_progress_image(
            empty, self.out / "empty-bracket.png", theme="studio_dark"
        )

    def test_horizontal_teams_are_aligned_and_long_names_stay_in_their_lanes(self):
        a = "Alpha International Esports Organization " * 5
        b = "Beta 超长中文战队名称 " * 10
        match = RenderMatch(
            "今天 · 2026-10-01 · 周四",
            "19:00",
            "未开始",
            "",
            a,
            b,
            "VCT",
            "Group Stage",
            "S",
            "Bo3",
        )
        placements = {}
        logos = []
        original = ImageDraw.ImageDraw.text
        original_logo = Canvas.logo

        def capture(draw, xy, text, *args, **kwargs):
            if str(text).startswith(("Alpha", "Beta")):
                placements[str(text).split()[0]] = draw.textbbox(
                    xy, text, font=kwargs["font"], anchor=kwargs["anchor"]
                )
            return original(draw, xy, text, *args, **kwargs)

        def logo(canvas, path, x, y, size, name="V"):
            if name in [a, b]:
                logos.append((x, y, size))
            return original_logo(canvas, path, x, y, size, name)

        with (
            patch.object(ImageDraw.ImageDraw, "text", new=capture),
            patch.object(Canvas, "logo", new=logo),
        ):
            render_match_cards_image(
                [match],
                date(2026, 10, 1),
                self.out / "long-names.png",
                source_name="VLR.gg",
                theme="studio_dark",
            )
        left, right = placements["Alpha"], placements["Beta"]
        self.assertGreaterEqual(left[0], 590 * 2)
        self.assertLessEqual(left[2], 804 * 2)
        self.assertGreaterEqual(right[0], 1029 * 2)
        self.assertLessEqual(right[2], 1243 * 2)
        self.assertEqual(left[1], right[1])
        self.assertEqual([item[2] for item in logos], [88, 88])
        self.assertEqual(logos[0][1], logos[1][1])

    def test_transparent_logos_adapt_contrast_and_keep_brand_colors(self):
        for color, label in [
            ("#000000", "black"),
            ("#EE2233", "red"),
            ("#FFFFFF", "white"),
        ]:
            image = Image.new("RGBA", (100, 100))
            ImageDraw.Draw(image).polygon([(50, 10), (10, 90), (90, 90)], fill=color)
            source = self.out / f"{label}.png"
            image.save(source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            logo = prepared_logo(
                source, 88, False, "Team Vitality" if label == "black" else "Example"
            )
            self.assertEqual(logo.getchannel("A").getextrema(), (0, 255))
            color_counts = logo.getcolors(logo.width * logo.height)
            dominant = max(
                (count, pixel) for count, pixel in color_counts if pixel[3] == 255
            )[1]
            self.assertEqual(
                dominant[:3],
                (255, 226, 52)
                if label == "black"
                else (238, 34, 51)
                if label == "red"
                else (255, 255, 255),
            )
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        matte = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(matte).polygon([(50, 10), (10, 90), (90, 90)], fill="black")
        source = self.out / "matte.png"
        matte.save(source)
        self.assertEqual(
            prepared_logo(source, 88, False, "Example").getchannel("A").getextrema(),
            (0, 255),
        )
        canvas = Canvas(300, 300)
        canvas.logo(str(source), 100, 100, 88, "Example")
        self.assertEqual(
            canvas.image.getpixel((200, 200)),
            Image.new("RGB", (1, 1), canvas.bg).getpixel((0, 0)),
        )
        badge = Image.new("RGBA", (100, 100))
        draw = ImageDraw.Draw(badge)
        draw.ellipse((10, 10, 90, 90), fill="black")
        draw.rectangle((30, 40, 70, 60), fill="white")
        source = self.out / "two-tone.png"
        badge.save(source)
        adapted = prepared_logo(source, 88, False, "Example")
        colors = {pixel[:3] for pixel in adapted.getdata() if pixel[3] == 255}
        self.assertIn((0, 0, 0), colors)
        self.assertIn((255, 255, 255), colors)

    def test_three_four_five_map_reports_keep_all_maps_and_portraits_flags(self):
        avatar = self.out / "avatar.png"
        flag = self.out / "flag.png"
        Image.new("RGBA", (80, 80), "#E25842").save(avatar)
        Image.new("RGB", (48, 32), "#FFFFFF").save(flag)
        players = [
            replace(
                p,
                avatar_path=str(avatar),
                country_flag_path=str(flag),
                country_code="CN",
            )
            for p in self.players
        ]
        original = ImageDraw.ImageDraw.text
        for count in [3, 4, 5]:
            for theme in ["studio_dark", "studio_light"]:
                texts = []

                def checked(draw, xy, text, *args, **kwargs):
                    bbox = draw.textbbox(
                        xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor")
                    )
                    width, height = draw._image.size
                    self.assertGreaterEqual(bbox[0], 0)
                    self.assertGreaterEqual(bbox[1], 0)
                    self.assertLessEqual(bbox[2], width)
                    self.assertLessEqual(bbox[3], height)
                    texts.append(str(text))
                    return original(draw, xy, text, *args, **kwargs)

                maps = [
                    RenderMapScore(f"MAP-NAME-{i}", "31", "29", "1:24:36")
                    for i in range(count)
                ]
                data = RenderMatchReport(
                    "Alpha",
                    "Beta",
                    "2:1" if count == 3 else "3:1" if count == 4 else "3:2",
                    "VCT",
                    "Grand Final",
                    "Bo3" if count == 3 else "Bo5",
                    maps,
                    players,
                    "",
                )
                output = self.out / f"report-{count}-{theme}.png"
                with patch.object(ImageDraw.ImageDraw, "text", new=checked):
                    render_match_report_image(data, output, theme=theme)
                for i in range(count):
                    self.assertIn(f"MAP-NAME-{i}", texts)
                self.assertEqual(texts.count("CN"), 10)
                with Image.open(output) as image:
                    # Portraits and flags retain their own color, bypassing logo recoloring.
                    table_y = 696 + (154 if count > 3 else 0)
                    self.assertEqual(
                        image.getpixel((103, table_y + 110)), (226, 88, 66)
                    )
                    self.assertEqual(
                        image.getpixel((156, table_y + 127)), (255, 255, 255)
                    )

    def test_report_retains_all_legacy_metrics_and_places_ten_players_in_ten_rows(self):
        agent = self.out / "agent.png"
        Image.new("RGBA", (64, 64), "#8866DD").save(agent)
        original_asset = hashlib.sha256(agent.read_bytes()).hexdigest()
        players = [
            replace(
                p,
                country_code="CN",
                country_name="China",
                agents=["Jett", "Sova"],
                agent_image_paths=[str(agent), str(agent)],
                kd_diff="+8",
                kast="73%",
                adr="156",
                headshot_percent="41%",
                first_kills="7",
                first_deaths="2",
                fk_diff="+5",
            )
            for p in self.players
        ]
        data = RenderMatchReport(
            "Alpha",
            "Beta",
            "2:1",
            "VCT",
            "Upper Final",
            "Bo3",
            [RenderMapScore("Haven", "13", "7", "48:22", "Alpha")],
            players,
            "保留完整赛后锐评。",
        )
        texts = []
        positions = []
        original = ImageDraw.ImageDraw.text

        def capture(draw, xy, text, *args, **kwargs):
            texts.append(str(text))
            if str(text).startswith("选手"):
                positions.append(xy)
            return original(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=capture):
            render_match_report_image(
                data, self.out / "full-stats.png", theme="studio_dark"
            )
        for value in [
            "Rating",
            "ACS",
            "K / D / A",
            "K/D ±",
            "KAST",
            "ADR",
            "HS%",
            "FK / FD",
            "FK/FD ±",
            "73%",
            "156",
            "41%",
            "7/2",
            "+8",
            "+5",
            "CN · China",
            "Jett, Sova",
            "选图 · Alpha",
            "48:22",
            "保留完整赛后锐评。",
        ]:
            self.assertIn(value, texts)
        self.assertEqual(len(positions), 10)
        self.assertEqual(len({xy[1] for xy in positions}), 10)
        self.assertEqual(len({xy[0] for xy in positions}), 1)
        self.assertTrue((self.out / "full-stats.png").exists())
        self.assertEqual(original_asset, hashlib.sha256(agent.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
