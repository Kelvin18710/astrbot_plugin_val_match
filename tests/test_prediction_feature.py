import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot.api.event import MessageChain
from astrbot.api.message_components import At
from test_predictions import NOW

from main import ValMatchPlugin
from predictions import PredictionStore


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = object.__new__(ValMatchPlugin)
        p = self.p
        p.config = {
            "prediction_enabled": True,
            "prediction_targets": "default:GroupMessage:42",
        }
        p.prediction_store = PredictionStore(Path(self.temp.name) / "p.db")
        p.prediction_store.sync_match(
            "123456",
            "EDward Gaming",
            "Paper Rex",
            3,
            NOW + timedelta(hours=1),
            "未开始",
        )
        import asyncio

        p._prediction_lock = asyncio.Lock()
        p._today_in_display_timezone = lambda: NOW.date()
        p._now_in_display_timezone = lambda: NOW
        p._refresh_predictions = AsyncMock()
        p._verify_prediction_match = AsyncMock()
        p._sync_prediction_members = AsyncMock()

    def tearDown(self):
        self.p.prediction_store.close()
        self.temp.cleanup()

    def event(self, text, group="default:GroupMessage:42", at="bot"):
        return SimpleNamespace(
            message_str=text,
            unified_msg_origin=group,
            message_obj=SimpleNamespace(self_id="bot", message=[At(qq=at)]),
            stop_event=lambda: None,
            get_sender_id=lambda: "user",
            get_sender_name=lambda: "群友",
            plain_result=lambda s: s,
            image_result=lambda path: MessageChain().file_image(path),
        )

    async def call(self, event):
        return [r async for r in self.p._handle_prediction_message(event)]

    async def test_event_submit_modify_help_and_scoreboard(self):
        r = await self.call(self.event("我觉得EDG二比一战胜PRX"))
        self.assertIn("竞猜成功", r[0])
        r = await self.call(self.event("改成2:0"))
        self.assertIn("已修改", r[0])
        self.assertEqual(
            self.p.prediction_store.predictions("default:GroupMessage:42")[0]["b"], 0
        )
        r = await self.call(self.event("我的竞猜"))
        self.assertIn("EDward Gaming 胜", r[0])
        self.assertNotIn("2 : 0", r[0])
        self.assertIn("群友 · 我的竞猜", r[0])
        self.assertIn("当前积分", r[0])
        r = await self.call(self.event("积分榜"))
        self.assertEqual(r[0].chain[0].type, "Image")
        self.assertIn("0 分", self.p._rank_text("default:GroupMessage:42"))
        r = await self.call(self.event("竞猜怎么玩"))
        self.assertIn("10 分钟", r[0])

    async def test_bot_change_request_does_not_modify_human_entry(self):
        await self.call(self.event("竞猜EDG2:1"))
        self.p.prediction_store.register_bot("default:GroupMessage:42", "bot", "Mira")
        reply = await self.call(self.event("把你的竞猜改成 2:0"))
        self.assertIn("不能由群成员修改", reply[0])
        self.assertEqual(
            self.p.prediction_store.predictions("default:GroupMessage:42", "user")[0][
                "b"
            ],
            0,
        )
        reply = await self.call(self.event("你的竞猜"))
        self.assertIn("🤖 Mira", reply[0])
        self.assertNotIn("✏️ 修改", reply[0])

    async def test_not_at_bot_or_not_target_ignored(self):
        self.assertEqual(
            await self.call(self.event("竞猜EDG2:1", at="someone-else")), []
        )
        self.assertEqual(
            await self.call(self.event("竞猜EDG2:1", group="default:GroupMessage:43")),
            [],
        )
        self.assertEqual(
            self.p.prediction_store.predictions("default:GroupMessage:42"), []
        )

    async def test_champion_and_hypothetical_discussion_do_not_intercept_or_modify(
        self,
    ):
        await self.call(self.event("竞猜EDG2:1"))
        self.p._refresh_predictions.reset_mock()
        self.p._verify_prediction_match.reset_mock()
        before = self.p.prediction_store.predictions("default:GroupMessage:42", "user")
        for text in [
            "预测下今年冠军",
            "我说预测下今年冠军",
            "你预测今年冠军会是谁",
            "我的冠军预测是EDG",
            "分析一下EDG夺冠概率",
            "你觉得EDG2:0赢PRX有可能吗",
            "EDG2:0赢PRX会不会太乐观？",
            "昨天的比分EDG2:0PRX",
            "世界战队排名怎么样",
            "14:30",
            "2:00",
            "10000:0",
        ]:
            event = self.event(text)
            event.stop_event = Mock()
            with self.subTest(text=text):
                self.assertEqual(await self.call(event), [])
                event.stop_event.assert_not_called()
        self.p._refresh_predictions.assert_not_awaited()
        self.p._verify_prediction_match.assert_not_awaited()
        self.assertEqual(
            before,
            self.p.prediction_store.predictions("default:GroupMessage:42", "user"),
        )

    async def test_explicit_guessing_views_and_short_score_forms_still_work(self):
        for text in [
            "我猜EDG2比1赢PRX",
            "EDG 2:1 PRX",
            "改成2:0",
            "帮我把EDG那场改成2:1",
        ]:
            event = self.event(text)
            event.stop_event = Mock()
            with self.subTest(text=text):
                reply = await self.call(event)
                self.assertTrue(reply)
                event.stop_event.assert_called_once()
                self.assertRegex(reply[0], "竞猜成功|已修改竞猜")
        for text, phrase in [
            ("我的竞猜", "我的竞猜"),
            ("我的预测呢？", "我的竞猜"),
            ("帮我看看积分榜", "0 分"),
            ("竞猜怎么玩？", "10 分钟"),
            ("今日竞猜", "今日竞猜"),
        ]:
            event = self.event(text)
            event.stop_event = Mock()
            with self.subTest(text=text):
                reply = await self.call(event)
                self.assertIn(
                    phrase,
                    self.p._rank_text("default:GroupMessage:42")
                    if text == "帮我看看积分榜"
                    else reply[0],
                )
                event.stop_event.assert_called_once()

    async def test_failed_or_invalid_modification_preserves_previous(self):
        await self.call(self.event("竞猜EDG2:1"))
        r = await self.call(self.event("改成99:0"))
        self.assertIn("BO3", r[0])
        r = await self.call(self.event("我要改一下，3 比 2 吧"))
        self.assertIn("BO3", r[0])
        self.p._verify_prediction_match.side_effect = RuntimeError("offline")
        r = await self.call(self.event("改成2:0"))
        self.assertIn("没有修改", r[0])
        self.assertEqual(
            self.p.prediction_store.predictions("default:GroupMessage:42")[0]["b"], 0
        )

    async def test_live_detail_closes_early_and_upcoming_countdown_is_accepted(self):
        # Use real detail verification with fixtures matching current VLR markup.
        del self.p._verify_prediction_match
        self.p.vlr_client = SimpleNamespace(
            _match_href=lambda m: "/123456", _get_vlr_match_detail_info=AsyncMock()
        )
        detail = {
            "html": '<div class="match-header-vs-score"><div class="match-header-vs-note"><span class="mod-upcoming">4h 50m</span></div><div class="match-header-vs-note">Bo3</div></div>',
            "utc_dt": NOW + timedelta(hours=1),
            "best_of": "Bo3",
            "team_a_display_name": "EDward Gaming",
            "team_b_display_name": "Paper Rex",
        }
        self.p.vlr_client._get_vlr_match_detail_info.return_value = detail
        r = await self.call(self.event("竞猜EDG2:1"))
        self.assertIn("竞猜成功", r[0])
        detail["html"] = (
            '<div class="match-header-vs-score"><span class="mod-live">LIVE</span></div>'
        )
        r = await self.call(self.event("改成2:0"))
        self.assertIn("封盘", r[0])
        self.assertEqual(
            self.p.prediction_store.predictions("default:GroupMessage:42")[0]["b"], 0
        )

    async def test_failed_send_never_marks_success(self):
        self.p.context = SimpleNamespace(send_message=AsyncMock(return_value=False))
        with self.assertRaises(RuntimeError):
            await self.p._broadcast_prediction(
                "default:GroupMessage:42", "竞猜", scheduled=True
            )
        self.assertFalse(
            self.p.prediction_store.delivered(
                "2026-10-01", "竞猜", "default:GroupMessage:42"
            )
        )

    async def test_manual_and_scheduled_rank_show_winner_accuracy_not_exact_score_accuracy(
        self,
    ):
        await self.call(self.event("竞猜EDG2:0"))
        self.p.prediction_store.settle("123456", 2, 1)
        reply = await self.call(self.event("积分榜"))
        self.assertEqual(reply[0].chain[0].type, "Image")
        self.assertIn(
            "胜负正确率：100.0%（猜中 1/1 场）",
            self.p._rank_text("default:GroupMessage:42"),
        )
        self.assertIn("无需比分完全一致", self.p._rank_text("default:GroupMessage:42"))
        self.p.context = SimpleNamespace(send_message=AsyncMock(return_value=True))
        await self.p._broadcast_prediction(
            "default:GroupMessage:42", "积分", scheduled=True
        )
        chain = self.p.context.send_message.call_args.args[1]
        self.assertEqual(chain.chain[0].type, "Image")
        self.assertFalse(any(c.type == "Plain" for c in chain.chain))

    def test_settings_validation(self):
        self.p.plugin_root = Path(__file__).resolve().parent.parent
        for body in [
            {"prediction_push_time": "29:99"},
            {"prediction_enabled": "false"},
            {"prediction_targets": "default:FriendMessage:42"},
            {"unknown": True},
            {"display_timezone": "bad"},
        ]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.p._validate_page_settings(body)
