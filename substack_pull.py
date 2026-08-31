#!/usr/bin/env python3
"""Compatibility entrypoint for the bundled substack-pull skill CLI."""

from pathlib import Path
import runpy


_SCRIPT = (
    Path(__file__).resolve().parent
    / "skills"
    / "substack-pull"
    / "scripts"
    / "substack_pull.py"
)
_IMPLEMENTATION = runpy.run_path(str(_SCRIPT))
globals().update(
    {
        name: value
        for name, value in _IMPLEMENTATION.items()
        if not name.startswith("__")
    }
)


if __name__ == "__main__":
    raise SystemExit(_IMPLEMENTATION["main"]())
