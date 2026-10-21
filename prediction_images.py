"""Build image payloads using the existing Studio typography and cached logos."""

import asyncio
import base64
import hashlib
import math
import time
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image

try:
    from .prediction_render import prediction_card, prediction_leaderboard
except ImportError:
    from prediction_render import prediction_card, prediction_leaderboard


class PredictionImages:
    async def _attach_prediction_avatars(self, group, rows):
        # QQ identifiers are scoped to the QQ adapter; never reinterpret another platform's IDs.
        try:
            platform = self.context.get_platform_inst(group.split(":", 1)[0])
            if platform.meta().name != "aiocqhttp":
                return
        except (AttributeError, KeyError):
            return
        root = self._prediction_image_root() / "avatars"
        root.mkdir(exist_ok=True)
        semaphore = asyncio.Semaphore(6)

        def valid(path):
            try:
                if not path.is_file() or path.stat().st_size > 1024 * 1024:
                    return False
                with Image.open(path) as image:
                    if max(image.size) > 2048:
                        return False
                    image.verify()
                return True
            except (OSError, ValueError):
                return False

        async with httpx.AsyncClient(
            follow_redirects=True, trust_env=False, timeout=3.0
        ) as client:

            async def avatar(row):
                user = str(row.get("user_id", ""))
                if not user.isascii() or not user.isdigit() or not 5 <= len(user) <= 20:
                    return
                path = root / (user + ".png")
                cached = valid(path)
                if cached:
                    row["avatar_path"] = str(path)
                if cached and time.time() - path.stat().st_mtime < 86400:
                    return
                async with semaphore:
                    try:
                        response = await client.get(
                            "https://q1.qlogo.cn/g",
                            params={"b": "qq", "nk": user, "s": "100"},
                        )
                        response.raise_for_status()
                        if len(response.content) > 1024 * 1024:
                            return
                        temp = path.with_suffix("." + uuid4().hex + ".tmp")
                        try:
                            temp.write_bytes(response.content)
                            if valid(temp):
                                temp.replace(path)
                                row["avatar_path"] = str(path)
                        finally:
                            temp.unlink(missing_ok=True)
                    except (httpx.HTTPError, OSError, ValueError):
                        pass

            try:
                await asyncio.wait_for(
                    asyncio.gather(*(avatar(row) for row in rows)), timeout=8
                )
            except asyncio.TimeoutError:
                pass

    def _prediction_image_root(self):
        db = self.prediction_store.db.execute("PRAGMA database_list").fetchone()[2]
        root = Path(db).parent / "prediction_images"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _prediction_image_theme(self):
        return (
            "studio_light"
            if "light" in str(self.config.get("image_theme", ""))
            else "studio_dark"
        )

    def _prediction_logo(self, value, team):
        if value and str(value).startswith("data:image/") and ";base64," in value:
            try:
                raw = base64.b64decode(value.split(";base64,", 1)[1], validate=True)
                if len(raw) > 1024 * 1024:
                    return None
                path = self._prediction_image_root() / (
                    "logo-" + hashlib.sha256(raw).hexdigest()[:24] + ".png"
                )
                if not path.exists():
                    path.write_bytes(raw)
                return str(path)
            except (ValueError, TypeError):
                return None
        if value and Path(value).is_file():
            return str(value)
        if getattr(self, "image_cache_dir", None):
            return self._find_cached_image_path("teams", team)
        return None

    async def _render_click_image(self, payload, *, demo=False, bot=None):
        render = dict(payload)
        for side in ("a", "b"):
            render["logo_" + side] = self._prediction_logo(
                payload.get("logo_" + side), payload["team_" + side]
            )
        path = self._prediction_image_root() / ("pick-" + uuid4().hex + ".png")
        return await asyncio.to_thread(
            prediction_card,
            render,
            path,
            theme=self._prediction_image_theme(),
            demo=demo,
            bot=bot,
        )

    async def _rank_images(self, group, *, tournament_id=None, day=None, text=""):
        # Match the same event selection as text queries, including historical day batches.
        if tournament_id:
            event = self.prediction_store.tournament(tournament_id)
            if not event:
                raise ValueError("请选择有效的赛事。")
            ids = [event["tournament_id"]]
        else:
            ids = (
                self.prediction_store.rank_day_tournaments(day, group)
                if day
                else self._view_tournament_ids(text)
            )
        paths = []
        name = getattr(self, "_prediction_groups", {}).get(group, "本群")
        now = self._now_in_display_timezone()
        for tid in ids:
            rows = self.prediction_store.leaderboard(group, tid)
            result_day = day or now.date().isoformat()
            results = self.prediction_store.rank_results(
                group, result_day, tid, batch=bool(day)
            )
            people = {r["user_id"]: r for r in rows}
            for result in results:
                for member in result["winners"]:
                    people.setdefault(member["user_id"], member)
                metadata = self.prediction_store.match_metadata(result["match_id"])
                for side in ("a", "b"):
                    result["logo_" + side] = self._prediction_logo(
                        metadata.get("logo_" + side), result["team_" + side]
                    )
            await self._attach_prediction_avatars(group, list(people.values()))
            for result in results:
                for member in result["winners"]:
                    member["avatar_path"] = people[member["user_id"]].get("avatar_path")
            event = self.prediction_store.tournament(tid)
            pages = max(1, math.ceil(len(rows) / 24))
            for page in range(pages):
                path = self._prediction_image_root() / ("rank-" + uuid4().hex + ".png")
                paths.append(
                    await asyncio.to_thread(
                        prediction_leaderboard,
                        name,
                        event["name"],
                        rows[page * 24 : (page + 1) * 24],
                        now,
                        path,
                        theme=self._prediction_image_theme(),
                        page=page + 1,
                        pages=pages,
                        all_rows=rows,
                        rank_day=day,
                        results=results,
                        result_day=result_day,
                    )
                )
        return paths
