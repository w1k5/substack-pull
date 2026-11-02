# Local analytics and MCP code

The dashboard and MCP server share one analytics service. The post and Note puller CLIs keep responsibility for backing up content, authentication setup, and Note scheduling.

| File | Responsibility |
| --- | --- |
| `analytics.py` | Authenticated Substack requests, caching, and normalized publication, post, and Note data. Add a new analytics field here first. |
| `web.py` | Local HTTP routes and static dashboard files. It passes through data from `AnalyticsService`. |
| `mcp_server.py` | MCP tool names, arguments, and response selection. Analytics tools call `AnalyticsService`; backup tools call `pulls.py`. |
| `pulls.py` | Small adapters that run the existing post and Note CLIs and return their JSON output. Keep sync logic in the CLIs. |
| `ui/app.js` | Publication overview, sorting, date range, and page startup. |
| `ui/post.js` | Post detail loading and layout. |
| `ui/post_trajectory.js` | Post performance charts and dated Note markers. |
| `ui/post_notes.js` | Note reach data, caching, and Note cards. |
| `ui/post_insights.js` | Post sources, reader journey, and response panels. |
| `ui/common.js` | Shared browser formatting and loading helpers. |
| `ui/index.html`, `ui/style.css` | Dashboard structure and styling. |

`../substack_analytics.py` and `../substack_analytics_mcp.py` are compatibility entry points used by the existing launchers. The primary source is in this directory.

## Common changes

- **New analytics field:** Fetch and normalize it in `analytics.py`, then show it in the relevant `ui/` module and, if useful to agents, expose it through `mcp_server.py`.
- **New backup or search tool:** Extend the appropriate standalone CLI, add a JSON adapter in `pulls.py`, then define the MCP tool in `mcp_server.py`.
- **New dashboard panel:** Keep loading in `post.js` or `app.js` and put the panel's rendering code in the relevant feature module.

Run the dashboard with `./substack-analytics`. Start the stdio MCP server with `./substack-analytics-mcp`. The MCP process does not depend on the dashboard process. Both read the saved Substack session when needed and do not return it to the browser or MCP caller.

For a quick check after changes:

```sh
python3 -m unittest discover -s tests -p 'test_substack_mcp_workflows.py'
python3 -m py_compile substack_local/*.py substack_analytics.py substack_analytics_mcp.py
node --check substack_local/ui/app.js
```
