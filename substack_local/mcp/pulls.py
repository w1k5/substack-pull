"""Compatibility import for the shared backup workflows."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("substack_local.workflows.backups")
