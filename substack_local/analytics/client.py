"""Shared authenticated Substack client and repository paths."""

from ..paths import data_root

ROOT = data_root()
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
