#!/usr/bin/env python3
"""Read-only, incremental Substack backup CLI.

The CLI uses Substack's undocumented dashboard API. Authentication is stored in
the macOS Keychain; the session value is never written to the project directory.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable
import urllib.error
import urllib.parse
import urllib.request


APP_NAME = "substack-pull"
KEYCHAIN_SERVICE = "com.local.substack-pull"
DEFAULT_CONFIG = ".substack-pull.json"
DEFAULT_OUTPUT = "substack"
STATE_VERSION = 1

CATEGORY_ENDPOINTS = {
    "drafts": (
        "/api/v1/post_management/drafts",
        "draft_updated_at",
    ),
    "scheduled": (
        "/api/v1/post_management/scheduled",
        "draft_updated_at",
    ),
    "published": (
        "/api/v1/post_management/published",
        "post_date",
    ),
}

# Fields that can indicate an editorial change. Engagement and delivery stats
# are intentionally excluded so they do not trigger body downloads.
FINGERPRINT_FIELDS = (
    "id",
    "slug",
    "type",
    "title",
    "subtitle",
    "draft_title",
    "draft_subtitle",
    "draft_updated_at",
    "updated_at",
    "post_date",
    "publish_date",
    "published_at",
    "scheduled_at",
    "scheduled_release",
    "scheduled_release_at",
    "send_at",
    "trigger_at",
    "email_audience",
    "post_audience",
    "section_id",
    "audience",
)


class PullError(RuntimeError):
    """An expected, user-facing sync error."""


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(item: dict[str, Any]) -> str:
    editorial = {key: item.get(key) for key in FINGERPRINT_FIELDS if key in item}
    return hashlib.sha256(canonical_json(editorial).encode("utf-8")).hexdigest()


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


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise PullError(f"Invalid JSON in {path}: {exc}") from exc


def load_config(path: Path, publication_override: str | None) -> dict[str, Any]:
    config = read_json(path, {})
    if not isinstance(config, dict):
        raise PullError(f"Configuration in {path} must be a JSON object.")
    publication = publication_override or config.get("publication")
    if not publication:
        raise PullError(
            f"No publication configured. Run './substack-pull auth --publication "
            f"https://YOURNAME.substack.com' first."
        )
    config["publication"] = normalize_publication(str(publication))
    # "output" was the original key. Continue reading it so existing configs
    # migrate without forcing another authentication run.
    config.setdefault("directory", config.get("output", DEFAULT_OUTPUT))
    return config


def save_config(path: Path, config: dict[str, Any]) -> None:
    safe = {
        "publication": normalize_publication(str(config["publication"])),
        "directory": str(
            config.get("directory", config.get("output", DEFAULT_OUTPUT))
        ),
    }
    atomic_write_json(path, safe)


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
        session_token: str,
        *,
        timeout: float = 30.0,
        request_delay: float = 0.25,
        opener: Callable[..., Any] | None = None,
    ):
        self.base_url = normalize_publication(base_url)
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

    def get_json(self, path: str) -> Any:
        if not path.startswith("/"):
            raise PullError(f"API path must start with '/': {path}")
        url = self.base_url + path
        headers = {
            "Accept": "application/json",
            "Cookie": (
                f"connect.sid={self.session_token}; "
                f"substack.sid={self.session_token}"
            ),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) substack-pull/1",
        }
        last_error: Exception | None = None
        for attempt in range(3):
            self._throttle()
            request = urllib.request.Request(url, headers=headers, method="GET")
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
                    raise PullError(
                        "Substack rejected the stored session. Re-copy connect.sid from "
                        "Safari or substack.sid from Chromium DevTools, then run "
                        "'./substack-pull auth' again."
                    ) from exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(1.0 * (2**attempt))
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


def item_id(item: dict[str, Any]) -> str:
    value = item.get("id") or item.get("post_id")
    if value is None:
        raise PullError("A Substack list item did not include an id.")
    return str(value)


def item_title(item: dict[str, Any]) -> str:
    return str(
        item.get("draft_title")
        or item.get("title")
        or item.get("slug")
        or "Untitled"
    )


def item_subtitle(item: dict[str, Any]) -> str | None:
    value = item.get("draft_subtitle") or item.get("subtitle")
    return str(value) if value else None


def item_updated_at(item: dict[str, Any]) -> str | None:
    for key in (
        "draft_updated_at",
        "updated_at",
        "trigger_at",
        "published_at",
        "publish_date",
        "post_date",
        "draft_created_at",
    ):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _marked_text(node: dict[str, Any]) -> str:
    text = str(node.get("text", ""))
    for mark in node.get("marks", []):
        if not isinstance(mark, dict):
            continue
        mark_type = mark.get("type")
        if mark_type == "link":
            href = mark.get("attrs", {}).get("href")
            if href:
                text = f"[{text}]({href})"
        elif mark_type in {"strong", "bold"}:
            text = f"**{text}**"
        elif mark_type in {"em", "italic"}:
            text = f"*{text}*"
        elif mark_type == "code":
            text = f"`{text}`"
    return text


def render_prosemirror(node: Any) -> str:
    """Render a Substack ProseMirror document as readable Markdown."""
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return _marked_text(node)
    if node_type == "hardBreak":
        return "\n"
    if node_type == "horizontal_rule":
        return "\n\n---\n\n"
    if node_type in {"image", "image2"}:
        attrs = node.get("attrs", {})
        src = attrs.get("src")
        if not src:
            return ""
        return f"![{attrs.get('alt') or ''}]({src})"

    children = "".join(render_prosemirror(child) for child in node.get("content", []))
    if node_type == "paragraph":
        return children.rstrip() + "\n\n"
    if node_type == "heading":
        level = int(node.get("attrs", {}).get("level") or 2)
        return f"{'#' * max(1, min(level, 6))} {children.strip()}\n\n"
    if node_type == "blockquote":
        body = children.strip()
        return "\n".join(f"> {line}" for line in body.splitlines()) + "\n\n"
    if node_type in {"bulletList", "orderedList"}:
        rendered: list[str] = []
        start = int(node.get("attrs", {}).get("start") or 1)
        for index, child in enumerate(node.get("content", [])):
            body = render_prosemirror(child).strip()
            prefix = f"{start + index}. " if node_type == "orderedList" else "- "
            lines = body.splitlines() or [""]
            rendered.append(prefix + lines[0])
            rendered.extend("  " + line for line in lines[1:])
        return "\n".join(rendered) + "\n\n"
    if node_type == "listItem":
        return children.strip()
    if node_type == "codeBlock":
        language = node.get("attrs", {}).get("language") or ""
        return f"```{language}\n{children.rstrip()}\n```\n\n"
    if node_type in {"ctaCaption", "subscribeWidget"}:
        return children.strip() + "\n\n" if children.strip() else ""
    return children


class _ReadableHTMLParser(HTMLParser):
    """Small dependency-free HTML-to-readable-text converter."""

    BLOCKS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "hr":
            self.parts.append("\n\n---\n\n")
        elif tag == "img":
            values = dict(attrs)
            if values.get("src"):
                self.parts.append(f"![{values.get('alt') or ''}]({values['src']})")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def markdown(self) -> str:
        text = "".join(self.parts).replace("\r\n", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def html_to_markdown(value: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(value)
    parser.close()
    return parser.markdown()


def readable_body(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("type") == "doc":
        rendered = render_prosemirror(value).strip()
        return rendered + "\n" if rendered else None
    if not isinstance(value, str) or not value.strip():
        return None
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = None
        rendered = readable_body(decoded)
        if rendered:
            return rendered
    if re.search(r"<(?:p|div|h[1-6]|article|section|br|blockquote)\b", value, re.I):
        return html_to_markdown(value)
    return stripped + "\n"


def find_readable(value: Any) -> tuple[str, str] | None:
    """Find and render the first likely body in a nested Substack response."""
    if not isinstance(value, dict):
        return None
    title = item_title(value)
    for key in ("body_html", "draft_body", "draft_body_html", "body"):
        rendered = readable_body(value.get(key))
        if rendered:
            return title, rendered
    for nested_key in ("post", "draft"):
        found = find_readable(value.get(nested_key))
        if found:
            return found
    return None


def find_html(value: Any) -> tuple[str, str] | None:
    """Find the first likely HTML body and title in a nested response."""
    if not isinstance(value, dict):
        return None
    title = str(
        value.get("draft_title")
        or value.get("title")
        or value.get("slug")
        or "Substack post"
    )
    for key in ("body_html", "draft_body", "draft_body_html", "body"):
        body = value.get(key)
        if isinstance(body, str) and ("<p" in body or "<div" in body or "<h" in body):
            return title, body
    for nested_key in ("post", "draft"):
        nested = value.get(nested_key)
        found = find_html(nested)
        if found:
            return found
    return None


def html_document(title: str, body: str) -> str:
    import html

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head><body>\n"
        f"{body}\n"
        "</body></html>\n"
    )


class SyncEngine:
    def __init__(
        self,
        api: ApiClient,
        output_dir: Path,
        *,
        page_limit: int = 50,
        now: Callable[[], str] = utc_now,
    ):
        self.api = api
        self.output_dir = output_dir
        self.page_limit = page_limit
        self.now = now
        self.state_path = output_dir / ".sync" / "state.json"

    def _load_state(self) -> dict[str, Any]:
        state = read_json(
            self.state_path,
            {
                "version": STATE_VERSION,
                "publication": self.api.base_url,
                "categories": {},
            },
        )
        if state.get("version") != STATE_VERSION:
            raise PullError(
                f"Unsupported state version in {self.state_path}: {state.get('version')}"
            )
        if state.get("publication") != self.api.base_url:
            raise PullError(
                f"{self.output_dir} belongs to {state.get('publication')}, not "
                f"{self.api.base_url}. Choose a different output directory."
            )
        state.setdefault("categories", {})
        return state

    def _fetch_full(self, category: str, post_id: str) -> Any:
        quoted = urllib.parse.quote(post_id, safe="")
        if category == "published":
            return self.api.get_json(f"/api/v1/posts/by-id/{quoted}")
        content = self.api.get_json(f"/api/v1/drafts/{quoted}")
        if category == "scheduled":
            schedule = self.api.get_json(f"/api/v1/drafts/{quoted}/scheduled_release")
            return {"draft": content, "scheduled_release": schedule}
        return content

    def _write_content(
        self,
        category: str,
        post_id: str,
        list_item: dict[str, Any],
        content: Any,
        synced_at: str,
    ) -> str:
        relative = Path(category) / f"{post_id}.json"
        envelope = {
            "schema_version": 1,
            "category": category,
            "synced_at": synced_at,
            "source": list_item,
            "content": content,
        }
        atomic_write_json(self.output_dir / relative, envelope)
        found = find_html(content)
        if found:
            title, body = found
            atomic_write_text(
                self.output_dir / category / f"{post_id}.html",
                html_document(title, body),
            )
        self._write_readable_companion(category, post_id, content)
        return relative.as_posix()

    def _write_readable_companion(
        self,
        category: str,
        post_id: str,
        content: Any,
    ) -> Path | None:
        readable = find_readable(content)
        if readable:
            title, body = readable
            path = self.output_dir / category / f"{post_id}.md"
            atomic_write_text(path, f"# {title}\n\n{body.lstrip()}")
            return path
        return None

    def sync(self, *, refresh_published: bool = False) -> dict[str, Any]:
        state = self._load_state()
        synced_at = self.now()
        summary: dict[str, Any] = {
            "publication": self.api.base_url,
            "directory": str(self.output_dir.resolve()),
            "synced_at": synced_at,
            "categories": {},
            "errors": [],
        }

        # Fetch every index before changing the manifest. A list failure should
        # not make untouched remote items appear missing.
        indexes: dict[str, list[dict[str, Any]]] = {}
        for category, (path, order_by) in CATEGORY_ENDPOINTS.items():
            indexes[category] = paginate_posts(
                self.api, path, order_by, limit=self.page_limit
            )

        for category, items in indexes.items():
            category_state = state["categories"].setdefault(category, {})
            seen: set[str] = set()
            fetched = 0
            fetched_items: list[dict[str, Any]] = []
            readable_backfilled = 0
            unchanged = 0
            failures = 0
            for list_item in items:
                post_id = item_id(list_item)
                seen.add(post_id)
                current_fingerprint = fingerprint(list_item)
                previous = category_state.get(post_id, {})
                should_fetch = (
                    not previous
                    or previous.get("fingerprint") != current_fingerprint
                    or (category == "published" and refresh_published)
                    or not (self.output_dir / previous.get("file", "")).is_file()
                )
                if should_fetch:
                    try:
                        content = self._fetch_full(category, post_id)
                        relative_file = self._write_content(
                            category,
                            post_id,
                            list_item,
                            content,
                            synced_at,
                        )
                    except PullError as exc:
                        failures += 1
                        summary["errors"].append(
                            {"category": category, "id": post_id, "error": str(exc)}
                        )
                        # Keep the old fingerprint so the next run retries.
                        if previous:
                            previous["last_seen_at"] = synced_at
                            previous["remote_status"] = "present"
                            previous.pop("missing_since", None)
                        continue
                    category_state[post_id] = {
                        "fingerprint": current_fingerprint,
                        "file": relative_file,
                        "last_fetched_at": synced_at,
                        "last_seen_at": synced_at,
                        "remote_status": "present",
                    }
                    fetched += 1
                    readable_file = self.output_dir / category / f"{post_id}.md"
                    fetched_item: dict[str, Any] = {
                        "id": post_id,
                        "title": item_title(list_item),
                        "updated_at": item_updated_at(list_item),
                        "file": str((self.output_dir / relative_file).resolve()),
                    }
                    if readable_file.is_file():
                        fetched_item["readable_file"] = str(readable_file.resolve())
                    fetched_items.append(fetched_item)
                else:
                    previous["last_seen_at"] = synced_at
                    previous["remote_status"] = "present"
                    previous.pop("missing_since", None)
                    markdown_path = self.output_dir / category / f"{post_id}.md"
                    if not markdown_path.is_file():
                        envelope = read_json(
                            self.output_dir / str(previous.get("file", "")),
                            None,
                        )
                        if isinstance(envelope, dict) and self._write_readable_companion(
                            category,
                            post_id,
                            envelope.get("content"),
                        ):
                            readable_backfilled += 1
                    unchanged += 1

            missing = 0
            for post_id, entry in category_state.items():
                if post_id not in seen:
                    missing += 1
                    entry["remote_status"] = "missing"
                    entry.setdefault("missing_since", synced_at)

            summary["categories"][category] = {
                "remote": len(items),
                "fetched": fetched,
                "fetched_items": fetched_items,
                "readable_backfilled": readable_backfilled,
                "unchanged": unchanged,
                "missing_local_preserved": missing,
                "failures": failures,
            }

        state["last_sync_at"] = synced_at
        atomic_write_json(self.state_path, state)
        return summary


def config_path_from(args: argparse.Namespace) -> Path:
    return Path(args.config).expanduser().resolve()


def resolve_output_dir(
    config_path: Path,
    config: dict[str, Any],
    directory_override: str | None = None,
) -> Path:
    directory_value = directory_override or config.get("directory", DEFAULT_OUTPUT)
    output_dir = Path(str(directory_value)).expanduser()
    if not output_dir.is_absolute():
        output_dir = config_path.parent / output_dir
    return output_dir.resolve()


def collect_local_posts(
    output_dir: Path,
    *,
    category: str | None = None,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    state_path = output_dir / ".sync" / "state.json"
    state = read_json(state_path, None)
    if state is None:
        raise PullError(f"No sync state exists at {state_path}. Run pull first.")
    categories = state.get("categories", {})
    category_names = [category] if category else list(CATEGORY_ENDPOINTS)
    posts: list[dict[str, Any]] = []
    for category_name in category_names:
        entries = categories.get(category_name, {})
        if not isinstance(entries, dict):
            continue
        for post_id, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            remote_status = entry.get("remote_status", "present")
            if remote_status == "missing" and not include_missing:
                continue
            relative_file = entry.get("file")
            if not relative_file:
                continue
            file_path = (output_dir / str(relative_file)).resolve()
            envelope = read_json(file_path, None)
            if not isinstance(envelope, dict):
                continue
            source = envelope.get("source", {})
            if not isinstance(source, dict):
                source = {}
            markdown_path = file_path.with_suffix(".md")
            result: dict[str, Any] = {
                "category": category_name,
                "id": str(post_id),
                "title": item_title(source),
                "subtitle": item_subtitle(source),
                "updated_at": item_updated_at(source) or entry.get("last_fetched_at"),
                "remote_status": remote_status,
                "file": str(file_path),
            }
            if markdown_path.is_file():
                result["readable_file"] = str(markdown_path)
            posts.append(result)
    posts.sort(
        key=lambda post: (str(post.get("updated_at") or ""), str(post.get("id") or "")),
        reverse=True,
    )
    return posts


def command_auth(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    existing = read_json(config_path, {})
    publication_value = args.publication or existing.get("publication")
    if not publication_value:
        publication_value = input("Publication URL: ").strip()
    publication = normalize_publication(str(publication_value))
    directory = (
        args.directory
        or existing.get("directory")
        or existing.get("output")
        or DEFAULT_OUTPUT
    )
    save_config(config_path, {"publication": publication, "directory": directory})

    account = host_for(publication)
    keychain = KeychainStore()
    keychain.store_interactive(account)

    token = keychain.get(account)
    api = ApiClient(publication, token, request_delay=args.request_delay)
    api.get_json("/api/v1/drafts?limit=1")
    print(f"Authentication verified for {publication}.")
    print(f"Configuration saved to {config_path} (no secret stored there).")
    return 0


def command_sync(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    publication = config["publication"]
    output_dir = resolve_output_dir(config_path, config, args.directory)

    token = KeychainStore().get(host_for(publication))
    api = ApiClient(
        publication,
        token,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    engine = SyncEngine(api, output_dir, page_limit=args.page_limit)
    summary = engine.sync(refresh_published=args.refresh_published)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"]:
        return 1
    return 0


def command_status(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    state_path = output_dir / ".sync" / "state.json"
    state = read_json(state_path, None)
    if state is None:
        raise PullError(f"No sync state exists at {state_path}. Run sync first.")
    result = {
        "publication": state.get("publication"),
        "directory": str(output_dir),
        "last_sync_at": state.get("last_sync_at"),
        "categories": {},
    }
    for category, entries in state.get("categories", {}).items():
        present = sum(1 for entry in entries.values() if entry.get("remote_status") == "present")
        missing = sum(1 for entry in entries.values() if entry.get("remote_status") == "missing")
        result["categories"][category] = {
            "tracked": len(entries),
            "present": present,
            "missing_local_preserved": missing,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_list(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    if args.limit < 1:
        raise PullError("--limit must be at least 1.")
    category = None if args.category == "all" else args.category
    posts = collect_local_posts(
        output_dir,
        category=category,
        include_missing=args.include_missing,
    )
    if args.query:
        needle = args.query.casefold()
        posts = [
            post
            for post in posts
            if needle
            in " ".join(
                str(post.get(key) or "")
                for key in ("title", "subtitle", "id", "category")
            ).casefold()
        ]
    posts = posts[: args.limit]
    result = {
        "publication": config["publication"],
        "directory": str(output_dir),
        "query": args.query,
        "count": len(posts),
        "items": posts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_configure(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    if args.directory:
        config["directory"] = args.directory
    save_config(config_path, config)
    print(f"Publication: {config['publication']}")
    print(f"Directory: {config['directory']}")
    print(f"Configuration saved to {config_path} (no secret stored there).")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "security_command": shutil.which("security") is not None,
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
    }
    healthy = sys.platform == "darwin" and report["security_command"]
    if config_path.is_file():
        try:
            config = load_config(config_path, args.publication)
            account = host_for(config["publication"])
            report["publication"] = config["publication"]
            output_dir = resolve_output_dir(config_path, config)
            report["directory"] = str(output_dir)
            report["sync_state_exists"] = (output_dir / ".sync" / "state.json").is_file()
            report["keychain_session_present"] = KeychainStore().exists(account)
            if not report["keychain_session_present"]:
                healthy = False
        except PullError as exc:
            report["config_error"] = str(exc)
            healthy = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="substack-pull",
        description="Read-only incremental backup of a Substack publication.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"configuration path (default: {DEFAULT_CONFIG})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="store and verify a browser session")
    auth.add_argument("--publication", help="publication URL or hostname")
    auth.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help=f"content directory (default: {DEFAULT_OUTPUT})",
    )
    auth.add_argument("--request-delay", type=float, default=0.25)
    auth.set_defaults(handler=command_auth)

    def add_pull_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--publication", help="override configured publication")
        command.add_argument(
            "-d",
            "--directory",
            "--output",
            dest="directory",
            help="override configured content directory for this pull",
        )
        command.add_argument("--refresh-published", action="store_true")
        command.add_argument("--page-limit", type=int, default=50)
        command.add_argument("--request-delay", type=float, default=0.25)
        command.add_argument("--timeout", type=float, default=30.0)
        command.set_defaults(handler=command_sync)

    pull = subparsers.add_parser(
        "pull", help="pull content and report exactly which posts changed"
    )
    add_pull_arguments(pull)

    sync = subparsers.add_parser("sync", help="alias for pull")
    add_pull_arguments(sync)

    status = subparsers.add_parser("status", help="show local sync state")
    status.add_argument("--publication", help="override configured publication")
    status.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help="override configured content directory",
    )
    status.set_defaults(handler=command_status)

    list_posts = subparsers.add_parser(
        "list", help="find recent posts in the local backup"
    )
    list_posts.add_argument("--publication", help="override configured publication")
    list_posts.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help="override configured content directory",
    )
    list_posts.add_argument("--query", help="case-insensitive title or ID search")
    list_posts.add_argument(
        "--category",
        choices=("all", "drafts", "scheduled", "published"),
        default="all",
    )
    list_posts.add_argument("--limit", type=int, default=20)
    list_posts.add_argument("--include-missing", action="store_true")
    list_posts.set_defaults(handler=command_list)

    configure = subparsers.add_parser(
        "configure", help="change publication or default content directory"
    )
    configure.add_argument("--publication", help="publication URL or hostname")
    configure.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help="new default content directory",
    )
    configure.set_defaults(handler=command_configure)

    doctor = subparsers.add_parser("doctor", help="check local prerequisites")
    doctor.add_argument("--publication", help="override configured publication")
    doctor.set_defaults(handler=command_doctor)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if not raw_args:
        raw_args = ["pull"]
    args = parser.parse_args(raw_args)
    try:
        return int(args.handler(args))
    except PullError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
