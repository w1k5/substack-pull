# substack-pull

## Code map

The local analytics dashboard and MCP server live in [`substack_local/`](substack_local/README.md). Their shared Substack requests and data shaping are in `substack_local/analytics.py`; `web.py` serves the dashboard, `mcp_server.py` defines the tools, and `pulls.py` connects MCP tools to the existing post and Note CLIs. The browser code is in `substack_local/ui/`.

The standalone post and Note pullers remain in `skills/substack-pull/scripts/` and `skills/substack-notes-pull/scripts/`. The root launchers (`./substack-analytics`, `./substack-analytics-mcp`, `./substack-pull`, and `./substack-notes-pull`) are the user-facing entry points.

## Local analytics dashboard

Run `./substack-analytics`, then open [http://127.0.0.1:8765](http://127.0.0.1:8765) in Safari. Stop it with Control-C in the terminal. It reuses the publication in `.substack-pull.json` and the session already stored by `./substack-pull auth` in macOS Keychain. No new authentication step is needed while that session remains valid.

The dashboard reads Substack's authenticated analytics requests for daily views, growth sources, traffic referrers, and published post stats. Opening a post also reads `/api/v1/post_management/detail/{id}` plus its `traffic`, `engagement`, and `growth` subresources. These supply source-level signups, device mix, reading depth, and reader response. Substack also calls `recipients` for individual reader activity, `discussion?tabId=…` for conversations, and `share_center/{id}` for sharing tools. Clearview shows aggregate performance without copying reader identities or conversations. The dashboard is read-only, listens only on `127.0.0.1`, and keeps the session out of page responses and local files. Publication metrics use the calendar date range shown at the top; post metrics are lifetime totals. Refresh forces a new fetch, while ordinary range changes may reuse a response for up to five minutes. The underlying endpoints are undocumented and may require updates if Substack changes them.

The selected date range can differ slightly from Substack's rolling “30d views” card. Parent growth sources include their child sources, so their subscriber counts should not be added together. Source signup ratios are directional attribution measures, not controlled conversion experiments.

### Substack MCP server

The dashboard and local MCP server use the same request and normalization code in `substack_local/analytics.py`. The MCP server reads the session already saved by `./substack-pull auth`; it does not need the dashboard to be running. Each process keeps its own short-lived in-memory cache, so using both at once can occasionally repeat a Substack request.

To set it up on another Mac with this repository and a saved Substack session:

```sh
python3 -m venv "$HOME/.codex/substack-analytics-mcp-venv"
"$HOME/.codex/substack-analytics-mcp-venv/bin/python" -m pip install -r requirements-analytics-mcp.txt
python3 register-analytics-mcp.py
```

Reconnect MCP servers in Codex after registration. The server includes analytics tools for publication trends, sources, posts, and Notes. `note_performance` accepts a numeric or `c-` ID; request `include_series=true` only when the impression series is needed.

It also wraps the existing pullers: `workspace_info`, `backup_status`, `pull_own_posts`, `pull_public_posts`, `find_post_copies`, `read_post_copy`, `pull_notes`, `find_note_copies`, `read_note_copy`, `note_schedule_runway`, `pull_published_notes`, and `find_published_notes`. The two bundled skills prefer these tools when `workspace_info` matches the requested local copy. Pull tools write to the local ignored backup directory, while making only read requests to Substack. Search and read tools use those local copies, so pull first when freshness matters. Refresh published posts before a performance comparison; ordinary incremental pulls can leave engagement stats stale. Published Note history is fetched anonymously only when requested, and each profile gets its own backup directory.

Note draft creation and scheduling continue through `./substack-notes-pull`, which previews the exact change and verifies it after explicit approval. The MCP server has no network listener and never returns the session value. See [`mcp.json`](mcp.json) for the stdio launch configuration.

Looking for the Notes-only companion? See
[`SUBSTACK_NOTES_PULL.md`](SUBSTACK_NOTES_PULL.md) and run
`./substack-notes-pull`.

A read-only, incremental local backup of Substack drafts, scheduled posts, and
published posts. It uses the same undocumented JSON endpoints as Substack's
writer dashboard.

Authentication stays in **macOS Keychain**. The project configuration contains
only the publication URL and backup directory—never the Substack session. The
default `substack/` backup directory is ignored by Git.

## Requirements

- macOS
- Python 3.10+
- Safari or a Chromium-based browser signed into the Substack account that
  owns or edits the publication

The same manual cookie-copy workflow applies to Google Chrome, Chromium, Brave,
Microsoft Edge, and other browsers with Chromium DevTools. The CLI does not
access the browser profile directly; it only uses the cookie value you paste
into Keychain. No Python packages or browser extension are required.

## Install as a Codex skill

In Codex, ask the built-in skill installer:

```text
Use $skill-installer to install https://github.com/w1k5/substack-pull/tree/main/skills/substack-pull
```

The skill becomes available on the next turn. It contains the complete CLI, so
the recipient does not need to clone this repository separately. Invoke it with:

```text
Use $substack-pull to pull my publication and tell me what changed.
```

Each person authenticates their own Substack account into their own macOS
Keychain. Credentials and publication content are never shared through the
skill or repository.

## One-time authentication

1. Sign into Substack in your browser.
2. Find the session cookie using that browser's developer tools:

   - **Safari:** Open a Substack page, then choose **Developer → Show Web
     Inspector**. If the Developer menu is hidden, enable developer features
     under Safari Settings → Advanced. Open **Storage → Cookies →
     `substack.com`** and find `connect.sid`.
   - **Chrome, Chromium, Brave, Edge, or another Chromium-based browser:** Open
     a Substack page and DevTools, then open **Application → Storage → Cookies**.
     Select the Substack origin containing `substack.sid` and find that cookie.

3. Copy only the cookie's **Value**, without `connect.sid=` or `substack.sid=`.
   Treat it like a password.
4. Run:

   ```bash
   ./substack-pull auth --publication https://YOURNAME.substack.com
   ```

   Paste the value at the Keychain prompt. Input is hidden. The command verifies
   editor access with a read-only drafts request.

Use the publication's canonical `*.substack.com` hostname, even if readers use a
custom domain. The CLI intentionally refuses to send the session credential to
other domains.

## Pull

```bash
./substack-pull
```

`pull` is the default command, so `./substack-pull pull` is equivalent. The
older `sync` name remains an alias. Output includes the absolute backup
directory, category counts, and the title and local paths of every fetched
post.

The first pull downloads every currently listed item. Later pulls always fetch
the three remote indexes, but downloads a full body only when:

- the post ID is new;
- an editorial timestamp/title/slug changed;
- its local file is missing; or
- `--refresh-published` was requested.

Substack's draft and scheduled indexes expose `draft_updated_at`; scheduled
items also expose `trigger_at`. Changes to either cause the complete draft and
its current scheduling metadata to be downloaded again on the next pull.

```bash
./substack-pull pull --refresh-published
```

Run that occasionally if you edit published posts and Substack does not expose
an updated timestamp in its list response.

## Local files

```text
substack/
├── drafts/
│   ├── 123.json
│   ├── 123.md         # readable companion generated from HTML or ProseMirror
│   └── 123.html       # when Substack returned an HTML body
├── scheduled/
├── published/
└── .sync/
    └── state.json
```

JSON files are the lossless source of truth. HTML companions are convenience
copies. Markdown companions make both current ProseMirror drafts and older HTML
posts easy to read. Items that disappear remotely are moved into `archive/`
and recorded there in `state.json`; their local copies are preserved.

## Find a post

Search recent local posts by title or ID after pulling:

```bash
./substack-pull list --query "whole foods roses" --limit 5
./substack-pull list --category scheduled
./substack-pull list --category published --limit 10
```

Results are newest first and include `readable_file` whenever a Markdown copy is
available. Use `--include-missing` to include preserved items that no longer
appear in Substack's current index.

## Other commands and options

```bash
./substack-pull doctor
./substack-pull status
./substack-pull pull --request-delay 0.5
./substack-pull pull --directory /absolute/backup/path
./substack-pull pull -d /absolute/backup/path
./substack-pull --config /path/to/config.json pull
```

`--directory` on `pull` overrides the location for one run. To save a new
default without re-entering authentication:

```bash
./substack-pull configure --directory /absolute/backup/path
./substack-pull
```

The older `--output` spelling remains available as an alias.

If Substack returns 401 or 403, copy the current session cookie value again
(`connect.sid` in Safari or `substack.sid` in Chromium DevTools) and run `auth`
again. Substack does not publish or support these endpoints, so a future
dashboard change may require updating this tool.

## Tests

The test suite uses a local HTTP server that reproduces the relevant Substack
response shapes. It never connects to Substack or reads Keychain.

```bash
python3 -m unittest discover -s tests -v
```
