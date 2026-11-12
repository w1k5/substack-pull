"""Split the Notes discovery surface by the kind of linked content.

These are Substack *source* credits for a selected period. They are not the
lifetime subscriber counts shown on individual posts or Notes.
"""

from __future__ import annotations
from urllib.parse import urlparse


def _safe_href(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and (parsed.hostname == "substack.com" or
               (parsed.hostname or "").endswith(".substack.com")) else None


def _subscribers(row: dict) -> int | None:
    for metric in row.get("metrics") or []:
        if str(metric.get("name", "")).lower() == "subscribers":
            value = metric.get("total")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return None


def notes_source_attribution(growth: dict, *, own_post_ids=(), own_note_ids=()) -> dict:
    """Use ``c-`` and ``p-`` source IDs; keep residual credits unclassified.

    Substack groups some long-tail items into an aggregate child. Those items
    cannot be safely assigned to a content type. Individual rows can also be
    other writers' content, so this function does not claim authorship.
    """
    substack = next((row for row in growth.get("sourceMetrics") or []
                     if row.get("source") == "substack"), None)
    notes = next((row for row in (substack or {}).get("children") or []
                  if row.get("source") == "notes"), None)
    if notes is None or _subscribers(notes) is None:
        return {"status": "unavailable", "surface": "Notes",
                "subscribers": None, "note_link_subscribers": None,
                "post_link_subscribers": None, "unclassified_subscribers": None,
                "note_link_share": None, "post_link_share": None,
                "unclassified_share": None, "classified_share": None,
                "majority_link_type": None, "outside_items": [], "items": []}

    total = _subscribers(notes)
    own_post_ids = {str(value) for value in own_post_ids}
    own_note_ids = {str(value) for value in own_note_ids}
    own_post_sources = {f"p-{item_id}" for item_id in own_post_ids}
    # Substack's sourceName uses "writer: title". Infer this publication's
    # label only from a post whose ID is in the authenticated published index.
    own_label = next((str(row.get("sourceName", "")).split(": ", 1)[0]
                      for row in notes.get("children") or []
                      if row.get("source") in own_post_sources
                      and ": " in str(row.get("sourceName", ""))), None)
    items = []
    counts = {"note": 0, "post": 0}
    for row in notes.get("children") or []:
        source = row.get("source")
        count = _subscribers(row)
        if row.get("isAggregation") or not isinstance(source, str) or count is None:
            continue
        prefix, _, item_id = source.partition("-")
        kind = {"c": "note", "p": "post"}.get(prefix)
        if kind is None or not item_id.isascii() or not item_id.isdecimal():
            continue
        counts[kind] += count
        title = " ".join(str(row.get("sourceName") or "").split())
        author, separator, body = title.partition(": ")
        known_own = item_id in (own_post_ids if kind == "post" else own_note_ids)
        ownership = ("own" if known_own or (own_label and separator and author == own_label)
                     else "outside_label" if own_label and separator and author != own_label
                     else "unverified")
        display = body if ownership in {"own", "outside_label"} and separator else title
        items.append({"kind": kind, "id": item_id, "subscribers": count,
                      "ownership": ownership, "author_label": author if separator else None,
                      "href": _safe_href(row.get("href")),
                      "preview": display[:180] + ("…" if len(display) > 180 else "")})
    items.sort(key=lambda row: (-row["subscribers"], row["kind"], row["id"]))
    classified = counts["note"] + counts["post"]
    unclassified = max(total - classified, 0)
    trackbacks = next((row for row in (substack or {}).get("children") or []
                       if row.get("source") == "trackbacks"), {})
    outside = [{"surface": "Trackback", "preview": " ".join(str(row.get("sourceName") or "").split())[:180],
                "subscribers": count, "href": _safe_href(row.get("href"))}
               for row in trackbacks.get("children") or []
               if not row.get("isAggregation") and (count := _subscribers(row)) and count > 0]
    outside.extend({"surface": "Another writer’s Note", "preview": row["preview"],
                    "author_label": row["author_label"], "subscribers": row["subscribers"],
                    "href": row["href"]}
                   for row in items if row["ownership"] == "outside_label" and row["kind"] == "note"
                   and row["subscribers"] > 0)
    outside.sort(key=lambda row: -row["subscribers"])
    return {"status": "available" if classified <= total else "inconsistent",
            "surface": "Notes", "subscribers": total,
            "note_link_subscribers": counts["note"],
            "post_link_subscribers": counts["post"],
            "unclassified_subscribers": unclassified,
            "note_link_share": counts["note"] / total if total else None,
            "post_link_share": counts["post"] / total if total else None,
            "unclassified_share": unclassified / total if total else None,
            "classified_share": classified / total if total else None,
            "majority_link_type": ("post" if counts["post"] > total / 2 else
                                   "note" if counts["note"] > total / 2 else None),
            "outside_items": outside,
            "items": items}
