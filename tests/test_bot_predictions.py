import asyncio
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bs4 import BeautifulSoup
from test_predictions import NOW

from bot_predictions import normalize_history, normalize_recent, prediction_reason
from clients.vlr import HeadToHeadRecord, RecentMatchRecord, VlrClient
from main import ValMatchPlugin
from prediction_text import leaderboard, my_predictions
from predictions import PredictionStore

GROUP = "default:GroupMessage:42"


def history(
    a="EDward Gaming",
    b="Paper Rex",
    score="2:1",
    day="2026-09-20",
    href="/111111/old-match",
):
    return HeadToHeadRecord(day, score, "Test", a, b, href)


class HistoryTests(unittest.TestCase):
    def test_orientation_future_unverified_and_duplicate_filtered(self):
        match = {
            "match_id": "123456",
            "team_a": "EDward Gaming",
            "team_b": "Paper Rex",
            "day": "2026-10-01",
        }
        rows = [
            history(),
            history("PRX", "EDG", "0:2", href="/111112/other"),
            history(day="2026-10-02"),
            history(href=""),
            history(a="Unrelated"),
            history(score="13:11"),
            history(href="/123456/current"),
            history(),
        ]
        normalized = normalize_history(rows, match, NOW)
        self.assertEqual(len(normalized), 2)
        self.assertEqual((normalized[1]["a"], normalized[1]["b"]), (2, 0))
        self.assertNotIn("event_name", normalized[0])

    def test_real_markup_has_explicit_score_orientation(self):
        client = object.__new__(VlrClient)
        html = """<div class="match-h2h-header"><a class="match-h2h-header-team">Paper Rex</a><a class="match-h2h-header-team mod-right">EDward Gaming</a></div><div class="match-h2h-matches"><a class="mod-h2h" href="/111111/old-match"><span class="match-h2h-matches-score"><span class="rf">1</span><span class="ra">2</span></span><span class="match-h2h-matches-date">2026/09/20</span><span class="match-h2h-matches-event-name">Test</span></a></div>"""
        rows = client._parse_preview_head_to_head(
            BeautifulSoup(html, "html.parser"), None
        )
        match = {
            "match_id": "123456",
            "team_a": "EDward Gaming",
            "team_b": "Paper Rex",
            "day": "2026-10-01",
        }
        self.assertEqual(normalize_history(rows, match, NOW)[0]["a"], 2)


