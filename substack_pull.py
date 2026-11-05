#!/usr/bin/env python3
"""Compatibility entrypoint for the bundled substack-pull skill CLI."""

from pathlib import Path
import sys

_SCRIPTS = (
    Path(__file__).resolve().parent
    / "skills"
    / "substack-pull"
    / "scripts"
)
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import substack_post_core as _implementation

globals().update({name: value for name, value in vars(_implementation).items()
                  if not name.startswith("__")})
if __name__ != "__main__" and __name__ in sys.modules:
    sys.modules[__name__] = _implementation


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
