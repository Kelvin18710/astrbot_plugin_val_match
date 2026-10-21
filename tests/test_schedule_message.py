import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot.api.message_components import At, Plain

from main import ValMatchPlugin


class ScheduleMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = object.__new__(ValMatchPlugin)
        self.plugin._today_in_display_timezone = lambda: date(2026, 10, 18)
        self.plugin._render_for_date = AsyncMock(return_value="今日赛程：LOUD vs VIT")
        self.prediction_calls = Mock()

        async def predictions(event):
            self.prediction_calls(event)
            if False:
                yield

        self.plugin._handle_prediction_message = predictions

    def event(self, text, mention="bot"):
        components = [Plain(text=text)]
        if mention is not None:
            components.insert(0, At(qq=mention))
        return SimpleNamespace(
            message_str=text,
            message_obj=SimpleNamespace(self_id="bot", message=components),
            stop_event=Mock(),
            plain_result=lambda message: message,
        )

    async def call(self, event):
        return [reply async for reply in self.plugin.prediction_message(event)]

    async def test_explicit_schedule_stops_chat_and_does_not_require_predictions(self):
        for text in [
            "赛程",
            "今天赛程",
            "帮我查一下今天的比赛赛程",
            "[At:bot] 赛程",
            "[CQ:at,qq=bot] 查看今日赛程表",
        ]:
            with self.subTest(text=text):
                event = self.event(text)
                self.assertEqual(await self.call(event), ["今日赛程：LOUD vs VIT"])
                event.stop_event.assert_called_once()
                self.prediction_calls.assert_not_called()
        self.plugin._render_for_date.assert_awaited_with(date(2026, 10, 18), None)

    async def test_yesterday_and_tomorrow_use_requested_date(self):
        for text, day in [("昨天赛程", 17), ("明天的赛程", 19)]:
            await self.call(self.event(text))
            self.plugin._render_for_date.assert_awaited_with(date(2026, 10, day), None)

    async def test_discussion_other_games_and_prediction_requests_are_not_intercepted(
        self,
    ):
        for text in [
            "这个赛程怎么安排的",
            "NBA赛程",
            "今年冠军你看好谁",
            "我的竞猜",
            "积分榜",
            "我猜VIT3:1赢LOUD",
            "/val today",
        ]:
            with self.subTest(text=text):
                event = self.event(text)
                self.assertEqual(await self.call(event), [])
                event.stop_event.assert_not_called()
        self.plugin._render_for_date.assert_not_awaited()
        self.assertEqual(self.prediction_calls.call_count, 7)

    async def test_real_bot_mention_required(self):
        for mention in [None, "someone_else"]:
            event = self.event("赛程", mention)
            self.assertEqual(await self.call(event), [])
            event.stop_event.assert_not_called()
        self.plugin._render_for_date.assert_not_awaited()

    async def test_source_failure_returns_service_error_and_stops_chat(self):
        self.plugin._render_for_date.side_effect = RuntimeError("network unavailable")
        event = self.event("赛程")
        self.assertEqual(await self.call(event), ["暂时无法获取赛程，请稍后再试。"])
        event.stop_event.assert_called_once()
        self.prediction_calls.assert_not_called()
