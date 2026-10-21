import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import test_prediction_feature as fixture
from test_predictions import NOW

from predictions import PredictionStore

OLD = "Valorant Champions 2026"
NEW = "VCT China 2026: Threshold"
GROUP = "default:GroupMessage:42"


class TournamentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "p.db"
        self.store = PredictionStore(self.path)
        for mid, name, eid in [("100001", OLD, "3000"), ("100002", NEW, "3166")]:
            self.store.sync_match(
                mid, "Alpha", "Beta", 3, NOW + timedelta(hours=1), "未开始"
            )
            self.store.set_match_metadata(
                mid, {"tournament": name, "event_href": "/event/" + eid + "/test"}
            )
        for user in ["human", "unplayed"]:
            self.store.member(GROUP, user, user)
        self.store.register_bot(GROUP, "bot", "Mira")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ranks(self, tid):
        return {r["user_id"]: r for r in self.store.leaderboard(GROUP, tid)}

    def test_new_event_starts_at_zero_for_members_and_bot(self):
        self.store.submit(GROUP, "human", "100001", 2, 1, NOW)
        self.store.settle("100001", 2, 1)
        self.assertEqual(self.ranks("vlr:3000")["human"]["points"], 5)
        for row in self.ranks("vlr:3166").values():
            self.assertEqual(
                (row["points"], row["predictions"], row["settled_predictions"]),
                (0, 0, 0),
            )
            self.assertIsNone(row["winner_accuracy"])

    def test_points_accuracy_bot_and_groups_are_isolated(self):
        for mid, score in [("100001", (2, 1)), ("100002", (0, 2))]:
            self.store.submit(GROUP, "human", mid, *score, NOW)
            self.store.save_bot_analysis(
                mid, "ready", {"a": 2, "b": 1, "basis": "limited_info"}, NOW, 1
            )
            self.store.submit_bot(GROUP, mid, 2, 1, NOW)
            self.store.settle(mid, 2, 1)
        old, new = self.ranks("vlr:3000"), self.ranks("vlr:3166")
        self.assertEqual(
            (old["human"]["points"], old["human"]["winner_accuracy"]), (5, 100.0)
        )
        self.assertEqual(
            (new["human"]["points"], new["human"]["winner_accuracy"]), (0, 0.0)
        )
        self.assertEqual(
            (new["human"]["correct_winners"], new["human"]["settled_predictions"]),
            (0, 1),
        )
        self.assertEqual(new["bot"]["points"], 5)
        self.assertEqual(new["bot"]["predictions"], 1)
        self.assertIsNone(new["unplayed"]["winner_accuracy"])
        self.store.member("another-group", "human", "human")
        self.assertEqual(
            self.store.leaderboard("another-group", "vlr:3000")[0]["points"], 0
        )
        self.assertEqual(len(self.store.predictions(GROUP, "human", "vlr:3166")), 1)

    def test_name_only_event_upgrades_to_vlr_identity_without_resetting_points(self):
        tid = self.store.ensure_tournament("Local Cup")["tournament_id"]
        self.store.sync_match(
            "100003", "Alpha", "Beta", 3, NOW + timedelta(hours=1), "未开始"
        )
        self.store.set_match_metadata("100003", {"tournament": "Local Cup"})
        self.store.submit(GROUP, "human", "100003", 2, 1, NOW)
        self.store.settle("100003", 2, 1)
        self.store.set_match_metadata("100003", {"event_href": "/event/9999/local-cup"})
        self.assertEqual(self.store.tournament(tid)["tournament_id"], "vlr:9999")
        self.assertEqual(self.ranks("vlr:9999")["human"]["points"], 5)
        self.store.ensure_tournament("Renamed Local Cup", "/event/9999/new-title")
        self.assertEqual(
            self.store.ensure_tournament("Local Cup")["tournament_id"], "vlr:9999"
        )

    def test_unclassified_history_never_leaks_into_new_event(self):
        self.store.sync_match(
            "100003", "Alpha", "Beta", 3, NOW + timedelta(hours=1), "未开始"
        )
        self.store.submit(GROUP, "human", "100003", 2, 1, NOW)
        self.store.settle("100003", 2, 1)
        self.assertEqual(self.ranks("legacy")["human"]["points"], 5)
        self.assertEqual(self.ranks("vlr:3166")["human"]["points"], 0)

    def test_restart_migration_keeps_all_prediction_rows_and_archived_points(self):
        self.store.submit(GROUP, "human", "100001", 2, 1, NOW)
        self.store.settle("100001", 2, 1)
        before = list(self.store.db.execute("SELECT * FROM predictions"))
        before = [tuple(r) for r in before]
        self.store.close()
        self.store = PredictionStore(self.path)
        self.assertEqual(
            [tuple(r) for r in self.store.db.execute("SELECT * FROM predictions")],
            before,
        )
        self.assertEqual(self.ranks("vlr:3000")["human"]["points"], 5)

    def test_legacy_database_backfills_metadata_without_changing_forecasts(self):
        path = Path(self.temp.name) / "legacy.db"
        c = sqlite3.connect(path)
        c.executescript("""
        CREATE TABLE matches(match_id TEXT PRIMARY KEY,team_a TEXT,team_b TEXT,bo INTEGER,start_at TEXT,lock_at TEXT,status TEXT,day TEXT,result_a INTEGER,result_b INTEGER);
        CREATE TABLE predictions(group_id TEXT,user_id TEXT,match_id TEXT,a INTEGER,b INTEGER,updated_at TEXT,points INTEGER,PRIMARY KEY(group_id,user_id,match_id));
        CREATE TABLE match_metadata(match_id TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE members(group_id TEXT,user_id TEXT,name TEXT,PRIMARY KEY(group_id,user_id));
        """)
        c.execute(
            "INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "old",
                "Alpha",
                "Beta",
                3,
                NOW.isoformat(),
                NOW.isoformat(),
                "已结束",
                "2026-10-01",
                2,
                1,
            ),
        )
        c.execute(
            "INSERT INTO predictions VALUES(?,?,?,?,?,?,?)",
            (GROUP, "human", "old", 2, 1, NOW.isoformat(), 5),
        )
        c.execute("INSERT INTO members VALUES(?,?,?)", (GROUP, "human", "human"))
        c.execute(
            "INSERT INTO match_metadata VALUES(?,?)",
            ("old", json.dumps({"tournament": OLD})),
        )
        c.commit()
        c.close()
        store = PredictionStore(path)
        try:
            old = store.ensure_tournament(OLD)["tournament_id"]
            new = store.ensure_tournament(NEW)["tournament_id"]
            self.assertEqual(store.leaderboard(GROUP, old)[0]["points"], 5)
            self.assertEqual(store.leaderboard(GROUP, new)[0]["points"], 0)
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1
            )
        finally:
            store.close()


