from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

try:
    from bs4 import BeautifulSoup, Tag
except (
    ImportError
):  # pragma: no cover - runtime fallback when optional dependency is absent.
    BeautifulSoup = None
    Tag = Any


class MatchSourceError(Exception):
    """Raised when a match source request or parser fails."""


VALORANT_MAP_SPLASH_URLS = {
    "Abyss": "https://media.valorant-api.com/maps/224b0a95-48b9-f703-1bd8-67aca101a61f/splash.png",
    "Ascent": "https://media.valorant-api.com/maps/7eaecc1b-4337-bbf6-6ab9-04b8f06b3319/splash.png",
    "Bind": "https://media.valorant-api.com/maps/2c9d57ec-4431-9c5e-2939-8f9ef6dd5cba/splash.png",
    "Breeze": "https://media.valorant-api.com/maps/2fb9a4fd-47b8-4e7d-a969-74b4046ebd53/splash.png",
    "Corrode": "https://media.valorant-api.com/maps/1c18ab1f-420d-0d8b-71d0-77ad3c439115/splash.png",
    "Fracture": "https://media.valorant-api.com/maps/b529448b-4d60-346e-e89e-00a4c527a405/splash.png",
    "Haven": "https://media.valorant-api.com/maps/2bee0dc9-4ffe-519b-1cbd-7fbe763a6047/splash.png",
    "Icebox": "https://media.valorant-api.com/maps/e2ad5c54-4114-a870-9641-8ea21279579a/splash.png",
    "Lotus": "https://media.valorant-api.com/maps/2fe4ed3a-450a-948b-6d6b-e89a78e680a9/splash.png",
    "Pearl": "https://media.valorant-api.com/maps/fd267378-4d1d-484f-ff52-77821ed10dc2/splash.png",
    "Split": "https://media.valorant-api.com/maps/d960549e-485c-e861-8d71-aa9d1aed12a2/splash.png",
    "Summit": "https://media.valorant-api.com/maps/756da597-416b-c0f2-f47b-afbdf28670bc/splash.png",
    "Sunset": "https://media.valorant-api.com/maps/92584fbe-486a-b1b2-9faa-39b0f486b498/splash.png",
}

VLR_TIMEZONE_OFFSETS = {
    "UTC": timedelta(hours=0),
    "GMT": timedelta(hours=0),
    "BST": timedelta(hours=1),
    "CET": timedelta(hours=1),
    "CEST": timedelta(hours=2),
    "MSK": timedelta(hours=3),
    "IST": timedelta(hours=5, minutes=30),
    "SGT": timedelta(hours=8),
    "CST": timedelta(hours=8),
    "JST": timedelta(hours=9),
    "KST": timedelta(hours=9),
    "AEST": timedelta(hours=10),
    "AEDT": timedelta(hours=11),
    "EST": timedelta(hours=-5),
    "EDT": timedelta(hours=-4),
    "CST-US": timedelta(hours=-6),
    "CDT": timedelta(hours=-5),
    "MST": timedelta(hours=-7),
    "MDT": timedelta(hours=-6),
    "PST": timedelta(hours=-8),
    "PDT": timedelta(hours=-7),
}


@dataclass(slots=True)
class MatchRecord:
    match_id: str
    match_date: str
    start_time: str
    status: str
    team_a: str
    team_b: str
    score: str
    tournament_name: str
    schedule_name: str
    level: str
    best_of: str
    source: str
    raw: dict[str, Any]


@dataclass(slots=True)
class RequestDebugInfo:
    url: str
    status_code: int | None
    response_preview: str
    error: str | None = None
    source: str = ""


@dataclass(slots=True)
class MapScore:
    map_name: str
    team_a_score: str
    team_b_score: str
    duration: str = ""
    pick: str = ""
    image_url: str = ""
    game_id: str = ""
    players: list[PlayerStat] | None = None


@dataclass(slots=True)
class PlayerStat:
    player: str
    team: str
    agents: list[str]
    kills: str
    deaths: str
    assists: str
    acs: str = ""
    adr: str = ""
    rating: str = ""
    country_code: str = ""
    country_name: str = ""
    player_url: str = ""
    avatar_url: str = ""
    agent_image_urls: list[str] | None = None
    kast: str = ""
    headshot_percent: str = ""
    first_kills: str = ""
    first_deaths: str = ""
    kd_diff: str = ""
    fk_diff: str = ""
    stats_available: bool = True


@dataclass(slots=True)
class MatchReport:
    match_id: str
    match_date: str
    href: str
    team_a: str
    team_b: str
    score: str
    tournament_name: str
    schedule_name: str
    best_of: str
    maps: list[MapScore]
    players: list[PlayerStat]
    event_logo_url: str = ""
    team_a_logo_url: str = ""
    team_b_logo_url: str = ""
    community_comments: list[str] | None = None


@dataclass(slots=True)
class HeadToHeadRecord:
    date_label: str
    score: str
    event_name: str
    team_a: str = ""
    team_b: str = ""
    href: str = ""


@dataclass(slots=True)
class RecentMatchRecord:
    team: str
    opponent: str
    date_label: str
    score: str
    href: str


@dataclass(slots=True)
class MatchPreview:
    match_id: str
    href: str
    team_a: str
    team_b: str
    tournament_name: str
    schedule_name: str
    best_of: str
    start_time: str
    team_a_logo_url: str = ""
    team_b_logo_url: str = ""
    event_logo_url: str = ""
    betting_info: str = ""
    team_a_odds: str = ""
    team_b_odds: str = ""
    head_to_head: list[HeadToHeadRecord] | None = None
    recent_matches: list[RecentMatchRecord] | None = None


@dataclass(slots=True)
class StandingRow:
    team: str
    record: str
    maps: str
    rounds: str
    round_diff: str
    logo_url: str = ""
    position_state: str = "neutral"


@dataclass(slots=True)
class StandingGroup:
    name: str
    rows: list[StandingRow]


@dataclass(slots=True)
class BracketMatch:
    team_a: str
    team_b: str
    score_a: str
    score_b: str
    logo_a_url: str = ""
    logo_b_url: str = ""
    winner: int = 0
    status: str = ""


@dataclass(slots=True)
class BracketRound:
    name: str
    matches: list[BracketMatch]


@dataclass(slots=True)
class BracketSection:
    name: str
    rounds: list[BracketRound]


@dataclass(slots=True)
class TournamentProgress:
    event_name: str
    stage_name: str
    kind: str
    source_url: str
    event_logo_url: str = ""
    groups: list[StandingGroup] | None = None
    brackets: list[BracketSection] | None = None


