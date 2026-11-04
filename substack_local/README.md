# Local Substack code map

The dashboard and MCP server use one analytics service. The browser reaches it through
the local dashboard HTTP server; AI clients reach it through MCP tools. Both analytics
interfaces use the same normalization and cache. The standalone post and Note CLIs in `../skills/`
continue to own backups, authentication setup, and Note scheduling, so each skill still
works without this package.

```text
Browser   → dashboard/server.py ──┐
                                  ├→ analytics/service.py → Substack
AI client → mcp/analytics_tools.py ┘            └→ analytics/cache.py

AI client → mcp/backup_tools.py → mcp/pulls.py → existing CLIs
```

The dashboard does not require an MCP process. Put reusable Substack requests and metric
definitions in `analytics/`; the two interfaces choose data and translate their transport.

| Area | Where to look |
| --- | --- |
| Analytics request setup | `analytics/client.py` loads the puller's authenticated client and repository paths. |
| Publication data | `analytics/publication.py` fetches traffic, sources, events, and the post index. |
| Post and Note data | `analytics/post.py` and `analytics/note.py` shape individual performance responses. `analytics/note_comparison.py` calculates Note rates, medians, and rankings for both the Notes page and MCP. `analytics/note_shares.py` links explicit post attachments in the published Notes backup to posts. |
| Shared cache | `analytics/service.py` validates IDs and combines cached post, Note, and publication data with bounded in-memory fallbacks; `analytics/cache.py` persists and prunes five-minute publication snapshots, the published post index, completed first-week post outcomes, individual post analytics, and Note stats for the dashboard and MCP. |
| MCP tools | `mcp/server.py` assembles the server; `mcp/registry.py` holds the server instance and annotations; `mcp/analytics_tools.py` registers read-only analytics; `mcp/backup_tools.py` registers backup and search operations through `mcp/pulls.py`. |
| Dashboard HTTP | `dashboard/server.py` handles local API requests and serves a fixed list of browser files. |
| Dashboard coordination | `dashboard/static/js/app.js` manages routes, data loading, and the date range. `dashboard/static/js/views/publication.js` renders the briefing and growth sources; `dashboard/static/js/views/tables.js` owns sorting, filtering, pagination, and CSV exports for source and post tables. |
| Publication charts | `dashboard/static/js/timeline.js` draws publication views and event markers; `dashboard/static/js/source-trend.js` draws subscriber source history on Discovery. |
| Notes and export UI | `dashboard/static/js/notes-page.js` renders individual Notes; `dashboard/static/js/notes-compare.js` loads and compares Note stats; `dashboard/static/js/notes-map.js` draws the outcome comparison on the Notes page. `dashboard/static/js/export.js` writes visible rows as CSV. |
| Post UI | `dashboard/static/js/post/` contains the first-week portfolio comparison, detail view, trajectory, Note reach, and insights. |
| Shared UI and styling | `dashboard/static/js/shared.js`, `dashboard/static/index.html`, and `dashboard/static/css/` (shell, overview, post, views). |

The UI tokens, control behavior, and analytics terms are recorded in [dashboard/DESIGN.md](dashboard/DESIGN.md).

The root launchers (`../substack-analytics` and `../substack-analytics-mcp`) still use `../substack_analytics.py` and `../substack_analytics_mcp.py`. The old imports `substack_local.web`, `substack_local.mcp_server`, and `substack_local.pulls` are compatibility shims; new code should import from the directories above.

## Where to make changes

- **New analytics field:** Fetch and normalize it in the matching `analytics/` file, then display it in the matching `dashboard/static/js/` file. Add an MCP response in `mcp/analytics_tools.py` when agents need the field.
- **New backup or search tool:** Extend the appropriate CLI under `../skills/`, add its JSON adapter in `mcp/pulls.py`, then define its tool in `mcp/backup_tools.py`.
- **New dashboard panel:** Keep page orchestration in `js/app.js` or `js/post/index.js` and put feature rendering beside related code.

Run the dashboard with `./substack-analytics` and the stdio MCP server with
`./substack-analytics-mcp`. The dashboard loads the saved session at launch; MCP analytics
loads it on the first analytics tool call. Neither returns it to the browser or MCP caller.

After changing code, run `python3 -m unittest discover -s tests`. Check browser module syntax with `node --check substack_local/dashboard/static/js/app.js` and open the local dashboard to verify its assets and data load.
