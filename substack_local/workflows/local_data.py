"""Browse and export the writer's local backup manifests."""

from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

from .modules import ROOT, POST_CONFIG, NOTE_CONFIG, post_puller, private_notes
from ..pullers.posts.content import item_title, item_updated_at
from ..analytics.note_shares import note_preview

CACHE = ROOT / "substack" / ".analytics-cache"
HISTORY = ROOT / "substack" / ".analytics-history"


def _json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _sources():
    posts, notes = post_puller(), private_notes()
    config = _json(POST_CONFIG)
    if "output" in config:
        config.setdefault("directory", config["output"])
    post_dir = posts.resolve_output_dir(POST_CONFIG, config)
    note_dir = notes.output_dir_from(NOTE_CONFIG, notes.load_config(NOTE_CONFIG), None)
    yield "Posts", "posts", post_dir, ".sync"
    yield "Draft and scheduled Notes", "private-notes", note_dir, ".private-sync"
    for profile in sorted((ROOT / "substack" / "published-notes").glob("*")):
        if re.fullmatch(r"[a-zA-Z0-9_-]+", profile.name) and profile.is_dir() and not profile.is_symlink():
            yield f"Published Notes · {profile.name}", f"published-notes/{profile.name}", profile, ".sync"


def _manifest_entries(state, group):
    if group == "posts":
        for section in ("categories", "archive"):
            for category, entries in state.get(section, {}).items():
                if category not in ("drafts", "scheduled", "published"):
                    continue
                for item_id, entry in entries.items():
                    base = f"{category}/{item_id}"
                    yield item_id, category, entry, f"archive/{base}" if section == "archive" else base
    elif group == "private-notes":
        for item_id, entry in state.get("items", {}).items():
            category = entry.get("category")
            if category in ("note-drafts", "note-scheduled"):
                yield item_id, category.removeprefix("note-"), entry, f"{category}/{item_id}"
    else:
        for item_id, entry in state.get("notes", {}).items():
            yield item_id, "published", entry, f"notes/{item_id}"


def _backup_index():
    groups, rows, files = [], [], {}
    for label, group, directory, manifest in _sources():
        state = _json(directory / manifest / "state.json")
        groups.append({"label": label, "path": str(directory), "last_sync_at": state.get("last_sync_at"),
                       "bytes": 0})
        for item_id, category, entry, base in _manifest_entries(state, group):
            if not re.fullmatch(r"[0-9]+", item_id) or entry.get("file") != f"{base}.json":
                continue
            root = directory.resolve()
            source = root / f"{base}.json"
            if not source.resolve().is_relative_to(root):
                continue
            envelope = _json(source)
            if not envelope:
                continue
            post = envelope.get("source") or {}
            note = envelope.get("note") or envelope.get("content") or {}
            is_post = group == "posts"
            row = {
                "title": (item_title(post) if is_post else note_preview(note)) or f"Item {item_id}",
                "date": ((post.get("post_date") or item_updated_at(post)) if is_post else
                         (note.get("date") or note.get("trigger_at") or note.get("edited_at")))
                        or entry.get("last_fetched_at"),
                "category": category, "status": entry.get("remote_status", "present"), "group": label,
            }
            for suffix in (".json", ".md"):
                path = root / f"{base}{suffix}"
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root):
                    key = f"{group}/{base}{suffix}"
                    files[key] = path
                    groups[-1]["bytes"] += path.stat().st_size
                    if suffix == ".md":
                        row["markdown"] = key
            rows.append(row)
    rows.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    return groups, rows, files


def _analytics_files(root):
    if root.is_symlink():
        return
    resolved_root = root.resolve()
    for path in root.glob("*/*/*/*.json"):
        if (path.is_file() and not path.is_symlink()
                and path.resolve().is_relative_to(resolved_root)):
            yield path


def local_data():
    groups, rows, _ = _backup_index()
    for label, root in (("Temporary cache", CACHE), ("Saved analytics", HISTORY)):
        stats = []
        for path in _analytics_files(root):
            try:
                stats.append(path.stat())
            except FileNotFoundError:
                continue
        groups.append({"label": label, "path": str(root), "bytes": sum(stat.st_size for stat in stats),
                       "last_sync_at": datetime.fromtimestamp(max(stat.st_mtime for stat in stats),
                                       timezone.utc).isoformat() if stats else None})
    return {"root": str(ROOT), "groups": groups, "items": rows}


def open_data_folder():
    if sys.platform == "win32":
        os.startfile(str(ROOT))
    elif sys.platform == "darwin":
        subprocess.Popen(["/usr/bin/open", str(ROOT)])
    else:
        subprocess.Popen(["xdg-open", str(ROOT)])


def clear_temporary_cache():
    count = 0
    for path in _analytics_files(CACHE):
        if (path.parent.name in {"notes", "posts", "post-index", "post-week", "publication"}
                and re.fullmatch(r"[0-9a-f]{24}", path.parent.parent.name)):
            path.unlink(missing_ok=True)
            count += 1
    return count


def backup_markdown(key):
    _, _, files = _backup_index()
    if key not in files or not key.endswith(".md"):
        raise LookupError("Markdown backup not found.")
    return files[key].read_bytes()


def export_backups(output):
    _, rows, files = _backup_index()
    html = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Clearview backups</title>',
            '<h1>Clearview writing backups</h1><table><thead><tr><th>Title</th><th>Date</th>'
            '<th>Collection</th><th>Status</th></tr></thead><tbody>']
    for row in rows:
        title = escape(row["title"])
        if row.get("markdown"):
            title = f'<a href="{quote(row["markdown"])}">{title}</a>'
        date = escape(str(row["date"] or "")[:10])
        collection = escape(f'{row["group"]} · {row["category"]}')
        html.append(f'<tr><td>{title}</td><td>{date}</td><td>{collection}</td>'
                    f'<td>{escape(row["status"])}</td></tr>')
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "".join(html) + "</tbody></table></html>")
        for key, path in files.items():
            archive.write(path, key)


def save_backup_export():
    directory = ROOT / "exports"
    directory.mkdir(mode=0o700, exist_ok=True)
    with NamedTemporaryFile(dir=directory, prefix="clearview-backups-", suffix=".zip",
                            delete=False) as output:
        path = Path(output.name)
        try:
            export_backups(output)
        except Exception:
            output.close()
            path.unlink(missing_ok=True)
            raise
    return str(path)
