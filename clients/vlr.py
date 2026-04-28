from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx


class MatchSourceError(Exception):
    """Raised when a match source request or parser fails."""


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
        return str(self.config.get("display_timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"

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
                    raise MatchSourceError(f"请求返回 HTTP {response.status_code}: {url}")
                return response
            except (httpx.TimeoutException, httpx.HTTPError, MatchSourceError) as exc:
                last_exc = exc
                previous_info = self._last_request_info
                self._last_request_info = RequestDebugInfo(
                    url=url,
                    status_code=(
                        previous_info.status_code
                        if previous_info and previous_info.url == url
                        else getattr(getattr(exc, "response", None), "status_code", None)
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
        self._page_display_offset: timedelta | None = None
        self.last_page_display_offset: timedelta | None = None
        self.last_detail_time_source: str = ""

    @property
    def api_url(self) -> str:
        return str(self.config.get("vlr_api_url") or "https://vlrggapi.vercel.app").rstrip("/")

    @property
    def web_url(self) -> str:
        return str(self.config.get("vlr_web_base_url") or "https://www.vlr.gg").rstrip("/")

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
    def browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            )
        }

    async def get_matches_by_date(self, target_date: date) -> list[MatchRecord]:
        cache_key = f"vlr:{target_date.isoformat()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            self.last_cache_hit = True
            self.last_parsed_count = len(cached)
            return cached

        self.last_cache_hit = False
        errors: list[str] = []
        for loader in (self._load_from_vlr_api, self._load_from_vlr_html):
            try:
                matches = await loader(target_date)
                if matches:
                    self.last_success_api = self.last_request_info.url if self.last_request_info else ""
                    self.last_failure_reason = ""
                    self.last_parsed_count = len(matches)
                    self._cache_set(cache_key, matches)
                    return matches
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{loader.__name__}: {self._describe_error(exc)}")
        self.last_failure_reason = " | ".join(errors) if errors else "未找到比赛数据。"
        self.last_parsed_count = 0
        self._cache_set(cache_key, [])
        return []

    async def discover_tournaments(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        page_specs = (
            ("schedule", max(self._safe_int(self.config.get("vlr_schedule_pages"), 3), 1), False),
            ("results", max(self._safe_int(self.config.get("vlr_results_pages"), 3), 1), True),
        )
        for kind, max_pages, completed in page_specs:
            for page in range(1, max_pages + 1):
                html = await self._get_vlr_page(kind, page)
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
        return sorted(names, key=str.casefold)

    async def debug_probe(self, target_date: date) -> RequestDebugInfo:
        try:
            await self._probe_vlr_api()
            if self._last_request_info:
                return self._last_request_info
        except Exception:
            pass

        try:
            await self._request("GET", f"{self.web_url}/matches", headers=self.browser_headers)
        except Exception as exc:  # noqa: BLE001
            return RequestDebugInfo(
                url=f"{self.web_url}/matches",
                status_code=self._last_request_info.status_code if self._last_request_info else None,
                response_preview=self._last_request_info.response_preview if self._last_request_info else "",
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
        schedule_payloads: list[tuple[str, str]] = [("upcoming", "upcoming"), ("live_score", "live")]
        today = self._today_in_display_timezone()
        if target_date <= today:
            schedule_payloads.append(("results", "completed"))

        aggregated: list[MatchRecord] = []
        for query, default_status in schedule_payloads:
            response = await self._request("GET", f"{self.api_url}/match", params={"q": query})
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
            await self._fill_best_of_from_details(aggregated[: self.max_detail_fetch_matches])
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
        status = str(self._coalesce(item, ["status"], default_status) or default_status).strip()
        return MatchRecord(
            match_id=str(self._coalesce(item, ["id", "match_id", "url"]) or ""),
            match_date=display_dt.date().isoformat(),
            start_time=display_dt.strftime("%H:%M"),
            status=self._normalize_vlr_status(status),
            team_a=str(self._coalesce(item, ["team_a", "team1", "teamA", "teams.0.name"]) or "TBD"),
            team_b=str(self._coalesce(item, ["team_b", "team2", "teamB", "teams.1.name"]) or "TBD"),
            score=self._format_score(
                self._coalesce(item, ["score_a", "team1_score", "scores.0"]),
                self._coalesce(item, ["score_b", "team2_score", "scores.1"]),
            ),
            tournament_name=str(tournament or "未知赛事").strip(),
            schedule_name=str(series or "").strip(),
            level=self._infer_vlr_level(str(tournament or ""), str(series or "")),
            best_of=str(self._coalesce(item, ["bo", "best_of"], "")),
            source=self.source_name,
            raw=item,
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

        await self._fill_match_times_from_details(matches)
        await self._normalize_matches_to_display_timezone(matches)
        matches = [match for match in matches if match.match_date == target_date.isoformat()]

        deduped: dict[str, MatchRecord] = {}
        for match in matches:
            key = match.match_id or f"{match.match_date}:{match.start_time}:{match.team_a}:{match.team_b}"
            deduped[key] = match
        results = sorted(
            deduped.values(),
            key=lambda item: (item.match_date, item.start_time, item.tournament_name, item.team_a),
        )
        if results and self.fetch_bo_from_details:
            await self._fill_best_of_from_details(results[: self.max_detail_fetch_matches])
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
            url = f"{self.web_url}/matches" if page == 1 else f"{self.web_url}/matches/?page={page}"
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
            end = date_sections[index + 1].start() if index + 1 < len(date_sections) else len(html)
            section_html = html[start:end]
            matches.extend(self._parse_vlr_match_blocks(section_html, section_date, completed))
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
            tournament_name = self._strip_tags(tournament_match.group(1)) if tournament_match else "未知赛事"
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
            status = self._normalize_vlr_status(status_text or ("Completed" if completed else "Upcoming"))
            best_of = self._extract_bo_from_text(note_text)
            match_id = href.strip("/").split("/", 1)[0]

            results.append(
                MatchRecord(
                    match_id=match_id,
                    match_date=section_date.isoformat(),
                    start_time=start_time,
                    status=status if status != "未知" else self._normalize_vlr_status(eta_text),
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
        for match in matches:
            href = match.raw.get("href") if isinstance(match.raw, dict) else None
            if not isinstance(href, str) or not href:
                continue
            detail = await self._get_vlr_match_detail_info(href)
            if not match.best_of and isinstance(detail.get("best_of"), str):
                match.best_of = str(detail.get("best_of") or "")
            if isinstance(match.raw, dict):
                match.raw["team_a_logo_url"] = detail.get("team_a_logo_url") or ""
                match.raw["team_b_logo_url"] = detail.get("team_b_logo_url") or ""
                match.raw["team_a_display_name"] = detail.get("team_a_display_name") or match.team_a
                match.raw["team_b_display_name"] = detail.get("team_b_display_name") or match.team_b
                match.raw["event_logo_url"] = detail.get("event_logo_url") or ""

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
            elif isinstance(utc_dt, datetime):
                localized = utc_dt.astimezone(self._get_display_tz())
                match.match_date = localized.date().isoformat()
                match.start_time = localized.strftime("%H:%M")
                self.last_detail_time_source = "DETAIL_UTC"
            else:
                continue
            if isinstance(match.raw, dict):
                match.raw["detail_utc_used"] = True
                match.raw["detail_time_source"] = self.last_detail_time_source
                match.raw["team_a_logo_url"] = detail.get("team_a_logo_url") or ""
                match.raw["team_b_logo_url"] = detail.get("team_b_logo_url") or ""
                match.raw["team_a_display_name"] = detail.get("team_a_display_name") or match.team_a
                match.raw["team_b_display_name"] = detail.get("team_b_display_name") or match.team_b
                match.raw["event_logo_url"] = detail.get("event_logo_url") or ""

    async def _get_vlr_match_detail_info(self, href: str) -> dict[str, Any]:
        cached = self._detail_cache.get(href)
        if cached is not None:
            return cached
        cache_key = f"vlr-bo:{href}"
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
                utc_dt = datetime.strptime(utc_match.group(1), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
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
        event_block = re.search(
            r'<a[^>]+class="match-header-event"[^>]*>(.*?)</a>',
            response.text,
            flags=re.S | re.I,
        )
        if event_block:
            event_img = re.search(r'<img\s+src="([^"]+)"', event_block.group(1), flags=re.I)
            if event_img:
                event_logo_url = self._normalize_asset_url(event_img.group(1))
        detail = {
            "best_of": match.group(1).strip() if match else "",
            "utc_dt": utc_dt,
            "timestamp_text": timestamp_text,
            "display_date_text": display_date_text,
            "display_time_text": display_time_text,
            "display_dt": display_dt,
            "team_a_display_name": team_a_display_name,
            "team_b_display_name": team_b_display_name,
            "team_a_logo_url": team_logo_map.get(team_a_display_name, ""),
            "team_b_logo_url": team_logo_map.get(team_b_display_name, ""),
            "event_logo_url": event_logo_url,
        }
        self._detail_cache[href] = detail
        self._cache_set(cache_key, detail, ttl=max(self.cache_ttl_seconds, 3600))
        return detail

    async def _normalize_matches_to_display_timezone(self, matches: list[MatchRecord]) -> None:
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
            self._page_display_offset = await self._infer_page_display_offset(unresolved)
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

    async def _infer_page_display_offset(self, matches: list[MatchRecord]) -> timedelta | None:
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

    @staticmethod
    def _strip_timezone_suffix(text: str) -> str:
        cleaned = BaseMatchClient._strip_tags(text)
        return re.sub(r"\s+[A-Z]{2,5}$", "", cleaned).strip()

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
        for parser in ("%A, %B %d", "%a, %B %d"):
            with contextlib.suppress(ValueError):
                parsed_date = datetime.strptime(display_date_text, parser).date().replace(year=reference_year)
                return datetime.combine(parsed_date, parsed_time)
        return None

    def _parse_vlr_datetime(self, item: dict[str, Any]) -> datetime | None:
        value = self._coalesce(
            item,
            ["utc", "time", "date", "datetime", "match_time", "timestamp"],
        )
        if value is None:
            return None
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if isinstance(value, str):
            text = value.strip().replace("Z", "+00:00")
            for parser in (
                lambda: datetime.fromisoformat(text),
                lambda: datetime.strptime(text, "%Y-%m-%d %H:%M:%S"),
                lambda: datetime.strptime(text, "%Y-%m-%d %H:%M"),
            ):
                with contextlib.suppress(ValueError):
                    return parser()
        return None

    @staticmethod
    def _parse_vlr_date_label(label: str) -> date | None:
        normalized = BaseMatchClient._strip_tags(label)
        match = re.search(
            r"([A-Za-z]{3,9},\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})",
            normalized,
        )
        candidate = match.group(1) if match else normalized.strip()
        for parser in ("%a, %B %d, %Y", "%A, %B %d, %Y"):
            with contextlib.suppress(ValueError):
                return datetime.strptime(candidate, parser).date()
        return None

    @staticmethod
    def _normalize_vlr_time(text: str) -> str:
        cleaned = BaseMatchClient._strip_tags(text)
        if not cleaned:
            return "--:--"
        for parser in ("%I:%M %p", "%I %p"):
            with contextlib.suppress(ValueError):
                return datetime.strptime(cleaned, parser).strftime("%H:%M")
        return cleaned

    @staticmethod
    def _parse_vlr_time_to_obj(text: str) -> dt_time | None:
        cleaned = BaseMatchClient._strip_tags(text)
        if not cleaned:
            return None
        for parser in ("%I:%M %p", "%I %p", "%H:%M"):
            with contextlib.suppress(ValueError):
                return datetime.strptime(cleaned, parser).time()
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
        if any(keyword in text for keyword in ["americas stage", "emea stage", "pacific stage", "china stage", "vct 202"]):
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
