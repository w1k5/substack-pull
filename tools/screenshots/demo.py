"""Fictional Clearview data. This module never reads a publication or local backup."""

from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from substack_local.analytics.derived import dashboard_metrics, post_detail_metrics
from substack_local.analytics.note_comparison import note_comparison_metrics, summarize_note_cohort
from substack_local.dashboard.server import DashboardHandler, STATIC_FILES
from substack_local.pullers.private_notes.planning import runway_payload
from substack_local.workflows.notes import suggested_openings

TODAY = date(2026, 10, 14)
POST = {"id": 101, "title": "What a neighborhood sounds like at dawn", "date": "2026-10-09",
        "views": 4820, "signups": 64, "likes": 287, "comments": 32, "shares": 48}
NOTES = [
    "The bakery is the first window lit on our street.",
    "A field guide to the benches that get the last of the sun.",
    "There is a small library inside the old station.",
    "What disappears when a neighborhood loses its noticeboard?",
    "The best map of a place is the one a neighbor draws.",
    "I took the long way home and found an open courtyard.",
    "Three sounds that tell me summer is over.",
    "A blue door I have walked past a hundred times.",
]
EVENTS = [
    {"id": 201 + i, "title": title, "type": "note", "day": str(TODAY - timedelta(days=1 + i * 3))}
    for i, title in enumerate(NOTES)
]
SOURCES = [("Substack", 5), ("Direct", 3), ("Recommendations", 2)]
TOTALS = {"views": 21648, "visitors": 9810, "subscribers": 248}


