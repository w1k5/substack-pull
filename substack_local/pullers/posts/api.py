"""Authenticated and public post request clients."""
from __future__ import annotations

from email.utils import parsedate_to_datetime
import json
import math
import shutil
import subprocess
import sys
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .common import KEYCHAIN_SERVICE, READ_ONLY_POST_PATHS, PullError


def normalize_publication(value: str) -> str:
    value = value.strip()
    if not value:
        raise PullError("Publication URL cannot be empty.")
    if "://" not in value:
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise PullError(f"Invalid publication URL: {value}")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise PullError("Publication URL must use HTTPS.")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

def host_for(base_url: str) -> str:
    host = urllib.parse.urlparse(base_url).hostname
    if not host:
        raise PullError(f"Cannot determine hostname from {base_url}")
    return host.lower()

def require_substack_host(base_url: str) -> None:
    host = host_for(base_url)
    if host in {"127.0.0.1", "localhost"}:
        return
    if host != "substack.com" and not host.endswith(".substack.com"):
        raise PullError(
            "For safety, authentication is only sent to substack.com hosts. "
            "Use your publication's canonical YOURNAME.substack.com URL, not its "
            "custom domain."
        )

class KeychainStore:
    def __init__(self, service: str = KEYCHAIN_SERVICE):
        self.service = service

    def _require_macos(self) -> None:
        if sys.platform != "darwin" or shutil.which("security") is None:
            raise PullError("macOS Keychain is required, but 'security' is unavailable.")

    def store_interactive(self, account: str) -> None:
        self._require_macos()
        print(
            "Paste the Substack session cookie VALUE at the Keychain prompt "
            "(Safari connect.sid or Chromium substack.sid). "
            "Input is hidden."
        )
        command = [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            account,
            "-s",
            self.service,
            "-l",
            f"Substack Pull ({account})",
            "-w",
        ]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise PullError("Keychain did not store the Substack session value.")

    def get(self, account: str) -> str:
        self._require_macos()
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                self.service,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise PullError(
                f"No session is stored for {account}. Run './substack-pull auth' first."
            )
        token = result.stdout.rstrip("\r\n")
        if not token:
            raise PullError(f"The stored session for {account} is empty.")
        return token

    def exists(self, account: str) -> bool:
        try:
            self.get(account)
            return True
        except PullError:
            return False

class ApiClient:
    def __init__(
        self,
        base_url: str,
        session_token: str | None = None,
        *,
        timeout: float = 30.0,
        request_delay: float = 0.25,
        opener: Callable[..., Any] | None = None,
    ):
        self.base_url = normalize_publication(base_url)
        if session_token is not None:
            require_substack_host(self.base_url)
        self.session_token = session_token
        self.timeout = timeout
        self.request_delay = max(0.0, request_delay)
        self.opener = opener or urllib.request.urlopen
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

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
                raise PullError(
                    "Substack requested a long pause after rate limiting. Stop this "
                    "operation and try again later."
                ) from exc
            return max(0.0, seconds)
        return 10.0 * (2**attempt)

    def get_json(self, path: str) -> Any:
        return self._request_json(path, method="GET")

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        """Send a JSON query to a read-only analytics endpoint."""
        if path not in READ_ONLY_POST_PATHS:
            raise PullError(f"POST query is not supported for {path}.")
        return self._request_json(path, method="POST", payload=payload)

    def _request_json(
        self, path: str, *, method: str, payload: dict[str, Any] | None = None
    ) -> Any:
        if not path.startswith("/"):
            raise PullError(f"API path must start with '/': {path}")
        url = self.base_url + path
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) substack-pull/1",
        }
        if self.session_token is not None:
            headers["Cookie"] = (
                f"connect.sid={self.session_token}; "
                f"substack.sid={self.session_token}"
            )
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        if body is not None:
            headers["Content-Type"] = "application/json"
        last_error: Exception | None = None
        for attempt in range(3):
            self._throttle()
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                self._last_request_at = time.monotonic()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise PullError(f"Substack returned non-JSON data for {path}.") from exc
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                if exc.code in {401, 403}:
                    if self.session_token is None:
                        raise PullError(
                            "Substack denied anonymous access to this public endpoint. "
                            "The publication may be private, restricted, or unavailable."
                        ) from exc
                    else:
                        raise PullError(
                            "Substack rejected the stored session. Re-copy connect.sid "
                            "from Safari or substack.sid from Chromium DevTools, then "
                            "run './substack-pull auth' again."
                        ) from exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_error = exc
                    if attempt < 2:
                        delay = (self._rate_limit_delay(exc, attempt) if exc.code == 429
                                 else 1.0 * (2**attempt))
                        time.sleep(delay)
                        continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise PullError(
                    f"Substack API request failed ({exc.code}) for {path}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
                if attempt < 2:
                    time.sleep(1.0 * (2**attempt))
                    continue
        raise PullError(f"Substack API request failed for {path}: {last_error}")

def query_path(path: str, params: dict[str, Any]) -> str:
    return path + "?" + urllib.parse.urlencode(params)

def paginate_posts(
    api: ApiClient,
    path: str,
    order_by: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    offset = 0
    collected: list[dict[str, Any]] = []
    while True:
        payload = api.get_json(
            query_path(
                path,
                {
                    "offset": offset,
                    "limit": limit,
                    "order_by": order_by,
                    "order_direction": "desc",
                },
            )
        )
        if isinstance(payload, dict):
            posts = payload.get("posts", [])
            total = payload.get("total")
        elif isinstance(payload, list):
            posts = payload
            total = None
        else:
            raise PullError(f"Unexpected response shape from {path}.")
        if not isinstance(posts, list) or any(not isinstance(item, dict) for item in posts):
            raise PullError(f"Unexpected posts list from {path}.")
        collected.extend(posts)
        offset += len(posts)
        if not posts:
            break
        if isinstance(total, int) and offset >= total:
            break
        if len(posts) < limit:
            break
    return collected

def paginate_public_posts(
    api: ApiClient,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List only posts exposed by a publication's anonymous public archive."""
    offset = 0
    collected: list[dict[str, Any]] = []
    while True:
        endpoint = query_path(
            "/api/v1/archive",
            {
                "sort": "new",
                "search": "",
                "offset": offset,
                "limit": limit,
            },
        )
        payload = api.get_json(endpoint)
        if isinstance(payload, dict):
            posts = payload.get("posts", [])
            total = payload.get("total")
        elif isinstance(payload, list):
            posts = payload
            total = None
        else:
            raise PullError("Unexpected response shape from /api/v1/archive.")
        if not isinstance(posts, list) or any(not isinstance(item, dict) for item in posts):
            raise PullError("Unexpected posts list from /api/v1/archive.")
        collected.extend(posts)
        offset += len(posts)
        if not posts:
            break
        if isinstance(total, int) and offset >= total:
            break
        if len(posts) < limit:
            break
    return collected
