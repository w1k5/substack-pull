"""Notes source credits must not be mistaken for standalone Note conversions."""

from unittest import TestCase

from substack_local.analytics.subscriber_attribution import notes_source_attribution


def source(name, count, **extra):
    return {"source": name, "metrics": [{"name": "Subscribers", "total": count}], **extra}


class SubscriberAttributionTests(TestCase):
    def test_splits_post_and_note_links_without_double_counting_parent(self):
        growth = {"sourceMetrics": [source("substack", 110, children=[
            source("notes", 100, children=[
                source("p-123", 65, sourceName="Post title", noteId="123"),
                source("c-456", 20, sourceName="  A long  Note\ntext  ", noteId="456"),
                source("other (4)", 15, isAggregation=True,
                       originalSourceName="substack notes: c-999"),
            ]),
        ])]}
        result = notes_source_attribution(growth)
        self.assertEqual(result["subscribers"], 100)
        self.assertEqual(result["post_link_subscribers"], 65)
        self.assertEqual(result["note_link_subscribers"], 20)
        self.assertEqual(result["unclassified_subscribers"], 15)
        self.assertEqual(result["classified_share"], .85)
        self.assertEqual(result["post_link_share"], .65)
        self.assertEqual(result["note_link_share"], .2)
        self.assertEqual(result["unclassified_share"], .15)
        self.assertEqual(result["majority_link_type"], "post")
        self.assertEqual([(row["kind"], row["id"]) for row in result["items"]],
                         [("post", "123"), ("note", "456")])
        self.assertEqual(result["items"][1]["preview"], "A long Note text")

    def test_missing_source_or_unknown_item_type_stays_unclassified(self):
        self.assertEqual(notes_source_attribution({})["status"], "unavailable")
        growth = {"sourceMetrics": [source("substack", 8, children=[
            source("notes", 5, children=[source("mystery", 3), source("c-nope", 2)]),
        ])]}
        result = notes_source_attribution(growth)
        self.assertEqual(result["note_link_subscribers"], 0)
        self.assertEqual(result["post_link_subscribers"], 0)
        self.assertEqual(result["unclassified_subscribers"], 5)
        self.assertIsNone(result["majority_link_type"])

    def test_own_titles_and_outside_labels_are_separate(self):
        growth = {"sourceMetrics": [source("substack", 20, children=[
            source("notes", 16, children=[
                source("p-123", 10, sourceName="My Publication: My post"),
                source("c-456", 4, sourceName="My Publication: My Note"),
                source("c-789", 2, sourceName="Kat: A Note about my writing",
                       href="https://substack.com/note/c-789"),
            ]),
            source("trackbacks", 4, children=[
                source("somewhere", 4, sourceName="Another publication",
                       href="https://another.substack.com/p/story"),
            ]),
        ])]}
        result = notes_source_attribution(growth, own_post_ids=[123], own_note_ids=[456])
        self.assertEqual([row["preview"] for row in result["items"]],
                         ["My post", "My Note", "A Note about my writing"])
        self.assertEqual([row["ownership"] for row in result["items"]],
                         ["own", "own", "outside_label"])
        self.assertEqual([row["surface"] for row in result["outside_items"]],
                         ["Trackback", "Another writer’s Note"])
        self.assertEqual(result["outside_items"][1]["author_label"], "Kat")
