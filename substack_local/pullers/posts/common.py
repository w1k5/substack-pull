"""Shared post puller constants and errors."""

APP_NAME = "substack-pull"
READ_ONLY_POST_PATHS = frozenset({"/api/v1/publication/stats/growth/partial-timeseries"})
KEYCHAIN_SERVICE = "com.local.substack-pull"
DEFAULT_CONFIG = ".substack-pull.json"
DEFAULT_OUTPUT = "substack"
STATE_VERSION = 1
POST_ARTIFACT_SUFFIXES = (".json", ".html", ".md")

CATEGORY_ENDPOINTS = {
    "drafts": ("/api/v1/post_management/drafts", "draft_updated_at"),
    "scheduled": ("/api/v1/post_management/scheduled", "draft_updated_at"),
    "published": ("/api/v1/post_management/published", "post_date"),
}

# Engagement and delivery counters do not trigger body downloads.
FINGERPRINT_FIELDS = (
    "id", "slug", "type", "title", "subtitle", "draft_title", "draft_subtitle",
    "draft_updated_at", "updated_at", "post_date", "publish_date",
    "published_at", "scheduled_at", "scheduled_release",
    "scheduled_release_at", "send_at", "trigger_at", "email_audience",
    "post_audience", "section_id", "audience",
)

class PullError(RuntimeError):
    """An expected, user-facing sync error."""
