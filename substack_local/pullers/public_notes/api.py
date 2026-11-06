"""Anonymous public Note requests and profile resolution."""
from __future__ import annotations

from email.utils import parsedate_to_datetime
import json
import re
import sys
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .common import DEFAULT_BASE_URL, PullError


def normalize_base_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PullError(f"Invalid API base URL: {value}")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise PullError("Substack requests must use HTTPS.")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

def normalize_handle(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise PullError("A Substack profile handle or URL is required.")

    candidate = raw
    if "://" in raw or raw.endswith(".substack.com"):
        url = raw if "://" in raw else "https://" + raw
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if host == "substack.com" or host == "www.substack.com":
            parts = [part for part in parsed.path.split("/") if part]
            if not parts or not parts[0].startswith("@"):
                raise PullError(
                    "Use a Substack profile URL such as https://substack.com/@handle."
                )
            candidate = parts[0][1:]
        elif host.endswith(".substack.com"):
            candidate = host[: -len(".substack.com")]
        else:
            raise PullError("Profile URLs must be on substack.com.")
    else:
        candidate = raw.removeprefix("@").split("/", 1)[0]

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", candidate):
        raise PullError(f"Invalid Substack handle: {candidate}")
    return candidate.lower()

def profile_url(handle: str) -> str:
    return f"https://substack.com/@{handle}"

def query_path(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return path + ("?" + urllib.parse.urlencode(clean) if clean else "")

class ApiClient:
    """Small anonymous GET client with conservative throttling and retries."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        request_delay: float = 1.25,
        attempts: int = 8,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.base_url = normalize_base_url(base_url)
        self.timeout = timeout
        self.request_delay = max(0.0, request_delay)
        self.attempts = max(1, attempts)
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper
        self.monotonic = monotonic
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        remaining = self.request_delay - (self.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleeper(remaining)

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
        header = exc.headers.get("Retry-After") if exc.headers else None
        if header:
            try:
                return min(120.0, max(0.0, float(header)))
            except ValueError:
                try:
                    target = parsedate_to_datetime(header)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    return min(
                        120.0,
                        max(0.0, (target - datetime.now(timezone.utc)).total_seconds()),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        if exc.code == 429:
            return min(60.0, 5.0 * (2**attempt))
        return min(30.0, 1.0 * (2**attempt))

    def _get(self, path: str, accept: str) -> bytes:
        if not path.startswith("/"):
            raise PullError(f"API path must start with '/': {path}")
        url = self.base_url + path
        headers = {
            "Accept": accept,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) substack-notes-pull/1",
        }
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            self._throttle()
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                self._last_request_at = self.monotonic()
                return raw
            except urllib.error.HTTPError as exc:
                self._last_request_at = self.monotonic()
                if exc.code in {401, 403}:
                    raise PullError(
                        "Substack denied anonymous access. The profile or Note may be "
                        "private, restricted, or unavailable."
                    ) from exc
                if exc.code == 404:
                    raise PullError(f"Substack did not find {path}.") from exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_error = exc
                    if attempt + 1 < self.attempts:
                        delay = self._retry_after(exc, attempt)
                        print(
                            f"Substack returned {exc.code}; retrying in {delay:g}s...",
                            file=sys.stderr,
                        )
                        self.sleeper(delay)
                        continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise PullError(
                    f"Substack request failed ({exc.code}) for {path}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                self._last_request_at = self.monotonic()
                last_error = exc
                if attempt + 1 < self.attempts:
                    self.sleeper(min(30.0, 1.0 * (2**attempt)))
                    continue
        raise PullError(f"Substack request failed for {path}: {last_error}")

    def get_json(self, path: str) -> Any:
        raw = self._get(path, "application/json")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PullError(f"Substack returned non-JSON data for {path}.") from exc

    def get_text(self, path: str) -> str:
        raw = self._get(path, "text/html,application/xhtml+xml")
        return raw.decode("utf-8", errors="replace")

def parse_preloads(html: str) -> dict[str, Any]:
    match = re.search(
        r"window\._preloads\s*=\s*JSON\.parse\((\"(?:\\.|[^\"\\])*\")\)",
        html,
        re.DOTALL,
    )
    try:
        if match:
            encoded = json.loads(match.group(1))
            value = json.loads(encoded)
        else:
            embedded = re.search(
                r'<script[^>]*\bid=["\']preloads-json["\'][^>]*>(.*?)</script>',
                html,
                re.DOTALL,
            )
            if not embedded:
                raise PullError("Substack's profile page did not contain profile metadata.")
            value = json.loads(embedded.group(1))
    except json.JSONDecodeError as exc:
        raise PullError("Substack returned unreadable profile metadata.") from exc
    if not isinstance(value, dict):
        raise PullError("Substack returned an unexpected profile metadata shape.")
    return value

def resolve_profile(api: ApiClient, reference: str) -> dict[str, Any]:
    handle = normalize_handle(reference)
    html = api.get_text(f"/@{urllib.parse.quote(handle, safe='')}")
    preload = parse_preloads(html)
    raw = preload.get("profile")
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise PullError(f"Substack did not expose a public profile for @{handle}.")
    resolved_handle = normalize_handle(str(raw.get("handle") or handle))
    return {
        "id": str(raw["id"]),
        "handle": resolved_handle,
        "name": str(raw.get("name") or resolved_handle),
        "bio": raw.get("bio"),
        "url": profile_url(resolved_handle),
    }
