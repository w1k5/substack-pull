# Local Substack code map

The dashboard and MCP server use one analytics service. The browser reaches it through
the local dashboard HTTP server; AI clients reach it through MCP tools. Both analytics
interfaces use the same normalization and cache. The post and Note CLIs in
`../skills/` remain available as compatibility entry points. Their shared
implementation now lives in `pullers/`, which the CLI, dashboard, and MCP import
directly without starting child processes.

```text
Browser   → dashboard/server.py ──┐
                                  ├→ analytics/service.py → Substack
AI client → mcp/analytics_tools.py ┘            └→ analytics/cache.py

AI client → mcp/backup_tools.py → workflows/backups.py ──┐
                                                ├→ workflows/modules.py → pullers/
AI client → mcp/note_writes.py ──────────────────┘
Browser   → dashboard/planner API → workflows/notes.py → pullers/private_notes/
CLI       → skills/*/scripts/ → pullers/
Mac app   → desktop/connection.py → pullers/posts/ + macOS Keychain
          → dashboard/server.py
Windows app → desktop/connection.py → Windows Credential Manager
            → dashboard/server.py
```

The dashboard does not require an MCP process. Put reusable Substack requests and metric
definitions in `analytics/`; the two interfaces choose data and translate their transport.

| Area | Where to look |
| --- | --- |
| Analytics request setup | `analytics/client.py` loads the puller's authenticated client and repository paths. |
| Publication data | `analytics/publication.py` fetches traffic, sources, events, and the post index. |
| Post and Note data | `analytics/post.py` and `analytics/note.py` shape individual performance responses. `analytics/note_comparison.py` calculates Note rates, medians, and rankings for both the Notes page and MCP. `analytics/note_shares.py` links explicit post attachments in the published Notes backup to posts. |
| Derived comparisons | `analytics/derived.py` calculates publication deltas, signup rates, age-matched post summaries, attribution shares, and reader rates. `analytics/post_comparison.py` chooses the post cohort and its per-lens eligibility, medians, and standouts. |
| Shared cache | `analytics/service.py` validates IDs and combines cached post, Note, and publication data with bounded in-memory fallbacks; `analytics/cache.py` persists and prunes five-minute publication snapshots, the published post index, completed first-week post outcomes, individual post analytics, and Note stats for the dashboard and MCP. |
| MCP tools | `mcp/server.py` assembles the server; `mcp/registry.py` holds the server instance and annotations; `mcp/analytics_tools.py` registers read-only analytics; `mcp/backup_tools.py` exposes shared backup and search operations; `mcp/note_writes.py` exposes Note drafts and scheduling. |
| Shared pullers | `pullers/posts/`, `pullers/private_notes/`, and `pullers/public_notes/` own requests, sync, local files, and CLI commands. Their package `__init__.py` files preserve the previous imports. |
| Shared workflows | `workflows/modules.py` selects the pullers and workspace paths; `workflows/backups.py` handles backup searches and sync; `workflows/notes.py` supplies the calendar snapshot and Note actions to the dashboard. |
| Dashboard HTTP | `dashboard/server.py` handles local API requests, protects Note action routes with same-origin checks, and serves a fixed list of browser files. |
| Mac desktop sign-in | `../desktop/macos/ClearviewApp.swift` owns the native sign-in and dashboard window; `desktop/connection.py` verifies publication access and saves the shared publication configuration. The app saves the session in macOS Keychain under the service already used by the CLI and MCP. |
| Dashboard coordination | `dashboard/static/js/app.js` manages routes, data loading, and the date range. `dashboard/static/js/views/publication.js` renders the briefing and growth sources; `dashboard/static/js/views/tables.js` owns sorting, filtering, pagination, and CSV exports for source and post tables. |
| Publication charts | `dashboard/static/js/timeline.js` draws publication views and event markers; `dashboard/static/js/source-trend.js` draws subscriber source history on Discovery. |
| Notes and export UI | `dashboard/static/js/notes-page.js` renders individual Notes; `dashboard/static/js/notes-compare.js` loads and compares Note stats, rendering the table in batches of 50; `dashboard/static/js/notes-map.js` draws the outcome comparison on the Notes page; `dashboard/static/js/planner.js` renders the Note calendar, draft backlog, and preview and confirm flows. `dashboard/static/js/export.js` writes the relevant filtered rows as CSV. |
| Post UI | `dashboard/static/js/post/` contains the first-week portfolio comparison, detail view, trajectory, Note reach, and insights. |
| Shared UI and styling | `dashboard/static/js/shared.js` holds general DOM helpers; `dashboard/static/js/comparison-elements.js` builds the Posts and Notes selection cards; `dashboard/static/css/comparison-map.css` owns their common layout. `dashboard/static/index.html` assembles the views and stylesheets. Other CSS files stay scoped to the shell or a feature. |

The UI tokens, control behavior, and analytics terms are recorded in [dashboard/DESIGN.md](dashboard/DESIGN.md).

The backend owns metric definitions and planning rules. The browser owns formatting,
DOM updates, chart coordinates, visible-row sorting and filtering, and navigation.
`analytics/service.py` retains completed comparison responses for five minutes within
each process, in addition to its shared disk caches for fetched data. The dashboard
renders only the active route, and post detail builds secondary source rows on demand.

The root launchers (`../substack-analytics` and `../substack-analytics-mcp`) still use `../substack_analytics.py` and `../substack_analytics_mcp.py`. The old imports `substack_local.web`, `substack_local.mcp_server`, and `substack_local.pulls` are compatibility shims; new code should import from the directories above. The skill script packages also forward to `pullers/`, so their old command paths still work from this checkout.

## Where to make changes

- **New analytics field:** Fetch and normalize it in the matching `analytics/` file, then display it in the matching `dashboard/static/js/` file. Add an MCP response in `mcp/analytics_tools.py` when agents need the field.
- **New backup or search tool:** Extend the matching package in `pullers/`, add its direct workflow in `workflows/backups.py`, then define its tool in `mcp/backup_tools.py`.
- **New Note draft or schedule action:** Keep the verified operation in `pullers/private_notes/`, then expose it through `mcp/note_writes.py` or `workflows/notes.py` with distinct preview and apply steps.
- **New dashboard panel:** Keep page orchestration in `js/app.js` or `js/post/index.js` and put feature rendering beside related code.

Run the dashboard with `./substack-analytics` and the stdio MCP server with
`./substack-analytics-mcp`. The dashboard loads the saved session at launch; MCP analytics
loads it on the first analytics tool call. Neither returns it to the browser or MCP caller.

After changing code, run `python3 -m unittest discover -s tests`. Check browser module syntax with `node --check substack_local/dashboard/static/js/app.js` and open the local dashboard to verify its assets and data load.
