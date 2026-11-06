"""Private Note puller constants."""

APP_NAME = "substack-notes-pull"
KEYCHAIN_SERVICE = "com.local.substack-pull"
LEGACY_KEYCHAIN_SERVICE = "com.local.substack-notes-pull"
LEGACY_KEYCHAIN_ACCOUNT = "substack.com"
SUBSTACK_PULL_CONFIG = ".substack-pull.json"
DEFAULT_CONFIG = ".substack-notes-pull.json"
DEFAULT_OUTPUT = "substack-notes"
STATE_VERSION = 1
NOTE_CATEGORIES = ("note-drafts", "note-scheduled")
MAX_NOTE_LENGTH = 5_000
