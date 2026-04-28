from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VLR client offline smoke test")
    parser.add_argument("--date", dest="custom_date", help="指定查询日期，格式 YYYY-MM-DD")
    parser.add_argument("--level", dest="level", help="按等级过滤，例如 S 或 A", default="")
    return parser.parse_args()


def split_levels(raw: str) -> list[str]:
    text = (
        str(raw or "")
        .replace("\n", ",")
        .replace("，", ",")
        .replace("；", ",")
        .replace(";", ",")
    )
    return [item.strip() for item in text.split(",") if item.strip()]


def normalize_level(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text.replace("级", "").replace(" ", "")


def filter_by_levels(matches: list[Any], levels: list[str]) -> list[Any]:
    if not levels:
        return matches
    normalized_levels = {normalize_level(level) for level in levels if level}
    filtered: list[Any] = []
    for match in matches:
        match_level = normalize_level(match.level)
        if match_level and match_level in normalized_levels:
            filtered.append(match)
    return filtered


def format_match(match: Any) -> str:
    title = match.tournament_name or "未知赛事"
    if match.schedule_name and match.schedule_name not in title:
        title = f"{title} / {match.schedule_name}"
    return (
        f"- {match.start_time} | {title} | {match.level or '-'} | "
        f"{match.team_a} vs {match.team_b} | {match.best_of or 'Bo?'} | {match.status}"
    )


async def run_query(client: Any, label: str, target_date: date, levels: list[str]) -> None:
    print(f"== {label}: {target_date.isoformat()} ==")
    print(f"display_timezone: {client.display_timezone}")
    matches = await client.get_matches_by_date(target_date)
    filtered = filter_by_levels(matches, levels)
    print(f"parsed_count: {len(matches)}")
    if levels:
        print(f"filtered_count: {len(filtered)}")
        print(f"levels: {', '.join(levels)}")
    preview = filtered if levels else matches
    if preview:
        for match in preview[:5]:
            print(format_match(match))
    else:
        request_entry = client.last_request_info.url if client.last_request_info else client.last_success_api
        print(f"last_failure_reason: {client.last_failure_reason or '(empty)'}")
        print(f"request_entry: {request_entry or '(none)'}")
    print()


async def main_async(args: argparse.Namespace) -> int:
    from clients.vlr import VlrClient

    custom_date = date.fromisoformat(args.custom_date) if args.custom_date else date.today()
    levels = split_levels(args.level)
    config: dict[str, Any] = {
        "vlr_api_url": "https://vlrggapi.vercel.app",
        "vlr_web_base_url": "https://www.vlr.gg",
        "display_timezone": "Asia/Shanghai",
        "request_timeout_seconds": 10,
        "retry_count": 2,
        "cache_ttl_seconds": 300,
        "include_completed": True,
        "fetch_bo_from_details": True,
        "max_detail_fetch_matches": 5,
        "vlr_schedule_pages": 3,
        "vlr_results_pages": 3,
    }
    for label, target_date in (
        ("today", date.today()),
        ("tomorrow", date.today() + timedelta(days=1)),
        ("custom_date", custom_date),
    ):
        client = VlrClient(config)
        try:
            await run_query(client, label, target_date, levels)
        finally:
            await client.close()
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except ValueError as exc:
        print(f"invalid_date: {exc}")
        return 2
    except ModuleNotFoundError as exc:
        print(f"missing_dependency: {exc.name}")
        print("请先执行: pip install -r requirements.txt")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
