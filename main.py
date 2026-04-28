from __future__ import annotations

import asyncio
import contextlib
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

try:
    from .clients.vlr import BaseMatchClient, MatchRecord, RequestDebugInfo, VlrClient
    from .render import RenderMatch, render_match_cards_image
except ImportError:
    from clients.vlr import BaseMatchClient, MatchRecord, RequestDebugInfo, VlrClient
    from render import RenderMatch, render_match_cards_image


class ValMatchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.plugin_root = Path(__file__).resolve().parent
        self.artifacts_dir = self.plugin_root / "artifacts"
        self.rendered_dir = self.artifacts_dir / "rendered"
        self.logo_cache_dir = self.artifacts_dir / "logo_cache"
        self.vlr_client = VlrClient(config)
        self._push_task: asyncio.Task[None] | None = None
        self.last_source_used: str = ""

    async def initialize(self) -> None:
        await self._restart_push_task()

    async def terminate(self) -> None:
        if self._push_task:
            self._push_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._push_task
            self._push_task = None
        await self.vlr_client.close()

    @property
    def display_timezone(self) -> str:
        return str(self.config.get("display_timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"

    def _get_display_tz(self) -> ZoneInfo:
        with contextlib.suppress(Exception):
            return ZoneInfo(self.display_timezone)
        return ZoneInfo("Asia/Shanghai")

    def _now_in_display_timezone(self) -> datetime:
        return datetime.now(self._get_display_tz())

    def _today_in_display_timezone(self) -> date:
        return self._now_in_display_timezone().date()

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
        message = await self._render_for_date(self._today_in_display_timezone() + timedelta(days=1), None)
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
            image_path = await self._render_daily_s_tier_image(self._today_in_display_timezone())
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
            count = self._update_preferred_tournament_options(names)
            preview = "、".join(names[:8])
            suffix = "..." if len(names) > 8 else ""
            yield event.plain_result(
                f"已同步 {count} 个可选赛事到插件设置。\n"
                "请重载插件或刷新插件配置页，然后到 WebUI 的“关注赛事”中多选。\n"
                f"预览：{preview}{suffix}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 同步赛事列表失败: %s", exc)
            yield event.plain_result(f"同步赛事列表失败：{exc}")

    @val.command("push_test")
    async def val_push_test(self, event: AstrMessageEvent):
        """立即向 push_targets 发送一张赛程图片，用于测试定时推送配置。"""
        if not self.push_targets:
            yield event.plain_result("未配置 push_targets，无法测试推送。")
            return
        image_path = await self._render_daily_s_tier_image(self._today_in_display_timezone())
        sent, failed = await self._push_image_to_targets(image_path)
        yield event.plain_result(f"推送测试完成：成功 {sent} 个，失败 {failed} 个。")

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
            f"- 当前关注赛事: {', '.join(self.preferred_tournaments) if self.preferred_tournaments else '(无)'}",
            f"- 当前默认等级过滤: {', '.join(self.default_levels) if self.default_levels else '(无)'}",
            f"- 图片命令日期偏移: {', '.join(str(item) for item in self.image_day_offsets)}",
            f"- 今日缓存是否命中: {'是' if used_client.last_cache_hit else '否'}",
            f"- 定时推送是否启用: {'是' if self._safe_bool(self.config.get('enable_daily_push')) else '否'}",
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

    @property
    def default_levels(self) -> list[str]:
        levels = self._split_csv_text(self.config.get("default_levels"))
        return levels or ["S"]

    @property
    def preferred_tournaments(self) -> list[str]:
        raw = self.config.get("preferred_tournaments")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return self._split_csv_text(raw)

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
        raw_targets = self._split_csv_text(self.config.get("push_targets"))
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

    async def _query_matches(self, target_date: date) -> tuple[list[MatchRecord], BaseMatchClient]:
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
        filtered, filter_summary = self._apply_preferred_filters(matches, levels, explicit_levels is not None)
        client.last_filtered_count = len(filtered)
        message = self._format_message(target_date, filtered, filter_summary, client)
        if not filtered and target_date == self._today_in_display_timezone():
            original_source = self.last_source_used
            state_snapshot = self._snapshot_client_state(self.vlr_client)
            tomorrow_matches, _ = await self._query_matches(target_date + timedelta(days=1))
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

        limit = max(BaseMatchClient._safe_int(self.config.get("max_matches_per_message"), 20), 1)
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
            logger.warning("astrbot_plugin_val_match: 未配置 push_targets，跳过启动定时推送。")
            return

        self._push_task = asyncio.create_task(self._push_loop())
        logger.info("astrbot_plugin_val_match: 每日推送任务已启动。")

    async def _push_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._seconds_until_next_push())
                await self._push_today_matches()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("astrbot_plugin_val_match: 推送任务异常: %s", exc)
                await asyncio.sleep(60)

    async def _push_today_matches(self) -> None:
        image_path = await self._render_daily_s_tier_image(self._today_in_display_timezone())
        await self._push_image_to_targets(image_path)

    async def _push_message_to_targets(self, message: str) -> tuple[int, int]:
        sent = 0
        failed = 0
        for target in self.push_targets:
            try:
                ok = await self.context.send_message(target, MessageChain().message(message))
                if not ok:
                    logger.warning("astrbot_plugin_val_match: 推送失败，未找到目标平台: %s", target)
                    failed += 1
                    continue
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("astrbot_plugin_val_match: 向 %s 推送失败: %s", target, exc)
                failed += 1
        return sent, failed

    async def _push_image_to_targets(self, image_path: str) -> tuple[int, int]:
        sent = 0
        failed = 0
        for target in self.push_targets:
            try:
                ok = await self.context.send_message(target, MessageChain().file_image(image_path))
                if ok:
                    sent += 1
                    continue
                logger.warning("astrbot_plugin_val_match: 图片推送失败，尝试文本回退: %s", target)
                fallback_message = await self._render_for_date(self._today_in_display_timezone(), None)
                fallback_ok = await self.context.send_message(target, MessageChain().message(fallback_message))
                if fallback_ok:
                    sent += 1
                else:
                    failed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("astrbot_plugin_val_match: 向 %s 推送图片失败: %s", target, exc)
                try:
                    fallback_message = await self._render_for_date(self._today_in_display_timezone(), None)
                    fallback_ok = await self.context.send_message(target, MessageChain().message(fallback_message))
                    if fallback_ok:
                        sent += 1
                    else:
                        failed += 1
                except Exception as fallback_exc:  # noqa: BLE001
                    logger.warning("astrbot_plugin_val_match: 向 %s 文本回退也失败: %s", target, fallback_exc)
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
        logger.warning("astrbot_plugin_val_match: push_time=%s 不合法，回退到 09:00。", raw)
        return time(hour=9, minute=0)

    @staticmethod
    def _filter_by_levels(matches: list[MatchRecord], levels: list[str]) -> list[MatchRecord]:
        if not levels:
            return matches
        normalized_levels = {ValMatchPlugin._normalize_level(level) for level in levels if level}
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

    @staticmethod
    def _normalize_level(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return text.replace("级", "").replace(" ", "")

    def _filter_by_preferred_tournaments(self, matches: list[MatchRecord]) -> list[MatchRecord]:
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
                return filtered, f"关注赛事: {', '.join(preferred)} | 等级过滤: {', '.join(levels)}"
            return filtered, f"关注赛事: {', '.join(preferred)}"
        if levels:
            return self._filter_by_levels(matches, levels), f"等级过滤: {', '.join(levels)}"
        return matches, ""

    async def _render_daily_s_tier_image(self, target_date: date) -> str:
        eyebrow_text = "VALORANT S-TIER"
        title_text = "多日 S 级赛事"
        preferred = self.preferred_tournaments
        if preferred:
            eyebrow_text = "VALORANT WATCHLIST"
            title_text = "多日关注赛事"

        render_matches: list[RenderMatch] = []
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
                render_matches.extend(await self._build_render_matches(filtered, query_date))
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

        suffix = "_".join(str(offset) for offset in self.image_day_offsets)
        output_path = self.rendered_dir / f"val_s_{target_date.isoformat()}_{suffix}.png"
        return await asyncio.to_thread(
            render_match_cards_image,
            render_matches,
            target_date,
            output_path,
            source_name=" / ".join(source_names) if source_names else "VLR.gg",
            eyebrow_text=eyebrow_text,
            title_text=title_text,
        )

    def _update_preferred_tournament_options(self, names: list[str]) -> int:
        schema_path = self.plugin_root / "_conf_schema.json"
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        field = payload.get("preferred_tournaments")
        if not isinstance(field, dict):
            raise ValueError("配置项 preferred_tournaments 不存在。")
        options = [name for name in names if str(name).strip()]
        field["options"] = options
        schema_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return len(options)

    async def _prepare_visual_matches(self, matches: list[MatchRecord], client: BaseMatchClient) -> None:
        if not matches:
            return
        if isinstance(client, VlrClient):
            await client.enrich_matches_for_visual(matches)

    async def _build_render_matches(self, matches: list[MatchRecord], target_date: date) -> list[RenderMatch]:
        render_matches: list[RenderMatch] = []
        day_label = self._format_render_day_label(target_date)
        for match in matches:
            raw = match.raw if isinstance(match.raw, dict) else {}
            team_a_name = str(raw.get("team_a_display_name") or match.team_a or "TBD")
            team_b_name = str(raw.get("team_b_display_name") or match.team_b or "TBD")
            logo_a_path = await self._cache_logo(raw.get("team_a_logo_url"), f"{match.match_id}_a")
            logo_b_path = await self._cache_logo(raw.get("team_b_logo_url"), f"{match.match_id}_b")
            event_logo_path = await self._cache_logo(raw.get("event_logo_url"), f"{match.match_id}_event")
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
        text = str(url or "").strip()
        if not text:
            return None
        ext = ".png"
        suffix_match = re.search(r"\.(png|jpg|jpeg|webp)(?:$|[?])", text, re.I)
        if suffix_match:
            ext = f".{suffix_match.group(1).lower()}"
        safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", cache_key).strip("_") or "logo"
        path = self.logo_cache_dir / f"{safe_key}{ext}"
        if path.exists() and path.stat().st_size > 0:
            return str(path)
        self.logo_cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(follow_redirects=True, trust_env=False, timeout=15.0) as client:
                response = await client.get(text, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                path.write_bytes(response.content)
                return str(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_val_match: 下载队标失败 %s: %s", text, exc)
            return None

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
    def _safe_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
