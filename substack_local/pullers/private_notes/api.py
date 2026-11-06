"""Authenticated, rate-limited requests for private Note workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .model import PrivateNotesError

BASE_URL = "https://substack.com"


class PrivateApiClient:
    def __init__(
        self,
        session_token: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        request_delay: float = 0.25,
        attempts: int = 6,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PrivateNotesError(f"Invalid Notes base URL: {base_url}")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise PrivateNotesError("Notes requests must use HTTPS.")
        if parsed.hostname not in {"127.0.0.1", "localhost", "substack.com"}:
            raise PrivateNotesError("Notes authentication is sent only to substack.com.")
        self.base_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        self.session_token = session_token
        self.timeout = timeout
        self.request_delay = max(0.0, request_delay)
        self.attempts = max(1, attempts)
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper
        self._last_request_at = 0.0

    @staticmethod
    def _rate_limit_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
        header = exc.headers.get("Retry-After") if exc.headers else None
        if header:
            try:
                seconds = float(header)
            except ValueError:
                try:
                    target = parsedate_to_datetime(header)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    seconds = (target - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    seconds = 10.0 * (2**attempt)
            if not math.isfinite(seconds):
                seconds = 10.0 * (2**attempt)
            if seconds > 120:
                raise PrivateNotesError(
                    "Substack requested a long pause after rate limiting. Stop this "
                    "operation and try again later."
                ) from exc
            return max(0.0, seconds)
        return 10.0 * (2**attempt)

    def get_json(self, path: str) -> Any:
        if not path.startswith("/"):
            raise PrivateNotesError(f"API path must start with '/': {path}")
        remaining = self.request_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleeper(remaining)
        headers = {
            "Accept": "application/json",
            "Cookie": f"substack.sid={self.session_token}; connect.sid={self.session_token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) substack-notes-pull/1",
        }
        url = self.base_url + path
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                self._last_request_at = time.monotonic()
                try:
                    return json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PrivateNotesError(f"Substack returned non-JSON data for {path}.") from exc
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                if exc.code in {401, 403}:
                    raise PrivateNotesError(
                        "The Notes session was rejected or expired. Run "
                        "'./substack-pull auth' again."
                    ) from exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_error = exc
                    if attempt + 1 < self.attempts:
                        delay = (self._rate_limit_delay(exc, attempt) if exc.code == 429
                                 else min(60.0, 2.0 * (2**attempt)))
                        self.sleeper(delay)
                        continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise PrivateNotesError(
                    f"Substack request failed ({exc.code}) for {path}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
                if attempt + 1 < self.attempts:
                    self.sleeper(min(30.0, 1.0 * (2**attempt)))
                    continue
        raise PrivateNotesError(f"Substack request failed for {path}: {last_error}")

    def _write_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        operation: str,
    ) -> Any:
        if not path.startswith("/"):
            raise PrivateNotesError(f"API path must start with '/': {path}")
        remaining = self.request_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleeper(remaining)
        raw_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            self.base_url + path,
            data=raw_payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": (
                    f"substack.sid={self.session_token}; "
                    f"connect.sid={self.session_token}"
                ),
                "Origin": self.base_url,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                    "substack-notes-pull/1"
                ),
            },
            method=method,
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
            self._last_request_at = time.monotonic()
        except urllib.error.HTTPError as exc:
            self._last_request_at = time.monotonic()
            if exc.code in {401, 403}:
                raise PrivateNotesError(
                    "The Notes session was rejected or expired. Run "
                    "'./substack-pull auth' again."
                ) from exc
            detail = exc.read(500).decode("utf-8", errors="replace")
            if 500 <= exc.code < 600:
                raise PrivateNotesError(
                    f"The {operation} request may have reached Substack, but the "
                    f"server returned {exc.code}. Pull and check the exact Note before "
                    "retrying."
                ) from exc
            raise PrivateNotesError(
                f"Substack rejected the {operation} ({exc.code}): {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            self._last_request_at = time.monotonic()
            raise PrivateNotesError(
                f"The {operation} request may have reached Substack, but its result "
                "could not be confirmed. Pull and check the exact Note before retrying."
            ) from exc
        try:
            return json.loads(raw) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivateNotesError(
                f"Substack accepted the {operation} request but returned non-JSON data. "
                "Pull and check the exact Note before retrying."
            ) from exc

    def patch_json(self, path: str, payload: dict[str, Any]) -> Any:
        return self._write_json("PATCH", path, payload, operation="schedule change")

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        return self._write_json("POST", path, payload, operation="draft creation")


def query_path(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return path + ("?" + urllib.parse.urlencode(clean) if clean else "")


def paginate_private_notes(api: PrivateApiClient, *, limit: int = 20) -> list[dict[str, Any]]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    collected: list[dict[str, Any]] = []
    while True:
        payload = api.get_json(
            query_path("/api/v1/feed/drafts", {"limit": limit, "cursor": cursor})
        )
        if not isinstance(payload, dict):
            raise PrivateNotesError("Unexpected response shape from /api/v1/feed/drafts.")
        drafts = payload.get("drafts", [])
        if not isinstance(drafts, list) or any(not isinstance(item, dict) for item in drafts):
            raise PrivateNotesError("Unexpected drafts list from /api/v1/feed/drafts.")
        collected.extend(drafts)
        next_cursor = payload.get("nextCursor")
        if payload.get("hasMore") is False or not drafts:
            break
        if next_cursor is None:
            if len(drafts) < limit:
                break
            raise PrivateNotesError("Substack reported more Notes without a cursor.")
        cursor = str(next_cursor)
        if cursor in seen_cursors:
            raise PrivateNotesError("Substack repeated a Notes pagination cursor.")
        seen_cursors.add(cursor)
    return collected
