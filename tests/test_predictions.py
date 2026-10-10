import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from predictions import PredictionStore, resolve_prediction, validate_score

NOW = datetime(2026, 10, 1, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
MATCH = {
    "match_id": "123456",
    "team_a": "EDward Gaming",
    "team_b": "Paper Rex",
    "bo": 3,
}


class ParserTests(unittest.TestCase):
    def test_natural_language_and_orientation(self):
        for text, score in [
            ("我觉得EDG会以二比一战胜PRX", (2, 1)),
            ("竞猜 PRX 2:0 赢 EDG", (0, 2)),
            ("把EDG那场改成2:0", (2, 0)),
            ("竞猜 #123456 1:2", (1, 2)),
            ("改成2:0", (2, 0)),
            ("我要改一下，2 比 0 吧", (2, 0)),
        ]:
            self.assertEqual(resolve_prediction(text, [MATCH], "123456")[1:], score)

    def test_invalid_or_ambiguous_messages_do_not_write(self):
        for text in [
            "竞猜EDG 99:0",
            "竞猜EDG 1:1",
            "竞猜EDG 13:11",
            "竞猜EDG 1:2赢PRX",
            "竞猜EDG 2:1或者2:0",
            "如果EDG 2:1赢PRX",
            "不要竞猜EDG 2:1",
            "EDG 2:1可以吗",
            "改NRG那场2:1",
            "竞猜EDG -2:1",
            "竞猜EDG 2.2:1",
            "EDG 2:1 输给 PRX",
            "EDG对PRX我猜2:1 PRX胜",
            "不要把EDG改成2:1",
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                resolve_prediction(text, [MATCH], "123456")
        with self.assertRaises(ValueError):
            resolve_prediction("竞猜EDG 2:1", [MATCH, {**MATCH, "match_id": "123457"}])
        with self.assertRaises(ValueError):
            resolve_prediction("竞猜 #999999 2:1", [MATCH])

    def test_all_legal_bo_scores(self):
        for bo in [1, 3, 5]:
            win = bo // 2 + 1
            for a in range(7):
                for b in range(7):
                    if (a == win and b < win) or (b == win and a < win):
                        validate_score(bo, a, b)
                    else:
                        with self.assertRaises(ValueError):
                            validate_score(bo, a, b)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "p.db"
        self.store = PredictionStore(self.path)
        self.start = NOW + timedelta(hours=1)
        self.store.sync_match(
            "123456", "EDward Gaming", "Paper Rex", 3, self.start, "未开始"
        )
        for group, user in [
            ("a", "exact"),
            ("a", "winner"),
            ("a", "wrong"),
            ("a", "zero"),
            ("b", "exact"),
        ]:
            self.store.member(group, user, user)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_group_isolation_modify_and_restart(self):
        self.assertFalse(self.store.submit("a", "exact", "123456", 2, 1, NOW))
        self.assertTrue(self.store.submit("a", "exact", "123456", 2, 0, NOW))
        self.store.submit("b", "exact", "123456", 0, 2, NOW)
        self.store.close()
        self.store = PredictionStore(self.path)
        self.assertEqual(self.store.predictions("a")[0]["a"], 2)
        self.assertEqual(self.store.predictions("b")[0]["a"], 0)
        self.assertEqual(len(self.store.predictions("a")), 1)

    def test_boundary_and_irreversible_lock_after_postponement(self):
        cutoff = self.start - timedelta(minutes=10)
        self.store.submit(
            "a", "exact", "123456", 2, 1, cutoff - timedelta(microseconds=1)
        )
        for when in [cutoff, cutoff + timedelta(seconds=1)]:
            with self.assertRaises(ValueError):
                self.store.submit("a", "exact", "123456", 2, 0, when)
        self.store.sync_match(
            "123456",
            "EDward Gaming",
            "Paper Rex",
            3,
            self.start + timedelta(hours=4),
            "未开始",
        )
        with self.assertRaises(ValueError):
            self.store.submit("a", "exact", "123456", 2, 0, cutoff)
        self.assertEqual(self.store.predictions("a")[0]["b"], 1)

    def test_early_live_and_team_changes(self):
        self.store.sync_match(
            "123456", "EDward Gaming", "Paper Rex", 3, self.start, "进行中"
        )
        self.store.sync_match(
            "123456", "EDward Gaming", "Paper Rex", 3, self.start, "未开始"
        )
        with self.assertRaises(ValueError):
            self.store.submit("a", "exact", "123456", 2, 0, NOW)
        self.store.sync_match("123456", "NRG", "Paper Rex", 3, self.start, "未开始")
        self.assertFalse(self.store.settle("123456", 2, 0))

    def test_scoring_idempotent_and_all_zero_members(self):
        for user, score in [("exact", (2, 1)), ("winner", (2, 0)), ("wrong", (0, 2))]:
            self.store.submit("a", user, "123456", *score, NOW)
        self.assertTrue(self.store.settle("123456", 2, 1))
        self.assertFalse(self.store.settle("123456", 2, 1))
        self.assertEqual(
            {r["user_id"]: r["points"] for r in self.store.leaderboard("a")},
            {"exact": 5, "winner": 2, "wrong": 0, "zero": 0},
        )
        self.assertEqual(self.store.leaderboard("b")[0]["points"], 0)
        rows = {r["user_id"]: r for r in self.store.leaderboard("a")}
        for user in ["exact", "winner"]:
            self.assertEqual(rows[user]["winner_accuracy"], 100.0)
            self.assertEqual(rows[user]["correct_winners"], 1)
            self.assertEqual(rows[user]["settled_predictions"], 1)
        self.assertEqual(rows["wrong"]["winner_accuracy"], 0.0)
        self.assertIsNone(rows["zero"]["winner_accuracy"])

    def test_winner_accuracy_excludes_unsettled_matches_and_is_group_scoped(self):
        for match_id in ["123457", "123458", "123459"]:
            self.store.sync_match(
                match_id, "EDward Gaming", "Paper Rex", 3, self.start, "未开始"
            )
        for match_id, a, b in [
            ("123456", 2, 0),
            ("123457", 0, 2),
            ("123458", 2, 0),
            ("123459", 2, 1),
        ]:
            self.store.submit("a", "winner", match_id, a, b, NOW)
        self.store.submit("b", "exact", "123456", 0, 2, NOW)
        self.store.register_bot("a", "bot", "Mira")
        self.store.save_bot_analysis(
            "123456", "ready", {"a": 2, "b": 1, "basis": "limited_info"}, NOW, 1
        )
        self.store.submit_bot("a", "123456", 2, 1, NOW)
        for match_id, a, b in [("123456", 2, 1), ("123457", 1, 2), ("123458", 0, 2)]:
            self.store.settle(match_id, a, b)
        self.store.sync_match(
            "123459", "EDward Gaming", "Paper Rex", 3, self.start, "进行中"
        )
        rows = {r["user_id"]: r for r in self.store.leaderboard("a")}
        user = rows["winner"]
        self.assertEqual(
            (user["predictions"], user["settled_predictions"], user["correct_winners"]),
            (4, 3, 2),
        )
        self.assertEqual(user["winner_accuracy"], 66.7)
        self.assertEqual(user["points"], 4)  # Both correct winners have inexact scores.
        self.assertEqual(rows["bot"]["winner_accuracy"], 100.0)
        self.assertTrue(rows["bot"]["is_bot"])
        self.assertIsNone(rows["zero"]["winner_accuracy"])
        other = self.store.leaderboard("b")[0]
        self.assertEqual(
            (
                other["settled_predictions"],
                other["correct_winners"],
                other["winner_accuracy"],
            ),
            (1, 0, 0.0),
        )

    def test_accuracy_uses_final_modified_pick_and_survives_restart(self):
        self.store.submit("a", "winner", "123456", 2, 0, NOW)
        self.store.submit("a", "winner", "123456", 0, 2, NOW)
        self.store.settle("123456", 2, 1)
        self.store.close()
        self.store = PredictionStore(self.path)
        row = next(r for r in self.store.leaderboard("a") if r["user_id"] == "winner")
        self.assertEqual(
            (
                row["predictions"],
                row["settled_predictions"],
                row["correct_winners"],
                row["winner_accuracy"],
            ),
            (1, 1, 0, 0.0),
        )

    def test_push_dedup_survives_restart_and_failure_not_marked(self):
        self.assertFalse(self.store.delivered("2026-10-01", "竞猜", "a"))
        self.store.mark_delivered("2026-10-01", "竞猜", "a")
        self.store.close()
        self.store = PredictionStore(self.path)
        self.assertTrue(self.store.delivered("2026-10-01", "竞猜", "a"))
        self.assertFalse(self.store.delivered("2026-10-01", "积分", "a"))
        self.assertFalse(self.store.delivered("2026-10-02", "竞猜", "a"))
