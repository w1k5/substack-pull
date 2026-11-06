"""Writable data location for source checkouts and packaged desktop builds."""

import os
from pathlib import Path
import sys


def data_root() -> Path:
    override = os.environ.get("CLEARVIEW_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Clearview"
    return Path(__file__).resolve().parents[1]
