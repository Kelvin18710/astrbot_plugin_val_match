from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.platform import MessageType
from astrbot.api.star import Context, Star
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.star.filter.command import GreedyStr

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - dependency is declared, keep runtime fallback.
    BeautifulSoup = None

try:
    from .clients.vlr import (
        BaseMatchClient,
        MapScore,
        MatchPreview,
        MatchRecord,
        MatchReport,
        RequestDebugInfo,
        TournamentProgress,
        VlrClient,
    )
    from .render import (
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
except ImportError:
    from clients.vlr import (
        BaseMatchClient,
        MapScore,
        MatchPreview,
        MatchRecord,
        MatchReport,
        RequestDebugInfo,
        TournamentProgress,
        VlrClient,
    )
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


try:
    from .prediction_feature import PredictionFeature
except ImportError:
    from prediction_feature import PredictionFeature


class ValMatchPlugin(PredictionFeature, Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.plugin_root = Path(__file__).resolve().parent
        self.artifacts_dir = self.plugin_root / "artifacts"
        self.rendered_dir = self.artifacts_dir / "rendered"
        self.logo_cache_dir = self.artifacts_dir / "logo_cache"
        self.image_cache_dir = self.artifacts_dir / "image_cache"
        self.monitor_dir = self.artifacts_dir / "monitor"
        self._image_cache_locks: dict[str, asyncio.Lock] = {}
        self._image_http: httpx.AsyncClient | None = None
        self._comment_context_cache: dict[str, tuple[datetime, list[str]]] = {}
        self._agent_portrait_urls: dict[str, str] = {}
        self._agent_portraits_loaded = False
        self.vlr_client = VlrClient(config)
        self._push_task: asyncio.Task[None] | None = None
        self._special_task: asyncio.Task[None] | None = None
        self._special_state: dict[str, dict[str, Any]] = {}
        self._special_timeline: list[dict[str, Any]] = []
        self._last_special_start_scan_hour: datetime | None = None
        self._last_special_scan_started_at: datetime | None = None
        self._last_special_scan_finished_at: datetime | None = None
        self._last_special_next_scan_at: datetime | None = None
        self._last_special_scan_summary: dict[str, Any] = {}
        self._monitor_last_written_at: datetime | None = None
        self.last_source_used: str = ""
        self._init_predictions()

    async def initialize(self) -> None:
        (self.monitor_dir / "status.html").unlink(missing_ok=True)
        await self._restart_push_task()
        await self._restart_special_task()
        await self._restart_prediction_task()

    async def terminate(self) -> None:
        if self._push_task:
            self._push_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._push_task
            self._push_task = None
        if self._special_task:
            self._special_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._special_task
            self._special_task = None
        if self._image_http is not None:
            await self._image_http.aclose()
            self._image_http = None
        await self._stop_predictions()
        await self.vlr_client.close()

    @property
    def display_timezone(self) -> str:
        return (
            str(self.config.get("display_timezone") or "Asia/Shanghai").strip()
            or "Asia/Shanghai"
        )

    def _get_display_tz(self) -> ZoneInfo:
        with contextlib.suppress(Exception):
            return ZoneInfo(self.display_timezone)
        return ZoneInfo("Asia/Shanghai")

    def _now_in_display_timezone(self) -> datetime:
        return datetime.now(self._get_display_tz())

    def _today_in_display_timezone(self) -> date:
        return self._now_in_display_timezone().date()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def prediction_message(self, event: AstrMessageEvent):
        async for result in self._handle_prediction_message(event):
            yield result

    @filter.command_group("val")
    def val(self) -> None:
        """无畏契约赛程查询。"""
        return None

    @val.command("today")
    async def val_today(self, event: AstrMessageEvent):
        """查询今天的无畏契约比赛，默认仅展示 S 级并包含已结束比赛。"""
        message = await self._render_for_date(self._today_in_display_timezone(), None)
        yield event.plain_result(message)

    @val.command("tomorrow")
    async def val_tomorrow(self, event: AstrMessageEvent):
        """查询明天的无畏契约比赛。"""
        message = await self._render_for_date(
            self._today_in_display_timezone() + timedelta(days=1), None
        )
        yield event.plain_result(message)

    @val.command("date")
    async def val_date(self, event: AstrMessageEvent, day: str):
        """查询指定日期的无畏契约比赛，格式: /val date 2026-04-27"""
        try:
            target_date = date.fromisoformat(day)
        except ValueError:
            yield event.plain_result("日期格式错误，请使用 YYYY-MM-DD。")
            return
        message = await self._render_for_date(target_date, None)
        yield event.plain_result(message)

    @val.command("level")
    async def val_level(self, event: AstrMessageEvent, level_name: str):
        """按比赛等级查询今天的无畏契约比赛，示例: /val level S"""
        levels = self._split_csv_text(level_name)
        if not levels:
            yield event.plain_result("请提供至少一个比赛等级，例如 /val level S。")
            return
        message = await self._render_for_date(self._today_in_display_timezone(), levels)
        yield event.plain_result(message)

    @val.command("s")
    async def val_s(self, event: AstrMessageEvent):
        """图片展示今日所有 S 级赛事。"""
        try:
            image_path = await self._render_daily_s_tier_image(
                self._today_in_display_timezone()
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 渲染 S 级赛程图片失败: %s", exc)
            yield event.plain_result(f"渲染今日 S 级赛程图片失败：{exc}")
            return
        yield event.image_result(image_path)

    @val.command("sync_events")
    async def val_sync_events(self, event: AstrMessageEvent):
        """同步 VLR 可选赛事列表到插件配置。"""
        try:
            names = await self.vlr_client.discover_tournaments()
            if not names:
                yield event.plain_result("没有同步到任何赛事列表，请稍后重试。")
                return
            synced_count, total_count = self._update_tournament_options(names)
            preview = "、".join(names[:8])
            suffix = "..." if len(names) > 8 else ""
            yield event.plain_result(
                f"已同步 {synced_count} 个当前赛事到插件设置，共 {total_count} 个可选项。\n"
                "请重载插件或刷新插件配置页，然后到 WebUI 的“特别关心赛事”中多选。\n"
                "删除关注项可用 /val unwatch 序号或关键词，删除特别关心可用 /val special_del 序号或关键词。\n"
                f"预览：{preview}{suffix}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 同步赛事列表失败: %s", exc)
            yield event.plain_result(f"同步赛事列表失败：{exc}")

    @val.command("watch")
    async def val_watch(self, event: AstrMessageEvent):
        """列出当前特别关心赛事。"""
        if not self.preferred_tournaments:
            yield event.plain_result("当前没有特别关心赛事。")
            return
        yield event.plain_result(
            self._format_numbered_list("特别关心赛事", self.preferred_tournaments)
        )

    @val.command("unwatch")
    async def val_unwatch(self, event: AstrMessageEvent, keyword: GreedyStr):
        """删除特别关心赛事，支持序号或关键词。"""
        removed, remaining = self._remove_configured_text_item(
            "special_tournaments", str(keyword)
        )
        if not removed:
            yield event.plain_result(
                "没有找到要删除的特别关心赛事。可用 /val watch 查看序号。"
            )
            return
        yield event.plain_result(
            f"已删除特别关心赛事：{removed}\n剩余 {remaining} 个。"
        )

    @val.command("special")
    async def val_special(self, event: AstrMessageEvent):
        """列出特别关心赛事。"""
        lines = [self._format_numbered_list("特别关心赛事", self.special_tournaments)]
        lines.append(
            f"推送目标：{', '.join(self.special_push_targets) if self.special_push_targets else '(未配置)'}"
        )
        lines.append(
            f"开赛提醒：{'开启' if self.special_start_notice_enabled else '关闭'}"
        )
        lines.append(
            f"逐图赛果：{'开启' if self.special_map_report_enabled else '关闭'}"
        )
        lines.append(f"赛后战报：{'开启' if self.special_report_enabled else '关闭'}")
        yield event.plain_result("\n".join(lines))

    @val.command("special_add")
    async def val_special_add(self, event: AstrMessageEvent, name: GreedyStr):
        """添加特别关心赛事。"""
        value = str(name).strip()
        if not value:
            yield event.plain_result(
                "请提供赛事名称，例如 /val special_add VCT 2026: Pacific Stage 1"
            )
            return
        added = self._add_configured_text_item("special_tournaments", value)
        await self._restart_special_task()
        yield event.plain_result(
            ("已添加" if added else "已存在") + f"特别关心赛事：{value}"
        )

    @val.command("special_del")
    async def val_special_del(self, event: AstrMessageEvent, keyword: GreedyStr):
        """删除特别关心赛事，支持序号或关键词。"""
        removed, remaining = self._remove_configured_text_item(
            "special_tournaments", str(keyword)
        )
        await self._restart_special_task()
        if not removed:
            yield event.plain_result(
                "没有找到要删除的特别关心赛事。可用 /val special 查看序号。"
            )
            return
        yield event.plain_result(
            f"已删除特别关心赛事：{removed}\n剩余 {remaining} 个。"
        )

    @val.command("special_bind")
    async def val_special_bind(self, event: AstrMessageEvent):
        """把当前会话加入特别关心推送目标。"""
        target = event.unified_msg_origin
        added = self._add_configured_text_item("special_push_targets", target)
        await self._restart_special_task()
        yield event.plain_result(
            ("已添加" if added else "已存在") + f"特别关心推送目标：{target}"
        )

    @val.command("special_unbind")
    async def val_special_unbind(self, event: AstrMessageEvent):
        """把当前会话从特别关心推送目标移除。"""
        removed, _ = self._remove_configured_text_item(
            "special_push_targets", event.unified_msg_origin
        )
        await self._restart_special_task()
        yield event.plain_result(
            "已移除当前会话推送目标。"
            if removed
            else "当前会话不在特别关心推送目标中。"
        )

    @val.command("report")
    async def val_report(self, event: AstrMessageEvent):
        """手动生成最近一场已结束比赛的战报图。"""
        async for result in self._handle_manual_report(event, ""):
            yield result

    @val.command("report_find")
    async def val_report_find(self, event: AstrMessageEvent, keyword: GreedyStr):
        """按关键词手动生成最近一场已结束比赛的战报图。"""
        async for result in self._handle_manual_report(event, str(keyword)):
            yield result

    async def _handle_manual_report(self, event: AstrMessageEvent, keyword: str):
        query = str(keyword or "").strip()
        try:
            match = await self._find_recent_completed_match(query)
            if not match:
                yield event.plain_result("没有找到可生成战报的已结束比赛。")
                return
            image_path = await self._render_match_report_image(match)
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 生成战报失败: %s", exc)
            yield event.plain_result(f"生成战报失败：{exc}")
            return
        yield event.image_result(image_path)

    @val.command("push_test")
    async def val_push_test(self, event: AstrMessageEvent):
        """立即测试每日赛程图和自动赛况图推送。"""
        if not self.push_targets:
            yield event.plain_result("未配置 push_targets，无法测试推送。")
            return
        image_path = await self._render_daily_s_tier_image(
            self._today_in_display_timezone()
        )
        sent, failed = await self._push_image_to_targets(image_path)
        progress_path: str | None = None
        try:
            progress_path = await self._render_daily_progress_image(
                self._today_in_display_timezone()
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 推送测试赛况图生成失败: %s", exc)
        progress_sent = progress_failed = 0
        if progress_path:
            progress_sent, progress_failed = await self._push_image_to_targets(
                progress_path
            )
        progress_result = (
            f"赛况图成功 {progress_sent} 个、失败 {progress_failed} 个"
            if progress_path
            else "当前没有可用的赛事阶段数据，已跳过赛况图"
        )
        yield event.plain_result(
            f"推送测试完成：赛程图成功 {sent} 个、失败 {failed} 个；{progress_result}。"
        )

    @val.command("progress")
    async def val_progress(self, event: AstrMessageEvent):
        """自动展示当前特别关心赛事的积分榜或淘汰赛晋级图。"""
        try:
            image_path = await self._render_daily_progress_image(
                self._today_in_display_timezone(),
                respect_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 渲染赛况图失败: %s", exc)
            yield event.plain_result(f"渲染赛况图失败：{exc}")
            return
        if not image_path:
            yield event.plain_result(
                "当前特别关心赛事暂时没有可用的积分榜或淘汰赛数据。"
            )
            return
        yield event.image_result(image_path)

    @val.command("debug")
    async def val_debug(self, event: AstrMessageEvent):
        """输出当前数据源与请求调试信息。"""
        today = self._today_in_display_timezone()
        matches, used_client = await self._query_matches(today)
        debug_client = self.vlr_client
        filtered = self._filter_by_levels(matches, self.default_levels)
        probe = await debug_client.debug_probe(today)
        lines = [
            "VAL Debug",
            f"- 展示时区: {self.display_timezone}",
            f"- 当前插件时间: {self._now_in_display_timezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "- 当前数据源: vlr",
            f"- 最近一次实际使用数据源: {self.last_source_used or '(无)'}",
            f"- 当前 debug 数据源: {debug_client.source_name}",
            f"- 当前数据源类型: {self._resolve_source_type(used_client, used_client.last_request_info or probe)}",
            f"- 当前候选 API 数量: {self._candidate_count(debug_client)}",
            f"- 当前请求 URL: {probe.url or '(无)'}",
            f"- HTTP 状态码: {probe.status_code if probe.status_code is not None else 'N/A'}",
            f"- 返回内容前 300 字符: {probe.response_preview if probe.response_preview else '(空)'}",
            f"- 当前特别关心赛事: {', '.join(self.preferred_tournaments) if self.preferred_tournaments else '(无)'}",
            f"- 当前默认等级过滤: {', '.join(self.default_levels) if self.default_levels else '(无)'}",
            f"- 图片命令日期偏移: {', '.join(str(item) for item in self.image_day_offsets)}",
            f"- 今日缓存是否命中: {'是' if used_client.last_cache_hit else '否'}",
            f"- 定时推送是否启用: {'是' if self._safe_bool(self.config.get('enable_daily_push')) else '否'}",
            "- 特别关心开赛扫描: 整点触发",
            f"- 特别关心开赛状态轮询: 每 {self.special_start_poll_interval_seconds} 秒，赛前 {self.special_start_poll_lookahead_minutes} 分钟开始",
            f"- 特别关心整场赛果检查间隔: {self.special_result_check_interval_seconds} 秒",
            f"- 特别关心逐图赛果: {'开启' if self.special_map_report_enabled else '关闭'}"
            f"（{self.special_map_check_interval_seconds} 秒）",
            f"- push_targets 是否为空: {'是' if not self.push_targets else '否'}",
            f"- 最近一次成功 API: {used_client.last_success_api or '(无)'}",
            f"- 最近一次失败原因: {used_client.last_failure_reason or '(无)'}",
            f"- 当前解析出的比赛数量: {used_client.last_parsed_count}",
            f"- 过滤后比赛数量: {len(filtered)}",
        ]
        if isinstance(used_client, VlrClient):
            lines.append(
                f"- VLR 页面时区推断: {used_client.format_offset_label(used_client.last_page_display_offset)}"
            )
            lines.append(
                f"- VLR 详情时间来源: {used_client.last_detail_time_source or '(unknown)'}"
            )
        if probe.error:
            lines.append(f"- 请求错误: {probe.error}")
        yield event.plain_result("\n".join(lines))

    @val.command("monitor")
    async def val_monitor(self, event: AstrMessageEvent):
        """查看 AstrBot 内置赛事控制台入口。"""
        yield event.plain_result(
            "请打开 AstrBot Dashboard → 插件 → VAL Match → 赛事控制台。可查看赛事监控、竞猜、积分和设置。"
        )

    @property
    def default_levels(self) -> list[str]:
        levels = self._split_csv_text(self.config.get("default_levels"))
        return levels or ["S"]

    @property
    def preferred_tournaments(self) -> list[str]:
        raw = (
            self.config.get("special_tournaments")
            if "special_tournaments" in self.config
            else self.config.get("preferred_tournaments")
        )
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return self._split_csv_text(raw)

    @property
    def special_tournaments(self) -> list[str]:
        raw = self.config.get("special_tournaments")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return self._split_csv_text(raw)

    @property
    def special_push_targets(self) -> list[str]:
        raw = self.config.get("special_push_targets")
        targets = (
            [str(item).strip() for item in raw if str(item).strip()]
            if isinstance(raw, list)
            else self._split_csv_text(raw)
        )
        return self._normalize_push_targets(targets)

    @property
    def special_start_notice_enabled(self) -> bool:
        return self._safe_bool(
            self.config.get("special_start_notice_enabled"), default=True
        )

    @property
    def special_report_enabled(self) -> bool:
        return self._safe_bool(self.config.get("special_report_enabled"), default=True)

    @property
    def special_map_report_enabled(self) -> bool:
        return self._safe_bool(
            self.config.get("special_map_report_enabled"), default=True
        )

    @property
    def special_map_check_interval_seconds(self) -> int:
        return max(
            BaseMatchClient._safe_int(
                self.config.get("special_map_check_interval_seconds"), 60
            ),
            60,
        )

    @property
    def special_result_check_interval_seconds(self) -> int:
        return max(
            BaseMatchClient._safe_int(
                self.config.get("special_result_check_interval_seconds"), 1800
            ),
            300,
        )

    @property
    def special_active_result_check_interval_seconds(self) -> int:
        if self.special_map_report_enabled:
            return min(
                self.special_map_check_interval_seconds,
                self.special_result_check_interval_seconds,
            )
        return self.special_result_check_interval_seconds

    @property
    def special_start_poll_interval_seconds(self) -> int:
        return max(
            BaseMatchClient._safe_int(
                self.config.get("special_start_poll_interval_seconds"), 300
            ),
            60,
        )

    @property
    def special_start_poll_lookahead_minutes(self) -> int:
        return max(
            BaseMatchClient._safe_int(
                self.config.get("special_start_poll_lookahead_minutes"), 60
            ),
            1,
        )

    @property
    def special_match_window_minutes(self) -> int:
        return max(
            BaseMatchClient._safe_int(
                self.config.get("special_match_window_minutes"), 20
            ),
            1,
        )

    @property
    def enable_ai_match_comment(self) -> bool:
        return self._safe_bool(self.config.get("enable_ai_match_comment"), default=True)

    @property
    def image_theme(self) -> str:
        value = str(self.config.get("image_theme") or "premium_dark").strip().casefold()
        aliases = {
            "black": "dark",
            "night": "dark",
            "深色": "dark",
            "黑色": "dark",
            "white": "light",
            "day": "light",
            "浅色": "light",
            "白色": "light",
            "高级黑": "premium_dark",
            "noir": "premium_dark",
            "高级白": "premium_light",
            "editorial": "premium_light",
        }
        supported = {
            "studio_dark",
            "studio_light",
            "premium_dark",
            "premium_light",
            "dark",
            "light",
        }
        return aliases.get(value, value if value in supported else "premium_dark")

    @property
    def image_day_offsets(self) -> list[int]:
        raw = self._split_csv_text(self.config.get("image_day_offsets"))
        offsets: list[int] = []
        for item in raw or ["-1", "0", "1"]:
            with contextlib.suppress(ValueError):
                offsets.append(int(item))
        if not offsets:
            offsets = [-1, 0, 1]
        return sorted(dict.fromkeys(offsets))[:7]

    def _candidate_count(self, client: BaseMatchClient) -> int:
        if isinstance(client, VlrClient):
            return 5
        return 1

    def _display_source_name(self, client: BaseMatchClient) -> str:
        if isinstance(client, VlrClient):
            return "VLR.gg"
        return client.source_name

    def _resolve_source_type(
        self,
        client: BaseMatchClient,
        probe: RequestDebugInfo | None,
    ) -> str:
        if client.current_data_source_type:
            return client.current_data_source_type
        if isinstance(client, VlrClient):
            url = probe.url if probe else ""
            if url.startswith(client.api_url):
                return "VLR_API"
            if client.web_url in url:
                return "VLR_HTML"
            return "VLR_HTML"
        return client.source_name.upper()

    @property
    def push_targets(self) -> list[str]:
        return self._normalize_push_targets(
            self._split_csv_text(self.config.get("push_targets"))
        )

    def _normalize_push_targets(self, raw_targets: list[str]) -> list[str]:
        normalized: list[str] = []
        for target in raw_targets:
            if "GroupMessage" in target or "FriendMessage" in target:
                normalized.append(target)
                continue
            if target.count(":") == 1:
                platform_id, group_id = target.split(":", 1)
                platform_id = platform_id.strip()
                group_id = group_id.strip()
                if platform_id and group_id:
                    normalized.append(
                        str(
                            MessageSession(
                                platform_name=platform_id,
                                message_type=MessageType.GROUP_MESSAGE,
                                session_id=group_id,
                            )
                        )
                    )
                    continue
            logger.warning("astrbot_plugin_val_match: 无法识别 push target: %s", target)
        return normalized

    async def _query_matches(
        self, target_date: date
    ) -> tuple[list[MatchRecord], BaseMatchClient]:
        client = self.vlr_client
        matches = await client.get_matches_by_date(target_date)
        self.last_source_used = client.source_name
        return matches, client

    async def _render_for_date(
        self,
        target_date: date,
        explicit_levels: list[str] | None,
    ) -> str:
        try:
            matches, client = await self._query_matches(target_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 查询赛程失败: %s", exc)
            return f"查询 {target_date.isoformat()} 赛程失败：{exc}"

        levels = explicit_levels if explicit_levels is not None else self.default_levels
        filtered, filter_summary = self._apply_preferred_filters(
            matches, levels, explicit_levels is not None
        )
        client.last_filtered_count = len(filtered)
        message = self._format_message(target_date, filtered, filter_summary, client)
        if not filtered and target_date == self._today_in_display_timezone():
            original_source = self.last_source_used
            state_snapshot = self._snapshot_client_state(self.vlr_client)
            tomorrow_matches, _ = await self._query_matches(
                target_date + timedelta(days=1)
            )
            tomorrow_filtered, _ = self._apply_preferred_filters(
                tomorrow_matches,
                levels,
                explicit_levels is not None,
            )
            self.last_source_used = original_source
            self._restore_client_state(self.vlr_client, state_snapshot)
            if tomorrow_filtered:
                message += "\n今日暂无比赛，可使用 /val tomorrow 查看明日比赛。"
        return message

    def _format_message(
        self,
        target_date: date,
        matches: list[MatchRecord],
        filter_summary: str,
        client: BaseMatchClient,
    ) -> str:
        if not matches:
            suffix = f"（{filter_summary}）" if filter_summary else ""
            return (
                f"无畏契约赛程 | {target_date.isoformat()} {suffix}\n"
                f"数据源：{self._display_source_name(client)}\n"
                f"数据源类型：{self._resolve_source_type(client, client.last_request_info)}\n"
                "暂无可展示的比赛数据。\n"
                f"最近失败原因：{client.last_failure_reason or '未知原因'}"
            )

        limit = max(
            BaseMatchClient._safe_int(self.config.get("max_matches_per_message"), 20), 1
        )
        lines = [
            f"无畏契约赛程 | {target_date.isoformat()}",
            f"数据源：{self._display_source_name(client)}",
            f"数据源类型：{self._resolve_source_type(client, client.last_request_info)}",
        ]
        if filter_summary:
            lines.append(filter_summary)
        for index, match in enumerate(matches[:limit], start=1):
            title = match.tournament_name or "未知赛事"
            if match.schedule_name and match.schedule_name not in title:
                title = f"{title} / {match.schedule_name}"
            score = f" | 比分 {match.score}" if match.score != "-" else ""
            bo = match.best_of or "Bo?"
            lines.append(
                f"{index}. {match.start_time} | {match.team_a} vs {match.team_b} | {title} | {match.level or '-'} | {bo} | {match.status}{score}"
            )
        if len(matches) > limit:
            lines.append(f"……共 {len(matches)} 场，仅显示前 {limit} 场。")
        return "\n".join(lines)

    async def _restart_push_task(self) -> None:
        if self._push_task:
            self._push_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._push_task
            self._push_task = None

        if not self._safe_bool(self.config.get("enable_daily_push")):
            logger.info("astrbot_plugin_val_match: 每日推送未启用。")
            return
        if not self.push_targets:
            logger.warning(
                "astrbot_plugin_val_match: 未配置 push_targets，跳过启动定时推送。"
            )
            return

        self._push_task = asyncio.create_task(self._push_loop())
        logger.info("astrbot_plugin_val_match: 每日推送任务已启动。")

    def _daily_schedule_pending(self) -> list[str]:
        store = getattr(self, "prediction_store", None)
        day = self._today_in_display_timezone().isoformat()
        return [
            group
            for group in self.push_targets
            if not store or not store.delivered(day, "赛程完成", group)
        ]

    def _daily_schedule_due(self) -> bool:
        now = self._now_in_display_timezone()
        at = datetime.combine(
            now.date(),
            self._parse_push_time(self.config.get("push_time")),
            tzinfo=now.tzinfo,
        )
        return now >= at and bool(self._daily_schedule_pending())

    async def _push_loop(self) -> None:
        while True:
            try:
                if not self._daily_schedule_due():
                    await asyncio.sleep(self._seconds_until_next_push())
                await self._push_today_matches()
                if self._daily_schedule_due():
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("astrbot_plugin_val_match: 推送任务异常: %s", exc)
                await asyncio.sleep(60)

    async def _push_today_matches(self) -> None:
        today = self._today_in_display_timezone()
        targets = self._daily_schedule_pending()
        if not targets:
            return
        image_path = await self._render_daily_s_tier_image(today, skip_empty=True)
        if image_path is None:
            logger.info(
                "astrbot_plugin_val_match: 日期窗口内无符合关心条件的比赛，跳过赛程图。"
            )
            if hasattr(self, "prediction_store"):
                for target in targets:
                    await self._after_daily_schedule(target)
            return
        try:
            progress_path = await self._render_daily_progress_image(today)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "astrbot_plugin_val_match: 每日赛况图生成失败，仍推送赛程和竞猜: %s",
                exc,
            )
            progress_path = None
        for target in targets:
            sent, failed = await self._push_image_to_targets(
                image_path, targets=[target]
            )
            if not sent:
                continue
            if progress_path:
                await self._push_image_to_targets(progress_path, targets=[target])
            if hasattr(self, "prediction_store"):
                await self._after_daily_schedule(target)
        if not progress_path:
            logger.info("astrbot_plugin_val_match: 当前没有可推送的赛事阶段数据。")

    async def _restart_special_task(self) -> None:
        if self._special_task:
            self._special_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._special_task
            self._special_task = None

        if not self.special_tournaments:
            logger.info("astrbot_plugin_val_match: 未配置特别关心赛事。")
            self._record_special_timeline(
                "特别关心任务未启动", "未配置特别关心赛事", level="warn"
            )
            await self._write_monitor_dashboard()
            return
        if not self.special_push_targets:
            logger.warning(
                "astrbot_plugin_val_match: 未配置 special_push_targets，跳过特别关心推送。"
            )
            self._record_special_timeline(
                "特别关心任务未启动", "未配置 special_push_targets", level="warn"
            )
            await self._write_monitor_dashboard()
            return

        self._special_task = asyncio.create_task(self._special_watch_loop())
        self._record_special_timeline("特别关心任务启动", "后台扫描循环已创建")
        await self._write_monitor_dashboard()
        logger.info("astrbot_plugin_val_match: 特别关心赛事任务已启动。")

    async def _special_watch_loop(self) -> None:
        recovery_done = False
        while True:
            try:
                if not recovery_done:
                    await self._scan_special_matches(
                        scan_starts=True, scan_results=True, recovery=True
                    )
                    recovery_done = True
                sleep_seconds = self._seconds_until_next_special_scan()
                self._last_special_next_scan_at = (
                    self._now_in_display_timezone() + timedelta(seconds=sleep_seconds)
                )
                await self._write_monitor_dashboard()
                await asyncio.sleep(sleep_seconds)
                now = self._now_in_display_timezone()
                hourly_scan_due = self._is_special_start_scan_due(now)
                status_poll_due = self._is_special_start_status_poll_due(now)
                scan_starts = hourly_scan_due or status_poll_due
                scan_hour = self._special_hour_bucket(now) if hourly_scan_due else None
                await self._scan_special_matches(
                    scan_starts=scan_starts, scan_results=True
                )
                if scan_hour is not None:
                    self._last_special_start_scan_hour = scan_hour
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("astrbot_plugin_val_match: 特别关心任务异常: %s", exc)
                self._record_special_timeline(
                    "特别关心任务异常", str(exc), level="error"
                )
                await self._write_monitor_dashboard()
                await asyncio.sleep(60)

    def _seconds_until_next_special_scan(self) -> float:
        now = self._now_in_display_timezone()
        next_scan = self._next_special_start_scan_time(now)
        next_result_check = self._next_special_result_check_time(now)
        if next_result_check is not None and next_result_check < next_scan:
            next_scan = next_result_check
        return max((next_scan - now).total_seconds(), 1.0)

    def _next_special_start_scan_time(self, now: datetime) -> datetime:
        candidates: list[datetime] = []
        if self._is_special_start_scan_due(now):
            candidates.append(now)
        current_hour = self._special_hour_bucket(now)
        candidates.append(current_hour + timedelta(hours=1))
        next_status_poll = self._next_special_start_status_poll_time(now)
        if next_status_poll is not None:
            candidates.append(next_status_poll)
        return min(candidates)

    def _next_special_start_status_poll_time(self, now: datetime) -> datetime | None:
        pending: list[datetime] = []
        for state in self._special_state.values():
            if state.get("start_sent") or state.get("report_sent"):
                continue
            match = state.get("match")
            if not isinstance(match, MatchRecord) or match.status == "已结束":
                continue
            if not self._should_poll_match_start_status(match, now):
                continue
            next_check = state.get("next_start_check")
            if isinstance(next_check, datetime):
                pending.append(self._coerce_special_datetime(next_check, now))
            else:
                pending.append(now)
        return min(pending) if pending else None

    def _is_special_start_status_poll_due(self, now: datetime) -> bool:
        next_check = self._next_special_start_status_poll_time(now)
        return next_check is not None and now >= next_check

    def _next_special_result_check_time(self, now: datetime) -> datetime | None:
        pending: list[datetime] = []
        for state in self._special_state.values():
            if not self._special_state_needs_result_poll(state):
                continue
            next_check = state.get("next_result_check")
            if isinstance(next_check, datetime):
                pending.append(self._coerce_special_datetime(next_check, now))
            else:
                pending.append(now)
        return min(pending) if pending else None

    def _special_state_needs_result_poll(self, state: dict[str, Any]) -> bool:
        if not state.get("start_sent"):
            return False
        if not state.get("report_sent"):
            return True
        return self.special_map_report_enabled and not state.get("map_reports_complete")

    def _is_special_start_scan_due(self, now: datetime) -> bool:
        hour_bucket = self._special_hour_bucket(now)
        if self._last_special_start_scan_hour == hour_bucket:
            return False
        return (
            0
            <= (now - hour_bucket).total_seconds()
            <= self.special_match_window_minutes * 60
        )

    @staticmethod
    def _special_hour_bucket(value: datetime) -> datetime:
        return value.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _coerce_special_datetime(value: datetime, reference: datetime) -> datetime:
        if value.tzinfo is None and reference.tzinfo is not None:
            return value.replace(tzinfo=reference.tzinfo)
        if value.tzinfo is not None and reference.tzinfo is not None:
            return value.astimezone(reference.tzinfo)
        return value

    async def _scan_special_matches(
        self,
        *,
        scan_starts: bool = True,
        scan_results: bool = True,
        recovery: bool = False,
    ) -> None:
        if not self.special_tournaments or not self.special_push_targets:
            return
        scan_started_at = self._now_in_display_timezone()
        self._last_special_scan_started_at = scan_started_at
        self._record_special_timeline(
            "扫描开始",
            f"开赛扫描={'是' if scan_starts else '否'}，赛果扫描={'是' if scan_results else '否'}，恢复={'是' if recovery else '否'}",
        )
        today = self._today_in_display_timezone()
        candidates: list[MatchRecord] = []
        active_result_checks = any(
            self._special_state_needs_result_poll(state)
            for state in self._special_state.values()
        )
        offsets = (
            (-1, 0, 1)
            if scan_results and (active_result_checks or recovery)
            else (0, 1)
        )
        for offset in offsets:
            query_date = today + timedelta(days=offset)
            if scan_starts:
                self._invalidate_special_start_status_cache(query_date)
            matches, _ = await self._query_matches(query_date)
            candidates.extend(self._filter_by_special_tournaments(matches))

        now = self._now_in_display_timezone()
        starting: list[MatchRecord] = []
        start_polling_scheduled = 0
        result_checks_run = 0
        seen_keys: set[str] = set()
        for match in candidates:
            match_key = self._match_state_key(match)
            seen_keys.add(match_key)
            state = self._special_state.get(match_key)
            if state is None:
                state = {"created_at": now}
                self._special_state[match_key] = state
                self._record_special_timeline(
                    "创建比赛状态", self._match_timeline_label(match), match=match
                )
            state["match"] = match
            if (
                not state.get("start_sent")
                and match.status != "已结束"
                and self._should_poll_match_start_status(match, now)
            ):
                if not isinstance(state.get("next_start_check"), datetime):
                    self._record_special_timeline(
                        "进入开赛轮询", self._match_timeline_label(match), match=match
                    )
                    start_polling_scheduled += 1
                state["next_start_check"] = now + timedelta(
                    seconds=self.special_start_poll_interval_seconds
                )
            should_send_start_notice = not state.get("start_sent") and (
                match.status == "进行中"
                or (scan_starts and self._is_match_starting(match, now))
            )
            if (
                recovery
                and not state.get("start_sent")
                and self._should_recover_special_match(match, now)
                and not should_send_start_notice
            ):
                logger.info(
                    "astrbot_plugin_val_match: 恢复特别关心赛果轮询 %s %s vs %s。",
                    match_key,
                    match.team_a,
                    match.team_b,
                )
                state["start_sent"] = True
                state["next_result_check"] = now
                state.pop("next_start_check", None)
                self._record_special_timeline(
                    "恢复赛果轮询", self._match_timeline_label(match), match=match
                )
            if match.status == "已结束":
                next_check = state.get("next_result_check")
                result_check_due = not isinstance(
                    next_check, datetime
                ) or now >= self._coerce_special_datetime(next_check, now)
                if (
                    scan_results
                    and self._special_state_needs_result_poll(state)
                    and result_check_due
                ):
                    result_checks_run += 1
                    self._record_special_timeline(
                        "赛果检查", self._match_timeline_label(match), match=match
                    )
                    await self._check_special_match_result(match, state)
                    state["next_result_check"] = now + timedelta(
                        seconds=self.special_active_result_check_interval_seconds
                    )
                else:
                    if not state.get("start_sent"):
                        state["report_sent"] = True
                continue
            if should_send_start_notice and not state.get("start_sent"):
                starting.append(match)
                state["start_sent"] = True
                state["next_result_check"] = now
                state.pop("next_start_check", None)
                self._record_special_timeline(
                    "检测到开赛", self._match_timeline_label(match), match=match
                )

        if starting and self.special_start_notice_enabled:
            await self._send_special_start_notice(starting)
            self._record_special_timeline("发送开赛提醒", f"共 {len(starting)} 场")
        elif starting:
            self._record_special_timeline(
                "开赛提醒已跳过", "special_start_notice_enabled=false", level="warn"
            )

        if not scan_results:
            await self._finish_special_scan_monitor(
                candidates_count=len(candidates),
                starting_count=len(starting),
                start_polling_scheduled=start_polling_scheduled,
                result_checks_run=result_checks_run,
            )
            return
        for match in candidates:
            match_key = self._match_state_key(match)
            state = self._special_state.setdefault(match_key, {})
            next_check = state.get("next_result_check")
            if self._special_state_needs_result_poll(state) and (
                not isinstance(next_check, datetime) or now >= next_check
            ):
                result_checks_run += 1
                self._record_special_timeline(
                    "赛果检查", self._match_timeline_label(match), match=match
                )
                await self._check_special_match_result(match, state)
                state["next_result_check"] = now + timedelta(
                    seconds=self.special_active_result_check_interval_seconds
                )

        for match_key, state in self._special_state.items():
            if match_key in seen_keys or not self._special_state_needs_result_poll(
                state
            ):
                continue
            next_check = state.get("next_result_check")
            if isinstance(next_check, datetime) and now < self._coerce_special_datetime(
                next_check, now
            ):
                continue
            stored_match = state.get("match")
            if isinstance(stored_match, MatchRecord):
                result_checks_run += 1
                self._record_special_timeline(
                    "赛果检查",
                    self._match_timeline_label(stored_match),
                    match=stored_match,
                )
                await self._check_special_match_result(stored_match, state)
            state["next_result_check"] = now + timedelta(
                seconds=self.special_active_result_check_interval_seconds
            )
        await self._finish_special_scan_monitor(
            candidates_count=len(candidates),
            starting_count=len(starting),
            start_polling_scheduled=start_polling_scheduled,
            result_checks_run=result_checks_run,
        )

    def _invalidate_special_start_status_cache(self, target_date: date) -> None:
        invalidate = getattr(self.vlr_client, "invalidate_matches_cache", None)
        if callable(invalidate):
            invalidate(target_date, include_schedule_pages=True)

    async def _finish_special_scan_monitor(
        self,
        *,
        candidates_count: int,
        starting_count: int,
        start_polling_scheduled: int,
        result_checks_run: int,
    ) -> None:
        self._last_special_scan_finished_at = self._now_in_display_timezone()
        self._last_special_scan_summary = {
            "candidates_count": candidates_count,
            "starting_count": starting_count,
            "start_polling_scheduled": start_polling_scheduled,
            "result_checks_run": result_checks_run,
        }
        self._record_special_timeline(
            "扫描结束",
            f"候选 {candidates_count} 场，开赛提醒 {starting_count} 场，新增盯盘 {start_polling_scheduled} 场，赛果检查 {result_checks_run} 次",
        )
        try:
            await self._write_monitor_dashboard()
        except Exception as exc:  # noqa: BLE001
            logger.debug("astrbot_plugin_val_match: 写入监控面板失败: %s", exc)

    def _record_special_timeline(
        self,
        action: str,
        detail: str = "",
        *,
        match: MatchRecord | None = None,
        level: str = "info",
    ) -> None:
        now = self._now_in_display_timezone()
        self._special_timeline.append(
            {
                "time": now.isoformat(timespec="seconds"),
                "action": str(action or ""),
                "detail": str(detail or ""),
                "level": level,
                "match_id": match.match_id if match else "",
                "match": self._match_timeline_label(match) if match else "",
            }
        )
        if len(self._special_timeline) > 200:
            self._special_timeline = self._special_timeline[-200:]

    @staticmethod
    def _match_timeline_label(match: MatchRecord | None) -> str:
        if match is None:
            return ""
        title = match.tournament_name or "未知赛事"
        return f"{match.match_date} {match.start_time} | {match.team_a} vs {match.team_b} | {title} | {match.status}"

    def _should_recover_special_match(self, match: MatchRecord, now: datetime) -> bool:
        if match.status == "进行中":
            return True
        if match.status != "已结束":
            return False
        start_dt = self._match_start_datetime(match)
        if start_dt is None:
            return False
        start_dt = self._coerce_special_datetime(start_dt, now)
        recovery_window_seconds = max(
            self.special_result_check_interval_seconds * 4, 12 * 3600
        )
        return 0 <= (now - start_dt).total_seconds() <= recovery_window_seconds

    async def _check_special_match_result(
        self, match: MatchRecord, state: dict[str, Any]
    ) -> None:
        target_date = self._parse_match_date(match)
        if target_date is None:
            target_date = self._today_in_display_timezone()
        matches, _ = await self._query_matches(target_date)
        latest = self._find_same_match(match, matches) or match
        report: MatchReport | None = None
        if self.special_map_report_enabled:
            report = await self._fetch_match_report(latest, force_refresh=True)
            if report is not None:
                try:
                    await self._maybe_send_special_map_reports(latest, state, report)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "astrbot_plugin_val_match: 逐图赛果处理失败，将保留轮询重试: %s",
                        exc,
                    )
                    self._record_special_timeline(
                        "逐图赛果重试", str(exc), match=latest, level="warn"
                    )
            if latest.status == "已结束":
                state["map_reports_complete"] = self._all_special_map_reports_sent(
                    report, state
                )
        if latest.status == "已结束":
            if self.special_report_enabled:
                await self._maybe_send_special_report(latest, state, report=report)
            else:
                state["report_sent"] = True

    async def _maybe_send_special_report(
        self,
        match: MatchRecord,
        state: dict[str, Any],
        *,
        report: MatchReport | None = None,
    ) -> None:
        if state.get("report_complete") or not self.special_report_enabled:
            return
        report = report or await self._fetch_match_report(match, force_refresh=True)
        if report is None:
            state["next_result_check"] = self._now_in_display_timezone() + timedelta(
                seconds=self.special_result_check_interval_seconds
            )
            self._record_special_timeline(
                "战报等待",
                f"{self._match_timeline_label(match)}：详情暂不可用",
                match=match,
            )
            return
        if not self._report_has_player_stats(report):
            now = self._now_in_display_timezone()
            state.setdefault("report_stats_missing_since", now)
            state["next_result_check"] = now + timedelta(
                seconds=self.special_result_check_interval_seconds
            )
            logger.info(
                "astrbot_plugin_val_match: %s 战报选手统计暂缺，等待下一轮检查。",
                self._match_state_key(match),
            )
            self._record_special_timeline(
                "战报等待",
                f"{self._match_timeline_label(match)}：选手统计暂缺",
                match=match,
            )
            return
        if self.special_map_report_enabled and not state.get("map_reports_complete"):
            now = self._now_in_display_timezone()
            state["next_result_check"] = now + timedelta(
                seconds=self.special_active_result_check_interval_seconds
            )
            self._record_special_timeline(
                "战报等待",
                f"{self._match_timeline_label(match)}：等待全部逐图赛果先发送",
                match=match,
            )
            return
        state.pop("report_stats_missing_since", None)
        image_path = await self._render_match_report_image_from_report(match, report)
        title = f"赛后战报：{match.team_a} {match.score} {match.team_b}"
        success_count = 0
        for target in self.special_push_targets:
            try:
                await self.context.send_message(
                    target, MessageChain().message(title).file_image(image_path)
                )
                success_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_val_match: 特别关心战报推送失败 %s: %s", target, exc
                )
        if success_count:
            state["report_sent"] = True
            state["report_complete"] = True
            self._record_special_timeline(
                "发送赛后战报", self._match_timeline_label(match), match=match
            )
        else:
            self._record_special_timeline(
                "战报重试",
                f"{self._match_timeline_label(match)}：所有推送目标均发送失败",
                match=match,
                level="warn",
            )

    async def _maybe_send_special_map_reports(
        self,
        match: MatchRecord,
        state: dict[str, Any],
        report: MatchReport,
    ) -> None:
        sent_ids = set(state.get("map_reports_sent") or [])
        for map_index, map_score in enumerate(report.maps, start=1):
            if not self._is_completed_report_map(map_score):
                continue
            map_id = self._special_map_report_id(map_score, map_index)
            if map_id in sent_ids:
                continue
            image_path = await self._render_single_map_result_image(
                report, map_score, map_index
            )
            title = (
                f"第 {map_index} 图赛果 · {map_score.map_name}："
                f"{report.team_a} {map_score.team_a_score}:{map_score.team_b_score} {report.team_b}"
            )
            success_count = 0
            for target in self.special_push_targets:
                try:
                    await self.context.send_message(
                        target, MessageChain().message(title).file_image(image_path)
                    )
                    success_count += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "astrbot_plugin_val_match: 特别关心逐图赛果推送失败 %s: %s",
                        target,
                        exc,
                    )
            if success_count:
                sent_ids.add(map_id)
                state["map_reports_sent"] = sorted(sent_ids)
                state["last_map_report_at"] = self._now_in_display_timezone()
                state["last_map_report_label"] = (
                    f"第 {map_index} 图 {map_score.map_name}"
                )
                self._record_special_timeline(
                    "发送逐图赛果",
                    f"{self._match_timeline_label(match)}：第 {map_index} 图 {map_score.map_name}",
                    match=match,
                )

    def _is_completed_report_map(self, map_score: MapScore) -> bool:
        return self.vlr_client.is_completed_report_map(map_score)

    @staticmethod
    def _special_map_report_id(map_score: MapScore, map_index: int) -> str:
        return map_score.game_id or (
            f"{map_index}:{map_score.map_name}:{map_score.team_a_score}:{map_score.team_b_score}"
        )

    def _all_special_map_reports_sent(
        self,
        report: MatchReport | None,
        state: dict[str, Any],
    ) -> bool:
        if report is None:
            return False
        played_maps = [
            (index, map_score)
            for index, map_score in enumerate(report.maps, start=1)
            if str(map_score.team_a_score).isdigit()
            or str(map_score.team_b_score).isdigit()
        ]
        if not played_maps or not all(
            self._is_completed_report_map(item) for _, item in played_maps
        ):
            return False
        sent_ids = set(state.get("map_reports_sent") or [])
        expected_ids = {
            self._special_map_report_id(item, index) for index, item in played_maps
        }
        return expected_ids.issubset(sent_ids)

    async def _send_special_start_notice(self, matches: list[MatchRecord]) -> None:
        lines = ["特别关心赛事开赛提醒"]
        sorted_matches = sorted(
            matches,
            key=lambda item: (item.match_date, item.start_time, item.tournament_name),
        )
        for match in sorted_matches:
            title = match.tournament_name or "未知赛事"
            if match.schedule_name and match.schedule_name not in title:
                title = f"{title} / {match.schedule_name}"
            lines.append(
                f"- {match.start_time} | {match.team_a} vs {match.team_b} | {title} | {match.best_of or 'Bo?'}"
            )
        message = "\n".join(lines)
        image_paths = await asyncio.gather(
            *(self._render_start_notice_image(match) for match in sorted_matches),
            return_exceptions=True,
        )
        valid_images: list[str] = []
        for item in image_paths:
            if isinstance(item, Exception):
                logger.warning("astrbot_plugin_val_match: 开赛提醒图生成失败: %s", item)
                continue
            valid_images.append(item)
        for target in self.special_push_targets:
            try:
                chain = MessageChain().message(message)
                for image_path in valid_images:
                    chain.file_image(image_path)
                await self.context.send_message(target, chain)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_val_match: 特别关心开赛提醒推送失败 %s: %s",
                    target,
                    exc,
                )

    async def _render_start_notice_image(self, match: MatchRecord) -> str:
        preview = await self._fetch_match_preview(match)
        if preview is None:
            preview = MatchPreview(
                match_id=match.match_id,
                href="",
                team_a=match.team_a,
                team_b=match.team_b,
                tournament_name=match.tournament_name,
                schedule_name=match.schedule_name,
                best_of=match.best_of,
                start_time=match.start_time,
                betting_info="",
                head_to_head=[],
            )
        render_notice = await self._build_render_start_notice(preview)
        notice_key = self._safe_filename(match.match_id) or self._safe_filename(
            f"{match.team_a}_{match.team_b}"
        )
        output_path = self.rendered_dir / f"val_start_{notice_key}.png"
        return await asyncio.to_thread(
            render_start_notice_image,
            render_notice,
            output_path,
            source_name="VLR.gg",
            theme=self.image_theme,
        )

    async def _fetch_match_preview(self, match: MatchRecord) -> MatchPreview | None:
        return await self.vlr_client.get_match_preview(match)

    async def _build_render_start_notice(
        self, preview: MatchPreview
    ) -> RenderStartNotice:
        team_a_logo, team_b_logo, event_logo = await asyncio.gather(
            self._cache_image(preview.team_a_logo_url, "teams", preview.team_a),
            self._cache_image(preview.team_b_logo_url, "teams", preview.team_b),
            self._cache_image(
                preview.event_logo_url, "events", preview.tournament_name
            ),
        )
        head_to_head = [
            RenderHeadToHead(
                date_label=item.date_label,
                score=item.score,
                event_name=item.event_name,
            )
            for item in list(preview.head_to_head or [])[:3]
        ]
        betting_info = preview.betting_info or "暂无 betting / 预测信息"
        return RenderStartNotice(
            start_time=preview.start_time,
            team_a=preview.team_a,
            team_b=preview.team_b,
            tournament_name=preview.tournament_name,
            schedule_name=preview.schedule_name,
            best_of=preview.best_of,
            betting_info=betting_info,
            head_to_head=head_to_head,
            team_a_odds=preview.team_a_odds,
            team_b_odds=preview.team_b_odds,
            team_a_logo_path=team_a_logo,
            team_b_logo_path=team_b_logo,
            event_logo_path=event_logo,
        )

    def _filter_by_special_tournaments(
        self, matches: list[MatchRecord]
    ) -> list[MatchRecord]:
        preferred = self.special_tournaments
        if not preferred:
            return []
        normalized = {item.casefold() for item in preferred}
        return [
            match
            for match in matches
            if str(match.tournament_name or "").strip().casefold() in normalized
        ]

    def _is_match_starting(self, match: MatchRecord, now: datetime) -> bool:
        if match.status == "进行中":
            return True
        start_dt = self._match_start_datetime(match)
        if start_dt is None:
            return False
        delta_seconds = (now - start_dt).total_seconds()
        return -60 <= delta_seconds <= self.special_match_window_minutes * 60

    def _should_poll_match_start_status(
        self, match: MatchRecord, now: datetime
    ) -> bool:
        if match.status == "进行中":
            return True
        start_dt = self._match_start_datetime(match)
        if start_dt is None:
            return False
        start_dt = self._coerce_special_datetime(start_dt, now)
        early_seconds = self.special_start_poll_lookahead_minutes * 60
        late_seconds = max(6 * 3600, self.special_result_check_interval_seconds * 4)
        return -early_seconds <= (now - start_dt).total_seconds() <= late_seconds

    def _match_start_datetime(self, match: MatchRecord) -> datetime | None:
        match_date = self._parse_match_date(match)
        if match_date is None:
            return None
        parsed_time = self._parse_time_text(match.start_time)
        if parsed_time is None:
            return None
        return datetime.combine(match_date, parsed_time, tzinfo=self._get_display_tz())

    @staticmethod
    def _parse_time_text(value: str) -> time | None:
        for parser in ("%H:%M", "%H:%M:%S"):
            with contextlib.suppress(ValueError):
                return datetime.strptime(str(value or "").strip(), parser).time()
        return None

    @staticmethod
    def _parse_match_date(match: MatchRecord) -> date | None:
        with contextlib.suppress(ValueError):
            return date.fromisoformat(match.match_date)
        return None

    @staticmethod
    def _match_state_key(match: MatchRecord) -> str:
        if match.match_id:
            return str(match.match_id)
        return f"{match.match_date}:{match.start_time}:{match.team_a}:{match.team_b}:{match.tournament_name}"

    def _find_same_match(
        self, needle: MatchRecord, matches: list[MatchRecord]
    ) -> MatchRecord | None:
        needle_key = self._match_state_key(needle)
        for match in matches:
            if self._match_state_key(match) == needle_key:
                return match
        for match in matches:
            same_teams = {match.team_a.casefold(), match.team_b.casefold()} == {
                needle.team_a.casefold(),
                needle.team_b.casefold(),
            }
            if (
                same_teams
                and match.tournament_name.casefold()
                == needle.tournament_name.casefold()
            ):
                return match
        return None

    async def _push_message_to_targets(self, message: str) -> tuple[int, int]:
        sent = 0
        failed = 0
        for target in self.push_targets:
            try:
                ok = await self.context.send_message(
                    target, MessageChain().message(message)
                )
                if not ok:
                    logger.warning(
                        "astrbot_plugin_val_match: 推送失败，未找到目标平台: %s", target
                    )
                    failed += 1
                    continue
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_val_match: 向 %s 推送失败: %s", target, exc
                )
                failed += 1
        return sent, failed

    async def _push_image_to_targets(
        self, image_path: str, *, targets: list[str] | None = None
    ) -> tuple[int, int]:
        sent = 0
        failed = 0
        for target in self.push_targets if targets is None else targets:
            try:
                ok = await self.context.send_message(
                    target, MessageChain().file_image(image_path)
                )
                if ok:
                    sent += 1
                    continue
                logger.warning(
                    "astrbot_plugin_val_match: 图片推送失败，尝试文本回退: %s", target
                )
                fallback_message = await self._render_for_date(
                    self._today_in_display_timezone(), None
                )
                fallback_ok = await self.context.send_message(
                    target, MessageChain().message(fallback_message)
                )
                if fallback_ok:
                    sent += 1
                else:
                    failed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_val_match: 向 %s 推送图片失败: %s", target, exc
                )
                try:
                    fallback_message = await self._render_for_date(
                        self._today_in_display_timezone(), None
                    )
                    fallback_ok = await self.context.send_message(
                        target, MessageChain().message(fallback_message)
                    )
                    if fallback_ok:
                        sent += 1
                    else:
                        failed += 1
                except Exception as fallback_exc:  # noqa: BLE001
                    logger.warning(
                        "astrbot_plugin_val_match: 向 %s 文本回退也失败: %s",
                        target,
                        fallback_exc,
                    )
                    failed += 1
        return sent, failed

    def _seconds_until_next_push(self) -> float:
        tz = self._get_display_tz()
        now = datetime.now(tz)
        configured = self._parse_push_time(self.config.get("push_time"))
        next_run = datetime.combine(now.date(), configured, tzinfo=tz)
        if next_run <= now:
            next_run += timedelta(days=1)
        return max((next_run - now).total_seconds(), 1.0)

    @staticmethod
    def _parse_push_time(value: Any) -> time:
        raw = str(value or "09:00").strip()
        with contextlib.suppress(ValueError):
            return datetime.strptime(raw, "%H:%M").time()
        logger.warning(
            "astrbot_plugin_val_match: push_time=%s 不合法，回退到 09:00。", raw
        )
        return time(hour=9, minute=0)

    @staticmethod
    def _filter_by_levels(
        matches: list[MatchRecord], levels: list[str]
    ) -> list[MatchRecord]:
        if not levels:
            return matches
        normalized_levels = {
            ValMatchPlugin._normalize_level(level) for level in levels if level
        }
        filtered: list[MatchRecord] = []
        for match in matches:
            match_level = ValMatchPlugin._normalize_level(match.level)
            if match_level and match_level in normalized_levels:
                filtered.append(match)
        return filtered

    @staticmethod
    def _split_csv_text(value: Any) -> list[str]:
        if value is None:
            return []
        text = (
            str(value)
            .replace("\n", ",")
            .replace("，", ",")
            .replace("；", ",")
            .replace(";", ",")
        )
        items = [item.strip() for item in text.split(",")]
        return [item for item in items if item]

    def _save_config_value(self, key: str, value: Any) -> None:
        if key in {"push_targets", "special_push_targets"} and isinstance(value, list):
            value = "\n".join(value)
        self.config[key] = value
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()

    def _add_configured_text_item(self, key: str, value: str) -> bool:
        current = self._config_text_list(key)
        text = str(value or "").strip()
        if not text:
            return False
        if any(item.casefold() == text.casefold() for item in current):
            return False
        current.append(text)
        self._save_config_value(key, current)
        return True

    def _remove_configured_text_item(self, key: str, selector: str) -> tuple[str, int]:
        current = self._config_text_list(key)
        if not current:
            return "", 0
        target = str(selector or "").strip()
        if not target:
            return "", len(current)
        remove_index: int | None = None
        with contextlib.suppress(ValueError):
            index = int(target)
            if 1 <= index <= len(current):
                remove_index = index - 1
        if remove_index is None:
            lowered = target.casefold()
            exact = [
                idx for idx, item in enumerate(current) if item.casefold() == lowered
            ]
            partial = [
                idx for idx, item in enumerate(current) if lowered in item.casefold()
            ]
            candidates = exact or partial
            if len(candidates) == 1:
                remove_index = candidates[0]
            elif len(candidates) > 1:
                return "", len(current)
        if remove_index is None:
            return "", len(current)
        removed = current.pop(remove_index)
        self._save_config_value(key, current)
        return removed, len(current)

    def _config_text_list(self, key: str) -> list[str]:
        raw = self.config.get(key)
        if isinstance(raw, list):
            return self._dedupe_text_items(raw)
        return self._dedupe_text_items(self._split_csv_text(raw))

    @staticmethod
    def _format_numbered_list(title: str, items: list[str]) -> str:
        if not items:
            return f"{title}：(无)"
        lines = [f"{title}："]
        lines.extend(f"{index}. {item}" for index, item in enumerate(items, start=1))
        return "\n".join(lines)

    @staticmethod
    def _normalize_level(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return text.replace("级", "").replace(" ", "")

    def _filter_by_preferred_tournaments(
        self, matches: list[MatchRecord]
    ) -> list[MatchRecord]:
        preferred = self.preferred_tournaments
        if not preferred:
            return matches
        normalized = {item.casefold() for item in preferred}
        return [
            match
            for match in matches
            if str(match.tournament_name or "").strip().casefold() in normalized
        ]

    def _apply_preferred_filters(
        self,
        matches: list[MatchRecord],
        levels: list[str],
        explicit_level_filter: bool,
    ) -> tuple[list[MatchRecord], str]:
        preferred = self.preferred_tournaments
        if preferred:
            filtered = self._filter_by_preferred_tournaments(matches)
            if explicit_level_filter and levels:
                filtered = self._filter_by_levels(filtered, levels)
                return (
                    filtered,
                    f"特别关心赛事: {', '.join(preferred)} | 等级过滤: {', '.join(levels)}",
                )
            return filtered, f"特别关心赛事: {', '.join(preferred)}"
        if levels:
            return self._filter_by_levels(
                matches, levels
            ), f"等级过滤: {', '.join(levels)}"
        return matches, ""

    async def _render_daily_s_tier_image(
        self, target_date: date, *, skip_empty: bool = False
    ) -> str | None:
        eyebrow_text = "VALORANT S-TIER"
        title_text = "多日 S 级赛事"
        preferred = self.preferred_tournaments
        if preferred:
            eyebrow_text = "VALORANT WATCHLIST"
            title_text = "多日特别关心赛事"

        render_matches: list[RenderMatch] = []
        has_matches = False
        source_names: list[str] = []
        for offset in self.image_day_offsets:
            query_date = target_date + timedelta(days=offset)
            matches, client = await self._query_matches(query_date)
            source_name = self._display_source_name(client)
            if source_name not in source_names:
                source_names.append(source_name)
            if preferred:
                filtered = self._filter_by_preferred_tournaments(matches)
            else:
                filtered = self._filter_by_levels(matches, ["S"])
            await self._prepare_visual_matches(filtered, client)
            if filtered:
                has_matches = True
                render_matches.extend(
                    await self._build_render_matches(filtered, query_date)
                )
            else:
                render_matches.append(
                    RenderMatch(
                        day_label=self._format_render_day_label(query_date),
                        start_time="--:--",
                        status="空白",
                        score="-",
                        team_a="",
                        team_b="",
                        tournament_name="",
                        schedule_name="",
                        level="",
                        best_of="",
                        is_placeholder=True,
                        placeholder_text="此日无关注比赛",
                    )
                )

        if skip_empty and not has_matches:
            return None
        suffix = "_".join(str(offset) for offset in self.image_day_offsets)
        output_path = (
            self.rendered_dir / f"val_s_{target_date.isoformat()}_{suffix}.png"
        )
        return await asyncio.to_thread(
            render_match_cards_image,
            render_matches,
            target_date,
            output_path,
            source_name=" / ".join(source_names) if source_names else "VLR.gg",
            eyebrow_text=eyebrow_text,
            title_text=title_text,
            theme=self.image_theme,
        )

    async def _render_daily_progress_image(
        self,
        target_date: date,
        *,
        respect_enabled: bool = True,
    ) -> str | None:
        if respect_enabled and not self._safe_bool(
            self.config.get("daily_progress_enabled"), default=True
        ):
            return None
        candidates: list[tuple[int, MatchRecord]] = []
        preferred = self.preferred_tournaments
        offsets = list(dict.fromkeys([0, *self.image_day_offsets, -2, 2, -3, 3]))
        for offset in offsets:
            query_date = target_date + timedelta(days=offset)
            matches, _ = await self._query_matches(query_date)
            filtered = (
                self._filter_by_preferred_tournaments(matches)
                if preferred
                else self._filter_by_levels(matches, ["S"])
            )
            candidates.extend((offset, match) for match in filtered)
        if not candidates:
            return None

        preferred_order = {
            name.casefold(): index for index, name in enumerate(preferred)
        }

        def candidate_key(item: tuple[int, MatchRecord]) -> tuple[int, int, int, str]:
            offset, match = item
            preferred_index = len(preferred_order)
            tournament_key = match.tournament_name.casefold()
            for name, index in preferred_order.items():
                if name in tournament_key or tournament_key in name:
                    preferred_index = index
                    break
            return (
                preferred_index,
                abs(offset),
                0 if offset >= 0 else 1,
                match.start_time,
            )

        candidates.sort(key=candidate_key)
        seen: set[str] = set()
        for _, match in candidates:
            raw = match.raw if isinstance(match.raw, dict) else {}
            key = str(raw.get("event_href") or match.tournament_name).casefold()
            if key in seen:
                continue
            seen.add(key)
            try:
                progress = await self.vlr_client.get_tournament_progress(match)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_val_match: 获取赛事阶段数据失败 %s: %s",
                    match.tournament_name,
                    exc,
                )
                continue
            if progress is None:
                continue
            render_progress = await self._build_render_tournament_progress(progress)
            identity = hashlib.sha1(progress.source_url.encode("utf-8")).hexdigest()[
                :10
            ]
            output_path = self.rendered_dir / (
                f"val_progress_{target_date.isoformat()}_{identity}_{self.image_theme}.png"
            )
            return await asyncio.to_thread(
                render_tournament_progress_image,
                render_progress,
                output_path,
                source_name="VLR.gg",
                theme=self.image_theme,
            )
        return None

    async def _build_render_tournament_progress(
        self,
        progress: TournamentProgress,
    ) -> RenderTournamentProgress:
        event_logo_task = asyncio.create_task(
            self._cache_image(progress.event_logo_url, "events", progress.event_name)
        )
        groups: list[RenderStandingGroup] = []
        for group in progress.groups or []:
            logo_tasks = [
                asyncio.create_task(self._cache_image(row.logo_url, "teams", row.team))
                for row in group.rows
            ]
            logo_paths = await asyncio.gather(*logo_tasks) if logo_tasks else []
            groups.append(
                RenderStandingGroup(
                    name=group.name,
                    rows=[
                        RenderStandingRow(
                            team=row.team,
                            record=row.record,
                            maps=row.maps,
                            rounds=row.rounds,
                            round_diff=row.round_diff,
                            logo_path=logo_paths[index],
                            position_state=row.position_state,
                        )
                        for index, row in enumerate(group.rows)
                    ],
                )
            )

        brackets: list[RenderBracketSection] = []
        for section in progress.brackets or []:
            render_rounds: list[RenderBracketRound] = []
            for round_item in section.rounds:
                tasks: list[asyncio.Task[str | None]] = []
                for match in round_item.matches:
                    tasks.append(
                        asyncio.create_task(
                            self._cache_image(match.logo_a_url, "teams", match.team_a)
                        )
                    )
                    tasks.append(
                        asyncio.create_task(
                            self._cache_image(match.logo_b_url, "teams", match.team_b)
                        )
                    )
                paths = await asyncio.gather(*tasks) if tasks else []
                render_rounds.append(
                    RenderBracketRound(
                        name=round_item.name,
                        matches=[
                            RenderBracketMatch(
                                team_a=match.team_a,
                                team_b=match.team_b,
                                score_a=match.score_a,
                                score_b=match.score_b,
                                logo_a_path=paths[index * 2],
                                logo_b_path=paths[index * 2 + 1],
                                winner=match.winner,
                                status=match.status,
                            )
                            for index, match in enumerate(round_item.matches)
                        ],
                    )
                )
            brackets.append(
                RenderBracketSection(name=section.name, rounds=render_rounds)
            )

        return RenderTournamentProgress(
            event_name=progress.event_name,
            stage_name=progress.stage_name,
            kind=progress.kind,
            groups=groups,
            brackets=brackets,
            event_logo_path=await event_logo_task,
        )

    async def _render_match_report_image(self, match: MatchRecord) -> str:
        report = await self._fetch_match_report(match, force_refresh=True)
        if report is None:
            raise ValueError("VLR 详情页暂时没有可用战报数据。")
        return await self._render_match_report_image_from_report(match, report)

    async def _render_match_report_image_from_report(
        self, match: MatchRecord, report: MatchReport
    ) -> str:
        for player in report.players:
            cached_avatar = self._find_cached_image_path("players", player.player)
            if cached_avatar:
                player.avatar_url = cached_avatar
        missing_avatar_players = [
            player for player in report.players if not player.avatar_url
        ]
        if missing_avatar_players:
            await self.vlr_client.enrich_player_avatars(missing_avatar_players)
        comment = await self._build_match_comment(report)
        render_report = await self._build_render_report(report, comment)
        report_key = self._safe_filename(match.match_id) or self._safe_filename(
            f"{match.team_a}_{match.team_b}"
        )
        output_path = self.rendered_dir / f"val_report_{report_key}.png"
        return await asyncio.to_thread(
            render_match_report_image,
            render_report,
            output_path,
            source_name="VLR.gg",
            theme=self.image_theme,
        )

    async def _fetch_match_report(
        self, match: MatchRecord, *, force_refresh: bool = False
    ) -> MatchReport | None:
        return await self.vlr_client.get_match_report(
            match, enrich_players=False, force_refresh=force_refresh
        )

    def _report_has_player_stats(self, report: MatchReport) -> bool:
        return self.vlr_client.has_complete_player_stats(report.players)

    async def _build_render_report(
        self, report: MatchReport, comment: str
    ) -> RenderMatchReport:
        team_a_logo, team_b_logo, event_logo = await asyncio.gather(
            self._cache_image(report.team_a_logo_url, "teams", report.team_a),
            self._cache_image(report.team_b_logo_url, "teams", report.team_b),
            self._cache_image(report.event_logo_url, "events", report.tournament_name),
        )
        map_images = await asyncio.gather(
            *(
                self._cache_image(item.image_url, "maps", item.map_name)
                for item in report.maps
            )
        )
        player_avatar_paths = await asyncio.gather(
            *(
                self._cache_image(item.avatar_url, "players", item.player)
                for item in report.players
            )
        )
        country_flag_paths = await asyncio.gather(
            *(
                self._cache_image(
                    self._country_flag_url(item.country_code),
                    "flags",
                    item.country_code,
                )
                for item in report.players
            )
        )
        agent_image_paths_by_player = await asyncio.gather(
            *(
                asyncio.gather(
                    *(
                        self._cache_image(url, "agents", agent)
                        for agent, url in zip(item.agents, item.agent_image_urls or [])
                    )
                )
                for item in report.players
            )
        )
        return RenderMatchReport(
            team_a=report.team_a,
            team_b=report.team_b,
            score=report.score,
            tournament_name=report.tournament_name,
            schedule_name=report.schedule_name,
            best_of=report.best_of,
            maps=[
                RenderMapScore(
                    map_name=item.map_name,
                    team_a_score=item.team_a_score,
                    team_b_score=item.team_b_score,
                    duration=item.duration,
                    pick=item.pick,
                    image_path=map_images[index],
                )
                for index, item in enumerate(report.maps)
            ],
            players=[
                RenderPlayerStat(
                    player=item.player,
                    team=item.team,
                    agents=item.agents,
                    kills=item.kills,
                    deaths=item.deaths,
                    assists=item.assists,
                    acs=item.acs,
                    adr=item.adr,
                    rating=item.rating,
                    country_code=item.country_code,
                    country_name=item.country_name,
                    country_flag_path=country_flag_paths[index],
                    avatar_path=player_avatar_paths[index],
                    agent_image_paths=[
                        path for path in agent_image_paths_by_player[index] if path
                    ],
                    kast=item.kast,
                    headshot_percent=item.headshot_percent,
                    first_kills=item.first_kills,
                    first_deaths=item.first_deaths,
                    kd_diff=item.kd_diff,
                    fk_diff=item.fk_diff,
                    stats_available=item.stats_available,
                )
                for index, item in enumerate(report.players)
            ],
            comment=comment,
            team_a_logo_path=team_a_logo,
            team_b_logo_path=team_b_logo,
            event_logo_path=event_logo,
        )

    async def _render_single_map_result_image(
        self,
        report: MatchReport,
        map_score: MapScore,
        map_index: int,
    ) -> str:
        players = list(map_score.players or [])
        await self._ensure_agent_portrait_urls()
        team_a_logo, team_b_logo, event_logo, map_image = await asyncio.gather(
            self._cache_image(report.team_a_logo_url, "teams", report.team_a),
            self._cache_image(report.team_b_logo_url, "teams", report.team_b),
            self._cache_image(report.event_logo_url, "events", report.tournament_name),
            self._cache_image(map_score.image_url, "maps", map_score.map_name),
        )
        agent_paths_by_player = await asyncio.gather(
            *(
                asyncio.gather(
                    *(
                        self._cache_image(url, "agents", agent)
                        for agent, url in zip(
                            player.agents, player.agent_image_urls or []
                        )
                    )
                )
                for player in players
            )
        )
        portrait_paths = await asyncio.gather(
            *(
                self._cache_image(
                    self._agent_portrait_urls.get(
                        self._normalize_agent_name((player.agents or [""])[0]), ""
                    ),
                    "agent_full",
                    (player.agents or [player.player])[0],
                )
                for player in players
            )
        )
        render_players = [
            RenderPlayerStat(
                player=player.player,
                team=player.team,
                agents=player.agents,
                kills=player.kills,
                deaths=player.deaths,
                assists=player.assists,
                acs=player.acs,
                adr=player.adr,
                rating=player.rating,
                country_code=player.country_code,
                country_name=player.country_name,
                agent_image_paths=[
                    path for path in agent_paths_by_player[index] if path
                ],
                kast=player.kast,
                headshot_percent=player.headshot_percent,
                first_kills=player.first_kills,
                first_deaths=player.first_deaths,
                kd_diff=player.kd_diff,
                fk_diff=player.fk_diff,
                stats_available=player.stats_available,
                agent_full_portrait_path=portrait_paths[index],
            )
            for index, player in enumerate(players)
        ]
        render_result = RenderSingleMapResult(
            map_number=map_index,
            map_name=map_score.map_name,
            team_a=report.team_a,
            team_b=report.team_b,
            team_a_score=map_score.team_a_score,
            team_b_score=map_score.team_b_score,
            tournament_name=report.tournament_name,
            schedule_name=report.schedule_name,
            players=render_players,
            team_a_logo_path=team_a_logo,
            team_b_logo_path=team_b_logo,
            event_logo_path=event_logo,
            map_image_path=map_image,
        )
        map_key = self._safe_filename(map_score.game_id or f"map_{map_index}")
        output_path = self.rendered_dir / (
            f"val_map_{self._safe_filename(report.match_id)}_{map_key}_{self.image_theme}.png"
        )
        return await asyncio.to_thread(
            render_single_map_result_image,
            render_result,
            output_path,
            source_name="VLR.gg",
            theme=self.image_theme,
        )

    async def _ensure_agent_portrait_urls(self) -> None:
        if self._agent_portraits_loaded:
            return
        self._agent_portraits_loaded = True
        try:
            response = await self._get_image_http_client().get(
                "https://valorant-api.com/v1/agents",
                params={"isPlayableCharacter": "true"},
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("data", []):
                name = self._normalize_agent_name(str(item.get("displayName") or ""))
                portrait = str(
                    item.get("bustPortrait")
                    or item.get("fullPortraitV2")
                    or item.get("fullPortrait")
                    or ""
                ).strip()
                if name and portrait:
                    self._agent_portrait_urls[name] = portrait
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "astrbot_plugin_val_match: 获取英雄半身图索引失败，将使用普通英雄头像: %s",
                exc,
            )

    @staticmethod
    def _normalize_agent_name(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    async def _build_match_comment(self, report: MatchReport) -> str:
        community_comments = await self._collect_match_comment_context(report)
        fallback = self._fallback_match_comment(report, community_comments)
        if not self.enable_ai_match_comment:
            return fallback
        provider = (
            self.context.get_using_provider()
            if hasattr(self.context, "get_using_provider")
            else None
        )
        if provider is None:
            return fallback
        with contextlib.suppress(Exception):
            provider_id = provider.meta().id
            prompt = self._build_comment_prompt(report, community_comments)
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=(
                    "你是无畏契约社区赛后编辑。只输出一句35到65字的中文锐评，任务是综合虎扑、VLR等社区中"
                    "反复出现的观点，而不是复述数据表。最多出现一个数字，不写Rating、ACS、KDA或回合统计；"
                    "不要逐条引用网友，不复述粗口和人身攻击，不把单条评论伪装成共识。比赛数据只用于防止张冠李戴。"
                ),
            )
            text = str(getattr(response, "completion_text", "") or "").strip()
            if text:
                candidate = re.sub(
                    r"^\s*(?:锐评|赛后锐评)\s*[:：]\s*", "", text.splitlines()[0]
                ).strip(" \"'“”")[:110]
                if self._comment_is_community_style(
                    candidate, report, community_comments
                ):
                    return candidate
                logger.debug(
                    "astrbot_plugin_val_match: AI 锐评不符合社区整合风格，改用本地社区摘要。"
                )
        return fallback

    async def _collect_match_comment_context(self, report: MatchReport) -> list[str]:
        cache_key = self._match_comment_cache_key(report)
        cached = self._comment_context_cache.get(cache_key)
        now = self._now_in_display_timezone()
        if cached:
            has_hupu = any(item.startswith("虎扑：") for item in cached[1])
            ttl_seconds = 6 * 3600 if has_hupu else 15 * 60
            if (now - cached[0]).total_seconds() < ttl_seconds:
                return cached[1]
        hupu_comments = await self._fetch_hupu_match_comments(report)
        comments: list[str] = []
        if hupu_comments:
            comments.extend(f"虎扑：{item}" for item in hupu_comments)
        comments.extend(
            f"VLR：{item}" for item in list(report.community_comments or [])[:6]
        )
        result = self._dedupe_text_items(comments)[:10]
        self._comment_context_cache[cache_key] = (now, result)
        return result

    @staticmethod
    def _match_comment_cache_key(report: MatchReport) -> str:
        return ":".join(
            str(item or "")
            for item in (
                report.match_id,
                report.match_date,
                report.team_a,
                report.team_b,
                report.score,
            )
        )

    async def _fetch_hupu_match_comments(self, report: MatchReport) -> list[str]:
        if BeautifulSoup is None:
            return []
        candidates = await self._search_hupu_match_threads(report)
        if not candidates:
            return []
        for item in candidates[:2]:
            comments = await self._fetch_hupu_thread_comments(item["href"])
            if comments:
                return [item["title"], item.get("excerpt", ""), *comments[:5]]
        return []

    async def _search_hupu_match_threads(
        self, report: MatchReport
    ) -> list[dict[str, Any]]:
        queries: list[str] = []
        for team_a, team_b in self._hupu_team_query_pairs(report):
            queries.extend(
                [
                    f"{team_a} {team_b} {report.score} 赛后",
                    f"{team_a} {report.score} {team_b}",
                    f"{team_a} {team_b} 赛后",
                    f"{team_a} {team_b} {report.tournament_name}",
                ]
            )
        queries = self._dedupe_text_items(queries)[:8]
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            follow_redirects=True, trust_env=False, timeout=4.0
        ) as client:

            async def search_one(query: str) -> list[dict[str, Any]]:
                url = "https://m.hupu.com/api/v2/search2"
                try:
                    response = await client.get(
                        url,
                        params={
                            "keyword": query,
                            "puid": 0,
                            "type": "posts",
                            "topicId": 0,
                            "page": 1,
                        },
                        headers={
                            "User-Agent": self._browser_user_agent(),
                            "Referer": "https://m.hupu.com/search",
                        },
                    )
                    response.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "astrbot_plugin_val_match: 虎扑搜索失败 %s: %s", query, exc
                    )
                    return []
                with contextlib.suppress(Exception):
                    return self._parse_hupu_search_payload(response.json(), report)
                return []

            results = await asyncio.gather(
                *(search_one(query) for query in queries), return_exceptions=True
            )
            for result in results:
                if isinstance(result, Exception):
                    continue
                for item in result:
                    href = item["href"]
                    if href in seen:
                        continue
                    seen.add(href)
                    candidates.append(item)
        return sorted(candidates, key=lambda item: item["score"], reverse=True)[:4]

    def _parse_hupu_search_payload(
        self, payload: Any, report: MatchReport
    ) -> list[dict[str, Any]]:
        raw_items = (
            payload.get("data", {}).get("result", {}).get("data", [])
            if isinstance(payload, dict)
            else []
        )
        results: list[dict[str, Any]] = []
        match_date = self._report_match_date(report)
        for item in raw_items:
            if (
                not isinstance(item, dict)
                or str(item.get("forum_name") or "") != "无畏契约"
            ):
                continue
            title = self._clean_external_comment(
                self._strip_html_text(str(item.get("title") or ""))
            )
            excerpt = self._clean_external_comment(
                self._strip_html_text(str(item.get("content") or ""))
            )
            thread_id = str(item.get("id") or "").strip()
            if not title or not thread_id.isdigit():
                continue
            posted_date = None
            with contextlib.suppress(ValueError, TypeError, OSError):
                posted_date = datetime.fromtimestamp(
                    int(item.get("addtime") or 0), tz=self._get_display_tz()
                ).date()
            search_text = f"{title} {excerpt}"
            score = self._score_hupu_search_result(
                search_text, posted_date, match_date, report
            )
            if score < 30:
                continue
            score += min(BaseMatchClient._safe_int(item.get("replies"), 0), 50) // 5
            score += min(BaseMatchClient._safe_int(item.get("lights"), 0), 50) // 10
            results.append(
                {
                    "title": title,
                    "excerpt": excerpt,
                    "href": f"https://m.hupu.com/bbs/{thread_id}.html",
                    "score": score,
                }
            )
        return results

    def _parse_hupu_search_results(
        self, html: str, report: MatchReport
    ) -> list[dict[str, Any]]:
        if BeautifulSoup is None:
            return []
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, Any]] = []
        match_date = self._report_match_date(report)
        for row in soup.select(".content-wrap"):
            links = row.select("a.content-wrap-span")
            if len(links) < 2:
                continue
            title = self._clean_external_comment(links[0].get_text(" ", strip=True))
            href = str(links[0].get("href") or "").strip()
            topic = links[1].get_text(" ", strip=True)
            spans = row.select("span")
            posted_date = (
                self._parse_iso_date(spans[0].get_text(" ", strip=True))
                if spans
                else None
            )
            if not title or not href or topic != "无畏契约":
                continue
            score = self._score_hupu_search_result(
                title, posted_date, match_date, report
            )
            if score <= 0:
                continue
            if score < 30:
                continue
            results.append({"title": title, "href": href, "score": score})
        return results

    def _score_hupu_search_result(
        self,
        title: str,
        posted_date: date | None,
        match_date: date | None,
        report: MatchReport,
    ) -> int:
        normalized_title = self._normalize_search_text(title)
        team_a_aliases = [
            self._normalize_search_text(item)
            for item in self._report_team_aliases(report, 0)
        ]
        team_b_aliases = [
            self._normalize_search_text(item)
            for item in self._report_team_aliases(report, 1)
        ]
        if not any(alias and alias in normalized_title for alias in team_a_aliases):
            return 0
        if not any(alias and alias in normalized_title for alias in team_b_aliases):
            return 0
        if "赛后" not in title and any(
            keyword in title for keyword in ("预测", "预告", "赛前", "究竟谁能")
        ):
            return 0
        score = 20
        if self._title_contains_match_score(title, report.score):
            score += 12
        if "赛后" in title:
            score += 12
        if any(
            keyword in title
            for keyword in ("赛后", "战胜", "击败", "夺得", "晋级", "冠军", "淘汰")
        ):
            score += 10
        if match_date is not None and posted_date is not None:
            delta_days = abs((posted_date - match_date).days)
            if delta_days > 3:
                return 0
            score += max(0, 6 - delta_days * 2)
        return score

    @staticmethod
    def _title_contains_match_score(title: str, score: str) -> bool:
        if not score or score == "-":
            return False
        match = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", str(score))
        if not match:
            return False
        left, right = match.groups()
        compact_title = re.sub(r"\s+", "", title).replace("：", ":")
        return any(
            pattern in compact_title
            for pattern in (
                f"{left}-{right}",
                f"{left}:{right}",
                f"{left}比{right}",
            )
        )

    def _hupu_team_query_pairs(self, report: MatchReport) -> list[tuple[str, str]]:
        left_aliases = self._report_team_aliases(report, 0)
        right_aliases = self._report_team_aliases(report, 1)
        pairs: list[tuple[str, str]] = []
        for left in left_aliases[:2]:
            for right in right_aliases[:2]:
                if left and right:
                    pairs.append((left, right))
        return pairs or [(report.team_a, report.team_b)]

    def _report_team_aliases(self, report: MatchReport, side: int) -> list[str]:
        team_name = report.team_a if side == 0 else report.team_b
        aliases = self._team_search_aliases(team_name)
        priority_aliases: list[str] = []
        team_codes: list[str] = []
        for player in report.players:
            code = str(player.team or "").strip()
            if code and code.casefold() not in {item.casefold() for item in team_codes}:
                team_codes.append(code)
        if side < len(team_codes):
            priority_aliases.append(team_codes[side])
        normalized = self._normalize_search_text(team_name)
        known_aliases = {
            "wolvesesports": ["WOL", "狼队"],
            "titansportsclub": ["TEC", "泰坦"],
            "titanesportsclub": ["TEC", "泰坦"],
            "funplusphoenix": ["FPX"],
            "traceesports": ["TE", "Trace"],
            "edwardgaming": ["EDG"],
            "bilibiligaming": ["BLG"],
            "jdgesports": ["JDG"],
            "jdmalljdgesports": ["JDG"],
            "allgamers": ["AG"],
            "xilaigaming": ["XLG"],
            "dragonrangergaming": ["DRG"],
            "novaesports": ["NOVA"],
            "tyloo": ["TYL", "TYLOO"],
        }
        for key, values in known_aliases.items():
            if key in normalized or normalized in key:
                priority_aliases.extend(values)
        return self._dedupe_text_items([*priority_aliases, *aliases])

    @staticmethod
    def _team_search_aliases(team_name: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(team_name or "")).strip()
        aliases: list[str] = []
        if text:
            aliases.append(text)
        uppercase = "".join(re.findall(r"[A-Z0-9]", text))
        if len(uppercase) >= 2:
            aliases.append(uppercase)
        initials = "".join(
            part[0] for part in re.findall(r"[A-Za-z0-9]+", text) if part
        )
        if len(initials) >= 2:
            aliases.append(initials.upper())
        return ValMatchPlugin._dedupe_text_items(aliases)

    async def _fetch_hupu_thread_comments(self, href: str) -> list[str]:
        async with httpx.AsyncClient(
            follow_redirects=True, trust_env=False, timeout=4.0
        ) as client:
            try:
                response = await client.get(
                    href, headers={"User-Agent": self._browser_user_agent()}
                )
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "astrbot_plugin_val_match: 虎扑帖子读取失败 %s: %s", href, exc
                )
                return []
        return self._parse_hupu_thread_comments(response.text)

    def _parse_hupu_thread_comments(self, html: str) -> list[str]:
        if BeautifulSoup is None:
            return []
        soup = BeautifulSoup(html, "html.parser")
        script = soup.select_one("script#__NEXT_DATA__")
        if script is None or not script.string:
            return []
        with contextlib.suppress(Exception):
            payload = json.loads(script.string)
            page_props = payload.get("props", {}).get("pageProps", {})
            detail = page_props.get("detail", {})
            raw_items = list(detail.get("lights") or [])
            replies = detail.get("replies", {})
            if isinstance(replies, dict):
                raw_items.extend(replies.get("list") or [])
            initial_replies = page_props.get("initialRepliesData", {})
            if isinstance(initial_replies, dict):
                raw_items.extend(initial_replies.get("lightReplies") or [])
                raw_items.extend(initial_replies.get("initialReplies") or [])
            return self._extract_hupu_comment_items(raw_items)
        return []

    def _extract_hupu_comment_items(self, raw_items: list[Any]) -> list[str]:
        scored: list[tuple[int, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            content = self._clean_external_comment(
                self._strip_html_text(str(item.get("content") or ""))
            )
            if not content:
                continue
            score = BaseMatchClient._safe_int(
                item.get("allLightCount") or item.get("count"), 0
            )
            scored.append((score, content))
        scored.sort(key=lambda item: item[0], reverse=True)
        comments: list[str] = []
        seen: set[str] = set()
        for _, text in scored:
            if not self._is_useful_external_comment(text):
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            comments.append(text)
            if len(comments) >= 8:
                break
        return comments

    def _build_comment_prompt(
        self, report: MatchReport, community_comments: list[str] | None = None
    ) -> str:
        top_players = sorted(
            [player for player in report.players if player.stats_available],
            key=self._player_impact_sort_key,
            reverse=True,
        )[:5]
        maps = ", ".join(
            f"{item.map_name} {item.team_a_score}:{item.team_b_score}"
            for item in report.maps
        )
        players = "; ".join(
            (
                f"{item.player}({item.team}) Rating {item.rating or '-'}、ACS {item.acs or '-'}、"
                f"KDA {item.kills}/{item.deaths}/{item.assists}、英雄 {','.join(item.agents) or '-'}"
            )
            for item in top_players
        )
        community = "；".join(
            (community_comments or report.community_comments or [])[:8]
        )
        community_line = (
            f"社区观点（可能主观，只可辅助判断）：{community}\n" if community else ""
        )
        data_insights = "；".join(self._build_match_data_insights(report))
        return (
            f"比赛：{report.team_a} {report.score} {report.team_b}\n"
            f"赛事：{report.tournament_name} {report.schedule_name}\n"
            f"地图：{maps}\n"
            f"事实校验信息（不要主动写进锐评）：{data_insights or '暂无'}；{players or '暂无选手数据'}\n"
            f"{community_line}"
            "请提炼多条社区讨论中重复出现的判断，写成自然、有立场的赛后短评。不要罗列比分或个人统计，"
            "不要写成数据播报；若讨论分歧明显，就概括分歧，不要强造共识。"
        )

    @staticmethod
    def _browser_user_agent() -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "")).casefold()

    @staticmethod
    def _strip_html_text(value: str) -> str:
        if BeautifulSoup is not None:
            return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        return re.sub(r"<[^>]+>", " ", value)

    @staticmethod
    def _clean_external_comment(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        cleaned = cleaned.replace("\u200b", "")
        if len(cleaned) < 8:
            return ""
        if "http://" in cleaned.casefold() or "https://" in cleaned.casefold():
            return ""
        if len(cleaned) > 160:
            cleaned = cleaned[:157].rstrip() + "..."
        return cleaned

    @staticmethod
    def _is_useful_external_comment(text: str) -> bool:
        cleaned = str(text or "")
        if len(cleaned) < 10:
            return False
        if "？" in cleaned and len(cleaned) < 30:
            return False
        signal_keywords = (
            "赢",
            "输",
            "冠军",
            "晋级",
            "淘汰",
            "决赛",
            "状态",
            "发挥",
            "失误",
            "战术",
            "枪",
            "图",
            "加时",
            "外战",
            "进",
            "稳",
        )
        return any(keyword in cleaned for keyword in signal_keywords)

    @staticmethod
    def _report_match_date(report: MatchReport) -> date | None:
        with contextlib.suppress(ValueError):
            return date.fromisoformat(str(report.match_date or ""))
        return None

    @staticmethod
    def _parse_iso_date(value: str) -> date | None:
        with contextlib.suppress(ValueError):
            return date.fromisoformat(str(value or "").strip())
        return None

    def _fallback_match_comment(
        self,
        report: MatchReport,
        community_comments: list[str] | None = None,
    ) -> str:
        community_summary = self._build_local_community_summary(
            report, community_comments or []
        )
        if community_summary:
            return community_summary
        winner = self._report_winner(report)
        if winner:
            return f"{winner}拿下系列赛，但目前没有抓到足够的虎扑或 VLR 赛后讨论，暂不替观众强下结论。"
        return "目前没有抓到足够的虎扑或 VLR 赛后讨论，社区观点尚不足以形成可靠摘要。"

    def _build_local_community_summary(
        self, report: MatchReport, comments: list[str]
    ) -> str:
        cleaned = [
            re.sub(r"^(?:虎扑|VLR)：", "", item).strip()
            for item in comments
            if item.strip()
        ]
        if len(cleaned) < 2:
            return ""
        corpus = " ".join(cleaned).casefold()
        winner = self._report_winner(report)
        loser = ""
        if winner:
            loser = report.team_b if winner == report.team_a else report.team_a
        player_mentions = sorted(
            (
                (
                    sum(
                        text.casefold().count(player.player.casefold())
                        for text in cleaned
                    ),
                    player.player,
                )
                for player in report.players
                if len(player.player) >= 3
            ),
            reverse=True,
        )
        focus_player = (
            player_mentions[0][1]
            if player_mentions and player_mentions[0][0] >= 2
            else ""
        )
        themes = {
            "个人发挥": (
                "发挥",
                "状态",
                "枪法",
                "接管",
                "carry",
                "smurf",
                "goat",
                "take over",
                "mvp",
            ),
            "战术执行": ("战术", "执行", "运营", "道具", "配合", "纪律", "默认"),
            "失误决策": (
                "失误",
                "决策",
                "上头",
                "送",
                "残局",
                "慢热",
                "急了",
                "throw",
                "choke",
            ),
            "整体压制": (
                "压制",
                "碾压",
                "差距",
                "打爆",
                "轻松",
                "完爆",
                "dominat",
                "stomp",
            ),
            "调整韧性": (
                "调整",
                "韧性",
                "追分",
                "逆转",
                "暂停",
                "comeback",
                "resilien",
            ),
        }
        theme_scores = {
            name: sum(corpus.count(keyword) for keyword in keywords)
            for name, keywords in themes.items()
        }
        top_theme, top_score = max(theme_scores.items(), key=lambda item: item[1])
        source_label = (
            "虎扑和 VLR"
            if any(item.startswith("虎扑：") for item in comments)
            else "VLR"
        )
        if focus_player and top_score:
            phrase = {
                "个人发挥": "个人发挥和持续影响力",
                "战术执行": "执行与团队配合",
                "失误决策": "关键决策与失误控制",
                "整体压制": "整场压制力",
                "调整韧性": "临场调整与韧性",
            }[top_theme]
            return f"{source_label}赛后讨论的焦点集中在{focus_player}，其{phrase}被反复视为比赛最鲜明的分水岭。"
        if top_score and winner:
            if top_theme == "失误决策" and loser:
                return f"{source_label}的赛后观点更倾向于把胜负归因于{loser}的决策与失误，而不是单纯的枪法差距。"
            phrase = {
                "个人发挥": "核心选手的个人发挥",
                "战术执行": "更完整的执行与配合",
                "整体压制": "从对枪到节奏的整体压制",
                "调整韧性": "更及时的临场调整",
                "失误决策": "更少的无谓失误",
            }[top_theme]
            return f"{source_label}赛后讨论较一致地认为，{winner}真正拉开差距的是{phrase}。"
        if focus_player:
            return f"{source_label}的讨论尚未形成统一战术结论，但{focus_player}是被反复提及最多的赛后焦点。"
        return ""

    def _build_match_data_insights(self, report: MatchReport) -> list[str]:
        insights: list[str] = []
        score_match = re.match(r"\s*(\d+)\s*[:\-]\s*(\d+)\s*$", str(report.score or ""))
        winner = self._report_winner(report)
        winner_side = 0
        if score_match:
            left, right = (int(value) for value in score_match.groups())
            winner_side = 1 if left > right else 2 if right > left else 0
            if winner and min(left, right) == 0:
                insights.append(f"{winner}以{left}:{right}完成零封")
            elif winner:
                insights.append(f"{winner}以{left}:{right}赢下系列赛")

        parsed_maps: list[tuple[MapScore, int, int]] = []
        for item in report.maps:
            with contextlib.suppress(ValueError):
                parsed_maps.append(
                    (item, int(item.team_a_score), int(item.team_b_score))
                )
        if parsed_maps:
            total_a = sum(left for _, left, _ in parsed_maps)
            total_b = sum(right for _, _, right in parsed_maps)
            insights.append(
                f"地图总回合为{total_a}:{total_b}，净差{abs(total_a - total_b)}回合"
            )
            if winner_side:
                first_left, first_right = parsed_maps[0][1], parsed_maps[0][2]
                lost_first = (winner_side == 1 and first_left < first_right) or (
                    winner_side == 2 and first_right < first_left
                )
                if lost_first and winner:
                    insights.append(f"{winner}在先丢首图后完成逆转")
            closest = min(parsed_maps, key=lambda item: abs(item[1] - item[2]))
            closest_margin = abs(closest[1] - closest[2])
            if closest_margin <= 2:
                insights.append(
                    f"最胶着的{closest[0].map_name}仅差{closest_margin}回合"
                )
        return insights

    def _comment_is_community_style(
        self,
        comment: str,
        report: MatchReport,
        community_comments: list[str],
    ) -> bool:
        if len(comment) < 18 or not community_comments:
            return False
        if any(
            keyword in comment.casefold()
            for keyword in ("rating", "acs", "kda", "地图总回合", "净差")
        ):
            return False
        if len(re.findall(r"\d+(?:\.\d+)?", comment)) > 2:
            return False
        entities = [
            *self._report_team_aliases(report, 0),
            *self._report_team_aliases(report, 1),
            *(player.player for player in report.players),
        ]
        return any(
            entity and entity.casefold() in comment.casefold() for entity in entities
        )

    @staticmethod
    def _player_impact_sort_key(player: Any) -> tuple[float, int, int]:
        rating = 0.0
        with contextlib.suppress(ValueError, TypeError):
            rating = float(str(player.rating or "").replace("%", ""))
        acs = BaseMatchClient._safe_int(player.acs, 0)
        kd_diff = BaseMatchClient._safe_int(
            player.kills, 0
        ) - BaseMatchClient._safe_int(player.deaths, 0)
        return rating, acs, kd_diff

    @staticmethod
    def _report_winner(report: MatchReport) -> str:
        match = re.match(r"\s*(\d+)\s*[:\-]\s*(\d+)\s*$", str(report.score or ""))
        if not match:
            return ""
        left = int(match.group(1))
        right = int(match.group(2))
        if left == right:
            return ""
        return report.team_a if left > right else report.team_b

    async def _find_recent_completed_match(
        self, keyword: str = ""
    ) -> MatchRecord | None:
        query = str(keyword or "").strip().casefold()
        today = self._today_in_display_timezone()
        for offset in (0, -1, -2):
            matches, _ = await self._query_matches(today + timedelta(days=offset))
            for match in matches:
                if match.status != "已结束":
                    continue
                haystack = " ".join(
                    [
                        match.team_a,
                        match.team_b,
                        match.tournament_name,
                        match.schedule_name,
                        match.match_id,
                    ]
                ).casefold()
                if not query or query in haystack:
                    return match
        return None

    def _update_tournament_options(self, names: list[str]) -> tuple[int, int]:
        schema_path = self.plugin_root / "_conf_schema.json"
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        discovered_options = self._dedupe_text_items(names)
        options = discovered_options
        for key in ("special_tournaments",):
            field = payload.get(key)
            if not isinstance(field, dict):
                raise ValueError(f"配置项 {key} 不存在。")
            field["options"] = options
        schema_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return len(discovered_options), len(options)

    @staticmethod
    def _dedupe_text_items(items: list[Any]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        return deduped

    async def _prepare_visual_matches(
        self, matches: list[MatchRecord], client: BaseMatchClient
    ) -> None:
        if not matches:
            return
        if isinstance(client, VlrClient):
            await client.enrich_matches_for_visual(matches)

    async def _build_render_matches(
        self, matches: list[MatchRecord], target_date: date
    ) -> list[RenderMatch]:
        day_label = self._format_render_day_label(target_date)
        logo_tasks: list[
            tuple[
                MatchRecord,
                str,
                str,
                asyncio.Task[str | None],
                asyncio.Task[str | None],
                asyncio.Task[str | None],
            ]
        ] = []
        for match in matches:
            raw = match.raw if isinstance(match.raw, dict) else {}
            team_a_name = str(raw.get("team_a_display_name") or match.team_a or "TBD")
            team_b_name = str(raw.get("team_b_display_name") or match.team_b or "TBD")
            logo_tasks.append(
                (
                    match,
                    team_a_name,
                    team_b_name,
                    asyncio.create_task(
                        self._cache_image(
                            raw.get("team_a_logo_url"), "teams", team_a_name
                        )
                    ),
                    asyncio.create_task(
                        self._cache_image(
                            raw.get("team_b_logo_url"), "teams", team_b_name
                        )
                    ),
                    asyncio.create_task(
                        self._cache_image(
                            raw.get("event_logo_url"), "events", match.tournament_name
                        )
                    ),
                )
            )

        render_matches: list[RenderMatch] = []
        for (
            match,
            team_a_name,
            team_b_name,
            logo_a_task,
            logo_b_task,
            event_logo_task,
        ) in logo_tasks:
            logo_a_path, logo_b_path, event_logo_path = await asyncio.gather(
                logo_a_task,
                logo_b_task,
                event_logo_task,
            )
            render_matches.append(
                RenderMatch(
                    day_label=day_label,
                    start_time=match.start_time,
                    status=match.status,
                    score=match.score,
                    team_a=team_a_name,
                    team_b=team_b_name,
                    tournament_name=match.tournament_name,
                    schedule_name=match.schedule_name,
                    level=match.level,
                    best_of=match.best_of or "Bo?",
                    logo_a_path=logo_a_path,
                    logo_b_path=logo_b_path,
                    event_logo_path=event_logo_path,
                )
            )
        return render_matches

    def _format_render_day_label(self, target_date: date) -> str:
        today = self._today_in_display_timezone()
        delta = (target_date - today).days
        if delta == -1:
            prefix = "昨天"
        elif delta == 0:
            prefix = "今天"
        elif delta == 1:
            prefix = "明天"
        else:
            prefix = target_date.strftime("%m-%d")
        weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return f"{prefix} · {target_date.isoformat()} · {weekday_map[target_date.weekday()]}"

    async def _cache_logo(self, url: Any, cache_key: str) -> str | None:
        return await self._cache_image(url, "legacy", cache_key)

    async def _cache_image(
        self, url: Any, category: str, cache_key: str = ""
    ) -> str | None:
        text = str(url or "").strip()
        if not text:
            return None
        if Path(text).exists():
            return text
        if text.startswith("//"):
            text = f"https:{text}"
        elif text.startswith("/"):
            text = f"https://www.vlr.gg{text}"
        ext = ".png"
        suffix_match = re.search(r"\.(png|jpg|jpeg|webp)(?:$|[?])", text, re.I)
        if suffix_match:
            ext = f".{suffix_match.group(1).lower()}"
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        safe_category = self._safe_filename(category) or "misc"
        safe_key = self._safe_filename(cache_key) or safe_category
        cache_dir = self.image_cache_dir / safe_category
        path = cache_dir / f"{safe_key}_{digest}{ext}"
        if path.exists() and path.stat().st_size > 0:
            return str(path)
        lock = self._image_cache_locks.setdefault(text, asyncio.Lock())
        async with lock:
            if path.exists() and path.stat().st_size > 0:
                return str(path)
            return await self._download_image_to_cache(text, path)

    def _find_cached_image_path(self, category: str, cache_key: str) -> str | None:
        safe_category = self._safe_filename(category) or "misc"
        safe_key = self._safe_filename(cache_key)
        if not safe_key:
            return None
        cache_dir = self.image_cache_dir / safe_category
        if not cache_dir.exists():
            return None
        matches = sorted(
            path
            for path in cache_dir.glob(f"{safe_key}_*")
            if path.is_file() and path.stat().st_size > 0
        )
        return str(matches[0]) if matches else None

    @staticmethod
    def _country_flag_url(country_code: str) -> str:
        normalized = str(country_code or "").strip().lower()
        normalized = {"en": "gb", "uk": "gb"}.get(normalized, normalized)
        if not re.fullmatch(r"[a-z]{2}", normalized):
            return ""
        return f"https://flagcdn.com/w80/{normalized}.png"

    async def _download_image_to_cache(self, url: str, path: Path) -> str | None:
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.vlr.gg/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._get_image_http_client().get(url, headers=headers)
                response.raise_for_status()
                if not response.content:
                    raise ValueError("empty image response")
                path.write_bytes(response.content)
                return str(path)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                await asyncio.sleep(0.4 * (attempt + 1))
        logger.warning("astrbot_plugin_val_match: 下载图片失败 %s: %s", url, last_exc)
        return None

    def _get_image_http_client(self) -> httpx.AsyncClient:
        if self._image_http is None:
            self._image_http = httpx.AsyncClient(
                follow_redirects=True,
                trust_env=False,
                timeout=httpx.Timeout(12.0),
                limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
            )
        return self._image_http

    @staticmethod
    def _safe_filename(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "")).strip("_")

    async def _write_monitor_dashboard(self) -> str:
        snapshot = self._build_monitor_snapshot()
        self.monitor_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.monitor_dir / "status.json"
        json_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._monitor_last_written_at = self._now_in_display_timezone()
        return str(json_path)

    def _build_monitor_snapshot(self) -> dict[str, Any]:
        now = self._now_in_display_timezone()
        states = self._build_monitor_match_states(now)
        start_polling_count = sum(
            1 for item in states if item["phase"] == "开赛状态轮询"
        )
        result_polling_count = sum(1 for item in states if item["phase"] == "赛果检查")
        next_start_check = self._next_special_start_status_poll_time(now)
        next_result_check = self._next_special_result_check_time(now)
        next_scan_seconds = (
            self._seconds_until_next_special_scan() if self._special_task else None
        )
        next_scan_at = (
            now + timedelta(seconds=next_scan_seconds)
            if next_scan_seconds is not None
            else None
        )
        return {
            "generated_at": now.isoformat(timespec="seconds"),
            "display_timezone": self.display_timezone,
            "metrics": {
                "special_task_running": bool(
                    self._special_task and not self._special_task.done()
                ),
                "daily_push_task_running": bool(
                    self._push_task and not self._push_task.done()
                ),
                "known_match_count": len(states),
                "start_polling_count": start_polling_count,
                "result_polling_count": result_polling_count,
                "timeline_count": len(self._special_timeline),
            },
            "config": {
                "special_tournaments": self.special_tournaments,
                "special_push_targets": self.special_push_targets,
                "special_start_poll_interval_seconds": self.special_start_poll_interval_seconds,
                "special_start_poll_lookahead_minutes": self.special_start_poll_lookahead_minutes,
                "special_result_check_interval_seconds": self.special_result_check_interval_seconds,
                "special_map_report_enabled": self.special_map_report_enabled,
                "special_map_check_interval_seconds": self.special_map_check_interval_seconds,
                "special_match_window_minutes": self.special_match_window_minutes,
            },
            "tasks": [
                {
                    "name": "每日推送任务",
                    "status": "运行中"
                    if self._push_task and not self._push_task.done()
                    else "未运行",
                    "next_run": self._format_monitor_datetime(
                        self._next_daily_push_datetime(now)
                    )
                    if self._push_task
                    else "-",
                    "detail": f"目标 {len(self.push_targets)} 个",
                },
                {
                    "name": "特别关心后台任务",
                    "status": "运行中"
                    if self._special_task and not self._special_task.done()
                    else "未运行",
                    "next_run": self._format_monitor_datetime(next_scan_at),
                    "detail": f"单循环调度；开赛轮询 {start_polling_count} 场，赛果轮询 {result_polling_count} 场",
                },
            ],
            "next_checks": {
                "next_scan_at": self._format_monitor_datetime(next_scan_at),
                "next_start_check": self._format_monitor_datetime(next_start_check),
                "next_result_check": self._format_monitor_datetime(next_result_check),
                "last_scan_started_at": self._format_monitor_datetime(
                    self._last_special_scan_started_at
                ),
                "last_scan_finished_at": self._format_monitor_datetime(
                    self._last_special_scan_finished_at
                ),
                "last_dashboard_written_at": self._format_monitor_datetime(
                    self._monitor_last_written_at
                ),
            },
            "last_scan_summary": dict(self._last_special_scan_summary),
            "match_states": states,
            "timeline": list(reversed(self._special_timeline[-80:])),
        }

    def _build_monitor_match_states(self, now: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, state in self._special_state.items():
            match = state.get("match")
            if not isinstance(match, MatchRecord):
                continue
            phase = self._monitor_match_phase(match, state, now)
            rows.append(
                {
                    "key": key,
                    "created_at": self._format_monitor_datetime(
                        state.get("created_at")
                    ),
                    "phase": phase,
                    "match_id": match.match_id,
                    "match_date": match.match_date,
                    "start_time": match.start_time,
                    "status": match.status,
                    "teams": f"{match.team_a} vs {match.team_b}",
                    "team_a": match.team_a,
                    "team_b": match.team_b,
                    "best_of": match.best_of,
                    "score": match.score,
                    "start_at": self._match_start_datetime(match).isoformat()
                    if self._match_start_datetime(match)
                    else None,
                    "tournament": match.tournament_name,
                    "schedule": match.schedule_name,
                    "start_sent": bool(state.get("start_sent")),
                    "report_sent": bool(state.get("report_sent")),
                    "map_reports_sent": len(state.get("map_reports_sent") or []),
                    "map_reports_complete": bool(state.get("map_reports_complete")),
                    "map_report_status": self._monitor_map_report_status(state),
                    "last_map_report_at": self._format_monitor_datetime(
                        state.get("last_map_report_at")
                    ),
                    "last_map_report_label": str(
                        state.get("last_map_report_label") or ""
                    ),
                    "next_start_check": self._format_monitor_datetime(
                        state.get("next_start_check")
                    ),
                    "next_result_check": self._format_monitor_datetime(
                        state.get("next_result_check")
                    ),
                }
            )
        return sorted(
            rows,
            key=lambda item: (
                item["phase"] not in {"开赛状态轮询", "赛果检查"},
                item["match_date"],
                item["start_time"],
                item["tournament"],
            ),
        )

    def _monitor_map_report_status(self, state: dict[str, Any]) -> str:
        if not self.special_map_report_enabled:
            return "未开启"
        sent_count = len(state.get("map_reports_sent") or [])
        if state.get("map_reports_complete"):
            return f"已完成 · {sent_count} 张"
        if state.get("report_sent") and not state.get("start_sent"):
            return "未跟踪"
        if sent_count:
            return f"监听中 · 已推 {sent_count} 张"
        if state.get("start_sent"):
            return "监听中 · 等待首图"
        return "等待开赛"

    def _monitor_match_phase(
        self, match: MatchRecord, state: dict[str, Any], now: datetime
    ) -> str:
        if self._special_state_needs_result_poll(state):
            return "赛果检查"
        if state.get("report_sent"):
            return "已完成"
        if match.status == "已结束":
            return "已结束"
        if self._should_poll_match_start_status(match, now):
            return "开赛状态轮询"
        return "等待进入窗口"

    def _next_daily_push_datetime(self, now: datetime) -> datetime:
        configured = self._parse_push_time(self.config.get("push_time"))
        next_run = datetime.combine(
            now.date(), configured, tzinfo=self._get_display_tz()
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    def _format_monitor_datetime(self, value: Any) -> str:
        if not isinstance(value, datetime):
            return "-"
        if value.tzinfo is not None:
            value = value.astimezone(self._get_display_tz())
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _snapshot_client_state(client: BaseMatchClient) -> dict[str, Any]:
        return {
            "current_data_source_type": client.current_data_source_type,
            "last_success_api": client.last_success_api,
            "last_failure_reason": client.last_failure_reason,
            "last_parsed_count": client.last_parsed_count,
            "last_filtered_count": client.last_filtered_count,
            "last_cache_hit": client.last_cache_hit,
            "last_request_info": client.last_request_info,
        }

    @staticmethod
    def _restore_client_state(client: BaseMatchClient, state: dict[str, Any]) -> None:
        client.current_data_source_type = state["current_data_source_type"]
        client.last_success_api = state["last_success_api"]
        client.last_failure_reason = state["last_failure_reason"]
        client.last_parsed_count = state["last_parsed_count"]
        client.last_filtered_count = state["last_filtered_count"]
        client.last_cache_hit = state["last_cache_hit"]
        client._last_request_info = state["last_request_info"]

    @staticmethod
    def _safe_bool(value: Any, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
