"""Post titles and readable body conversion for local backups."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from typing import Any


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