class TournamentFeatureTests(unittest.IsolatedAsyncioTestCase):
    event = fixture.FeatureTests.event
    call = fixture.FeatureTests.call
    tearDown = fixture.FeatureTests.tearDown

    def setUp(self):
        fixture.FeatureTests.setUp(self)
        self.p.config["special_tournaments"] = [NEW]
        self.p._prediction_groups = {GROUP: "测试群"}
        self.p.prediction_store.set_match_metadata("123456", {"tournament": OLD})
        self.p.prediction_store.member(GROUP, "user", "群友")
        self.p.prediction_store.submit(GROUP, "user", "123456", 2, 0, NOW)
        self.p.prediction_store.settle("123456", 2, 1)

    async def test_current_and_archived_chat_queries_use_separate_boards(self):
        for text in [
            "积分榜",
            "帮我看看积分榜",
            "帮我看看群里的积分情况",
            "晋升赛积分榜",
            "Threshold积分榜",
            "积分",
        ]:
            image = (await self.call(self.event(text)))[0]
            self.assertEqual(image.chain[0].type, "Image")
            reply = self.p._rank_text(GROUP, text=text)
            self.assertIn(NEW, reply)
            self.assertNotIn(OLD, reply)
            self.assertIn("已参与 0 场 · 已结算 0 场", reply)
        for text in ["冠军赛积分榜", "2026冠军赛积分榜", "历史积分榜"]:
            image = (await self.call(self.event(text)))[0]
            self.assertEqual(image.chain[0].type, "Image")
            reply = self.p._rank_text(GROUP, text=text)
            self.assertIn(OLD, reply)
            self.assertNotIn(NEW, reply)
            self.assertIn("已参与 1 场 · 已结算 1 场", reply)
            self.assertIn("100.0%（猜中 1/1 场）", reply)

    async def test_my_predictions_default_to_current_and_allow_history(self):
        reply = (await self.call(self.event("我的竞猜")))[0]
        self.assertIn(NEW, reply)
        self.assertIn("当前积分：0 分", reply)
        self.assertNotIn("EDG vs PRX", reply)
        reply = (await self.call(self.event("冠军赛我的竞猜")))[0]
        self.assertIn(OLD, reply)
        self.assertIn("当前积分：2 分", reply)
        self.assertIn("EDG vs PRX", reply)

    async def test_multiple_followed_events_are_rendered_separately(self):
        self.p.config["special_tournaments"] = [OLD, NEW]
        images = await self.call(self.event("积分榜"))
        self.assertEqual(len(images), 2)
        self.assertTrue(all(result.chain[0].type == "Image" for result in images))
        reply = self.p._rank_text(GROUP)
        self.assertIn(OLD, reply)
        self.assertIn(NEW, reply)
        self.assertEqual(reply.count("竞猜积分榜"), 2)

    async def test_unknown_event_does_not_silently_return_current_points(self):
        reply = (await self.call(self.event("不存在的杯赛积分榜")))[0]
        self.assertIn("没有找到这项赛事", reply)

    async def test_late_final_rank_uses_watched_event_even_after_following_new_event(
        self,
    ):
        self.p.prediction_store.watch_rank_day(
            NOW.date().isoformat(), GROUP, ["123456"]
        )
        self.p.context = SimpleNamespace(send_message=AsyncMock(return_value=True))
        reply = await self.p._broadcast_prediction(
            GROUP, "积分", rank_day=NOW.date().isoformat()
        )
        self.assertIn(OLD, reply)
        self.assertNotIn(NEW, reply)
        self.assertIn("已参与 1 场 · 已结算 1 场", reply)

    async def test_panel_filters_rank_and_entries_and_rejects_invalid_event(self):
        self.p._prediction_task = None
        self.p._prediction_last_refresh = None
        self.p._prediction_last_error = ""
        self.p._build_monitor_snapshot = Mock(return_value={"match_states": []})
        for tid, points, entries in [(None, 0, 0), ("name:" + OLD.casefold(), 2, 1)]:
            query = {"group": GROUP, "tournament": tid or ""}
            with patch("prediction_feature.request", SimpleNamespace(query=query)):
                response = await self.p.page_status()
            data = json.loads(response.body)["predictions"]
            self.assertEqual(data["leaderboard"][0]["points"], points)
            self.assertEqual(len(data["entries"]), entries)
            self.assertEqual(len(data["tournaments"]), 2)
        with patch(
            "prediction_feature.request",
            SimpleNamespace(query={"group": GROUP, "tournament": "unknown"}),
        ):
            response = await self.p.page_status()
        self.assertEqual(response.status_code, 400)