class RecentHistoryTests(unittest.TestCase):
    def test_side_and_score_are_relative_to_own_team_and_future_is_filtered(self):
        match = {
            "match_id": "123456",
            "team_a": "EDward Gaming",
            "team_b": "Paper Rex",
            "day": "2026-10-01",
        }
        rows = [
            RecentMatchRecord("EDG", "Team Liquid", "2026-09-25", "0:2", "/111111/old"),
            RecentMatchRecord("Paper Rex", "Gen.G", "2026-09-26", "2:1", "/111112/old"),
            RecentMatchRecord("EDG", "Gen.G", "2026-10-02", "2:1", "/111113/future"),
            RecentMatchRecord(
                "Unrelated", "Gen.G", "2026-09-25", "2:1", "/111114/other"
            ),
        ]
        result = normalize_recent(rows, match, NOW)
        self.assertEqual(len(result["a"]), 1)
        self.assertEqual(result["a"][0]["for"], 0)
        self.assertEqual(len(result["b"]), 1)
        self.assertEqual(result["b"][0]["against"], 1)

    def test_recent_html_parser_maps_each_panel_to_verified_header(self):
        client = object.__new__(VlrClient)
        html = '<div class="match-h2h-header"><a class="match-h2h-header-team">EDward Gaming</a><a class="match-h2h-header-team">Paper Rex</a></div>'
        for name, score in [("Team Liquid", (0, 2)), ("Gen.G", (2, 1))]:
            html += f'<div class="match-histories"><a class="match-histories-item" href="/111111/old"><div class="match-histories-item-result"><span class="rf">{score[0]}</span><span class="ra">{score[1]}</span></div><span class="match-histories-item-opponent-name">{name}</span><span class="match-histories-item-date">2026/09/25</span></a></div>'
        records = client._parse_preview_recent_matches(
            BeautifulSoup(html, "html.parser")
        )
        self.assertEqual(
            [(r.team, r.score) for r in records],
            [("EDward Gaming", "0:2"), ("Paper Rex", "2:1")],
        )


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "p.db"
        self.p = object.__new__(ValMatchPlugin)
        p = self.p
        p.config = {
            "prediction_enabled": True,
            "prediction_bot_enabled": True,
            "prediction_targets": GROUP,
            "special_tournaments": ["Champions"],
        }
        p.prediction_store = PredictionStore(self.path)
        p.prediction_store.sync_match(
            "123456",
            "EDward Gaming",
            "Paper Rex",
            3,
            NOW + timedelta(hours=1),
            "未开始",
        )
        p._bot_prediction_lock = asyncio.Lock()
        p._prediction_lock = asyncio.Lock()
        p._now_in_display_timezone = lambda: NOW
        p._today_in_display_timezone = lambda: NOW.date()
        provider = SimpleNamespace(meta=lambda: SimpleNamespace(id="test-provider"))
        p.context = SimpleNamespace(
            get_platform_inst=lambda _: SimpleNamespace(
                bot=SimpleNamespace(
                    call_action=AsyncMock(
                        return_value={"user_id": 123, "nickname": "Mira"}
                    )
                )
            ),
            get_using_provider=lambda: provider,
            llm_generate=AsyncMock(
                return_value=SimpleNamespace(completion_text='{"a":2,"b":1}')
            ),
        )
        p.vlr_client = SimpleNamespace(
            get_match_preview=AsyncMock(
                return_value=SimpleNamespace(head_to_head=[history()])
            )
        )
        p._verify_prediction_match = AsyncMock()
        p._record_prediction_error = lambda *args: None

    def tearDown(self):
        self.p.prediction_store.close()
        self.temp.cleanup()

    async def test_model_only_sees_encounters_and_bot_is_immutable_scored_once(self):
        p = self.p
        await p._ensure_bot_predictions()
        entries = p.prediction_store.predictions(GROUP)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["is_bot"])
        evidence = json.loads(p.context.llm_generate.call_args.kwargs["prompt"])
        self.assertEqual(
            set(evidence),
            {
                "team_a",
                "team_b",
                "best_of",
                "past_encounters",
                "recent_matches",
                "tournament",
                "schedule",
                "basis",
            },
        )
        self.assertEqual(evidence["past_encounters"][0]["a"], 2)
        self.assertNotIn("group", evidence)
        self.assertNotIn("ranking", evidence)
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()
        with self.assertRaises(ValueError):
            p.prediction_store.submit(GROUP, "123", "123456", 2, 0, NOW)
        p.prediction_store.member(GROUP, "human", "群友")
        p.prediction_store.submit(GROUP, "human", "123456", 0, 2, NOW)
        p.prediction_store.settle("123456", 2, 1)
        self.assertFalse(p.prediction_store.settle("123456", 2, 1))
        rank = p.prediction_store.leaderboard(GROUP)
        self.assertEqual(rank[0]["points"], 5)
        self.assertTrue(rank[0]["is_bot"])

    async def test_sweep_prediction_preserved_and_daily_message_has_score_without_reason(
        self,
    ):
        p = self.p
        p.context.llm_generate.return_value = SimpleNamespace(
            completion_text='{"a":2,"b":0,"reason":"交手优势明显"}'
        )
        await p._ensure_bot_predictions()
        entry = p.prediction_store.predictions(GROUP)[0]
        self.assertEqual((entry["a"], entry["b"]), (2, 0))
        prompt = p.context.llm_generate.call_args.kwargs["system_prompt"]
        self.assertIn("不能以保守为由一律选2:1", prompt)
        self.assertIn("2:0", prompt)
        info = p._bot_match_info(GROUP, "123456")
        self.assertTrue(info["reason"])
        text = p._prediction_list_text(GROUP)
        self.assertIn("🤖 Mira 的预测：EDG 2 : 0 PRX", text)
        self.assertNotIn("依据：", text)
        self.assertNotIn(info["reason"], text)
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()

    async def test_no_head_to_head_uses_recent_form_and_still_predicts(self):
        p = self.p
        p.vlr_client.get_match_preview.return_value = SimpleNamespace(
            head_to_head=[],
            recent_matches=[
                RecentMatchRecord(
                    "EDward Gaming", "Team Liquid", "2026-09-25", "2:0", "/111112/old"
                )
            ],
        )
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()
        self.assertEqual(len(p.prediction_store.predictions(GROUP)), 1)
        analysis = p.prediction_store.bot_analysis("123456")["payload"]
        self.assertEqual(analysis["basis"], "recent_form")
        self.assertIn("暂无直接交手", analysis["reason"])
        self.assertIn("不确定性较高", analysis["reason"])
        self.assertEqual(analysis["recent"]["a"][0]["for"], 2)

    async def test_no_any_records_or_source_failure_uses_low_confidence_model_prediction(
        self,
    ):
        p = self.p
        p.vlr_client.get_match_preview.side_effect = RuntimeError("network unavailable")
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()
        self.assertEqual(len(p.prediction_store.predictions(GROUP)), 1)
        analysis = p.prediction_store.bot_analysis("123456")["payload"]
        self.assertEqual(analysis["basis"], "limited_info")
        self.assertIn("低置信度预测", analysis["reason"])

    async def test_old_no_history_cache_immediately_upgraded_without_redrawing_ready(
        self,
    ):
        p = self.p
        p.prediction_store.save_bot_analysis(
            "123456", "no_history", {"note": "old abstention"}, NOW, 0
        )
        p.vlr_client.get_match_preview.return_value = SimpleNamespace(
            head_to_head=[], recent_matches=[]
        )
        await p._ensure_bot_predictions()
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()
        self.assertEqual(p.prediction_store.bot_analysis("123456")["state"], "ready")
        self.assertEqual(len(p.prediction_store.predictions(GROUP)), 1)

    async def test_bad_model_scores_never_written(self):
        for content in [
            '{"a":99,"b":0}',
            '{"a":2,"b":2}',
            '{"a":true,"b":0}',
            '{"a":2.0,"b":0}',
            "not json",
        ]:
            self.p.prediction_store.db.execute("DELETE FROM bot_analyses")
            self.p.prediction_store.db.commit()
            self.p.context.llm_generate.return_value = SimpleNamespace(
                completion_text=content
            )
            await self.p._ensure_bot_predictions()
            self.assertEqual(self.p.prediction_store.predictions(GROUP), [])
            self.assertEqual(
                self.p.prediction_store.bot_analysis("123456")["state"], "error"
            )

    async def test_reload_reuses_prediction_without_model_redraw(self):
        p = self.p
        await p._ensure_bot_predictions()
        p.prediction_store.close()
        p.prediction_store = PredictionStore(self.path)
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()
        self.assertEqual(len(p.prediction_store.predictions(GROUP)), 1)
        self.assertEqual(p._bot_match_info(GROUP, "123456")["a"], 2)
        self.assertEqual(p._bot_match_info("", "123456")["state"], "pending")

    async def test_commit_failure_retains_generated_pick_then_retries_same(self):
        p = self.p
        p._verify_prediction_match.side_effect = RuntimeError("offline")
        await p._ensure_bot_predictions()
        self.assertEqual(p.prediction_store.bot_analysis("123456")["state"], "ready")
        self.assertEqual(p.prediction_store.predictions(GROUP), [])
        p._verify_prediction_match.side_effect = None
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_awaited_once()
        self.assertEqual(len(p.prediction_store.predictions(GROUP)), 1)

    async def test_model_finishing_at_cutoff_abstains(self):
        p = self.p

        async def delayed(**kwargs):
            p._now_in_display_timezone = lambda: NOW + timedelta(minutes=50)
            return SimpleNamespace(completion_text='{"a":2,"b":1}')

        p.context.llm_generate.side_effect = delayed
        await p._ensure_bot_predictions()
        self.assertEqual(p.prediction_store.predictions(GROUP), [])

    async def test_closed_match_or_disabled_toggle_never_invokes_model(self):
        p = self.p
        p.config["prediction_bot_enabled"] = False
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_not_awaited()
        p.config["prediction_bot_enabled"] = True
        p._now_in_display_timezone = lambda: NOW + timedelta(minutes=50)
        await p._ensure_bot_predictions()
        p.context.llm_generate.assert_not_awaited()

    def test_public_reason_never_displays_unverified_model_claims_or_truncated_sentence(
        self,
    ):
        match = {"team_a": "EDward Gaming", "team_b": "Paper Rex"}
        payload = {
            "a": 2,
            "b": 1,
            "history": [],
            "recent": {"a": [{"for": 2, "against": 0, "date": "2026-09-25"}]},
            "model_analysis": "他们和别的队战平了，并且有未经证实的伤病",
        }
        reason = prediction_reason(payload, match)
        self.assertIn("近 1 场 1 胜 0 负", reason)
        self.assertNotIn("战平", reason)
        self.assertNotIn("伤病", reason)
        self.assertTrue(reason.endswith("我更看好 EDG。"))

    def test_unified_special_tournaments_and_personalized_medals(self):
        p = self.p
        p.config["preferred_tournaments"] = ["Old ignored"]
        self.assertEqual(p.preferred_tournaments, ["Champions"])
        p.config["special_tournaments"] = []
        self.assertEqual(p.preferred_tournaments, [])
        p.prediction_store.member(GROUP, "human", "群友")
        p.prediction_store.submit(GROUP, "human", "123456", 2, 0, NOW)
        text = my_predictions(
            "群友", p.prediction_store.predictions(GROUP, "human"), 0, NOW, NOW.tzinfo
        )
        self.assertIn("群友 · 我的竞猜", text)
        self.assertIn("2 : 0", text)
        self.assertIn("仍可修改", text)
        rank = leaderboard(
            "测试群",
            [
                {"name": "Mira", "is_bot": True, "points": 5, "predictions": 1},
                {"name": "第二名", "points": 2, "predictions": 1},
                {"name": "第三名", "points": 0, "predictions": 0},
            ],
            NOW,
        )
        for mark in ["🥇", "🥈", "🥉", "🤖 Mira", "合计 5 分"]:
            self.assertIn(mark, rank)
