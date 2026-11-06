"""Provide the shared pullers and workspace paths to dashboard and MCP workflows."""

from pathlib import Path

from ..pullers import posts, private_notes as private_notes_core, public_notes as public_notes_core

ROOT = Path(__file__).resolve().parents[2]
POST_CONFIG = ROOT / ".substack-pull.json"
NOTE_CONFIG = ROOT / ".substack-notes-pull.json"


def post_puller():
    return posts


def private_notes():
    return private_notes_core


def public_notes():
    return public_notes_core
