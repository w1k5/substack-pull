# Local Substack code map

The dashboard and MCP server use one analytics service. The standalone post and Note CLIs in `../skills/` continue to own backups, authentication setup, and Note scheduling, so each skill still works without this package.

| Area | Where to look |
| --- | --- |
| Analytics request setup | `analytics/client.py` loads the puller's authenticated client and repository paths. |
| Publication data | `analytics/publication.py` fetches traffic, sources, events, and the post index. |
| Post and Note data | `analytics/post.py` and `analytics/note.py` shape individual performance responses. |
| Shared cache | `analytics/service.py` validates IDs and caches data for both interfaces. |
| MCP tools | `mcp/server.py` defines tool arguments and responses; `mcp/pulls.py` runs the existing CLIs for backup and search. |
| Dashboard HTTP | `dashboard/server.py` handles local API requests and serves a fixed list of browser files. |
| Publication UI | `dashboard/static/js/app.js` manages the overview, sorting, and date range. |
| Post UI | `dashboard/static/js/post/` contains the detail view, trajectory, Note reach, and insights. |
| Shared UI and styling | `dashboard/static/js/shared.js`, `dashboard/static/index.html`, and `dashboard/static/css/` (shell, overview, post). |

The root launchers (`../substack-analytics` and `../substack-analytics-mcp`) still use `../substack_analytics.py` and `../substack_analytics_mcp.py`. The old imports `substack_local.web`, `substack_local.mcp_server`, and `substack_local.pulls` are compatibility shims; new code should import from the directories above.

## Where to make changes

- **New analytics field:** Fetch and normalize it in the matching `analytics/` file, then display it in the matching `dashboard/static/js/` file. Add an MCP response in `mcp/server.py` when agents need the field.
- **New backup or search tool:** Extend the appropriate CLI under `../skills/`, add its JSON adapter in `mcp/pulls.py`, then define its tool in `mcp/server.py`.
- **New dashboard panel:** Keep page orchestration in `js/app.js` or `js/post/index.js` and put feature rendering beside related code.

Run the dashboard with `./substack-analytics` and the stdio MCP server with `./substack-analytics-mcp`. Both read the saved session only when needed; neither returns it to the browser or MCP caller.

After changing code, run `python3 -m unittest discover -s tests`. Check browser module syntax with `node --check substack_local/dashboard/static/js/app.js` and open the local dashboard to verify its assets and data load.