class BaseMatchClient:
    source_name = "base"

    def __init__(self, config: Any) -> None:
        self.config = config
        self._http = httpx.AsyncClient(follow_redirects=True, trust_env=False)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_request_info: RequestDebugInfo | None = None
        self.current_data_source_type: str = ""
        self.last_success_api: str = ""
        self.last_failure_reason: str = ""
        self.last_parsed_count: int = 0
        self.last_filtered_count: int = 0
        self.last_cache_hit: bool = False

    async def close(self) -> None:
        await self._http.aclose()

    @property
    def display_timezone(self) -> str:
        return (
            str(self.config.get("display_timezone") or "Asia/Shanghai").strip()
            or "Asia/Shanghai"
        )

    @property
    def last_request_info(self) -> RequestDebugInfo | None:
        return self._last_request_info

    def _get_display_tz(self) -> ZoneInfo:
        with contextlib.suppress(Exception):
            return ZoneInfo(self.display_timezone)
        return ZoneInfo("Asia/Shanghai")

    def _today_in_display_timezone(self) -> date:
        return datetime.now(self._get_display_tz()).date()

    def _to_display_datetime(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(self._get_display_tz())

    def _cache_get(self, key: str) -> Any | None:
        cached = self._cache.get(key)
        if not cached:
            return None
        if cached[0] <= asyncio.get_running_loop().time():
            self._cache.pop(key, None)
            return None
        return cached[1]

    def _cache_set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expire_in = ttl if ttl is not None else self.cache_ttl_seconds
        self._cache[key] = (
            asyncio.get_running_loop().time() + max(expire_in, 0),
            value,
        )

    @property
    def timeout_seconds(self) -> int:
        return max(self._safe_int(self.config.get("request_timeout_seconds"), 10), 1)

    @property
    def retry_count(self) -> int:
        return max(self._safe_int(self.config.get("retry_count"), 2), 1)

    @property
    def cache_ttl_seconds(self) -> int:
        return max(self._safe_int(self.config.get("cache_ttl_seconds"), 300), 0)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.retry_count + 1):
            try:
                response = await self._http.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=httpx.Timeout(self.timeout_seconds),
                )
                self._last_request_info = RequestDebugInfo(
                    url=url,
                    status_code=response.status_code,
                    response_preview=self._build_response_preview(response.text),
                    error=None,
                    source=self.source_name,
                )
                if response.status_code == 403:
                    raise MatchSourceError(f"请求返回 HTTP 403: {url}")
                if response.status_code >= 500 and attempt < self.retry_count:
                    await asyncio.sleep(0.4 * attempt)
                    continue
                if response.status_code >= 400:
                    raise MatchSourceError(
                        f"请求返回 HTTP {response.status_code}: {url}"
                    )
                return response
            except (httpx.TimeoutException, httpx.HTTPError, MatchSourceError) as exc:
                last_exc = exc
                previous_info = self._last_request_info
                self._last_request_info = RequestDebugInfo(
                    url=url,
                    status_code=(
                        previous_info.status_code
                        if previous_info and previous_info.url == url
                        else getattr(
                            getattr(exc, "response", None), "status_code", None
                        )
                    ),
                    response_preview=(
                        previous_info.response_preview
                        if previous_info and previous_info.url == url
                        else ""
                    ),
                    error=str(exc),
                    source=self.source_name,
                )
                if attempt >= self.retry_count:
                    break
                await asyncio.sleep(0.4 * attempt)
        raise MatchSourceError(str(last_exc) if last_exc else f"请求失败: {url}")

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _build_response_preview(text: str, limit: int = 300) -> str:
        if not text:
            return ""
        return text[:limit]

    @staticmethod
    def _describe_error(exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    @staticmethod
    def _strip_tags(text: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", text)
        normalized = unescape(without_tags)
        normalized = normalized.replace("\xa0", " ")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @staticmethod
    def _parse_iso_date(value: str) -> date | None:
        with contextlib.suppress(ValueError):
            return date.fromisoformat(value)
        return None

    async def get_matches_by_date(self, target_date: date) -> list[MatchRecord]:
        raise NotImplementedError

    async def debug_probe(self, target_date: date) -> RequestDebugInfo:
        raise NotImplementedError


class VlrClient(BaseMatchClient):
    source_name = "vlr"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._detail_cache: dict[str, dict[str, Any]] = {}
        self._player_cache: dict[str, dict[str, str]] = {}
        self._api_skip_until: float = 0.0
        self._page_display_offset: timedelta | None = None
        self.last_page_display_offset: timedelta | None = None
        self.last_detail_time_source: str = ""
        self._cached_event_selection = self._selected_event_names()

    @property
    def api_url(self) -> str:
        return str(
            self.config.get("vlr_api_url") or "https://vlrggapi.vercel.app"
        ).rstrip("/")

    @property
    def web_url(self) -> str:
        return str(self.config.get("vlr_web_base_url") or "https://www.vlr.gg").rstrip(
            "/"
        )

    @property
    def include_completed(self) -> bool:
        return self._safe_bool(self.config.get("include_completed"), default=True)

    @property
    def fetch_bo_from_details(self) -> bool:
        return self._safe_bool(self.config.get("fetch_bo_from_details"), default=True)

    @property
    def max_detail_fetch_matches(self) -> int:
        return max(self._safe_int(self.config.get("max_detail_fetch_matches"), 12), 0)

    @property
    def api_failure_cooldown_seconds(self) -> int:
        return max(
            self._safe_int(self.config.get("vlr_api_failure_cooldown_seconds"), 600), 0
        )

    @property
    def prefer_api(self) -> bool:
        return self._safe_bool(self.config.get("vlr_prefer_api"), default=False)

    @property
    def browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            )
        }

    async def get_matches_by_date(self, target_date: date) -> list[MatchRecord]:
        selection = self._selected_event_names()
        if selection != self._cached_event_selection:
            for key in list(self._cache):
                if key.startswith("vlr:"):
                    self._cache.pop(key, None)
            self._cached_event_selection = selection
        cache_key = f"vlr:{target_date.isoformat()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            self.last_cache_hit = True
            self.last_parsed_count = len(cached)
            return cached

        self.last_cache_hit = False
        errors: list[str] = []
        event_matches: list[MatchRecord] = []
        if selection:
            try:
                event_matches = await self._load_selected_event_matches(target_date)
            except Exception as exc:
                errors.append(f"event_schedule: {self._describe_error(exc)}")
        skip_api = self._should_skip_vlr_api()
        if skip_api:
            loaders = [self._load_from_vlr_html]
        elif self.prefer_api:
            loaders = [self._load_from_vlr_api, self._load_from_vlr_html]
        else:
            loaders = [self._load_from_vlr_html, self._load_from_vlr_api]
        if skip_api:
            errors.append("VLR API 临时熔断，直接使用网页解析。")
        for loader in loaders:
            try:
                matches = await loader(target_date)
                if matches or event_matches:
                    merged = {m.match_id: m for m in [*matches, *event_matches]}
                    matches = sorted(
                        merged.values(), key=lambda m: (m.start_time, m.match_id)
                    )
                    if loader == self._load_from_vlr_api:
                        self._api_skip_until = 0.0
                    self.last_success_api = (
                        self.last_request_info.url if self.last_request_info else ""
                    )
                    self.last_failure_reason = ""
                    self.last_parsed_count = len(matches)
                    self._cache_set(cache_key, matches)
                    return matches
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{loader.__name__}: {self._describe_error(exc)}")
                if loader == self._load_from_vlr_api:
                    self._mark_vlr_api_failed()
        if event_matches:
            self.current_data_source_type = "VLR_EVENT"
            self.last_parsed_count = len(event_matches)
            self.last_failure_reason = ""
            self._cache_set(cache_key, event_matches)
            return event_matches
        self.last_failure_reason = " | ".join(errors) if errors else "未找到比赛数据。"
        self.last_parsed_count = 0
        self._cache_set(cache_key, [])
        return []

    def invalidate_matches_cache(
        self, target_date: date, *, include_schedule_pages: bool = False
    ) -> None:
        self._cache.pop(f"vlr:{target_date.isoformat()}", None)
        if not include_schedule_pages:
            return
        for key in list(self._cache):
            if key.startswith("vlr-page:schedule:"):
                self._cache.pop(key, None)

    def _should_skip_vlr_api(self) -> bool:
        return self._api_skip_until > asyncio.get_running_loop().time()

    def _mark_vlr_api_failed(self) -> None:
        cooldown = self.api_failure_cooldown_seconds
        if cooldown <= 0:
            return
        self._api_skip_until = asyncio.get_running_loop().time() + cooldown

    async def discover_tournaments(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        errors: list[str] = []
        try:
            events = await self._get_vlr_events(force_refresh=True)
            for event in events:
                seen.add(event["name"].casefold())
                names.append(event["name"])
        except Exception as exc:
            errors.append(self._describe_error(exc))
        page_specs = (
            (
                "schedule",
                max(self._safe_int(self.config.get("vlr_schedule_pages"), 3), 1),
                False,
            ),
            (
                "results",
                max(self._safe_int(self.config.get("vlr_results_pages"), 3), 1),
                True,
            ),
        )
        for kind, max_pages, completed in page_specs:
            for page in range(1, max_pages + 1):
                self._cache.pop(f"vlr-page:{kind}:{page}", None)
                try:
                    html = await self._get_vlr_page(kind, page)
                except Exception as exc:
                    errors.append(self._describe_error(exc))
                    continue
                parsed = self._parse_vlr_match_list_html(html, completed=completed)
                if not parsed:
                    continue
                for match in parsed:
                    name = str(match.tournament_name or "").strip()
                    if not name:
                        continue
                    key = name.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    names.append(name)
        if not names and errors:
            raise MatchSourceError("无法更新赛事列表：" + " | ".join(errors))
        return sorted(names, key=str.casefold)

    def _selected_event_names(self) -> tuple[str, ...]:
        raw = self.config.get(
            "special_tournaments", self.config.get("preferred_tournaments", [])
        )
        if isinstance(raw, str):
            raw = re.split(r"[,，;；\n]", raw)
        return tuple(
            sorted(
                {
                    str(name).strip().casefold()
                    for name in (raw or [])
                    if str(name).strip()
                }
            )
        )

    async def _get_vlr_events(
        self, *, force_refresh: bool = False
    ) -> list[dict[str, str]]:
        if not force_refresh:
            cached = self._cache_get("vlr-events")
            if isinstance(cached, list):
                return cached
        response = await self._request(
            "GET", f"{self.web_url}/events", headers=self.browser_headers
        )
        events = self._parse_vlr_events_html(response.text)
        if not events:
            raise MatchSourceError("VLR 赛事目录未返回可识别的赛事。")
        self._cache_set("vlr-events", events, ttl=max(self.cache_ttl_seconds, 120))
        return events

    def _parse_vlr_events_html(self, html: str) -> list[dict[str, str]]:
        if BeautifulSoup is None:
            raise MatchSourceError("缺少 BeautifulSoup，无法解析赛事目录。")
        soup = BeautifulSoup(html, "html.parser")
        events: dict[str, dict[str, str]] = {}
        for node in soup.select("a.event-item[href]"):
            name = self._node_text(node.select_one(".event-item-title"))
            href = str(node.get("href", ""))
            if name and re.fullmatch(r"/event/\d+/[^/?#]+/?", href):
                events.setdefault(
                    name.casefold(), {"name": name, "href": href.rstrip("/")}
                )
        return list(events.values())

    async def _load_selected_event_matches(
        self, target_date: date
    ) -> list[MatchRecord]:
        selected = set(self._selected_event_names())
        events = await self._get_vlr_events()
        matches: list[MatchRecord] = []
        for event in events:
            if event["name"].casefold() not in selected:
                continue
            href = (
                event["href"].replace("/event/", "/event/matches/", 1)
                + "/?series_id=all"
            )
            cache_key = "vlr-event-page:" + href
            html = self._cache_get(cache_key)
            if not isinstance(html, str):
                response = await self._request(
                    "GET", self.web_url + href, headers=self.browser_headers
                )
                html = response.text
                self._cache_set(cache_key, html, ttl=max(self.cache_ttl_seconds, 120))
            rows = self._parse_vlr_match_list_html(html, completed=False)
            for match in rows:
                stage = match.tournament_name
                match.tournament_name = event["name"]
                match.schedule_name = ": ".join(
                    s for s in (stage, match.schedule_name) if s and s != "未知赛事"
                )
                match.level = self._infer_vlr_level(
                    match.tournament_name, match.schedule_name
                )
                match.raw["event_href"] = event["href"]
            # Event pages use the same date/time markup as the global schedule.
            # Normalize before filtering so cross-midnight fixtures keep their date.
            self._page_display_offset = None
            await self._normalize_matches_to_display_timezone(rows)
            rows = [m for m in rows if m.match_date == target_date.isoformat()]
            await self._fill_match_times_from_details(rows)
            rows = [m for m in rows if m.match_date == target_date.isoformat()]
            for match in rows:
                match.raw["event_href"] = event["href"]
            if rows and self.fetch_bo_from_details:
                await self._fill_best_of_from_details(
                    rows[: self.max_detail_fetch_matches]
                )
            matches.extend(rows)
        return sorted(matches, key=lambda m: (m.start_time, m.match_id))

    async def debug_probe(self, target_date: date) -> RequestDebugInfo:
        try:
            await self._probe_vlr_api()
            if self._last_request_info:
                return self._last_request_info
        except Exception:
            pass

        try:
            await self._request(
                "GET", f"{self.web_url}/matches", headers=self.browser_headers
            )
        except Exception as exc:  # noqa: BLE001
            return RequestDebugInfo(
                url=f"{self.web_url}/matches",
                status_code=self._last_request_info.status_code
                if self._last_request_info
                else None,
                response_preview=self._last_request_info.response_preview
                if self._last_request_info
                else "",
                error=str(exc),
                source=self.source_name,
            )
        return self._last_request_info or RequestDebugInfo(
            url=f"{self.web_url}/matches",
            status_code=None,
            response_preview="",
            error="VLR probe failed",
            source=self.source_name,
        )

    async def _probe_vlr_api(self) -> None:
        await self._request("GET", f"{self.api_url}/match", params={"q": "upcoming"})

    async def _load_from_vlr_api(self, target_date: date) -> list[MatchRecord]:
        self.current_data_source_type = "VLR_API"
        schedule_payloads: list[tuple[str, str]] = [
            ("upcoming", "upcoming"),
            ("live_score", "live"),
        ]
        today = self._today_in_display_timezone()
        if target_date <= today:
            schedule_payloads.append(("results", "completed"))

        aggregated: list[MatchRecord] = []
        for query, default_status in schedule_payloads:
            response = await self._request(
                "GET", f"{self.api_url}/match", params={"q": query}
            )
            if "DEPLOYMENT_NOT_FOUND" in response.text:
                raise MatchSourceError("vlrggapi.vercel.app 当前不可用。")
            try:
                payload = response.json()
            except ValueError as exc:
                raise MatchSourceError("VLR API 返回了非 JSON 数据。") from exc
            raw_matches = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(raw_matches, list):
                continue
            for item in raw_matches:
                if not isinstance(item, dict):
                    continue
                record = self._normalize_vlr_api_match(item, default_status)
                if record and record.match_date == target_date.isoformat():
                    aggregated.append(record)

        if aggregated and self.fetch_bo_from_details:
            await self._fill_best_of_from_details(
                aggregated[: self.max_detail_fetch_matches]
            )
        return aggregated

    def _normalize_vlr_api_match(
        self,
        item: dict[str, Any],
        default_status: str,
    ) -> MatchRecord | None:
        dt = self._parse_vlr_datetime(item)
        if not dt:
            return None
        display_dt = self._to_display_datetime(dt)
        tournament = self._coalesce(
            item,
            ["tournament", "event", "competition", "series"],
        )
        series = self._coalesce(item, ["series", "round", "stage", "match_series"])
        status = str(
            self._coalesce(item, ["status"], default_status) or default_status
        ).strip()
        raw_href = str(
            self._coalesce(item, ["url", "match_url", "href", "link"], "") or ""
        )
        match_id = str(self._coalesce(item, ["id", "match_id", "url"]) or "")
        href = self._normalize_match_href(raw_href, match_id)
        raw = dict(item)
        if href:
            raw["href"] = href
        return MatchRecord(
            match_id=match_id,
            match_date=display_dt.date().isoformat(),
            start_time=display_dt.strftime("%H:%M"),
            status=self._normalize_vlr_status(status),
            team_a=str(
                self._coalesce(item, ["team_a", "team1", "teamA", "teams.0.name"])
                or "TBD"
            ),
            team_b=str(
                self._coalesce(item, ["team_b", "team2", "teamB", "teams.1.name"])
                or "TBD"
            ),
            score=self._format_score(
                self._coalesce(item, ["score_a", "team1_score", "scores.0"]),
                self._coalesce(item, ["score_b", "team2_score", "scores.1"]),
            ),
            tournament_name=str(tournament or "未知赛事").strip(),
            schedule_name=str(series or "").strip(),
            level=self._infer_vlr_level(str(tournament or ""), str(series or "")),
            best_of=str(self._coalesce(item, ["bo", "best_of"], "")),
            source=self.source_name,
            raw=raw,
        )

    async def _load_from_vlr_html(self, target_date: date) -> list[MatchRecord]:
        self.current_data_source_type = "VLR_HTML"
        self._page_display_offset = None
        self.last_page_display_offset = None
        today = self._today_in_display_timezone()
        matches: list[MatchRecord] = []

        if target_date >= today:
            matches.extend(await self._scan_vlr_schedule_pages(target_date))
        if target_date <= today:
            matches.extend(await self._scan_vlr_result_pages(target_date))

        await self._normalize_matches_to_display_timezone(matches)
        matches = [
            match for match in matches if match.match_date == target_date.isoformat()
        ]
        await self._fill_match_times_from_details(matches)
        matches = [
            match for match in matches if match.match_date == target_date.isoformat()
        ]

        deduped: dict[str, MatchRecord] = {}
        for match in matches:
            key = (
                match.match_id
                or f"{match.match_date}:{match.start_time}:{match.team_a}:{match.team_b}"
            )
            deduped[key] = match
        results = sorted(
            deduped.values(),
            key=lambda item: (
                item.match_date,
                item.start_time,
                item.tournament_name,
                item.team_a,
            ),
        )
        if results and self.fetch_bo_from_details:
            await self._fill_best_of_from_details(
                results[: self.max_detail_fetch_matches]
            )
        return results

    async def _scan_vlr_schedule_pages(self, target_date: date) -> list[MatchRecord]:
        max_pages = max(self._safe_int(self.config.get("vlr_schedule_pages"), 3), 1)
        matches: list[MatchRecord] = []
        for page in range(1, max_pages + 1):
            html = await self._get_vlr_page("schedule", page)
            parsed = self._parse_vlr_match_list_html(html, completed=False)
            if parsed:
                matches.extend(parsed)
            if matches:
                break
        return matches

    async def _scan_vlr_result_pages(self, target_date: date) -> list[MatchRecord]:
        max_pages = max(self._safe_int(self.config.get("vlr_results_pages"), 3), 1)
        matches: list[MatchRecord] = []
        for page in range(1, max_pages + 1):
            html = await self._get_vlr_page("results", page)
            parsed = self._parse_vlr_match_list_html(html, completed=True)
            if parsed:
                matches.extend(parsed)
            if matches:
                break
        return matches

    async def _get_vlr_page(self, kind: str, page: int) -> str:
        cache_key = f"vlr-page:{kind}:{page}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, str):
            return cached

        if kind == "schedule":
            url = (
                f"{self.web_url}/matches"
                if page == 1
                else f"{self.web_url}/matches/?page={page}"
            )
        else:
            url = (
                f"{self.web_url}/matches/results"
                if page == 1
                else f"{self.web_url}/matches/results/?page={page}"
            )
        response = await self._request(
            "GET",
            url,
            headers=self.browser_headers,
        )
        self._cache_set(cache_key, response.text, ttl=max(self.cache_ttl_seconds, 120))
        return response.text

    def _parse_vlr_match_list_html(
        self,
        html: str,
        *,
        completed: bool,
    ) -> list[MatchRecord]:
        label_pattern = re.compile(
            r'<div class="wf-label mod-large">\s*(?P<label>.*?)\s*</div>',
            re.S,
        )
        date_sections = list(label_pattern.finditer(html))
        if not date_sections:
            return []

        matches: list[MatchRecord] = []
        for index, match in enumerate(date_sections):
            label = self._strip_tags(match.group("label"))
            section_date = self._parse_vlr_date_label(label)
            if section_date is None:
                continue
            start = match.end()
            end = (
                date_sections[index + 1].start()
                if index + 1 < len(date_sections)
                else len(html)
            )
            section_html = html[start:end]
            matches.extend(
                self._parse_vlr_match_blocks(section_html, section_date, completed)
            )
        return matches

    def _parse_vlr_match_blocks(
        self,
        section_html: str,
        section_date: date,
        completed: bool,
    ) -> list[MatchRecord]:
        block_pattern = re.compile(
            r'<a href="(?P<href>/[^"]+)" class="wf-module-item match-item[^"]*?(?P<class_suffix>[^"]*)">(?P<body>.*?)</a>',
            re.S,
        )
        results: list[MatchRecord] = []
        for block in block_pattern.finditer(section_html):
            href = block.group("href")
            body = block.group("body")
            team_names = re.findall(
                r'<div class="match-item-vs-team-name">.*?<div class="text-of">(.*?)</div>',
                body,
                flags=re.S,
            )
            score_values = re.findall(
                r'<div class="match-item-vs-team-score[^"]*">\s*([^<]+)\s*</div>',
                body,
                flags=re.S,
            )
            if len(team_names) < 2:
                continue
            time_text = self._first_group(
                body,
                r'<div class="match-item-time">\s*(.*?)\s*</div>',
            )
            status_text = self._first_group(
                body,
                r'<div class="ml-status">\s*(.*?)\s*</div>',
            )
            eta_text = self._first_group(
                body,
                r'<div class="ml-eta[^"]*">\s*(.*?)\s*</div>',
            )
            schedule_name = self._first_group(
                body,
                r'<div class="match-item-event-series text-of">\s*(.*?)\s*</div>',
            )
            tournament_match = re.search(
                r'<div class="match-item-event text-of">\s*(?:<div class="match-item-event-series text-of">.*?</div>)?\s*(.*?)\s*</div>',
                body,
                flags=re.S,
            )
            tournament_name = (
                self._strip_tags(tournament_match.group(1))
                if tournament_match
                else "未知赛事"
            )
            note_text = self._first_group(
                body,
                r'<div class="match-item-note">\s*(.*?)\s*</div>',
            )

            team_a = self._strip_tags(team_names[0]) or "TBD"
            team_b = self._strip_tags(team_names[1]) or "TBD"
            score = self._format_score(
                self._clean_score(score_values[0]) if len(score_values) > 0 else None,
                self._clean_score(score_values[1]) if len(score_values) > 1 else None,
            )
            start_time = self._normalize_vlr_time(time_text)
            status = self._normalize_vlr_status(
                status_text or ("Completed" if completed else "Upcoming")
            )
            best_of = self._extract_bo_from_text(note_text)
            match_id = href.strip("/").split("/", 1)[0]

            results.append(
                MatchRecord(
                    match_id=match_id,
                    match_date=section_date.isoformat(),
                    start_time=start_time,
                    status=status
                    if status != "未知"
                    else self._normalize_vlr_status(eta_text),
                    team_a=team_a,
                    team_b=team_b,
                    score=score,
                    tournament_name=tournament_name,
                    schedule_name=self._strip_tags(schedule_name),
                    level=self._infer_vlr_level(tournament_name, schedule_name),
                    best_of=best_of,
                    source=self.source_name,
                    raw={
                        "href": href,
                        "eta": eta_text,
                        "completed": completed,
                        "display_section_date": section_date.isoformat(),
                        "display_time_text": time_text,
                    },
                )
            )
        return results

    async def _fill_best_of_from_details(self, matches: list[MatchRecord]) -> None:
        for match in matches:
            if match.best_of:
                continue
            href = match.raw.get("href") if isinstance(match.raw, dict) else None
            if not isinstance(href, str) or not href:
                continue
            detail = await self._get_vlr_match_detail_info(href)
            bo = detail.get("best_of", "")
            if bo:
                match.best_of = bo

    async def enrich_matches_for_visual(self, matches: list[MatchRecord]) -> None:
        semaphore = asyncio.Semaphore(4)

        async def enrich_one(match: MatchRecord) -> None:
            href = self._match_href(match)
            if not href:
                return
            async with semaphore:
                detail = await self._get_vlr_match_detail_info(href)
            if not match.best_of and isinstance(detail.get("best_of"), str):
                match.best_of = str(detail.get("best_of") or "")
            if isinstance(match.raw, dict):
                match.raw["team_a_logo_url"] = detail.get("team_a_logo_url") or ""
                match.raw["team_b_logo_url"] = detail.get("team_b_logo_url") or ""
                match.raw["team_a_display_name"] = (
                    detail.get("team_a_display_name") or match.team_a
                )
                match.raw["team_b_display_name"] = (
                    detail.get("team_b_display_name") or match.team_b
                )
                match.raw["event_logo_url"] = detail.get("event_logo_url") or ""
                match.raw["event_href"] = detail.get("event_href") or ""

        await asyncio.gather(*(enrich_one(match) for match in matches))

    async def get_tournament_progress(
        self,
        match: MatchRecord,
        *,
        force_refresh: bool = False,
    ) -> TournamentProgress | None:
        href = self._match_href(match)
        if not href:
            return None
        detail = await self._get_vlr_match_detail_info(
            href, force_refresh=force_refresh
        )
        event_href = str(detail.get("event_href") or "").strip()
        if not event_href:
            return None
        cache_key = f"vlr-progress:{event_href}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if isinstance(cached, TournamentProgress):
                return cached
        url = urljoin(f"{self.web_url}/", event_href.lstrip("/"))
        response = await self._request("GET", url, headers=self.browser_headers)
        progress = self._parse_tournament_progress_html(response.text, url, match)
        if progress is not None:
            self._cache_set(cache_key, progress, ttl=max(self.cache_ttl_seconds, 300))
        return progress

    async def get_match_report(
        self,
        match: MatchRecord,
        *,
        enrich_players: bool = True,
        force_refresh: bool = False,
    ) -> MatchReport | None:
        href = self._match_href(match)
        if not href:
            return None
        detail = await self._get_vlr_match_detail_info(
            href, force_refresh=force_refresh
        )
        html = detail.get("html")
        if not isinstance(html, str) or not html:
            return None
        report_url = self._match_report_url(href)
        response = await self._request("GET", report_url, headers=self.browser_headers)
        if self._report_html_has_player_rows(response.text):
            html = response.text
        report = self._parse_match_report_html(html, match, href, detail)
        await self._fill_incomplete_report_maps(report, match, href, detail)
        if not report.maps and not report.players:
            return None
        if enrich_players:
            await self.enrich_player_avatars(report.players)
        return report

    def _match_report_url(self, href: str) -> str:
        return self._match_map_report_url(href, "all")

    def _match_map_report_url(self, href: str, map_value: str | int) -> str:
        url = urljoin(f"{self.web_url}/", href.lstrip("/"))
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["map"] = str(map_value)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    async def _fill_incomplete_report_maps(
        self,
        report: MatchReport,
        match: MatchRecord,
        href: str,
        detail: dict[str, Any],
    ) -> None:
        for map_index, map_score in enumerate(list(report.maps), start=1):
            if not self.has_completed_map_score(
                map_score
            ) or self.is_completed_report_map(map_score):
                continue
            response = await self._request(
                "GET",
                self._match_map_report_url(href, map_index),
                headers=self.browser_headers,
            )
            candidate_report = self._parse_match_report_html(
                response.text, match, href, detail
            )
            candidate = next(
                (
                    item
                    for item in candidate_report.maps
                    if map_score.game_id and item.game_id == map_score.game_id
                ),
                candidate_report.maps[map_index - 1]
                if len(candidate_report.maps) >= map_index
                else None,
            )
            if candidate is not None and self.is_completed_report_map(candidate):
                report.maps[map_index - 1] = candidate

    @staticmethod
    def _report_html_has_player_rows(html: str) -> bool:
        return bool(
            re.search(
                r'<(?:tr|div)\b[^>]*class="[^"]*\b(?:mod-player|ovw-row)\b',
                html,
                flags=re.I,
            )
        )

    async def enrich_player_avatars(self, players: list[PlayerStat]) -> None:
        await self._enrich_player_avatars(players)

    async def get_match_preview(
        self, match: MatchRecord, *, force_refresh: bool = False
    ) -> MatchPreview | None:
        href = self._match_href(match)
        if not href:
            return None
        detail = await self._get_vlr_match_detail_info(
            href, force_refresh=force_refresh
        )
        html = detail.get("html")
        if not isinstance(html, str) or not html:
            return None
        return self._parse_match_preview_html(html, match, href, detail)

    async def _fill_match_times_from_details(self, matches: list[MatchRecord]) -> None:
        for match in matches:
            href = match.raw.get("href") if isinstance(match.raw, dict) else None
            if not isinstance(href, str) or not href:
                continue
            detail = await self._get_vlr_match_detail_info(href)
            detail_display_dt = detail.get("display_dt")
            utc_dt = detail.get("utc_dt")
            if isinstance(detail_display_dt, datetime):
                match.match_date = detail_display_dt.date().isoformat()
                match.start_time = detail_display_dt.strftime("%H:%M")
                self.last_detail_time_source = "DETAIL_DISPLAY"
                detail_time_authoritative = True
            elif isinstance(utc_dt, datetime):
                localized = utc_dt.astimezone(self._get_display_tz())
                match.match_date = localized.date().isoformat()
                match.start_time = localized.strftime("%H:%M")
                self.last_detail_time_source = "DETAIL_SOURCE_TS"
                detail_time_authoritative = True
            else:
                continue
            if isinstance(match.raw, dict):
                match.raw["detail_utc_used"] = detail_time_authoritative
                match.raw["detail_time_source"] = self.last_detail_time_source
                match.raw["team_a_logo_url"] = detail.get("team_a_logo_url") or ""
                match.raw["team_b_logo_url"] = detail.get("team_b_logo_url") or ""
                match.raw["team_a_display_name"] = (
                    detail.get("team_a_display_name") or match.team_a
                )
                match.raw["team_b_display_name"] = (
                    detail.get("team_b_display_name") or match.team_b
                )
                match.raw["event_logo_url"] = detail.get("event_logo_url") or ""
                match.raw["event_href"] = detail.get("event_href") or ""

    async def _get_vlr_match_detail_info(
        self, href: str, *, force_refresh: bool = False
    ) -> dict[str, Any]:
        if not force_refresh:
            cached = self._detail_cache.get(href)
            if cached is not None:
                return cached
        cache_key = f"vlr-bo:{href}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if isinstance(cached, dict):
                self._detail_cache[href] = cached
                return cached
        url = urljoin(f"{self.web_url}/", href.lstrip("/"))
        response = await self._request("GET", url, headers=self.browser_headers)
        match = re.search(
            r'<div class="match-header-vs-note">\s*(?:<span[^>]*>)?\s*(Bo\d+)\s*(?:</span>)?\s*</div>',
            response.text,
            flags=re.S | re.I,
        )
        moment_blocks = re.findall(
            r'<div class="moment-tz-convert"[^>]*data-utc-ts="([^"]+)"[^>]*data-moment-format="([^"]+)"[^>]*>\s*([^<]+?)\s*</div>',
            response.text,
            flags=re.S | re.I,
        )
        utc_match = re.search(
            r'data-utc-ts="(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"',
            response.text,
        )
        utc_dt = None
        timestamp_text = utc_match.group(1) if utc_match else ""
        if utc_match:
            with contextlib.suppress(ValueError):
                utc_dt = self._parse_vlr_source_timestamp(utc_match.group(1))
        display_date_text = ""
        display_time_text = ""
        for _, moment_format, text in moment_blocks:
            cleaned = self._strip_tags(text)
            if not cleaned:
                continue
            if moment_format == "dddd, MMMM D" and not display_date_text:
                display_date_text = cleaned
            elif moment_format == "h:mm A z" and not display_time_text:
                display_time_text = cleaned
        display_dt = self._parse_detail_display_datetime(
            display_date_text,
            display_time_text,
            timestamp_text,
        )
        team_name_matches = re.findall(
            r'<div class="match-header-link-name\s+mod-(1|2)">\s*(.*?)\s*</div>',
            response.text,
            flags=re.S | re.I,
        )
        team_display_names: dict[str, str] = {}
        for side, raw_name in team_name_matches:
            cleaned = self._strip_tags(raw_name)
            if cleaned:
                team_display_names[side] = cleaned
        team_logo_by_side: dict[str, str] = {}
        team_blocks = re.findall(
            r'<a\s+[^>]*class="[^"]*\bmatch-header-link\b[^"]*\bmod-(1|2)\b[^"]*"[^>]*>(.*?)</a>',
            response.text,
            flags=re.S | re.I,
        )
        for side, block in team_blocks:
            img_match = re.search(r'<img\s+[^>]*src="([^"]+)"[^>]*>', block, flags=re.I)
            if not img_match:
                continue
            normalized_url = self._normalize_asset_url(img_match.group(1))
            if normalized_url:
                team_logo_by_side[side] = normalized_url

        team_logo_matches = re.findall(
            r'<img\s+src="([^"]+)"\s+alt="([^"]+?)\s+team logo"',
            response.text,
            flags=re.I,
        )
        team_logo_map: dict[str, str] = {}
        for raw_url, team_name in team_logo_matches[:2]:
            normalized_url = self._normalize_asset_url(raw_url)
            cleaned_name = self._strip_tags(team_name)
            if cleaned_name and normalized_url:
                team_logo_map[cleaned_name] = normalized_url

        team_a_display_name = team_display_names.get("1", "")
        team_b_display_name = team_display_names.get("2", "")
        event_logo_url = ""
        event_href = ""
        event_block = re.search(
            r'<a[^>]+class="match-header-event"[^>]*>(.*?)</a>',
            response.text,
            flags=re.S | re.I,
        )
        if event_block:
            event_tag = event_block.group(0)
            event_href_match = re.search(r'href="([^"]+)"', event_tag, flags=re.I)
            if event_href_match:
                event_href = event_href_match.group(1).strip()
            event_img = re.search(
                r'<img\s+src="([^"]+)"', event_block.group(1), flags=re.I
            )
            if event_img:
                event_logo_url = self._normalize_asset_url(event_img.group(1))
        detail = {
            "html": response.text,
            "best_of": match.group(1).strip() if match else "",
            "utc_dt": utc_dt,
            "timestamp_text": timestamp_text,
            "display_date_text": display_date_text,
            "display_time_text": display_time_text,
            "display_dt": display_dt,
            "team_a_display_name": team_a_display_name,
            "team_b_display_name": team_b_display_name,
            "team_a_logo_url": team_logo_by_side.get("1")
            or team_logo_map.get(team_a_display_name, ""),
            "team_b_logo_url": team_logo_by_side.get("2")
            or team_logo_map.get(team_b_display_name, ""),
            "event_logo_url": event_logo_url,
            "event_href": event_href,
        }
        self._detail_cache[href] = detail
        self._cache_set(cache_key, detail, ttl=max(self.cache_ttl_seconds, 3600))
        return detail

    def _parse_tournament_progress_html(
        self,
        html: str,
        source_url: str,
        match: MatchRecord,
    ) -> TournamentProgress | None:
        if BeautifulSoup is None:
            return None
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one(".event-header-main-title")
        event_name = self._node_text(title_node) or match.tournament_name
        stage_node = soup.select_one(".wf-subnav-item.mod-active .wf-subnav-item-title")
        stage_name = self._node_text(stage_node) or self._event_stage_from_url(
            source_url
        )
        logo_node = soup.select_one(".event-header-thumb img")
        event_logo_url = (
            self._normalize_asset_url(str(logo_node.get("src") or ""))
            if logo_node
            else ""
        )

        groups = self._parse_event_standing_groups(soup)
        bracket_sections = self._parse_event_bracket_sections(soup)
        stage_hint = f"{stage_name} {match.schedule_name}".casefold()
        bracket_keywords = (
            "playoff",
            "play-in",
            "knockout",
            "bracket",
            "quarter",
            "semifinal",
            "semi-final",
            "upper",
            "lower",
            "grand final",
        )
        prefer_bracket = any(keyword in stage_hint for keyword in bracket_keywords)
        if bracket_sections and (prefer_bracket or not groups):
            return TournamentProgress(
                event_name=event_name,
                stage_name=stage_name or "淘汰赛",
                kind="bracket",
                source_url=source_url,
                event_logo_url=event_logo_url,
                brackets=bracket_sections,
            )
        if groups:
            return TournamentProgress(
                event_name=event_name,
                stage_name=stage_name or "常规赛",
                kind="standings",
                source_url=source_url,
                event_logo_url=event_logo_url,
                groups=groups,
            )
        if bracket_sections:
            return TournamentProgress(
                event_name=event_name,
                stage_name=stage_name or "淘汰赛",
                kind="bracket",
                source_url=source_url,
                event_logo_url=event_logo_url,
                brackets=bracket_sections,
            )
        return None

    def _parse_event_standing_groups(self, soup: Any) -> list[StandingGroup]:
        groups: list[StandingGroup] = []
        for table in soup.select(".event-group-block table.mod-group"):
            name = (
                self._node_text(table.select_one("thead .mod-title"))
                or f"Group {len(groups) + 1}"
            )
            rows: list[StandingRow] = []
            for row in table.select("tbody tr"):
                team_node = row.select_one(".event-group-team-name")
                if team_node is None:
                    continue
                region_node = team_node.select_one(".event-group-team-region")
                if region_node is not None:
                    region_node.extract()
                team = self._node_text(team_node)
                if not team:
                    continue
                stat_nodes = row.select("td.mod-stat")
                stat_values = [self._compact_record_text(node) for node in stat_nodes]
                while len(stat_values) < 4:
                    stat_values.append("-")
                row_classes = set(row.get("class") or [])
                state = "neutral"
                if "mod-adv" in row_classes:
                    state = "advance"
                elif "mod-elim" in row_classes:
                    state = "eliminated"
                logo_node = row.select_one(".event-group-team-logo")
                rows.append(
                    StandingRow(
                        team=team,
                        record=stat_values[0],
                        maps=stat_values[1],
                        rounds=stat_values[2],
                        round_diff=stat_values[3],
                        logo_url=self._normalize_asset_url(
                            str(logo_node.get("src") or "")
                        )
                        if logo_node
                        else "",
                        position_state=state,
                    )
                )
            if rows:
                groups.append(StandingGroup(name=name, rows=rows))
        return groups

    def _parse_event_bracket_sections(self, soup: Any) -> list[BracketSection]:
        sections: list[BracketSection] = []
        for container_index, container in enumerate(
            soup.select(".event-brackets-container .bracket-container")
        ):
            classes = set(container.get("class") or [])
            if "mod-upper" in classes:
                section_name = "Upper Bracket"
            elif "mod-lower" in classes:
                section_name = "Lower Bracket"
            else:
                section_name = (
                    "Bracket"
                    if container_index == 0
                    else f"Bracket {container_index + 1}"
                )
            rounds: list[BracketRound] = []
            for column in container.select(":scope > .bracket-col"):
                round_name = self._node_text(
                    column.select_one(":scope > .bracket-col-label")
                )
                matches: list[BracketMatch] = []
                for item in column.select(
                    ":scope > .bracket-row > .bracket-item:not(.mod-empty)"
                ):
                    team_nodes = item.select(":scope > .bracket-item-team")
                    if len(team_nodes) < 2:
                        continue
                    parsed_teams: list[tuple[str, str, str, bool]] = []
                    for team_node in team_nodes[:2]:
                        name = (
                            self._node_text(
                                team_node.select_one(".bracket-item-team-name span")
                            )
                            or "TBD"
                        )
                        score = (
                            self._node_text(
                                team_node.select_one(".bracket-item-team-score")
                            )
                            or "-"
                        )
                        logo = team_node.select_one(".bracket-item-team-name img")
                        parsed_teams.append(
                            (
                                name,
                                score,
                                self._normalize_asset_url(str(logo.get("src") or ""))
                                if logo
                                else "",
                                "mod-winner" in set(team_node.get("class") or []),
                            )
                        )
                    status_node = item.select_one(".bracket-item-status")
                    status = self._node_text(status_node)
                    winner = 1 if parsed_teams[0][3] else 2 if parsed_teams[1][3] else 0
                    matches.append(
                        BracketMatch(
                            team_a=parsed_teams[0][0],
                            team_b=parsed_teams[1][0],
                            score_a=parsed_teams[0][1],
                            score_b=parsed_teams[1][1],
                            logo_a_url=parsed_teams[0][2],
                            logo_b_url=parsed_teams[1][2],
                            winner=winner,
                            status=status,
                        )
                    )
                if matches:
                    rounds.append(
                        BracketRound(
                            name=round_name or f"Round {len(rounds) + 1}",
                            matches=matches,
                        )
                    )
            if rounds:
                sections.append(BracketSection(name=section_name, rounds=rounds))
        return sections

    @staticmethod
    def _compact_record_text(node: Any) -> str:
        if node is None:
            return "-"
        return "".join(node.stripped_strings).replace("–", "-") or "-"

    @staticmethod
    def _event_stage_from_url(value: str) -> str:
        slug = str(value or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if slug.isdigit() or slug == "event":
            return "Main Event"
        return slug.replace("-", " ").title()

    def _parse_match_report_html(
        self,
        html: str,
        match: MatchRecord,
        href: str,
        detail: dict[str, Any],
    ) -> MatchReport:
        if BeautifulSoup is None:
            return MatchReport(
                match_id=match.match_id,
                match_date=match.match_date,
                href=href,
                team_a=match.team_a,
                team_b=match.team_b,
                score=match.score,
                tournament_name=match.tournament_name,
                schedule_name=match.schedule_name,
                best_of=match.best_of,
                maps=[],
                players=[],
                event_logo_url=str(detail.get("event_logo_url") or ""),
                team_a_logo_url=str(detail.get("team_a_logo_url") or ""),
                team_b_logo_url=str(detail.get("team_b_logo_url") or ""),
            )

        soup = BeautifulSoup(html, "html.parser")
        maps = self._parse_report_maps(soup)
        players = self._parse_report_players(soup)
        community_comments = self._parse_report_community_comments(soup)
        return MatchReport(
            match_id=match.match_id,
            match_date=match.match_date,
            href=href,
            team_a=str(detail.get("team_a_display_name") or match.team_a),
            team_b=str(detail.get("team_b_display_name") or match.team_b),
            score=match.score,
            tournament_name=match.tournament_name,
            schedule_name=match.schedule_name,
            best_of=str(detail.get("best_of") or match.best_of or ""),
            maps=maps,
            players=players,
            event_logo_url=str(detail.get("event_logo_url") or ""),
            team_a_logo_url=str(detail.get("team_a_logo_url") or ""),
            team_b_logo_url=str(detail.get("team_b_logo_url") or ""),
            community_comments=community_comments,
        )

    def _parse_match_preview_html(
        self,
        html: str,
        match: MatchRecord,
        href: str,
        detail: dict[str, Any],
    ) -> MatchPreview:
        soup = BeautifulSoup(html, "html.parser") if BeautifulSoup is not None else None
        betting_info, team_a_odds, team_b_odds = self._parse_preview_betting_info(
            soup, html, match
        )
        head_to_head = (
            self._parse_preview_head_to_head(soup, match) if soup is not None else []
        )
        display_dt = detail.get("display_dt")
        utc_dt = detail.get("utc_dt")
        start_time = match.start_time
        if isinstance(display_dt, datetime):
            start_time = display_dt.strftime("%H:%M")
        elif isinstance(utc_dt, datetime):
            start_time = utc_dt.astimezone(self._get_display_tz()).strftime("%H:%M")
        return MatchPreview(
            match_id=match.match_id,
            href=href,
            team_a=str(detail.get("team_a_display_name") or match.team_a),
            team_b=str(detail.get("team_b_display_name") or match.team_b),
            tournament_name=match.tournament_name,
            schedule_name=match.schedule_name,
            best_of=str(detail.get("best_of") or match.best_of or ""),
            start_time=start_time,
            team_a_logo_url=str(detail.get("team_a_logo_url") or ""),
            team_b_logo_url=str(detail.get("team_b_logo_url") or ""),
            event_logo_url=str(detail.get("event_logo_url") or ""),
            betting_info=betting_info,
            team_a_odds=team_a_odds,
            team_b_odds=team_b_odds,
            head_to_head=head_to_head,
            recent_matches=self._parse_preview_recent_matches(soup)
            if soup is not None
            else [],
        )

    def _parse_preview_betting_info(
        self, soup: Any, html: str, match: MatchRecord
    ) -> tuple[str, str, str]:
        if soup is not None:
            candidates: list[str] = []
            team_a_odds = ""
            team_b_odds = ""
            for node in soup.select(".match-bet-item"):
                text = self._node_text(node)
                normalized = re.sub(r"\s+", " ", text).strip()
                if not normalized:
                    continue
                candidates.append(normalized)
                pair_odds = self._parse_vlr_bet_pair(normalized, match)
                if pair_odds:
                    team_a_odds, team_b_odds = pair_odds
                    continue
                team_label, odds = self._parse_vlr_bet_item(node)
                if not odds:
                    continue
                side = self._match_betting_team_side(team_label, normalized, match)
                if side == "a":
                    team_a_odds = odds
                elif side == "b":
                    team_b_odds = odds

            if team_a_odds or team_b_odds:
                if team_a_odds and team_b_odds:
                    info = f"VLR/Rainbet 赛前赔率：{match.team_a} {team_a_odds} / {match.team_b} {team_b_odds}"
                else:
                    known_team = match.team_a if team_a_odds else match.team_b
                    known_odds = team_a_odds or team_b_odds
                    info = f"VLR/Rainbet 仅保留 {known_team} 赛前赔率 {known_odds}，另一侧未公开"
                return self._trim_preview_text(info, 140), team_a_odds, team_b_odds

            for node in soup.select(
                ".match-bet, .match-prediction, .predict-container"
            ):
                text = self._node_text(node)
                normalized = re.sub(r"\s+", " ", text).strip()
                if not normalized:
                    continue
                lower = normalized.casefold()
                if any(
                    keyword in lower
                    for keyword in ("bet", "odds", "prediction", "预测", "赔率")
                ):
                    candidates.append(normalized)
                    odds_match = re.search(
                        r"\b(\d+(?:\.\d+)?)\s+(?:[A-Z0-9]{2,8}\s+)?odds\s+pre-match\b",
                        normalized,
                        flags=re.I,
                    )
                    if odds_match:
                        if match.team_a.casefold() in lower:
                            team_a_odds = odds_match.group(1)
                        elif match.team_b.casefold() in lower:
                            team_b_odds = odds_match.group(1)
            if candidates:
                return (
                    self._trim_preview_text(" | ".join(candidates), 120),
                    team_a_odds,
                    team_b_odds,
                )

        plain = self._strip_tags(html)
        odds_text = re.search(
            r"(?i)(betting|odds|prediction|预测|赔率)\s*[:：]?\s*(.{8,160})",
            plain,
        )
        if odds_text:
            return self._trim_preview_text(odds_text.group(0), 120), "", ""
        return "", "", ""

    def _parse_vlr_bet_pair(
        self, text: str, match: MatchRecord
    ) -> tuple[str, str] | None:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        pair_match = re.search(
            r"\b(\d+(?:\.\d+)?)\s+vs\s+(\d+(?:\.\d+)?)\b",
            normalized,
            flags=re.I,
        )
        if not pair_match:
            return None
        left_odds, right_odds = pair_match.group(1), pair_match.group(2)
        before = normalized[: pair_match.start()]
        after = normalized[pair_match.end() :]
        left_side = self._match_betting_team_side(before, before, match)
        right_side = self._match_betting_team_side(after, after, match)
        if left_side == "a" and right_side == "b":
            return left_odds, right_odds
        if left_side == "b" and right_side == "a":
            return right_odds, left_odds
        if (
            self._match_betting_team_side(match.team_a, before, match) == "a"
            and self._match_betting_team_side(match.team_b, after, match) == "b"
        ):
            return left_odds, right_odds
        return None

    def _parse_vlr_bet_item(self, node: Any) -> tuple[str, str]:
        team_node = node.select_one(
            ".match-bet-item-return-msg .match-bet-item-teamzzz"
        )
        short_node = node.select_one(
            ".match-bet-item-return-short .match-bet-item-teamzzz"
        )
        team_label = self._node_text(team_node) or self._node_text(short_node)

        short_text = self._node_text(node.select_one(".match-bet-item-return-short"))
        odds_match = re.search(
            r"\b(\d+(?:\.\d+)?)\s+(?:[A-Z0-9]{2,8}\s+)?odds\s+pre-match\b",
            short_text,
            flags=re.I,
        )
        if odds_match:
            return team_label, odds_match.group(1)

        odds_values: list[str] = []
        for odds_node in node.select(".match-bet-item-odds"):
            value = self._node_text(odds_node).replace("$", "").strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", value):
                odds_values.append(value)
        for value in reversed(odds_values):
            with contextlib.suppress(ValueError):
                number = float(value)
                if 1 < number < 50:
                    return team_label, value
        return team_label, ""

    def _match_betting_team_side(
        self, team_label: str, full_text: str, match: MatchRecord
    ) -> str:
        label = self._normalize_team_alias_text(team_label)
        text = self._normalize_team_alias_text(full_text)
        team_a_aliases = self._team_aliases(match.team_a)
        team_b_aliases = self._team_aliases(match.team_b)

        label_a = bool(label and label in team_a_aliases)
        label_b = bool(label and label in team_b_aliases)
        if label_a and not label_b:
            return "a"
        if label_b and not label_a:
            return "b"

        text_a = any(
            alias and alias in text for alias in team_a_aliases if len(alias) >= 3
        )
        text_b = any(
            alias and alias in text for alias in team_b_aliases if len(alias) >= 3
        )
        if text_a and not text_b:
            return "a"
        if text_b and not text_a:
            return "b"
        return ""

    @staticmethod
    def _team_aliases(team_name: str) -> set[str]:
        words = re.findall(r"[a-z0-9]+", str(team_name or "").casefold())
        aliases = {"".join(words)}
        ignored = {"team", "esports", "esport", "gaming", "club", "valorant"}
        useful_words = [word for word in words if word not in ignored]
        aliases.update(useful_words)
        aliases.update(word[:3] for word in useful_words if len(word) >= 3)
        if words:
            aliases.add("".join(word[0] for word in useful_words or words))
        return {alias for alias in aliases if alias}

    @staticmethod
    def _normalize_team_alias_text(value: str) -> str:
        return "".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

    def _parse_preview_recent_matches(self, soup: Any) -> list[RecentMatchRecord]:
        headers = soup.select(".match-h2h-header .match-h2h-header-team")
        groups = soup.select(".match-histories")
        if len(headers) != 2 or len(groups) != 2:
            return []
        records = []
        for header, group in zip(headers, groups):
            team = self._node_text(header)
            for item in group.select("a.match-histories-item")[:5]:
                a = self._node_text(item.select_one(".match-histories-item-result .rf"))
                b = self._node_text(item.select_one(".match-histories-item-result .ra"))
                opponent = self._node_text(
                    item.select_one(".match-histories-item-opponent-name")
                )
                day = self._node_text(
                    item.select_one(".match-histories-item-date")
                ).replace("/", "-")
                href = str(item.get("href") or "")
                if a and b and opponent and day and href:
                    records.append(
                        RecentMatchRecord(team, opponent, day, f"{a}:{b}", href)
                    )
        return records

    def _parse_preview_head_to_head(
        self, soup: Any, match: MatchRecord
    ) -> list[HeadToHeadRecord]:
        rows: list[HeadToHeadRecord] = []
        seen: set[str] = set()
        headers = soup.select(".match-h2h-header .match-h2h-header-team")
        left_team = self._node_text(headers[0]) if len(headers) > 1 else ""
        right_team = self._node_text(headers[1]) if len(headers) > 1 else ""
        for node in soup.select(".match-h2h-matches a.mod-h2h"):
            left_score = self._node_text(
                node.select_one(".match-h2h-matches-score .rf")
            )
            right_score = self._node_text(
                node.select_one(".match-h2h-matches-score .ra")
            )
            if not left_score or not right_score:
                continue
            date_label = self._node_text(
                node.select_one(".match-h2h-matches-date")
            ).replace("/", "-")
            event_name = self._node_text(
                node.select_one(".match-h2h-matches-event-name")
            )
            series = self._node_text(node.select_one(".match-h2h-matches-event-series"))
            if series:
                event_name = f"{event_name} {series}".strip()
            key = str(
                node.get("href")
                or f"{date_label}:{event_name}:{left_score}:{right_score}"
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                HeadToHeadRecord(
                    date_label=date_label or "-",
                    score=f"{left_score}:{right_score}",
                    event_name=self._trim_preview_text(event_name or "-", 92),
                    team_a=left_team,
                    team_b=right_team,
                    href=str(node.get("href") or ""),
                )
            )
            if len(rows) >= 3:
                return rows
        return rows

    @staticmethod
    def _trim_preview_text(value: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _parse_report_maps(self, soup: Any) -> list[MapScore]:
        maps: list[MapScore] = []
        for game in soup.select('.vm-stats-game:not([data-game-id="all"])'):
            header = game.select_one(".vm-stats-game-header")
            if header is None:
                continue
            teams = header.select(".team")
            map_node = header.select_one(".map")
            if len(teams) < 2 or map_node is None:
                continue
            left_score = self._node_text(teams[0].select_one(".score"))
            right_score = self._node_text(teams[1].select_one(".score"))
            map_title = self._node_text(map_node.select_one("div"))
            map_name = (
                re.sub(r"\bPICK\b", "", map_title, flags=re.I).strip() or "Unknown"
            )
            duration = self._node_text(map_node.select_one(".map-duration"))
            pick = ""
            picked = map_node.select_one(".picked")
            if picked is not None:
                picked_classes = set(picked.get("class") or [])
                if "mod-1" in picked_classes:
                    pick = self._node_text(teams[0].select_one(".team-name"))
                elif "mod-2" in picked_classes:
                    pick = self._node_text(teams[1].select_one(".team-name"))
            if left_score or right_score:
                maps.append(
                    MapScore(
                        map_name=map_name,
                        team_a_score=left_score or "-",
                        team_b_score=right_score or "-",
                        duration=duration,
                        pick=pick,
                        image_url=self._map_image_url(map_name),
                        game_id=str(game.get("data-game-id") or "").strip(),
                        players=self._parse_report_player_rows(game),
                    )
                )
        return maps

    def _parse_report_players(self, soup: Any) -> list[PlayerStat]:
        all_game = soup.select_one('.vm-stats-game[data-game-id="all"]')
        players = (
            self._parse_report_player_rows(all_game) if all_game is not None else []
        )
        if self._players_have_effective_stats(players):
            return players

        fallback_players = players
        map_rows: list[list[PlayerStat]] = []
        for game in soup.select('.vm-stats-game:not([data-game-id="all"])'):
            rows = self._parse_report_player_rows(game)
            if rows and not fallback_players:
                fallback_players = rows
            map_rows.append(rows)
        aggregated = self._aggregate_report_players_from_maps(map_rows)
        if aggregated:
            return aggregated

        for player in fallback_players:
            player.stats_available = False
        return fallback_players

    def _parse_report_player_rows(self, container: Any) -> list[PlayerStat]:
        if container is None:
            return []
        players: list[PlayerStat] = []
        rows = container.select("tbody tr")
        new_layout = not rows
        if new_layout:
            rows = container.select(".ovw-row:not(.mod-head)")
        for row in rows:
            player_cell = row.select_one(".mod-player")
            player_name_node = (
                player_cell.select_one(".ovw-player-name, .text-of")
                if player_cell
                else None
            )
            team_node = (
                player_cell.select_one(".ovw-player-tag, .ge-text-light")
                if player_cell
                else None
            )
            flag_node = player_cell.select_one(".flag") if player_cell else None
            player_link = (
                player_cell.select_one('a[href^="/player/"]') if player_cell else None
            )
            player = self._node_text(player_name_node)
            team = self._node_text(team_node).upper()
            if not player:
                continue
            agent_nodes = row.select(".mod-agents img, .ovw-agents img")
            agents = []
            agent_image_urls = []
            for img in agent_nodes:
                agent_name = str(img.get("title") or img.get("alt") or "").strip()
                if agent_name:
                    agents.append(agent_name.title())
                agent_url = self._normalize_asset_url(str(img.get("src") or ""))
                if agent_url:
                    agent_image_urls.append(agent_url)
            country_code, country_name = self._flag_info(flag_node)
            player_url = (
                self._normalize_asset_url(str(player_link.get("href") or ""))
                if player_link
                else ""
            )
            if new_layout:
                stat_values = {
                    "kills": self._stat_value(row, '[data-col="kills"]'),
                    "deaths": self._stat_value(row, '[data-col="deaths"]'),
                    "assists": self._stat_value(row, '[data-col="assists"]'),
                    "acs": self._stat_value(row, '[data-col="acs"]'),
                    "adr": self._stat_value(row, '[data-col="adr"]'),
                    "rating": self._stat_value(row, '[data-col="rating2"]'),
                    "kast": self._stat_value(row, '[data-col="kast"]'),
                    "headshot_percent": self._stat_value(row, '[data-col="hsp"]'),
                    "first_kills": self._stat_value(row, '[data-col="fb"]'),
                    "first_deaths": self._stat_value(row, '[data-col="fd"]'),
                    "kd_diff": self._stat_value(row, '[data-col="kd-diff"]'),
                    "fk_diff": self._stat_value(row, '[data-col="fk-diff"]'),
                }
            else:
                stat_values = {
                    "kills": self._stat_value(row, ".mod-vlr-kills"),
                    "deaths": self._stat_value(row, ".mod-vlr-deaths"),
                    "assists": self._stat_value(row, ".mod-vlr-assists"),
                    "acs": self._stat_value(row, "td.mod-stat:nth-of-type(4)"),
                    "adr": self._stat_value(row, ".mod-combat"),
                    "rating": self._stat_value(row, "td.mod-stat:nth-of-type(3)"),
                    "kast": self._stat_value(row, "td.mod-stat:nth-of-type(9)"),
                    "headshot_percent": self._stat_value(
                        row, "td.mod-stat:nth-of-type(11)"
                    ),
                    "first_kills": self._stat_value(row, ".mod-fb"),
                    "first_deaths": self._stat_value(row, ".mod-fd"),
                    "kd_diff": self._stat_value(row, ".mod-kd-diff"),
                    "fk_diff": self._stat_value(row, ".mod-fk-diff"),
                }
            stat = PlayerStat(
                player=player,
                team=team,
                agents=agents,
                kills=stat_values["kills"],
                deaths=stat_values["deaths"],
                assists=stat_values["assists"],
                acs=stat_values["acs"],
                adr=stat_values["adr"],
                rating=stat_values["rating"],
                country_code=country_code,
                country_name=country_name,
                player_url=player_url,
                agent_image_urls=agent_image_urls,
                kast=stat_values["kast"],
                headshot_percent=stat_values["headshot_percent"],
                first_kills=stat_values["first_kills"],
                first_deaths=stat_values["first_deaths"],
                kd_diff=stat_values["kd_diff"],
                fk_diff=stat_values["fk_diff"],
            )
            stat.stats_available = self._player_has_effective_stats(stat)
            players.append(stat)
        return players

    def _aggregate_report_players_from_maps(self, map_players: Any) -> list[PlayerStat]:
        aggregated: dict[tuple[str, str], dict[str, Any]] = {}
        order: list[tuple[str, str]] = []
        for players in map_players:
            if not self._players_have_effective_stats(players):
                continue
            for player in players:
                key = (player.team.casefold(), player.player.casefold())
                if key not in aggregated:
                    aggregated[key] = {
                        "player": player.player,
                        "team": player.team,
                        "agents": [],
                        "agent_image_urls": [],
                        "country_code": player.country_code,
                        "country_name": player.country_name,
                        "player_url": player.player_url,
                        "avatar_url": player.avatar_url,
                        "kills": 0,
                        "deaths": 0,
                        "assists": 0,
                        "first_kills": 0,
                        "first_deaths": 0,
                        "has_kda": False,
                        "metric_values": {
                            "acs": [],
                            "adr": [],
                            "rating": [],
                            "kast": [],
                            "headshot_percent": [],
                        },
                        "percent_metrics": set(),
                    }
                    order.append(key)
                item = aggregated[key]
                if player.country_code and not item["country_code"]:
                    item["country_code"] = player.country_code
                if player.country_name and not item["country_name"]:
                    item["country_name"] = player.country_name
                if player.player_url and not item["player_url"]:
                    item["player_url"] = player.player_url
                for agent in player.agents:
                    if agent and agent not in item["agents"]:
                        item["agents"].append(agent)
                for url in player.agent_image_urls or []:
                    if url and url not in item["agent_image_urls"]:
                        item["agent_image_urls"].append(url)
                for field in (
                    "kills",
                    "deaths",
                    "assists",
                    "first_kills",
                    "first_deaths",
                ):
                    value = self._parse_report_int(getattr(player, field))
                    if value is None:
                        continue
                    item[field] += value
                    if field in {"kills", "deaths", "assists"}:
                        item["has_kda"] = True
                for field in ("acs", "adr", "rating", "kast", "headshot_percent"):
                    value = self._parse_report_float(getattr(player, field))
                    if value is None:
                        continue
                    item["metric_values"][field].append(value)
                    if "%" in str(getattr(player, field) or ""):
                        item["percent_metrics"].add(field)

        results: list[PlayerStat] = []
        for key in order:
            item = aggregated[key]
            metric_values = item["metric_values"]
            kills = item["kills"] if item["has_kda"] else None
            deaths = item["deaths"] if item["has_kda"] else None
            first_kills = (
                item["first_kills"]
                if item["first_kills"] or item["first_deaths"]
                else None
            )
            first_deaths = (
                item["first_deaths"]
                if item["first_kills"] or item["first_deaths"]
                else None
            )
            results.append(
                PlayerStat(
                    player=item["player"],
                    team=item["team"],
                    agents=item["agents"],
                    kills=str(kills) if kills is not None else "",
                    deaths=str(deaths) if deaths is not None else "",
                    assists=str(item["assists"]) if item["has_kda"] else "",
                    acs=self._format_report_average(metric_values["acs"]),
                    adr=self._format_report_average(metric_values["adr"], decimals=1),
                    rating=self._format_report_average(
                        metric_values["rating"], decimals=2
                    ),
                    country_code=item["country_code"],
                    country_name=item["country_name"],
                    player_url=item["player_url"],
                    avatar_url=item["avatar_url"],
                    agent_image_urls=item["agent_image_urls"],
                    kast=self._format_report_average(
                        metric_values["kast"],
                        percent="kast" in item["percent_metrics"],
                    ),
                    headshot_percent=self._format_report_average(
                        metric_values["headshot_percent"],
                        percent="headshot_percent" in item["percent_metrics"],
                    ),
                    first_kills=str(first_kills) if first_kills is not None else "",
                    first_deaths=str(first_deaths) if first_deaths is not None else "",
                    kd_diff=(
                        self._format_report_signed(item["kills"] - item["deaths"])
                        if item["has_kda"]
                        else ""
                    ),
                    fk_diff=(
                        self._format_report_signed(
                            item["first_kills"] - item["first_deaths"]
                        )
                        if first_kills is not None and first_deaths is not None
                        else ""
                    ),
                    stats_available=True,
                )
            )
        return results

    @classmethod
    def _players_have_effective_stats(cls, players: list[PlayerStat]) -> bool:
        return any(cls._player_has_effective_stats(player) for player in players)

    @classmethod
    def is_completed_report_map(cls, map_score: MapScore) -> bool:
        if not cls.has_completed_map_score(map_score):
            return False
        players = list(map_score.players or [])
        return cls.has_complete_player_stats(players)

    @staticmethod
    def has_completed_map_score(map_score: MapScore) -> bool:
        try:
            left = int(map_score.team_a_score)
            right = int(map_score.team_b_score)
        except (TypeError, ValueError):
            return False
        if max(left, right) < 13 or abs(left - right) < 2:
            return False
        return True

    @classmethod
    def has_complete_player_stats(cls, players: list[PlayerStat]) -> bool:
        return len(players) >= 10 and all(
            cls._player_has_complete_map_stats(player) for player in players
        )

    @staticmethod
    def _player_has_complete_map_stats(player: PlayerStat) -> bool:
        if not player.agents:
            return False
        required_values = (player.kills, player.deaths, player.assists, player.acs)
        return all(re.search(r"\d", str(value or "")) for value in required_values)

    @staticmethod
    def _player_has_effective_stats(player: PlayerStat) -> bool:
        stat_values = (
            player.kills,
            player.deaths,
            player.assists,
            player.acs,
            player.adr,
            player.rating,
            player.kast,
            player.headshot_percent,
            player.first_kills,
            player.first_deaths,
        )
        return bool(
            player.agents
            or any(re.search(r"\d", str(value or "")) for value in stat_values)
        )

    @staticmethod
    def _parse_report_int(value: str) -> int | None:
        match = re.search(r"[-+]?\d+", str(value or ""))
        return int(match.group(0)) if match else None

    @staticmethod
    def _parse_report_float(value: str) -> float | None:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
        return float(match.group(0)) if match else None

    @staticmethod
    def _format_report_average(
        values: list[float], *, decimals: int = 0, percent: bool = False
    ) -> str:
        if not values:
            return ""
        average = sum(values) / len(values)
        if decimals <= 0:
            text = str(int(round(average)))
        else:
            text = f"{average:.{decimals}f}"
        return f"{text}%" if percent else text

    @staticmethod
    def _format_report_signed(value: int) -> str:
        return f"+{value}" if value > 0 else str(value)

    def _parse_report_community_comments(self, soup: Any) -> list[str]:
        posts: list[tuple[int, int, str]] = []
        for order, post in enumerate(soup.select(".post")):
            body = post.select_one(".post-body")
            if body is None:
                continue
            text = self._clean_community_comment(self._node_text(body))
            if not text:
                continue
            posts.append(
                (self._post_number(post, order), self._post_frag_score(post), text)
            )

        if not posts:
            return []

        max_number = max(number for number, _, _ in posts)
        latest_cutoff = max(1, max_number - max(40, len(posts) // 3))
        latest_posts = [item for item in posts if item[0] >= latest_cutoff]
        pool = latest_posts or posts
        pool.sort(key=lambda item: (item[1], item[0]), reverse=True)

        comments: list[str] = []
        seen: set[str] = set()
        for _, _, text in pool:
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            comments.append(text)
            if len(comments) >= 8:
                break
        return comments

    @staticmethod
    def _post_number(post: Any, fallback: int) -> int:
        node = post.select_one(".post-header-num")
        text = node.get_text(" ", strip=True) if node is not None else ""
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else fallback

    @staticmethod
    def _post_frag_score(post: Any) -> int:
        node = post.select_one(".post-frag-count")
        text = node.get_text(" ", strip=True) if node is not None else ""
        match = re.search(r"-?\d+", text)
        return int(match.group(0)) if match else 0

    @staticmethod
    def _clean_community_comment(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(cleaned) < 12:
            return ""
        lower = cleaned.casefold()
        blocked_terms = {
            "fuck",
            "shit",
            "bitch",
            "cunt",
            "retard",
            "shitternal",
            "turkekw",
        }
        if any(term in lower for term in blocked_terms):
            return ""
        if "http://" in lower or "https://" in lower:
            return ""
        if len(cleaned) > 180:
            cleaned = cleaned[:177].rstrip() + "..."
        return cleaned

    async def _enrich_player_avatars(self, players: list[PlayerStat]) -> None:
        semaphore = asyncio.Semaphore(3)

        async def enrich_one(player: PlayerStat) -> None:
            if not player.player_url:
                return
            async with semaphore:
                detail = await self._get_vlr_player_info(player.player_url)
            avatar_url = detail.get("avatar_url", "")
            if avatar_url:
                player.avatar_url = avatar_url

        await asyncio.gather(*(enrich_one(player) for player in players))

    async def _get_vlr_player_info(self, player_url: str) -> dict[str, str]:
        href = self._normalize_player_href(player_url)
        if not href:
            return {}
        cached = self._player_cache.get(href)
        if cached is not None:
            return cached
        cache_key = f"vlr-player:{href}"
        cached_value = self._cache_get(cache_key)
        if isinstance(cached_value, dict):
            normalized = {str(key): str(value) for key, value in cached_value.items()}
            self._player_cache[href] = normalized
            return normalized
        url = urljoin(f"{self.web_url}/", href.lstrip("/"))
        try:
            response = await self._request("GET", url, headers=self.browser_headers)
        except Exception:
            self._player_cache[href] = {}
            return {}
        avatar_url = ""
        if BeautifulSoup is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            avatar_img = soup.select_one(".wf-avatar.mod-player img")
            if avatar_img is not None:
                avatar_url = self._normalize_asset_url(str(avatar_img.get("src") or ""))
        if not avatar_url:
            match = re.search(
                r'<meta\s+property="og:image"\s+content="([^"]+)"',
                response.text,
                flags=re.I,
            )
            if match:
                avatar_url = self._normalize_asset_url(match.group(1))
        detail = {"avatar_url": avatar_url}
        self._player_cache[href] = detail
        self._cache_set(cache_key, detail, ttl=max(self.cache_ttl_seconds, 86400))
        return detail

    @staticmethod
    def _flag_info(flag_node: Any) -> tuple[str, str]:
        if flag_node is None:
            return "", ""
        classes = flag_node.get("class") or []
        code = ""
        for class_name in classes:
            text = str(class_name)
            if text.startswith("mod-"):
                code = text.removeprefix("mod-").upper()
                break
        title = str(flag_node.get("title") or "").strip()
        return code, title

    @staticmethod
    def _map_image_url(map_name: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(map_name or "")).strip()
        if not cleaned:
            return ""
        for name, url in VALORANT_MAP_SPLASH_URLS.items():
            if name.casefold() == cleaned.casefold():
                return url
        return ""

    def _normalize_player_href(self, value: str) -> str:
        text = str(value or "").strip()
        if text.startswith(self.web_url):
            text = text[len(self.web_url) :]
        if text.startswith("https://www.vlr.gg"):
            text = text[len("https://www.vlr.gg") :]
        if text.startswith("http://www.vlr.gg"):
            text = text[len("http://www.vlr.gg") :]
        if text.startswith("/player/"):
            return text.split("#", 1)[0]
        match = re.search(r"(?:vlr\.gg)?(/player/\d+/[^\\s?#]+)", text)
        return match.group(1) if match else ""

    @staticmethod
    def _node_text(node: Any) -> str:
        if node is None:
            return ""
        return str(node.get_text(" ", strip=True))

    def _stat_value(self, row: Any, selector: str) -> str:
        node = row.select_one(selector)
        if node is None:
            return ""
        both = node.select_one(".mod-both")
        return self._node_text(both or node).replace("/", "").strip()

    async def _normalize_matches_to_display_timezone(
        self, matches: list[MatchRecord]
    ) -> None:
        if not matches:
            return
        unresolved = [
            match
            for match in matches
            if not (isinstance(match.raw, dict) and match.raw.get("detail_utc_used"))
        ]
        if not unresolved:
            self.last_page_display_offset = None
            return
        if self._page_display_offset is None:
            self._page_display_offset = await self._infer_page_display_offset(
                unresolved
            )
        self.last_page_display_offset = self._page_display_offset
        if self._page_display_offset is None:
            return
        target_tz = ZoneInfo(self.display_timezone)
        page_tz = timezone(self._page_display_offset)
        for match in unresolved:
            display_dt = self._match_display_datetime(match)
            if display_dt is None:
                continue
            localized = display_dt.replace(tzinfo=page_tz).astimezone(target_tz)
            match.match_date = localized.date().isoformat()
            match.start_time = localized.strftime("%H:%M")

    async def _infer_page_display_offset(
        self, matches: list[MatchRecord]
    ) -> timedelta | None:
        for match in matches[: min(6, len(matches))]:
            href = match.raw.get("href") if isinstance(match.raw, dict) else None
            if not isinstance(href, str) or not href:
                continue
            display_dt = self._match_display_datetime(match)
            if display_dt is None:
                continue
            detail = await self._get_vlr_match_detail_info(href)
            utc_dt = detail.get("utc_dt")
            if not isinstance(utc_dt, datetime):
                continue
            offset = display_dt - utc_dt.replace(tzinfo=None)
            return self._round_offset(offset)
        return None

    def _match_display_datetime(self, match: MatchRecord) -> datetime | None:
        raw = match.raw if isinstance(match.raw, dict) else {}
        section_date_text = raw.get("display_section_date")
        time_text = raw.get("display_time_text")
        if not isinstance(section_date_text, str) or not isinstance(time_text, str):
            return None
        section_date = self._parse_iso_date(section_date_text)
        parsed_time = self._parse_vlr_time_to_obj(time_text)
        if section_date is None or parsed_time is None:
            return None
        return datetime.combine(section_date, parsed_time)

    @staticmethod
    def _round_offset(offset: timedelta) -> timedelta:
        seconds = int(round(offset.total_seconds() / 900) * 900)
        return timedelta(seconds=seconds)

    @staticmethod
    def format_offset_label(offset: timedelta | None) -> str:
        if offset is None:
            return "(unknown)"
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        total_minutes = abs(total_minutes)
        hours, minutes = divmod(total_minutes, 60)
        return f"UTC{sign}{hours:02d}:{minutes:02d}"

    @staticmethod
    def _normalize_asset_url(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith("//"):
            return f"https:{text}"
        if text.startswith("/"):
            return f"https://www.vlr.gg{text}"
        return text

    def _match_href(self, match: MatchRecord) -> str:
        raw = match.raw if isinstance(match.raw, dict) else {}
        href = raw.get("href")
        if isinstance(href, str) and href.strip():
            return self._normalize_match_href(href, match.match_id)
        return self._normalize_match_href(str(match.match_id or ""), match.match_id)

    def _normalize_match_href(self, value: str, match_id: str = "") -> str:
        text = str(value or "").strip()
        if text.startswith(self.web_url):
            text = text[len(self.web_url) :]
        if text.startswith("https://www.vlr.gg"):
            text = text[len("https://www.vlr.gg") :]
        if text.startswith("http://www.vlr.gg"):
            text = text[len("http://www.vlr.gg") :]
        if text.startswith("/"):
            return text.split("#", 1)[0]
        match = re.search(r"(?:vlr\.gg/)?(\d{4,})(?:/[^\\s?#]*)?", text)
        if match:
            suffix = text[match.end(1) :]
            if suffix.startswith("/"):
                return f"/{match.group(1)}{suffix.split('#', 1)[0]}"
            return f"/{match.group(1)}"
        if str(match_id or "").isdigit():
            return f"/{match_id}"
        return ""

    @staticmethod
    def _strip_timezone_suffix(text: str) -> str:
        cleaned = BaseMatchClient._strip_tags(text)
        return re.sub(r"\s+[A-Z]{2,5}$", "", cleaned).strip()

    @staticmethod
    def _extract_timezone_suffix(text: str) -> str:
        cleaned = BaseMatchClient._strip_tags(text)
        match = re.search(r"\s+([A-Z]{2,5})$", cleaned)
        if not match:
            return ""
        suffix = match.group(1)
        if suffix == "CST":
            return "CST"
        return suffix

    def _detail_timezone_offset(self, display_time_text: str) -> timedelta | None:
        suffix = self._extract_timezone_suffix(display_time_text)
        if not suffix:
            return None
        if suffix == "CST":
            # VLR's rendered CST is China Standard Time in this environment.
            return VLR_TIMEZONE_OFFSETS["CST"]
        return VLR_TIMEZONE_OFFSETS.get(suffix)

    def _parse_detail_display_datetime(
        self,
        display_date_text: str,
        display_time_text: str,
        timestamp_text: str,
    ) -> datetime | None:
        if not display_date_text or not display_time_text:
            return None
        cleaned_time = self._strip_timezone_suffix(display_time_text)
        parsed_time = self._parse_vlr_time_to_obj(cleaned_time)
        if parsed_time is None:
            return None
        reference_year = None
        with contextlib.suppress(ValueError):
            reference_year = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S").year
        if reference_year is None:
            reference_year = self._today_in_display_timezone().year
        parsed_date = self._parse_vlr_date_label(
            f"{display_date_text}, {reference_year}"
        )
        if parsed_date is None:
            return None
        display_dt = datetime.combine(parsed_date, parsed_time)
        offset = self._detail_timezone_offset(display_time_text)
        if offset is None:
            return display_dt
        return (
            display_dt.replace(tzinfo=timezone(offset))
            .astimezone(self._get_display_tz())
            .replace(tzinfo=None)
        )

    @staticmethod
    def _parse_vlr_source_timestamp(value: str) -> datetime:
        source_tz = ZoneInfo("America/New_York")
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=source_tz)
        return parsed.astimezone(timezone.utc)

    def _parse_vlr_datetime(self, item: dict[str, Any]) -> datetime | None:
        for key in (
            "unix_timestamp",
            "utc",
            "time",
            "date",
            "datetime",
            "match_time",
            "timestamp",
        ):
            value = self._coalesce(item, [key])
            if value is None:
                continue
            parsed = self._parse_vlr_datetime_value(value, key)
            if parsed is not None:
                return parsed
        return None

    def _parse_vlr_datetime_value(self, value: Any, key: str) -> datetime | None:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if isinstance(value, str):
            raw_text = value.strip()
            if re.fullmatch(r"\d{10,13}", raw_text):
                timestamp = float(raw_text)
                if timestamp > 1_000_000_000_000:
                    timestamp /= 1000
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            text = raw_text.replace("Z", "+00:00")
            for parser in (
                lambda: datetime.fromisoformat(text),
                lambda: datetime.strptime(text, "%Y-%m-%d %H:%M:%S"),
                lambda: datetime.strptime(text, "%Y-%m-%d %H:%M"),
            ):
                with contextlib.suppress(ValueError):
                    parsed = parser()
                    if parsed.tzinfo is None:
                        if key == "utc":
                            return parsed.replace(tzinfo=timezone.utc)
                        source_tz = ZoneInfo("America/New_York")
                        return parsed.replace(tzinfo=source_tz).astimezone(timezone.utc)
                    return parsed
        return None

    @staticmethod
    def _parse_vlr_date_label(label: str) -> date | None:
        normalized = BaseMatchClient._strip_tags(label)
        # VLR uses English months regardless of the host process LC_TIME.
        match = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\b", normalized)
        if not match:
            return None
        months = (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        )
        month = next(
            (
                i
                for i, name in enumerate(months, 1)
                if match[1].lower() in (name.lower(), name[:3].lower())
            ),
            None,
        )
        if month is None:
            return None
        with contextlib.suppress(ValueError):
            return date(int(match[3]), month, int(match[2]))
        return None

    @staticmethod
    def _normalize_vlr_time(text: str) -> str:
        cleaned = BaseMatchClient._strip_tags(text)
        parsed = VlrClient._parse_vlr_time_to_obj(cleaned)
        return parsed.strftime("%H:%M") if parsed else cleaned or "--:--"

    @staticmethod
    def _parse_vlr_time_to_obj(text: str) -> dt_time | None:
        cleaned = BaseMatchClient._strip_tags(text)
        match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)?", cleaned, re.I)
        if not match:
            return None
        hour, minute = int(match[1]), int(match[2] or 0)
        if match[3]:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if match[3].upper() == "PM" else 0)
        elif match[2] is None:
            return None
        with contextlib.suppress(ValueError):
            return dt_time(hour, minute)
        return None

    @staticmethod
    def _normalize_vlr_status(value: str) -> str:
        normalized = (value or "").strip().lower()
        if not normalized:
            return "未知"
        if "upcoming" in normalized:
            return "未开始"
        if "live" in normalized:
            return "进行中"
        if "completed" in normalized:
            return "已结束"
        if "postponed" in normalized:
            return "已延期"
        if "cancel" in normalized:
            return "已取消"
        return value.strip()

    @staticmethod
    def _clean_score(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"–", "&ndash;", "-"}:
            return None
        return text

    @staticmethod
    def _format_score(left: Any, right: Any) -> str:
        if left in (None, "") and right in (None, ""):
            return "-"
        return f"{left if left not in (None, '') else '-'}:{right if right not in (None, '') else '-'}"

    @staticmethod
    def _extract_bo_from_text(text: str) -> str:
        cleaned = BaseMatchClient._strip_tags(text)
        match = re.search(r"\bBo\d+\b", cleaned, flags=re.I)
        return match.group(0) if match else ""

    @staticmethod
    def _infer_vlr_level(tournament_name: str, schedule_name: str) -> str:
        text = f"{tournament_name} {schedule_name}".lower()
        if any(keyword in text for keyword in ["champions", "masters", "kickoff"]):
            return "S"
        if any(
            keyword in text
            for keyword in [
                "americas stage",
                "emea stage",
                "pacific stage",
                "china stage",
                "vct 202",
            ]
        ):
            return "S"
        if "ascension" in text:
            return "A"
        if "challengers" in text:
            return "A"
        if "game changers" in text:
            return "A"
        if "qualifier" in text:
            return "B"
        if "off" in text and "season" in text:
            return "B"
        return "B"

    @staticmethod
    def _first_group(text: str, pattern: str) -> str:
        match = re.search(pattern, text, flags=re.S)
        return BaseMatchClient._strip_tags(match.group(1)) if match else ""

    @staticmethod
    def _safe_bool(value: Any, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _coalesce(self, data: Any, paths: list[str], default: Any = None) -> Any:
        for path in paths:
            current = data
            found = True
            for part in path.split("."):
                if isinstance(current, dict):
                    current = current.get(part)
                elif isinstance(current, list) and part.isdigit():
                    index = int(part)
                    if 0 <= index < len(current):
                        current = current[index]
                    else:
                        found = False
                        break
                else:
                    found = False
                    break
            if found and current not in (None, "", [], {}):
                return current
        return default
