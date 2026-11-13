"""Conservative, cross-process pacing for real Substack HTTP requests."""

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
import sys
import time
import urllib.error
from urllib.parse import urlparse

from ..paths import data_root


def _lock(handle):
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX)


def _unlock(handle):
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_UN)


def _endpoint(path: str) -> str:
    # Log a known API family only; arbitrary path segments can contain private slugs.
    parts = urlparse(path).path.strip("/").split("/")
    families = {"archive", "comment", "drafts", "feed", "note_stats", "notes",
                "post_management", "posts", "publication", "reader"}
    if len(parts) >= 3 and parts[:2] == ["api", "v1"]:
        return f"/api/v1/{parts[2] if parts[2] in families else 'other'}"
    return "/page"


@contextmanager
def paced_request(base_url: str, path: str, *, enabled: bool, delay: float = 0.25):
    """Serialize real Substack requests across dashboard, MCP, and pullers.

    Hold the lock through the response so another process cannot start a burst.
    Test openers and localhost fixtures are deliberately unaffected.
    """
    host = urlparse(base_url).hostname or ""
    if not enabled or (host != "substack.com" and not host.endswith(".substack.com")):
        yield
        return
    root = data_root() / "substack"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = root / ".request-pacing"
    started_wait = time.monotonic()
    with open(lock_path, "a+b") as handle:
        _lock(handle)
        try:
            handle.seek(0)
            try:
                deadline_file = root / ".request-pacing-deadline"
                raw = deadline_file.read_text(encoding="ascii") if sys.platform == "win32" else handle.read()
                next_allowed = float(raw.strip() or 0)
            except (FileNotFoundError, ValueError):
                next_allowed = 0.0
            while (remaining := next_allowed - time.time()) > 0:
                if remaining > 120:
                    raise RuntimeError("Substack requested a long pause after rate limiting. Try again later.")
                time.sleep(min(remaining, 120.0))
            waited = time.monotonic() - started_wait
            started = time.monotonic()
            status = "ok"
            cooldown = 0.0
            try:
                yield
            except urllib.error.HTTPError as exc:
                status = str(exc.code)
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After", "10") if exc.headers else "10"
                    try:
                        cooldown = float(retry_after)
                    except ValueError:
                        try:
                            when = parsedate_to_datetime(retry_after)
                            if when.tzinfo is None:
                                when = when.replace(tzinfo=timezone.utc)
                            cooldown = (when - datetime.now(timezone.utc)).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            cooldown = 10.0
                    cooldown = min(86400.0, max(10.0, cooldown))
                raise
            except Exception:
                status = "error"
                raise
            finally:
                # Byte zero is reserved for the Windows lock. Never truncate
                # the file while another process is waiting on that byte.
                deadline = f"{time.time() + max(1.0, delay, cooldown):.6f}\n"
                handle.seek(0)
                if sys.platform == "win32":
                    # Release the byte lock only after persisting the deadline.
                    # Use a separate file for the deadline so readers and writes
                    # never touch the locked byte.
                    deadline_file.write_text(deadline, encoding="ascii")
                else:
                    handle.truncate()
                    handle.write(deadline.encode())
                    handle.flush()
                if os.environ.get("CLEARVIEW_REQUEST_TIMING") == "1":
                    print(f"clearview request {_endpoint(path)} status={status} "
                          f"wait_ms={waited * 1000:.0f} network_ms={(time.monotonic() - started) * 1000:.0f}",
                          file=sys.stderr, flush=True)
        finally:
            _unlock(handle)
