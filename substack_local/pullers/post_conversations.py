"""Read and archive the visible Note conversation attached to a Substack post."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from .public_notes import ApiClient, PullError, atomic_write_json, query_path, read_json, utc_now
from .public_notes.model import note_body


def post_id_from(reference: str) -> str:
    """Accept a numeric post ID or a substack.com Note-style post URL."""
    value = str(reference).strip()
    if re.fullmatch(r"[0-9]+", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
        "substack.com", "www.substack.com"
    } or parsed.username or parsed.password or parsed.port:
        raise ValueError("Use a numeric post ID or an HTTPS substack.com /note/p-ID URL.")
    match = re.fullmatch(r"/(?:@[^/]+/)?note/p-([0-9]+)/?", parsed.path)
    if not match:
        raise ValueError("Use a numeric post ID or an HTTPS substack.com /note/p-ID URL.")
    return match.group(1)


def _numeric(value: Any) -> str:
    return str(value) if str(value).isascii() and str(value).isdecimal() else ""


def _metadata(api: ApiClient, post_id: str) -> dict[str, Any]:
    payload = api.get_json(f"/api/v1/posts/by-id/{post_id}?as-feed-item=1")
    if not isinstance(payload, dict):
        raise PullError("Substack returned an unexpected post metadata shape.")
    post = payload.get("post")
    publication = payload.get("publication")
    if not isinstance(post, dict) or not isinstance(publication, dict):
        raise PullError("Substack did not return a public post and publication.")
    publication_id = _numeric(publication.get("id"))
    if _numeric(post.get("id")) != post_id or not publication_id:
        raise PullError("Substack returned metadata for a different post or no publication ID.")
    if post.get("publication_id") is not None and _numeric(post["publication_id"]) != publication_id:
        raise PullError("Substack returned inconsistent publication IDs.")
    return {
        "id": post_id,
        "publication_id": publication_id,
        "title": post.get("title"),
        "canonical_url": post.get("canonical_url"),
        "published_at": post.get("post_date"),
        "publication_name": publication.get("name"),
    }


def _comments(branch: dict[str, Any], post_id: str) -> list[dict[str, Any]]:
    """Flatten a branch while retaining its root and the API's ancestor path."""
    root = branch.get("comment")
    if not isinstance(root, dict) or not _numeric(root.get("id")):
        raise PullError("Substack returned a reply branch without a root comment ID.")
    root_id = _numeric(root["id"])
    pending = [(root, root_id, None)]
    descendants = branch.get("descendantComments") or []
    if not isinstance(descendants, list):
        raise PullError("Substack returned an unexpected descendant list.")
    for item in descendants:
        if not isinstance(item, dict) or not isinstance(item.get("comment"), dict):
            raise PullError("Substack returned an unexpected descendant comment.")
        pending.append((item["comment"], root_id, item))
    rows = []
    for comment, branch_id, _ in pending:
        comment_id = _numeric(comment.get("id"))
        if not comment_id or _numeric(comment.get("post_id")) != post_id:
            raise PullError("Substack returned a reply for another post or without an ID.")
        path = str(comment.get("ancestor_path") or "")
        ancestors = re.findall(r"[0-9]+", path)
        parent_id = ancestors[-1] if ancestors else None
        if comment_id == branch_id:
            parent_id = None
        elif parent_id == comment_id:
            parent_id = ancestors[-2] if len(ancestors) > 1 else branch_id
        rows.append({
            "id": comment_id,
            "post_id": post_id,
            "branch_id": branch_id,
            "parent_id": parent_id or (branch_id if comment_id != branch_id else None),
            "ancestor_path": path,
            "name": comment.get("name"),
            "user_id": _numeric(comment.get("user_id")) or None,
            "date": comment.get("date"),
            "edited_at": comment.get("edited_at"),
            "body": note_body(comment),
            "children_count": comment.get("children_count"),
            "reaction_count": comment.get("reaction_count"),
        })
    return rows


def pull_conversation(reference: str, directory: Path, *, api: ApiClient | None = None) -> dict:
    post_id = post_id_from(reference)
    api = api or ApiClient()
    post = _metadata(api, post_id)
    cursor = None
    seen_cursors: set[str] = set()
    rows: dict[str, dict] = {}
    pages = []
    while True:
        path = query_path(f"/api/v1/reader/post/{post_id}/replies", {
            "publication_id": post["publication_id"], "cursor": cursor,
        })
        payload = api.get_json(path)
        if not isinstance(payload, dict) or not isinstance(payload.get("commentBranches"), list):
            raise PullError("Substack returned an unexpected post replies shape.")
        branches = payload["commentBranches"]
        before_count = len(rows)
        for branch in branches:
            if not isinstance(branch, dict):
                raise PullError("Substack returned an unexpected reply branch.")
            for row in _comments(branch, post_id):
                rows[row["id"]] = row
        pages.append(payload)
        next_cursor = payload.get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise PullError("Substack returned an unexpected replies cursor.")
        if not next_cursor:
            break
        if len(rows) == before_count:
            raise PullError("Substack repeated a replies page without returning new comments. A signed-in session may be required.")
        if next_cursor in seen_cursors or len(pages) >= 1000:
            raise PullError("Substack's replies pagination repeated or exceeded 1,000 pages.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    comments = list(rows.values())
    comment_ids = set(rows)
    unresolved_parents = sorted({row["parent_id"] for row in comments
                                 if row["parent_id"] and row["parent_id"] not in comment_ids})
    # Substack may count replies that it does not return in the visible branch data.
    returned_child_counts: dict[str, int] = {}
    for row in comments:
        if row["parent_id"]:
            returned_child_counts[row["parent_id"]] = returned_child_counts.get(row["parent_id"], 0) + 1
    short_branches = [
        {"id": row["id"], "reported_children": row["children_count"],
         "returned_children": returned_child_counts.get(row["id"], 0)}
        for row in comments if isinstance(row["children_count"], int)
        and row["children_count"] > returned_child_counts.get(row["id"], 0)
    ]
    reported_unreturned_children = sum(
        item["reported_children"] - item["returned_children"]
        for item in short_branches
    )
    envelope = {
        "schema_version": 1, "post": post, "source_url": reference,
        "pulled_at": utc_now(), "pages": pages, "comments": comments,
        "unresolved_parent_ids": unresolved_parents, "short_branches": short_branches,
        "pagination_complete": True,
        "reported_unreturned_children": reported_unreturned_children,
    }
    target = directory / f"{post_id}.json"
    atomic_write_json(target, envelope)
    return {"post": post, "file": str(target.resolve()), "pulled_at": envelope["pulled_at"],
            "pages": len(pages), "replies": len(comments),
            "unresolved_parent_ids": unresolved_parents,
            "short_branches": short_branches,
            "pagination_complete": True,
            "reported_unreturned_children": reported_unreturned_children}


def load_conversation(reference: str, directory: Path) -> dict:
    post_id = post_id_from(reference)
    target = directory / f"{post_id}.json"
    envelope = read_json(target, None)
    if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
        raise LookupError(f"No saved post conversation at {target}. Pull it first.")
    if (envelope.get("post") or {}).get("id") != post_id or not isinstance(envelope.get("comments"), list):
        raise PullError(f"Invalid saved post conversation at {target}.")
    return envelope
