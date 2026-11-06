"""Incremental post backup and category reconciliation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
import urllib.parse

from .api import ApiClient, paginate_posts, paginate_public_posts
from .common import CATEGORY_ENDPOINTS, POST_ARTIFACT_SUFFIXES, STATE_VERSION, PullError
from .content import find_html, find_readable, html_document, item_title, item_updated_at
from .storage import (atomic_write_json, atomic_write_text, fingerprint, item_id,
                      read_json, utc_now)


class SyncEngine:
    def __init__(
        self,
        api: ApiClient,
        output_dir: Path,
        *,
        page_limit: int = 50,
        public_only: bool = False,
        now: Callable[[], str] = utc_now,
    ):
        self.api = api
        self.output_dir = output_dir
        self.page_limit = page_limit
        self.public_only = public_only
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
        state.setdefault("archive", {})
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

    def _remove_stale_category_copy(
        self,
        state: dict[str, Any],
        *,
        post_id: str,
        old_category: str,
    ) -> bool:
        categories = state.get("categories", {})
        old_entries = categories.get(old_category, {})
        if not isinstance(old_entries, dict):
            return False
        old_entry = old_entries.get(post_id)
        if not isinstance(old_entry, dict):
            return False

        category_dir = (self.output_dir / old_category).resolve()
        candidates = {
            (category_dir / f"{post_id}{suffix}").resolve()
            for suffix in POST_ARTIFACT_SUFFIXES
        }
        relative_file = old_entry.get("file")
        if relative_file:
            manifest_path = (self.output_dir / str(relative_file)).resolve()
            if (
                manifest_path.parent == category_dir
                and manifest_path.name == f"{post_id}.json"
            ):
                candidates.add(manifest_path)

        for path in sorted(candidates):
            # Category names are controlled by CATEGORY_ENDPOINTS, but keep the
            # cleanup bounded even if an old manifest contains a bad path.
            if path.parent != category_dir:
                continue
            try:
                if path.is_file():
                    path.unlink()
            except OSError as exc:
                raise PullError(
                    f"Could not remove stale {old_category} copy for post "
                    f"{post_id}: {exc}"
                ) from exc

        del old_entries[post_id]
        return True

    def _reconcile_category_location(
        self,
        state: dict[str, Any],
        *,
        post_id: str,
        current_category: str,
        remote_locations: dict[str, set[str]],
    ) -> None:
        # Public mode does not query private category indexes, so it cannot
        # safely infer that a private draft or scheduled post changed category.
        if self.public_only or remote_locations.get(post_id) != {current_category}:
            return

        for old_category in CATEGORY_ENDPOINTS:
            if old_category == current_category:
                continue
            self._remove_stale_category_copy(
                state,
                post_id=post_id,
                old_category=old_category,
            )

    def _archive_missing_post(
        self,
        state: dict[str, Any],
        *,
        category: str,
        post_id: str,
        entry: dict[str, Any],
        archived_at: str,
    ) -> None:
        source_dir = (self.output_dir / category).resolve()
        archive_dir = (self.output_dir / "archive" / category).resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)

        for suffix in POST_ARTIFACT_SUFFIXES:
            source = (source_dir / f"{post_id}{suffix}").resolve()
            destination = (archive_dir / f"{post_id}{suffix}").resolve()
            if source.parent != source_dir or destination.parent != archive_dir:
                continue
            try:
                if source.is_file():
                    os.replace(source, destination)
            except OSError as exc:
                raise PullError(
                    f"Could not archive missing {category} post {post_id}: {exc}"
                ) from exc

        archived_entry = dict(entry)
        archived_entry.update(
            {
                "archived_at": archived_at,
                "former_category": category,
                "remote_status": "archived",
                "file": (Path("archive") / category / f"{post_id}.json").as_posix(),
            }
        )
        state.setdefault("archive", {}).setdefault(category, {})[post_id] = (
            archived_entry
        )
        del state["categories"][category][post_id]

    def sync(self, *, refresh_published: bool = False) -> dict[str, Any]:
        state = self._load_state()
        synced_at = self.now()
        summary: dict[str, Any] = {
            "publication": self.api.base_url,
            "directory": str(self.output_dir.resolve()),
            "mode": "public" if self.public_only else "authenticated",
            "synced_at": synced_at,
            "categories": {},
            "errors": [],
        }

        # Fetch every index before changing the manifest. A list failure should
        # not make untouched remote items appear missing.
        if self.public_only:
            indexes = {
                "published": paginate_public_posts(self.api, limit=self.page_limit)
            }
        else:
            indexes: dict[str, list[dict[str, Any]]] = {}
            for category, (path, order_by) in CATEGORY_ENDPOINTS.items():
                indexes[category] = paginate_posts(
                    self.api, path, order_by, limit=self.page_limit
                )

        remote_locations: dict[str, set[str]] = {}
        for category, items in indexes.items():
            for list_item in items:
                remote_locations.setdefault(item_id(list_item), set()).add(category)

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

                self._reconcile_category_location(
                    state,
                    post_id=post_id,
                    current_category=category,
                    remote_locations=remote_locations,
                )

            missing = 0
            archived = 0
            for post_id, entry in list(category_state.items()):
                if post_id not in seen:
                    if post_id in remote_locations:
                        # The destination category will remove this copy after a
                        # successful fetch. Preserve it if that fetch fails.
                        missing += 1
                        entry["remote_status"] = "missing"
                        entry.setdefault("missing_since", synced_at)
                    else:
                        self._archive_missing_post(
                            state,
                            category=category,
                            post_id=post_id,
                            entry=entry,
                            archived_at=synced_at,
                        )
                        archived += 1

            summary["categories"][category] = {
                "remote": len(items),
                "fetched": fetched,
                "fetched_items": fetched_items,
                "readable_backfilled": readable_backfilled,
                "unchanged": unchanged,
                "missing_local_preserved": missing,
                "archived": archived,
                "failures": failures,
            }

        # A transition may be discovered after its former category has already
        # been summarized. Recalculate this value from the reconciled state so
        # the report does not count moved posts as preserved missing posts.
        for category, category_summary in summary["categories"].items():
            entries = state["categories"].get(category, {})
            category_summary["missing_local_preserved"] = sum(
                1
                for entry in entries.values()
                if isinstance(entry, dict)
                and entry.get("remote_status") == "missing"
            )

        state["last_sync_at"] = synced_at
        atomic_write_json(self.state_path, state)
        return summary
