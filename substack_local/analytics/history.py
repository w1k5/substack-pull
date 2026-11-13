"""Durable analytics records written from data already fetched by the service."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .derived import number
from ..pullers.posts.storage import atomic_write_json


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else None
    except (TypeError, ValueError):
        return None


class AnalyticsHistory:
    def __init__(self, directory: Path):
        self.directory = directory

    def read(self, kind, key):
        pattern = {"notes": r"[0-9]+", "posts": r"[0-9]+",
                   "sources": r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}-[0-9]{2}-[0-9]{2}"}.get(kind)
        if not pattern or not re.fullmatch(pattern, key):
            raise ValueError("Choose a Note or post ID, or a source range as YYYY-MM-DD_YYYY-MM-DD.")
        try:
            path = self.directory / kind / f"{key}.json"
            if path.is_symlink() or not path.resolve().is_relative_to(self.directory.resolve()):
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(record, dict) and record.get("schema_version") == 1
                    and isinstance(record.get("data"), dict)):
                return record
        except (OSError, ValueError):
            pass
        return None

    def index(self):
        return [{"kind": kind, "key": path.stem}
                for kind in ("notes", "posts", "sources")
                for path in sorted((self.directory / kind).glob("*.json"), reverse=True)
                if not path.is_symlink()]

    def save(self, kind, key, data):
        existing = self.read(kind, key)
        if existing and existing.get("data") == data:
            return
        try:
            atomic_write_json(self.directory / kind / f"{key}.json", {
                "schema_version": 1, "saved_at": datetime.now(timezone.utc).isoformat(),
                "data": data,
            })
        except (OSError, ValueError):
            # Local history is optional when the data directory is unavailable.
            pass

    def note(self, stats):
        published = _timestamp(stats.get("published_at"))
        if published is None:
            return
        points = {}
        for series in stats.get("impression_series") or []:
            key = "impressions" if series.get("is_primary") else "typical_impressions"
            if key in points:
                continue
            points[key] = {}
            for point in series.get("points") or []:
                timestamp = _timestamp(point.get("timestamp"))
                value = number(point.get("value"))
                if timestamp and value is not None and value >= 0:
                    seconds = (timestamp - published).total_seconds()
                    if seconds in (21600, 86400, 172800):
                        points[key][int(seconds / 3600)] = value
        actual = points.get("impressions", {})
        if not actual:
            return
        note_id = stats["id"]
        existing = self.read("notes", note_id) or {}
        prior = existing.get("data", {})
        checkpoints = prior.get("checkpoints", {}).copy() if prior.get("published_at") == stats["published_at"] else {}
        for hour, impressions in actual.items():
            checkpoint = {**checkpoints.get(str(hour), {}), "impressions": impressions}
            typical = points.get("typical_impressions", {}).get(hour)
            if typical is not None:
                checkpoint["typical_impressions"] = typical
            checkpoints[str(hour)] = checkpoint
        self.save("notes", note_id, {"id": note_id, "published_at": stats["published_at"],
                                     "checkpoints": checkpoints})

    def publication(self, snapshot, *, from_cache=False):
        period = snapshot.get("range", {})
        dates = [period.get(key) for key in ("start", "end")]
        if all(isinstance(day, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day)
               for day in dates):
            key = "_".join(dates)
            if from_cache and self.read("sources", key):
                return
            self.save("sources", key, {
                "range": period, "refreshed_at": snapshot.get("refreshed_at"),
                "growth_sources": snapshot.get("growth_sources", []),
                "notes_source_attribution": snapshot.get("notes_source_attribution"),
            })
