"""Public Note puller defaults and errors."""

APP_NAME = "substack-notes-pull"
DEFAULT_CONFIG = ".substack-notes-pull.json"
DEFAULT_OUTPUT = "substack-notes"
DEFAULT_BASE_URL = "https://substack.com"
STATE_VERSION = 1

class PullError(RuntimeError):
    """An expected, user-facing pull error."""
