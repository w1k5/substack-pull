"""Provide the shared pullers and workspace paths to dashboard and MCP workflows."""

from ..pullers import posts, private_notes as private_notes_core, public_notes as public_notes_core
from ..paths import data_root

ROOT = data_root()
POST_CONFIG = ROOT / ".substack-pull.json"
NOTE_CONFIG = ROOT / ".substack-notes-pull.json"


def post_puller():
    return posts


def private_notes():
    return private_notes_core


def public_notes():
    return public_notes_core
