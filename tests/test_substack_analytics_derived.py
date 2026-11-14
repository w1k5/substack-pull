"""Writer-facing derived metrics stay consistent across cached and live responses."""

from unittest import TestCase

from substack_local.analytics.derived import activity_period, dashboard_metrics, post_detail_metrics, publication_buckets
from substack_local.analytics.leaderboard import note_rows
from substack_local.analytics.post_comparison import summarize_post_portfolio
from substack_local.workflows.notes import suggested_openings


class DerivedMetricsTests(TestCase):
    def test_events_use_the_bucket_dates_returned_by_each_series(self):
        events = [{"day": "2026-11-11"}, {"day": "2026-11-06"}]
        shown, earlier = publication_buckets(events, [["2026/11/09", 10]], ["2026-11-08"], 7)
        self.assertEqual(shown["view_bucket_index"], 0)
        self.assertEqual(shown["subscriber_bucket_day"], "2026-11-08")
        self.assertIsNone(earlier["view_bucket_index"])
        self.assertIsNone(earlier["subscriber_bucket_day"])

    def test_activity_bucket_is_partial_only_if_it_contains_period_end(self):
        for days, last, partial in ((30, "2026/11/14", True), (30, "2026/11/13", False),
                                    (180, "2026/11/08", True), (180, "2026/11/07", False)):
            with self.subTest(days=days, last=last):
                result = activity_period({"days": days, "end": "2026-11-14"}, [[last, 20]])
                self.assertEqual(result["last_bucket_partial"], partial)
        self.assertFalse(activity_period({"days": 30, "end": "2026-11-14"}, [])["last_bucket_partial"])

    def test_note_ranking_preserves_missing_counts_and_age_matched_reach(self):
        row, = note_rows([{"id": 2, "title": "Note", "day": "2026-11-04",
                           "likes": 0, "pace": {"ratio": 2.2}}])
        self.assertEqual(row["likes"], 0)
        self.assertIsNone(row["growth"])
        self.assertIsNone(row["discussion"])
        self.assertEqual(row["relative"], 2.2)

    def test_discovery_ranking_omits_outside_labels_and_marks_dashboard_links(self):
        data = dashboard_metrics({
            "publication_events": [{"type": "note", "id": 3}],
            "notes_source_attribution": {"items": [
                {"kind": "note", "id": "1", "ownership": "outside_label", "subscribers": 10},
                {"kind": "note", "id": "2", "subscribers": 6},
                {"kind": "note", "id": "3", "subscribers": 5},
                {"kind": "note", "id": "4", "subscribers": 1},
                {"kind": "note", "id": "5", "subscribers": 1},
            ]},
        })
        rows = data["discovery_rankings"]["note"]
        self.assertEqual([row["id"] for row in rows], ["2", "3", "4"])
        self.assertEqual([row["in_dashboard"] for row in rows], [False, True, False])

    def test_publication_metrics_use_new_york_day_and_source_denominators(self):
        data = dashboard_metrics({
            "range": {"start": "2026-11-01", "end": "2026-11-14", "days": 14},
            "totals": {"views": 120, "visitors": 90, "subscribers": 10},
            "previous": {"totals": {"views": 100, "visitors": 0, "subscribers": 5}},
            "growth_sources": [{"name": "Substack", "subscribers": 8, "parent": None},
                               {"name": "Notes", "subscribers": 3, "parent": "Substack"}],
            "traffic_sources": [{"users": 20, "free_signups": 2, "paid_signups": 1}],
            "posts": [{"id": "1", "date": "2026-11-04T02:00:00Z", "views": 1000,
                       "signups": 2, "likes": 25, "comments": 5, "restacks": 4, "shares": 10}],
        })
        self.assertEqual(data["posts"][0]["publication_day"], "2026-11-03")
        self.assertTrue(data["posts"][0]["published_in_period"])
        self.assertTrue(data["posts"][0]["meets_view_floor"])
        self.assertEqual(data["posts"][0]["signup_yield"], 2)
        self.assertEqual(data["posts"][0]["likes_per_1k"], 25)
        self.assertEqual(data["posts"][0]["restacks_per_1k"], 4)
        self.assertEqual(data["traffic_sources"][0]["signup_rate"], .15)
        self.assertEqual(data["briefing"]["changes"]["views"]["percent"], 20)
        self.assertEqual(data["briefing"]["changes"]["visitors"]["status"], "new")
        self.assertEqual(data["briefing"]["notes_share"], .3)
        self.assertEqual(data["leaderboard_rows"][0]["signupYield"], 2)
        self.assertEqual([row["name"] for row in data["ranked_growth_sources"]], ["Substack", "Notes"])

    def test_post_story_excludes_today_and_precomputes_daily_and_source_rates(self):
        post = post_detail_metrics({
            "first_week": [
                {"day_n": 1, "dt": "2026-11-04T12:00:00Z", "cumulative_views": 300,
                 "cumulative_signups": 3, "comps": {"avg_cumulative_views": 200, "avg_cumulative_signups": 2}},
                {"day_n": 0, "dt": "2026-11-03T12:00:00Z", "cumulative_views": 100,
                 "cumulative_signups": 1, "comps": {"avg_cumulative_views": 80, "avg_cumulative_signups": 1}},
            ],
            "reach": {"views": 500, "sent": 100, "delivered": 90, "shares": 5},
            "traffic": {"referrers": [
                {"source": "A", "views": 50, "signups": 2, "subscribes": 0, "percent_of_total_views": .5},
                {"source": "B", "views": 10, "signups": 1, "subscribes": 0, "percent_of_total_views": .1},
            ], "devices": [{"device_type": "Mobile", "views": 75},
                           {"device_type": "Desktop", "views": 25}]},
            "engagement": {"likes": 10, "comments": 2, "restacks": 3,
                           "scroll_depth": {"preview": {"readers": 20, "reached_25": 10}}},
        }, today="2026-11-04")
        self.assertEqual(post["first_week"][1]["daily_views"], 200)
        self.assertEqual(post["first_week"][1]["typical_daily_views"], 120)
        self.assertEqual(post["story"]["performance"]["views"], 100)
        self.assertTrue(post["story"]["performance"]["has_partial_day"])
        self.assertEqual(post["insights"]["sources"][0]["signup_share"], 2 / 3)
        self.assertTrue(post["insights"]["sources"][0]["leading"])
        self.assertEqual(post["insights"]["delivered_share"], .9)
        self.assertEqual(post["insights"]["reading_shares"]["reached_25"], .5)
        self.assertEqual(post["insights"]["devices"][0]["share"], .75)
        self.assertEqual(post["insights"]["response_rates"]["likes"], 20)
        self.assertEqual(post["insights"]["response_rates"]["restacks"], 6)

    def test_post_cohort_rules_and_medians_are_server_owned(self):
        rows = [
            {"id": "1", "post_type": "newsletter", "audience": "everyone", "views": 100,
             "lifetime_views": 1500, "later_week_share": .4, "signup_yield": 10,
             "share_rate": 2, "likes_rate": 20, "comments_rate": 3, "restacks_rate": 1,
             "later_views": 1400, "later_multiple": 14, "signups": 1, "title": "First"},
            {"id": "2", "post_type": "newsletter", "audience": "everyone", "views": 200,
             "lifetime_views": 2200, "later_week_share": .6, "signup_yield": 20,
             "share_rate": 3, "likes_rate": 30, "comments_rate": 4, "restacks_rate": 2,
             "later_views": 2000, "later_multiple": 10, "signups": 4, "title": "Second"},
            {"id": "3", "post_type": "newsletter", "audience": "everyone", "views": 50,
             "lifetime_views": 300, "later_week_share": .8, "signup_yield": 0,
             "share_rate": None, "later_views": 250, "later_multiple": 5, "signups": 0, "title": "Too small"},
            {"id": "4", "post_type": "podcast", "audience": "everyone", "views": 1000,
             "lifetime_views": 2000, "later_week_share": .9, "signup_yield": 30,
             "share_rate": 4, "later_views": 1000, "later_multiple": 1, "signups": 30, "title": "Other type"},
        ]
        result = summarize_post_portfolio(rows)
        self.assertEqual(result["cohort_size"], 3)
        self.assertEqual(result["other_types"], 1)
        self.assertEqual(result["lenses"]["staying"]["eligible_ids"], ["1", "2"])
        self.assertEqual(result["lenses"]["staying"]["median_y"], .5)
        self.assertEqual(result["lenses"]["yield"]["standout_ids"], ["2"])
        self.assertEqual(result["lenses"]["sharing"]["eligible_ids"], ["1", "2"])
        self.assertEqual(result["lenses"]["likes"]["median_y"], 25)
        self.assertEqual(result["lenses"]["comments"]["eligible_ids"], ["1", "2"])
        self.assertEqual(result["lenses"]["restacks"]["median_y"], 1.5)

    def test_planner_openings_respect_spacing_and_busy_weeks(self):
        runway = {"start": "2026-11-02", "end": "2026-11-15", "minimumSpacing": 3,
                  "events": [{"date": "2026-11-02"}, {"date": "2026-11-08"},
                             {"date": "2026-11-09"}, {"date": "2026-11-10"},
                             {"date": "2026-11-11"}]}
        self.assertEqual(suggested_openings(runway), ["2026-11-05"])
