"""Shared Substack analytics interface."""

from .client import (
    ApiClient,
    CONFIG,
    ROOT,
    KeychainStore,
    PullError,
    host_for,
    load_config,
    paginate_posts,
    query_path,
)
from .note import note_stats
from .post import fetch_post
from .publication import fetch_dashboard, fetch_posts, metric, source_row
from .service import ALLOWED_DAYS, AnalyticsService, numeric_id
