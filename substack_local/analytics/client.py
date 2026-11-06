"""Shared authenticated Substack client and repository paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from ..pullers.posts import (
    ApiClient,
    KeychainStore,
    PullError,
    host_for,
    load_config,
    paginate_posts,
    query_path,
)

CONFIG = ROOT / ".substack-pull.json"
