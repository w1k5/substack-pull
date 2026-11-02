"""Compatibility import for CLI adapters; implementation lives in mcp.pulls."""

from .mcp import pulls as _pulls
from .mcp.pulls import *  # noqa: F401,F403
from .mcp.pulls import (  # noqa: F401
    _bounded_limit,
    _post_args,
    _profile,
    _public_note_dir,
    _public_post_dir,
    _public_post_url,
    _read_markdown,
    _run_json,
)

subprocess = _pulls.subprocess
