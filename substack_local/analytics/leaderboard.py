"""Shared ranking rows for posts and Notes."""

def post_rows(posts):
    return [{
        "kind": "Post", "id": row["id"], "title": row.get("title") or "Untitled post",
        "date": row["publication_day"], "reach": row.get("views"), "growth": row.get("signups"),
        "likes": row.get("likes"), "discussion": row.get("comments"),
        "restacks": row.get("restacks"), "shares": row.get("shares"),
        "likeRate": row.get("likes_per_1k"), "discussionRate": row.get("comments_per_1k"),
        "restackRate": row.get("restacks_per_1k"), "shareRate": row.get("shares_per_1k"),
        "signupYield": row.get("signup_yield"),
    } for row in posts if row["published_in_period"]]


def note_rows(notes):
    return [{
        "kind": "Note", "id": row["id"], "title": row["title"], "date": row["day"],
        "reach": row.get("impressions"), "growth": None, "signupYield": None,
        "likes": row.get("likes"), "discussion": row.get("replies"),
        "restacks": row.get("restacks"), "shares": row.get("shares"),
        "likeRate": row.get("likeRate"), "discussionRate": row.get("replyRate"),
        "restackRate": row.get("restackRate"), "shareRate": row.get("shareRate"),
        "relative": (row.get("pace") or {}).get("ratio"),
    } for row in notes]
