"""Aggregate reach and interactions for one published Note."""

from .client import ApiClient

def note_stats(api: ApiClient, note_id: str) -> dict:
    """Fetch one published Note's aggregate stats using the puller's numeric ID."""
    payload = api.get_json(f"/api/v1/note_stats/c-{note_id}")
    cards = {card.get("cardId"): card for card in payload.get("cards") or []}
    note = ((cards.get("note") or {}).get("note") or {}).get("note") or {}
    if str(note.get("id")) != f"c-{note_id}":
        raise ValueError("Substack returned stats for a different Note.")

    def header_value(card_id):
        headers = (cards.get(card_id) or {}).get("headers") or []
        return headers[0].get("value") if headers else None

    def rows(card_id):
        return [{key: item.get(key) for key in ("title", "value", "percent")}
                for item in (cards.get(card_id) or {}).get("items") or []]

    graph = (cards.get("impressions") or {}).get("graphData") or {}
    return {
        "id": note_id,
        "permalink": note.get("permalink"),
        "published_at": note.get("timestamp"),
        "last_updated_at": payload.get("lastUpdatedAt"),
        "impressions": header_value("impressions"),
        "impression_series": [{
            "label": series.get("label"),
            "is_primary": series.get("isPrimary"),
            "points": [{"timestamp": point.get("timestamp"), "value": point.get("value")}
                       for point in series.get("values") or []],
        } for series in graph.get("series") or []],
        "shares": header_value("shareValues"),
        "surfaces": rows("surfaces"),
        "audience": rows("audience"),
        "interactions": {
            "total": header_value("interactions"),
            "items": [{"title": item.get("title"), "value": item.get("value")}
                      for item in (cards.get("interactions") or {}).get("items") or []],
        },
    }
