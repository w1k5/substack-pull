"""Private, short-lived disk caches for normalized post and Note analytics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time


NOTE_TTL_SECONDS = 3600
POST_TTL_SECONDS = 3600
POST_INDEX_TTL_SECONDS = 900
POST_WEEK_TTL_SECONDS = 86400


class _JsonDiskCache:
    """Atomic JSON cache with one validated record per key."""

    key_field = ""
    ttl_seconds = 0

    def __init__(self, directory: Path):
        self.directory = directory

    def _valid(self, key: str, data: object) -> bool:
        raise NotImplementedError

    def read(self, key: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            return None
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

    def write(self, key: str, data: object) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or not self._valid(key, data):
            raise ValueError("Invalid analytics cache record.")
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
            isinstance(row, dict) and str(row.get("id") or "").isdecimal() for row in data
        )

    def read(self) -> list[dict] | None:
        return super().read("published")

    def write(self, data: list[dict]) -> None:
        super().write("published", data)
