"""Private, short-lived disk caches for normalized post and Note analytics."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import re
import tempfile
import time
from zoneinfo import ZoneInfo


NOTE_TTL_SECONDS = 3600
POST_TTL_SECONDS = 3600
POST_INDEX_TTL_SECONDS = 900
POST_WEEK_TTL_SECONDS = 86400
PUBLICATION_TTL_SECONDS = 300
PRUNE_INTERVAL_SECONDS = 3600


def _publication_today() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


class _JsonDiskCache:
    """Atomic JSON cache with one validated record per key."""

    key_field = ""
    ttl_seconds = 0

    def __init__(self, directory: Path):
        self.directory = directory
        self._last_pruned = 0.0

    def _valid(self, key: str, data: object) -> bool:
        raise NotImplementedError

    def read(self, key: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            return None
        self._prune_if_due()
        return self._read_value(key)

    def _read_value(self, key: str):
        try:
            record = json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            return None
        fetched_at = record.get("fetched_at")
        data = record.get("data")
        if (record.get(self.key_field) != key or not self._valid(key, data)
                or not isinstance(fetched_at, (int, float))
                or isinstance(fetched_at, bool)):
            return None
        age = time.time() - fetched_at
        return data if 0 <= age < self.ttl_seconds else None

    def prune(self) -> int:
        """Remove expired or invalid JSON records from this disposable cache."""
        removed = 0
        if self.directory.is_dir():
            for path in self.directory.glob("*.json"):
                try:
                    before = path.lstat()
                    valid_key = bool(re.fullmatch(r"[A-Za-z0-9_-]+", path.stem))
                    if not path.is_symlink() and valid_key and self._read_value(path.stem) is not None:
                        continue
                    after = path.lstat()
                    # A concurrent atomic writer may have replaced the record.
                    if (before.st_ino, before.st_mtime_ns, before.st_size) != (
                        after.st_ino, after.st_mtime_ns, after.st_size
                    ):
                        continue
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        self._last_pruned = time.monotonic()
        return removed

    def _prune_if_due(self) -> None:
        if time.monotonic() - self._last_pruned >= PRUNE_INTERVAL_SECONDS:
            self.prune()

    def write(self, key: str, data: object) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or not self._valid(key, data):
            raise ValueError("Invalid analytics cache record.")
        self._prune_if_due()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {"schema_version": 1, self.key_field: key,
                  "fetched_at": time.time(), "data": data}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.directory,
                                             prefix=".analytics-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(record, handle, ensure_ascii=False, allow_nan=False)
            os.replace(temporary, self.directory / f"{key}.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class NoteDiskCache(_JsonDiskCache):
    """Share Note stats between the dashboard and MCP, including after restarts."""

    key_field = "note_id"
    ttl_seconds = NOTE_TTL_SECONDS

    def _valid(self, key: str, data: object) -> bool:
        return key.isdecimal() and isinstance(data, dict) and data.get("id") == key


class PostDiskCache(_JsonDiskCache):
    """Persist one post's normalized owner analytics."""

    key_field = "post_id"
    ttl_seconds = POST_TTL_SECONDS

    def _valid(self, key: str, data: object) -> bool:
        return key.isdecimal() and isinstance(data, dict) and data.get("id") == key


class PostWeekDiskCache(_JsonDiskCache):
    """Cache completed first-week outcomes for the post portfolio."""

    key_field = "post_id"
    ttl_seconds = POST_WEEK_TTL_SECONDS

    def _valid(self, key: str, data: object) -> bool:
        return (key.isdecimal() and isinstance(data, dict) and data.get("id") == key
                and isinstance(data.get("views"), int) and not isinstance(data.get("views"), bool)
                and isinstance(data.get("signups"), int) and not isinstance(data.get("signups"), bool)
                and isinstance(data.get("daily"), list))


class PublishedPostsDiskCache(_JsonDiskCache):
    """Persist the published post index and its summary metrics."""

    key_field = "index_id"
    ttl_seconds = POST_INDEX_TTL_SECONDS

    def _valid(self, key: str, data: object) -> bool:
        return key == "published" and isinstance(data, list) and all(
            isinstance(row, dict) and str(row.get("id") or "").isdecimal()
            and all(field in row for field in ("likes", "comments", "restacks"))
            for row in data
        )

    def read(self) -> list[dict] | None:
        return super().read("published")

    def write(self, data: list[dict]) -> None:
        super().write("published", data)


class PublicationDiskCache(_JsonDiskCache):
    """Share a short-lived publication snapshot across dashboard and MCP processes."""

    key_field = "days"
    ttl_seconds = PUBLICATION_TTL_SECONDS

    def _valid(self, key: str, data: object) -> bool:
        if not key.isdecimal() or not isinstance(data, dict):
            return False
        period = data.get("range")
        if not isinstance(period, dict) or period.get("days") != int(key):
            return False
        if period.get("end") != _publication_today():
            return False
        fields = {
            "previous": dict, "totals": dict, "series": list,
            "publication_events": list, "growth_sources": list,
            "subscriber_source_series": list, "traffic_sources": list,
            "posts": list,
        }
        return (isinstance(data.get("publication"), str)
                and isinstance(data.get("refreshed_at"), str)
                and all(isinstance(data.get(name), kind) for name, kind in fields.items()))

    def read(self, days: int) -> dict | None:
        return super().read(str(days))

    def write(self, days: int, data: dict) -> None:
        super().write(str(days), data)


def prune_analytics_caches(host_cache_root: Path) -> int:
    """Prune this publication's current and older session-scoped caches."""
    try:
        sessions = list(host_cache_root.iterdir())
    except OSError:
        return 0
    kinds = (
        ("notes", NoteDiskCache), ("posts", PostDiskCache),
        ("post-index", PublishedPostsDiskCache),
        ("post-week", PostWeekDiskCache),
        ("publication", PublicationDiskCache),
    )
    removed = 0
    for session in sessions:
        if session.is_symlink() or not session.is_dir() or not re.fullmatch(r"[0-9a-f]{24}", session.name):
            continue
        for name, cache_type in kinds:
            removed += cache_type(session / name).prune()
    return removed
