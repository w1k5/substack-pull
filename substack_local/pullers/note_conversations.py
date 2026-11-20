"""Read a Substack Note and its visible reply tree from a Note or reply URL."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .public_notes import ApiClient, PullError, query_path
from .public_notes.model import note_body


def note_id_from(reference: str) -> str:
    value = str(reference).strip()
    if re.fullmatch(r"(?:c-)?[0-9]+", value):
        return value.removeprefix("c-")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() not in
            {"substack.com", "www.substack.com"} or parsed.username or
            parsed.password or parsed.port):
        raise ValueError("Use a numeric Note ID or an HTTPS substack.com /note/c-ID URL.")
    match = re.fullmatch(r"/(?:@[^/]+|profile/[^/]+)/note/c-([0-9]+)/?", parsed.path)
    if not match:
        raise ValueError("Use a numeric Note ID or an HTTPS substack.com /note/c-ID URL.")
    return match.group(1)


def _row(comment: dict, parent_id: str | None = None) -> dict:
    comment_id = str(comment.get("id") or "")
    if not comment_id.isascii() or not comment_id.isdecimal():
        raise PullError("Substack returned a Note reply without a numeric ID.")
    ancestors = re.findall(r"[0-9]+", str(comment.get("ancestor_path") or ""))
    if ancestors and ancestors[-1] != comment_id:
        parent_id = ancestors[-1]
    elif len(ancestors) > 1:
        parent_id = ancestors[-2]
    return {
        "id": comment_id, "parent_id": parent_id,
        "name": comment.get("name"), "handle": comment.get("handle"),
        "user_id": comment.get("user_id"), "date": comment.get("date"),
        "body": note_body(comment), "children_count": comment.get("children_count"),
        "reaction_count": comment.get("reaction_count"),
    }


def read_note_conversation(reference: str, *, api: ApiClient | None = None) -> dict:
    """Return the root Note and every visible reply, including the selected reply's ancestors."""
    selected_id = note_id_from(reference)
    api = api or ApiClient()
    detail = api.get_json(f"/api/v1/reader/comment/{selected_id}")
    item = detail.get("item") if isinstance(detail, dict) else None
    selected = item.get("comment") if isinstance(item, dict) else None
    parents = item.get("parentComments") if isinstance(item, dict) else None
    if not isinstance(selected, dict) or str(selected.get("id")) != selected_id:
        raise PullError("Substack did not return the requested Note or reply.")
    if parents is None:
        parents = []
    if not isinstance(parents, list) or any(not isinstance(p, dict) for p in parents):
        raise PullError("Substack returned an unexpected Note ancestor list.")
    root = parents[0] if parents else selected
    root_id = str(root.get("id") or "")
    if not root_id.isascii() or not root_id.isdecimal():
        raise PullError("Substack returned a Note without a numeric root ID.")
    rows = {root_id: _row(root)}
    for index, parent in enumerate(parents[1:], 1):
        row = _row(parent, str(parents[index - 1]["id"]))
        rows[row["id"]] = row
    if selected_id != root_id:
        rows[selected_id] = _row(selected, str(parents[-1]["id"]) if parents else root_id)
    pages = 0
    def fetch_replies(parent_id: str) -> None:
        nonlocal pages
        cursor = None
        seen = set()
        while True:
            path = query_path(f"/api/v1/reader/comment/{parent_id}/replies", {
                "publication_id": root.get("publication_id"),
                "comment_id": parent_id, "cursor": cursor,
            })
            payload = api.get_json(path)
            branches = payload.get("commentBranches") if isinstance(payload, dict) else None
            if not isinstance(branches, list):
                raise PullError("Substack returned an unexpected Note replies shape.")
            pages += 1
            for branch in branches:
                first = branch.get("comment") if isinstance(branch, dict) else None
                descendants = branch.get("descendantComments") if isinstance(branch, dict) else None
                if not isinstance(first, dict) or not isinstance(descendants, list):
                    raise PullError("Substack returned an unexpected Note reply branch.")
                branch_row = _row(first, parent_id)
                rows[branch_row["id"]] = branch_row
                for descendant in descendants:
                    comment = descendant.get("comment") if isinstance(descendant, dict) else None
                    if not isinstance(comment, dict):
                        raise PullError("Substack returned an unexpected descendant reply.")
                    row = _row(comment, branch_row["id"])
                    rows[row["id"]] = row
            next_cursor = payload.get("nextCursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise PullError("Substack returned an unexpected Note replies cursor.")
            if not next_cursor:
                break
            if next_cursor in seen or pages >= 1000:
                raise PullError("Substack repeated a Note replies page or cursor.")
            seen.add(next_cursor)
            cursor = next_cursor

    def gaps() -> list[dict]:
        returned = {}
        for row in rows.values():
            if row["parent_id"] in rows:
                returned[row["parent_id"]] = returned.get(row["parent_id"], 0) + 1
        return [{"id": row["id"], "reported_children": row["children_count"],
                 "returned_children": returned.get(row["id"], 0)}
                for row in rows.values() if isinstance(row["children_count"], int)
                and row["children_count"] > returned.get(row["id"], 0)]

    fetch_replies(root_id)
    # The root endpoint can omit deeper branches. Query only parents whose
    # reported direct-child count exceeds the children actually returned.
    queried = {root_id}
    while True:
        missing = [gap["id"] for gap in gaps() if gap["id"] not in queried]
        if not missing:
            break
        for parent_id in missing:
            if len(queried) >= 1000:
                raise PullError("Note conversation exceeded 1,000 reply-parent requests.")
            queried.add(parent_id)
            fetch_replies(parent_id)
    short_branches = gaps()
    return {"root_id": root_id, "selected_id": selected_id,
            "pages": pages, "replies": list(rows.values()),
            "pagination_complete": True,
            "conversation_complete": not short_branches,
            "short_branches": short_branches,
            "reported_unreturned_children": sum(
                gap["reported_children"] - gap["returned_children"]
                for gap in short_branches),
            "queried_parent_ids": sorted(queried, key=int)}
