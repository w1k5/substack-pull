"""Compatibility import for the shared private Note puller."""

from importlib import import_module
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.modules[__name__] = import_module("substack_local.pullers.private_notes")
