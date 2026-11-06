"""Post backup files, configuration, and local indexes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .api import normalize_publication
from .common import DEFAULT_OUTPUT, FINGERPRINT_FIELDS, PullError
from .content import item_subtitle, item_title, item_updated_at


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def fingerprint(item: dict[str, Any]) -> str:
    editorial = {key: item.get(key) for key in FINGERPRINT_FIELDS if key in item}
    return hashlib.sha256(canonical_json(editorial).encode("utf-8")).hexdigest()

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

def item_id(item: dict[str, Any]) -> str:
    value = item.get("id") or item.get("post_id")
    if value is None:
        raise PullError("A Substack list item did not include an id.")
    return str(value)

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
    query: str = "",
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
    if query:
        needle = query.casefold()
        posts = [post for post in posts if needle in " ".join(
            str(post.get(key) or "") for key in ("title", "subtitle", "id", "category")
        ).casefold()]
    posts.sort(
        key=lambda post: (str(post.get("updated_at") or ""), str(post.get("id") or "")),
        reverse=True,
    )
    return posts

def local_status(output_dir: Path) -> dict[str, Any]:
    """Describe a post backup without contacting Substack."""
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
    return result
