"""Compatibility import for the dashboard; implementation lives in dashboard.server."""

from .dashboard.server import DashboardHandler, STATIC, STATIC_FILES, main

if __name__ == "__main__":
    main()
