"""Shared authenticated Substack client and repository paths."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "substack-pull" / "scripts"))
from substack_post_core import (  # noqa: E402
    ApiClient,
    KeychainStore,
    PullError,
    host_for,
    load_config,
    paginate_posts,
    query_path,
)

CONFIG = ROOT / ".substack-pull.json"
