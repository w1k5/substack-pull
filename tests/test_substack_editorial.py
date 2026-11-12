"""Writer observations use measured comparisons and retain missing values."""

import unittest

from substack_local.analytics.derived import dashboard_metrics, post_index_metrics


class EditorialTests(unittest.TestCase):
    def test_missing_signups_do_not_become_zero_yield(self):
        row = post_index_metrics([{"id": "1", "date": "2026-11-01T12:00:00Z",
                                   "views": 2000, "signups": None}])[0]
        self.assertIsNone(row["signup_yield"])

    def test_period_observations_are_based_on_real_comparisons(self):
        snapshot = {
            "range": {"start": "2026-11-01", "end": "2026-11-30", "days": 30},
            "totals": {"views": 1500, "visitors": 700, "subscribers": 12},
            "previous": {"totals": {"views": 1000, "visitors": 600, "subscribers": 15}},
            "posts": [{"id": "10", "title": "Example", "date": "2026-11-03T12:00:00Z",
                       "views": 2000, "signups": 8}],
        }
        data = dashboard_metrics(snapshot)
        observations = data["editorial"]["observations"]
        self.assertEqual(observations[0]["title"], "More exposure, without more subscribers")
        self.assertEqual(observations[0]["path"], "/discovery")
        self.assertEqual(observations[-1]["path"], "/posts/10")

    def test_no_history_yields_no_invented_trend(self):
        data = dashboard_metrics({"range": {"start": "2026-11-01", "end": "2026-11-30", "days": 30},
                                  "totals": {"views": 100}})
        self.assertEqual(data["editorial"]["observations"], [])


if __name__ == "__main__":
    unittest.main()
