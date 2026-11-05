"""Import the self-contained puller packages shared by CLI, dashboard, and MCP."""

from functools import lru_cache
from importlib import import_module
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
POST_CONFIG = ROOT / ".substack-pull.json"
NOTE_CONFIG = ROOT / ".substack-notes-pull.json"


@lru_cache(maxsize=3)
def _load(directory: Path, name: str):
    if not directory.is_dir():
        raise RuntimeError(f"Substack implementation is unavailable: {directory}")
    path = str(directory)
    if path not in sys.path:
        sys.path.insert(0, path)
    return import_module(name)


def post_puller():
    return _load(ROOT / "skills/substack-pull/scripts", "substack_post_core")


def private_notes():
    return _load(
        ROOT / "skills/substack-notes-pull/scripts", "substack_private_core",
    )


def public_notes():
    return _load(
        ROOT / "skills/substack-notes-pull/scripts", "substack_public_core",
    )