class DemoAnalytics:
    def dashboard(self, days, **_):
        start = TODAY - timedelta(days=days - 1)
        dates = [str(start + timedelta(days=i)) for i in range(days)]
        return dashboard_metrics({
            "publication": "https://citymargin.example",
            "refreshed_at": f"{TODAY}T14:30:00Z",
            "range": {"start": str(start), "end": str(TODAY), "days": days},
            "totals": TOTALS,
            "previous": {"totals": {"views": 18810, "visitors": 8770, "subscribers": 171}},
            "series": [[day, 420 + (i * 83 % 390) + (550 if i in (9, 17, 24) else 0)]
                       for i, day in enumerate(dates)],
            "posts": [POST],
            "publication_events": [event for event in EVENTS if event["day"] >= str(start)] +
                [{"id": POST["id"], "title": POST["title"], "type": "text", "day": POST["date"]}],
            "growth_sources": [
                {"name": name, "category": "Discovery", "subscribers": count, "visitors": count * 32}
                for name, count in [("Substack", 148), ("Direct", 66), ("Recommendations", 34)]
            ] + [{"name": "Notes", "parent": "Substack", "subscribers": 93, "visitors": 2100}],
            "subscriber_source_series": [
                {"key": name, "name": name, "points": [[day, (i * (base + 2) % 11) // 2 + base
                    + (6 if (i + base) % 12 == 0 else 0)] for i, day in enumerate(dates)]}
                for name, base in SOURCES
            ],
            "traffic_sources": [{"name": name, "category": "Discovery", "views": count * 30,
                                 "users": count * 14, "free_signups": count, "paid_signups": 0}
                                for name, count in [("Substack", 148), ("Direct", 66), ("Recommendations", 34)]],
            "notes_source_attribution": {
                "status": "available", "subscribers": 93, "majority_link_type": "post",
                "post_link_subscribers": 55, "note_link_subscribers": 27, "unclassified_subscribers": 11,
                "post_link_share": 55 / 93, "note_link_share": 27 / 93, "unclassified_share": 11 / 93,
                "items": [{"kind": "post", "id": POST["id"], "preview": POST["title"], "subscribers": 55}]
                + [{"kind": "note", "id": event["id"], "preview": event["title"], "subscribers": count}
                   for event, count in zip(EVENTS, [14, 8, 5])],
            },
        })

    def latest(self, **_):
        return {"post": POST, "notes_since_post": 2, "notes": [
            {**event, "published_at": event["day"], "impressions": self.note(event["id"])["impressions"]}
            for event in EVENTS[:3]
        ]}

    def post(self, post_id, **_):
        if str(post_id) != str(POST["id"]):
            raise LookupError("Sample post unavailable.")
        return post_detail_metrics({
            **POST, "reach": {"views": POST["views"]},
            "growth": {"signups": 64, "subscribes": 5, "unsubscribes": 2},
            "traffic": {"referrers": [
                {"source": name, "views": views, "signups": count}
                for name, views, count in [("Notes", 2300, 37), ("Direct", 1300, 16), ("Recommendations", 920, 11)]
            ]},
        }, today=str(TODAY))

    def note(self, note_id, **_):
        event = next((event for event in EVENTS if str(event["id"]) == str(note_id)), None)
        if event is None:
            raise LookupError("Sample Note unavailable.")
        i = event["id"] - 201
        reach = [2350, 1170, 1680, 3420, 720, 1460, 900, 2720][i]
        points = lambda total: [
            {"timestamp": f"{event['day']}T12:00:00Z", "value": 0},
            {"timestamp": f"{date.fromisoformat(event['day']) + timedelta(days=1)}T12:00:00Z",
             "value": total},
        ]
        result = {
            **event, "id": str(note_id), "full_text": event["title"], "published_at": event["day"],
            "impressions": reach, "impression_series": [
                {"is_primary": True, "points": points(reach // 2)},
                {"is_primary": False, "points": points(610)},
            ],
            "interactions": {"items": [{"title": name, "value": value} for name, value in zip(
                ("Like", "Reply", "Restack", "Share", "Profile visit", "Link click"),
                (round(reach * (.018 + i % 4 * .008)), i + 5, i + 1, i + 2, 18 - i, 7 + i),
            )]},
            "audience": [{"title": "Unconnected", "value": 280 + i * 12},
                         {"title": "Subscribers", "value": 220}],
        }
        return {**result, "comparison": note_comparison_metrics(result)}

    def note_cohort(self, days, **_):
        rows = [{**event, **self.note(event["id"])["comparison"]} for event in EVENTS
                if (TODAY - date.fromisoformat(event["day"])).days < days]
        return {"rows": rows, "total": len(rows), "considered": len(rows),
                "unavailable_ids": [], "lenses": summarize_note_cohort(rows)}


class DemoPlanner:
    def snapshot(self, *, days, spacing):
        drafts = [{"id": 801 + i, "text": title} for i, title in enumerate([
            "An invitation to send me a photograph of your favorite street corner.",
            "The small rituals people keep at the end of the market day.",
            "Five minutes at the ferry terminal before the first boat.",
        ])]
        scheduled = [{"id": 901 + i, "body": NOTES[i % len(NOTES)],
                      "trigger_at": f"{TODAY + timedelta(days=offset)}T14:00:00Z"}
                     for i, offset in enumerate([0, 2, 5, 5, 9, 13, 18, 22, 32, 43, 54, 69])]
        runway = runway_payload(drafts + scheduled, start=TODAY, days=days,
                                zone_name="America/New_York", minimum_spacing=spacing)
        events_by_day = {}
        for event in runway["events"]:
            events_by_day.setdefault(event["date"], []).append(event)
        return {"runway": runway, "events_by_day": events_by_day, "drafts": drafts,
                "opening_days": suggested_openings(runway), "last_sync_at": f"{TODAY}T14:30:00Z"}


class DemoHandler(DashboardHandler):
    service = DemoAnalytics()
    planner = DemoPlanner()

    def do_GET(self):
        path = urlsplit(self.path).path
        if (path in STATIC_FILES or path in {"/discovery", "/notes", "/planner",
                                             "/api/dashboard", "/api/latest", "/api/note-comparison", "/api/planner"}
                or path.startswith(("/api/post/", "/api/note/"))):
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        self.send_error(405)


def demo_server():
    return ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
