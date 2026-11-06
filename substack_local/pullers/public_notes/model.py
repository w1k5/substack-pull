"""Published Note identity, Markdown, and change fingerprints."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

def _marked_text(node: dict[str, Any]) -> str:
    text = str(node.get("text", ""))
    for mark in node.get("marks", []):
        if not isinstance(mark, dict):
            continue
        kind = mark.get("type")
        if kind == "link":
            href = mark.get("attrs", {}).get("href")
            if href:
                text = f"[{text}]({href})"
        elif kind in {"strong", "bold"}:
            text = f"**{text}**"
        elif kind in {"em", "italic"}:
            text = f"*{text}*"
        elif kind == "code":
            text = f"`{text}`"
    return text

def render_prosemirror(node: Any) -> str:
    """Render the common Note ProseMirror nodes as readable Markdown."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return _marked_text(node)
    if kind == "hardBreak":
        return "\n"
    if kind in {"horizontal_rule", "horizontalRule"}:
        return "\n\n---\n\n"
    if kind in {"image", "image2"}:
        attrs = node.get("attrs", {})
        source = attrs.get("src") or attrs.get("imageUrl")
        return f"![{attrs.get('alt') or ''}]({source})" if source else ""

    children = "".join(render_prosemirror(child) for child in node.get("content", []))
    if kind == "paragraph":
        return children.rstrip() + "\n\n"
    if kind == "heading":
        level = int(node.get("attrs", {}).get("level") or 2)
        return f"{'#' * max(1, min(6, level))} {children.strip()}\n\n"
    if kind == "blockquote":
        body = children.strip()
        return "\n".join(f"> {line}" for line in body.splitlines()) + "\n\n"
    if kind in {"bulletList", "orderedList"}:
        rendered: list[str] = []
        start = int(node.get("attrs", {}).get("start") or 1)
        for index, child in enumerate(node.get("content", [])):
            body = render_prosemirror(child).strip()
            prefix = f"{start + index}. " if kind == "orderedList" else "- "
            lines = body.splitlines() or [""]
            rendered.append(prefix + lines[0])
            rendered.extend("  " + line for line in lines[1:])
        return "\n".join(rendered) + "\n\n"
    if kind == "listItem":
        return children.strip()
    if kind == "codeBlock":
        language = node.get("attrs", {}).get("language") or ""
        return f"```{language}\n{children.rstrip()}\n```\n\n"
    return children

def note_body(note: dict[str, Any]) -> str:
    document = note.get("body_json")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            document = None
    rendered = render_prosemirror(document).strip() if isinstance(document, dict) else ""
    if rendered:
        return rendered
    return str(note.get("body") or "").strip()

def _attachment_markdown(attachment: dict[str, Any]) -> str:
    kind = str(attachment.get("type") or "attachment")
    if kind == "image":
        url = attachment.get("imageUrl") or attachment.get("url")
        return f"![Attached image]({url})" if url else "- Attached image"
    if kind == "post":
        post = attachment.get("post")
        if isinstance(post, dict):
            title = str(post.get("title") or post.get("subtitle") or "Attached post")
            url = post.get("canonical_url")
            return f"[{title}]({url})" if url else f"- {title}"
    if kind == "comment":
        comment = attachment.get("comment")
        if isinstance(comment, dict):
            author = comment.get("handle")
            user = comment.get("user")
            if not author and isinstance(user, dict):
                author = user.get("handle")
            body = note_body(comment).replace("\n", " ").strip()
            note_id = comment.get("id")
            if author and note_id:
                url = f"https://substack.com/@{author}/note/c-{note_id}"
                return f"> [{('@' + str(author))}]({url}): {body}".rstrip()
            return f"> {body}".rstrip()
    for key in ("url", "videoUrl", "audioUrl"):
        if attachment.get(key):
            return f"[{kind.title()} attachment]({attachment[key]})"
    return f"- {kind.title()} attachment (details preserved in JSON)"

def note_permalink(profile: dict[str, Any], note: dict[str, Any]) -> str:
    return f"https://substack.com/@{profile['handle']}/note/c-{note['id']}"

def note_markdown(profile: dict[str, Any], note: dict[str, Any]) -> str:
    permalink = note_permalink(profile, note)
    lines = [
        f"# Note {note['id']}",
        "",
        f"- Profile: [@{profile['handle']}]({profile['url']})",
        f"- Published: {note.get('date') or 'unknown'}",
    ]
    if note.get("edited_at"):
        lines.append(f"- Edited: {note['edited_at']}")
    lines.extend(
        [
            f"- Permalink: {permalink}",
            f"- Reactions: {int(note.get('reaction_count') or 0)}",
            f"- Restacks: {int(note.get('restacks') or 0)}",
            f"- Replies: {int(note.get('children_count') or 0)}",
            "",
            note_body(note),
        ]
    )
    attachments = [
        item for item in note.get("attachments", []) if isinstance(item, dict)
    ]
    if attachments:
        lines.extend(["", "## Attachments", ""])
        lines.extend(_attachment_markdown(item) for item in attachments)
    return "\n".join(lines).rstrip() + "\n"

def authored_note(item: Any, profile_id: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("type") != "comment":
        return None
    context = item.get("context")
    if not isinstance(context, dict) or context.get("type") != "note":
        return None
    note = item.get("comment")
    if not isinstance(note, dict) or note.get("id") is None:
        return None
    if str(note.get("user_id")) != str(profile_id):
        return None
    if str(note.get("ancestor_path") or "").strip("/"):
        return None
    return note

_VOLATILE_FEED_KEYS = {
    "autotranslate_to", "impression_id", "reaction", "restacked",
    "trackingParameters", "userStatus",
}

_NESTED_ENGAGEMENT_KEYS = {
    "child_comment_count", "children_count", "comment_count",
    "reaction_count", "reactions", "restacks",
}

def _stable_feed_value(value: Any, *, drop_engagement: bool) -> Any:
    """Remove per-request and nested engagement data from fingerprint inputs."""
    if isinstance(value, dict):
        return {
            key: _stable_feed_value(item, drop_engagement=drop_engagement)
            for key, item in value.items()
            if key not in _VOLATILE_FEED_KEYS
            and (not drop_engagement or key not in _NESTED_ENGAGEMENT_KEYS)
        }
    if isinstance(value, list):
        return [
            _stable_feed_value(item, drop_engagement=drop_engagement)
            for item in value
        ]
    return value

def note_content_fingerprint(note: dict[str, Any]) -> str:
    return digest(
        {
            key: (
                _stable_feed_value(note.get(key), drop_engagement=True)
                if key == "attachments"
                else note.get(key)
            )
            for key in (
                "id",
                "user_id",
                "body",
                "body_json",
                "attachments",
                "date",
                "edited_at",
                "language",
            )
        }
    )

def note_snapshot_fingerprint(item: dict[str, Any]) -> str:
    comment = item.get("comment")
    stable_comment = _stable_feed_value(comment, drop_engagement=False)
    if isinstance(comment, dict) and isinstance(stable_comment, dict):
        stable_comment["attachments"] = _stable_feed_value(
            comment.get("attachments"), drop_engagement=True
        )
    return digest(
        {
            "comment": stable_comment,
            "context": _stable_feed_value(item.get("context"), drop_engagement=True),
            "post": _stable_feed_value(item.get("post"), drop_engagement=True),
            "publication": _stable_feed_value(
                item.get("publication"), drop_engagement=True
            ),
        }
    )
