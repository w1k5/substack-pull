"""Packaged engine entry point shared by the Windows dashboard and MCP."""

import sys

from substack_local.dashboard.server import main as dashboard_main
from substack_local.desktop.connection import main as connection_main


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"connection", "dashboard", "mcp"}:
        print("Usage: clearview-engine {connection|dashboard|mcp} ...", file=sys.stderr)
        return 2
    action = sys.argv.pop(1)
    if action == "connection":
        return connection_main()
    if action == "dashboard":
        dashboard_main()
    else:
        from substack_local.mcp.server import main as mcp_main
        mcp_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
