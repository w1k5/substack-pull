#!/usr/bin/env python3
"""Compatibility command for the substack_public_core implementation."""

from pathlib import Path
import sys

SCRIPTS = str(Path(__file__).resolve().parent)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import substack_public_core as _implementation

# Existing imports keep the same public functions and classes.
globals().update({name: value for name, value in vars(_implementation).items()
                  if not name.startswith("__")})
if __name__ != "__main__" and __name__ in sys.modules:
    sys.modules[__name__] = _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
