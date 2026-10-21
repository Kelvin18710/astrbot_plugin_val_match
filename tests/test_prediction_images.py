import io
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import test_prediction_feature as fixture
from PIL import Image
from test_predictions import NOW

from prediction_render import Canvas, honors, prediction_card, prediction_leaderboard
from predictions import PredictionStore


class HonorTests(unittest.TestCase):
    def test_result_cards_filter_day_event_group_and_use_winner_not_exact_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PredictionStore(Path(tmp) / "p.db")
            for group, user in [
                ("g", "right"),
                ("g", "wrong"),
                ("g", "none"),
                ("other", "outsider"),
            ]:
                store.member(group, user, user)
            for mid, days, event in [
                ("today", 0, "Cup"),
                ("other-cup", 0, "Another"),
                ("tomorrow", 1, "Cup"),
            ]:
                store.sync_match(
                    mid, "A", "B", 3, NOW + timedelta(days=days, hours=1), "未开始"
                )
                store.set_match_metadata(mid, {"tournament": event})
            store.submit("g", "right", "today", 2, 0, NOW)
            store.submit("g", "wrong", "today", 0, 2, NOW)
            store.submit("other", "outsider", "today", 2, 1, NOW)
            store.settle("today", 2, 1)
            results = store.rank_results("g", NOW.date().isoformat(), "name:cup")
            self.assertEqual([r["match_id"] for r in results], ["today"])
            self.assertEqual([m["user_id"] for m in results[0]["winners"]], ["right"])
            self.assertEqual((results[0]["result_a"], results[0]["result_b"]), (2, 1))
            pending = store.rank_results(
                "g", (NOW + timedelta(days=1)).date().isoformat(), "name:cup"
            )[0]
            self.assertIsNone(pending["result_a"])
            self.assertEqual(pending["winners"], [])
            store.close()

    def test_postponed_batch_keeps_original_match_day_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PredictionStore(Path(tmp) / "p.db")
            day = NOW.date().isoformat()
            store.sync_match("m", "A", "B", 3, NOW + timedelta(hours=1), "未开始")
            store.set_match_metadata("m", {"tournament": "Cup"})
            store.watch_rank_day(day, "g", ["m"])
            store.sync_match(
                "m", "A", "B", 3, NOW + timedelta(days=1, hours=1), "未开始"
            )
            store.settle("m", 2, 0)
            self.assertEqual(store.rank_results("g", day, "name:cup"), [])
            self.assertEqual(
                store.rank_results("g", day, "name:cup", batch=True)[0]["match_id"], "m"
            )
            store.close()

    def test_streaks_follow_match_order_and_skip_nonparticipated_or_unsettled_matches(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            store = PredictionStore(Path(tmp) / "p.db")
            group = "g"
            store.member(group, "u", "群友")
            for i in range(8):
                mid = str(i)
                store.sync_match(
                    mid, "A", "B", 3, NOW + timedelta(hours=i + 1), "未开始"
                )
                store.set_match_metadata(
                    mid, {"tournament": "Current" if i < 7 else "Other"}
                )
                if i != 4:
                    store.submit(group, "u", mid, 1, 0, NOW, mode="winner")
            # Actual participated sequence in Current: W W L W W, then pending.
            for i in [5, 3, 4, 2, 1, 0, 7]:
                store.settle(str(i), 0 if i == 2 else 2, 2 if i == 2 else 0)
            row = store.leaderboard(group, "name:current")[0]
            self.assertEqual((row["longest_streak"], row["current_streak"]), (2, 2))
            self.assertEqual(row["recent_results"], [True, True, False, True, True])
            self.assertEqual(
                (row["correct_winners"], row["settled_predictions"]), (4, 5)
            )
            self.assertEqual(row["predictions"], 6)
            self.assertEqual(store.leaderboard("another", "name:current"), [])
            store.close()

    def test_honors_keep_ties_exact_denominators_and_zero_accuracy(self):
        rows = [
            {
                "name": "一场哥",
                "predictions": 1,
                "settled_predictions": 1,
                "correct_winners": 1,
                "longest_streak": 1,
            },
            {
                "name": "稳定哥",
                "predictions": 5,
                "settled_predictions": 5,
                "correct_winners": 5,
                "longest_streak": 5,
            },
            {
                "name": "新同学",
                "predictions": 9,
                "settled_predictions": 0,
                "correct_winners": 0,
                "longest_streak": 0,
            },
        ]
        awards = honors(rows)
        self.assertEqual(awards[0]["names"], "稳定哥")
        self.assertEqual(awards[1]["names"], "一场哥、稳定哥")
        self.assertEqual(awards[1]["note"], "1/1 场 · 5/5 场")
        self.assertEqual(awards[2]["names"], "新同学")
        self.assertEqual(honors([dict(rows[0], correct_winners=0)])[1]["value"], "0.0%")
        self.assertEqual(honors([])[0]["value"], "等待首位命中")
        # Rounded 33.3% values must not turn unequal fractions into a tie.
        close = [
            dict(rows[0], correct_winners=1, settled_predictions=3),
            dict(rows[1], correct_winners=333, settled_predictions=1000),
        ]
        self.assertEqual(honors(close)[1]["names"], "一场哥")


class RenderingTests(unittest.TestCase):
    def test_result_grid_and_award_avatars_without_member_streak_or_leader_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            members = [
                {
                    "name": "群友" + str(i),
                    "user_id": str(i),
                    "points": 2,
                    "predictions": 1,
                    "settled_predictions": 1,
                    "correct_winners": 1,
                    "winner_accuracy": 100.0,
                    "longest_streak": 1,
                }
                for i in range(4)
            ]
            results = [
                {
                    "team_a": "A" + str(i),
                    "team_b": "B" + str(i),
                    "result_a": 2,
                    "result_b": 1,
                    "start_at": NOW.isoformat(),
                    "winners": members,
                }
                for i in range(3)
            ]
            written = []
            placements = []
            portraits = []
            original_text = Canvas.text
            import prediction_render as renderer

            original_result = renderer.draw_result
            original_avatar = renderer.member_avatar

            def text(c, x, y, value, *args, **kwargs):
                written.append(str(value))
                return original_text(c, x, y, value, *args, **kwargs)

            def result(c, r, x, y, *args):
                placements.append((x, y))
                return original_result(c, r, x, y, *args)

            def avatar(c, path, x, y, size, name):
                portraits.append(name)
                return original_avatar(c, path, x, y, size, name)

            with (
                patch.object(Canvas, "text", text),
                patch.object(renderer, "draw_result", result),
                patch.object(renderer, "member_avatar", avatar),
            ):
                prediction_leaderboard(
                    "群", "赛事", members, NOW, Path(tmp) / "rank.png", results=results
                )
            self.assertEqual(placements[0][1], placements[1][1])
            self.assertGreater(placements[2][1], placements[0][1])
            self.assertEqual([x for x, _ in placements], [64, 612, 64])
            self.assertIn("竞猜荣誉榜", written)
            self.assertFalse(
                any(
                    "本赛事积分领跑" in t
                    or "当前 " in t
                    or "本赛事最长 1 连准" in t
                    or "赛 场 小 荣 誉" in t
                    for t in written
                )
            )
            # Each member has a ranking portrait, three result portraits and three award portraits.
            for member in members:
                self.assertEqual(portraits.count(member["name"]), 7)

    def test_original_qq_faces_and_neutral_instruction_replace_color_prompts(self):
        from click_predictions import winner_choices
        from prediction_render import FACE_ROOT

        self.assertEqual(set(winner_choices()), {"285", "293"})
        with tempfile.TemporaryDirectory() as tmp:
            written = []
            icons = []
            original = Canvas.text
            original_icon = Canvas.icon

            def text(c, x, y, value, *args, **kwargs):
                written.append(str(value))
                return original(c, x, y, value, *args, **kwargs)

            def icon(c, path, *args):
                icons.append(Path(path).name)
                return original_icon(c, path, *args)

            payload = {"team_a": "A", "team_b": "B", "lock_at": NOW.isoformat()}
            with patch.object(Canvas, "text", text), patch.object(Canvas, "icon", icon):
                prediction_card(payload, Path(tmp) / "card.png")
            self.assertEqual(icons, ["285.png", "293.png"])
            self.assertEqual(written.count("预测该队获胜"), 2)
            self.assertFalse(
                any("选我胜" in t or "蓝色" in t or "橙色" in t for t in written)
            )
            for face in ["285", "293"]:
                with Image.open(FACE_ROOT / (face + ".png")) as asset:
                    self.assertEqual(
                        asset.convert("RGBA").getchannel("A").getextrema(), (0, 255)
                    )

    def test_flat_card_both_themes_long_names_and_dark_transparent_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = root / "logo.png"
            Image.new("RGBA", (20, 20), (0, 0, 0, 180)).save(logo)
            payload = {
                "team_a": "A very long team name " + ("Team " * 15),
                "team_b": "一支名称非常非常长的队伍" * 6,
                "start_at": NOW.isoformat(),
                "lock_at": (NOW + timedelta(minutes=50)).isoformat(),
                "logo_a": str(logo),
                "logo_b": None,
                "tournament": "Test Tournament",
            }
            before = logo.read_bytes()
            for theme in ["studio_dark", "studio_light"]:
                path = prediction_card(
                    payload, root / (theme + ".png"), theme=theme, demo=True
                )
                with Image.open(path) as image:
                    self.assertEqual(image.size, (720, 300))
                    self.assertEqual(image.mode, "RGB")
                self.assertEqual(logo.read_bytes(), before)

    def test_rank_renderer_keeps_zero_and_exact_statistics_without_fake_honors(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {
                    "name": "群友",
                    "points": 0,
                    "predictions": 0,
                    "settled_predictions": 0,
                    "correct_winners": 0,
                    "winner_accuracy": None,
                    "longest_streak": 0,
                }
            ]
            written = []
            original = Canvas.text

            def capture(c, x, y, value, *args, **kwargs):
                written.append(str(value))
                return original(c, x, y, value, *args, **kwargs)

            with patch.object(Canvas, "text", capture):
                prediction_leaderboard(
                    "测试群",
                    "新赛事",
                    rows,
                    NOW,
                    Path(tmp) / "rank.png",
                    rank_day="2026-10-01",
                )
            self.assertIn("0", written)
            self.assertIn("10月01日赛果", written)
            self.assertIn("等待首位命中", written)
            self.assertNotIn("100.0%", written)


class ImageDeliveryTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.FeatureTests.setUp
    tearDown = fixture.FeatureTests.tearDown
    event = fixture.FeatureTests.event
    call = fixture.FeatureTests.call

    async def test_avatar_cache_keeps_accounts_distinct_and_reuses_valid_images(self):
        platform = SimpleNamespace(meta=lambda: SimpleNamespace(name="aiocqhttp"))
        self.p.context = SimpleNamespace(get_platform_inst=lambda _: platform)
        requests = []

        def response(request):
            user = request.url.params["nk"]
            requests.append(user)
            out = io.BytesIO()
            Image.new("RGB", (100, 100), "red" if user == "12345" else "blue").save(
                out, format="PNG"
            )
            return httpx.Response(200, content=out.getvalue())

        client_class = httpx.AsyncClient

        def client(**kwargs):
            return client_class(transport=httpx.MockTransport(response))

        rows = [{"user_id": "12345"}, {"user_id": "54321"}, {"user_id": "not-qq"}]
        with patch("prediction_images.httpx.AsyncClient", side_effect=client):
            await self.p._attach_prediction_avatars("default:GroupMessage:42", rows)
            await self.p._attach_prediction_avatars("default:GroupMessage:42", rows)
        self.assertEqual(sorted(requests), ["12345", "54321"])
        for row, color in zip(rows[:2], [(255, 0, 0), (0, 0, 255)]):
            with Image.open(row["avatar_path"]) as image:
                self.assertEqual(image.getpixel((50, 50)), color)
        self.assertNotIn("avatar_path", rows[2])

    async def test_invalid_avatar_response_never_becomes_a_cached_portrait(self):
        self.p.context = SimpleNamespace(
            get_platform_inst=lambda _: SimpleNamespace(
                meta=lambda: SimpleNamespace(name="aiocqhttp")
            )
        )
        client_class = httpx.AsyncClient

        def client(**kwargs):
            return client_class(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, content=b"<html>not an avatar</html>"
                    )
                )
            )

        rows = [{"user_id": "12345"}]
        with patch("prediction_images.httpx.AsyncClient", side_effect=client):
            await self.p._attach_prediction_avatars("default:GroupMessage:42", rows)
        self.assertNotIn("avatar_path", rows[0])
        self.assertEqual(
            list((self.p._prediction_image_root() / "avatars").iterdir()), []
        )

    async def test_rank_query_pages_all_members_and_contains_no_plaintext(self):
        group = "default:GroupMessage:42"
        for i in range(26):
            self.p.prediction_store.member(group, str(i), "Member " + str(i))
        images = await self.call(self.event("积分榜"))
        self.assertEqual(len(images), 2)
        for result in images:
            self.assertEqual([part.type for part in result.chain], ["Image"])
            self.assertTrue(Path(result.chain[0].path).is_file())
