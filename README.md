# Substack Pull

Local tools for backing up Substack posts and Notes, exploring publication analytics,
and giving Codex access to the same data through MCP.

| What you want to do                                                     | Command                                        |
| ----------------------------------------------------------------------- | ---------------------------------------------- |
| Back up your publication's drafts, scheduled posts, and published posts | `./substack-pull pull`                         |
| Back up draft and scheduled Notes                                       | `./substack-notes-pull pull`                   |
| Explore analytics and plan Note drafts and schedules                     | `./substack-analytics`                         |
| Use analytics and backups from Codex                                    | Set up the [MCP server](#mcp-server-for-codex) |

The post puller and analytics views read Substack data. The Notes CLI, MCP Note tools,
and dashboard Note planner can also create a draft or change a schedule after a preview
and confirmation step. They do not publish immediately.

For a possible no-code Mac and Windows app, see the [desktop app plan](docs/desktop-app-plan.md).

## Requirements

- macOS and Python 3.10 or newer.
- For your own publication: a browser signed in to a Substack account that can edit it.
- For the MCP server only: the Python package in `requirements-analytics-mcp.txt`.

The CLIs and dashboard need no third-party Python packages. Public post and public Note
backups do not need a Substack login.

## First-time setup for your own publication

1. In Safari or a Chromium-based browser, sign in to Substack.
2. Open the browser's developer tools and find the Substack session cookie:
   - **Safari:** Developer → Show Web Inspector → Storage → Cookies → `substack.com` →
     `connect.sid`. Enable developer features in Safari Settings → Advanced if the
     Developer menu is hidden.
   - **Chrome, Edge, Brave, or Chromium:** DevTools → Application → Storage → Cookies →
     the Substack origin → `substack.sid`.
3. Copy only the cookie's **Value**. Treat it like a password.
4. From this repository, run:

   ```sh
   ./substack-pull auth --publication https://YOURNAME.substack.com
   ```

   Paste the value at the hidden prompt. The command checks editor access and saves the
   session in macOS Keychain.

Use the publication's `*.substack.com` address even if readers visit a custom domain.
The saved configuration contains the publication URL and backup directory, not the
session. If Substack later returns 401 or 403, repeat the authentication step with a
current cookie.

## Back up and find posts

```sh
./substack-pull pull
./substack-pull list --query "whole foods roses"
./substack-pull list --category scheduled --limit 10
```

The first pull downloads everything currently listed in the publication's draft,
scheduled, and published indexes. Later pulls check those indexes and download a full
post again when its editorial details change or its local copy is missing.
`./substack-pull` without a subcommand also runs `pull`.

For current published engagement or delivery numbers, refresh the published posts before
comparing performance:

```sh
./substack-pull pull --refresh-published
```

Ordinary incremental pulls may keep older engagement snapshots for unchanged published
posts. Use `./substack-pull status` to see the last sync. Run `./substack-pull --help`
for directory, configuration, and request options.

Posts are saved under the ignored `substack/` directory:

```text
substack/
├── drafts/          # JSON and readable Markdown; HTML when available
├── scheduled/
├── published/
├── archive/         # local copies of posts no longer listed remotely
└── .sync/state.json # sync state
```

JSON preserves the returned post data; Markdown is the readable copy. A post that
disappears from Substack's indexes is moved to `archive/`, not deleted locally.

To back up another publication's public posts without using your session:

```sh
./substack-pull pull --public \
  --publication https://EXAMPLE.substack.com \
  --directory substack/public-example
```

## Work with Notes

`./substack-notes-pull pull` backs up your draft and scheduled Notes and builds a
planning runway. Use `./substack-notes-pull list` to find a local Note. New Note drafts
and schedule changes have separate preview and `--apply` steps; see the
[Notes skill instructions](skills/substack-notes-pull/SKILL.md).

For another profile's public, published Notes, see the
[public Notes guide](SUBSTACK_NOTES_PULL.md). That workflow needs no session.

## Analytics dashboard

Start the dashboard, then open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) in a
browser:

```sh
./substack-analytics
```

The dashboard uses the publication and session from the first-time setup. It listens
only on `127.0.0.1`; the session stays in Keychain and is not sent to the page. Keep the
terminal open while using the dashboard, then stop it with Control-C. This command does
not install a background service.

### Views and time ranges

Use the sidebar to move between four writer-focused views:

| View | What it answers |
| --- | --- |
| Briefing | What changed in views and subscriber growth, and which post or Note was published near a traffic change? |
| Posts | Which posts kept finding readers after launch day, brought in subscribers, or continued drawing views after week one? Select two dots to compare them, then open a post for its sources, direct Note shares, and reader response. |
| Discovery | When did each subscriber source contribute, where were subscriptions attributed, and which referrers brought traffic? |
| Notes | Which Notes combine strong age-matched reach with reader response, profile interest, link clicks, or a new audience? Browse and sort every Note in one table, then select one for its detailed reach and reader actions. |
| Note planner | When are Notes scheduled, where is there room, and which unpublished draft should go next? Create drafts and schedule or reschedule Notes from the calendar. |

The [Note planner](http://127.0.0.1:8765/planner) opens from the sidebar. Its calendar
and unscheduled draft list use the local Notes backup, so opening it does not contact
Substack. **Sync Notes** refreshes that backup on demand. Select a date to inspect its
scheduled Notes, choose a draft, then preview and confirm a future schedule. You can
also write and preview a new draft before saving it. The calendar marks days that have
room at the selected spacing; those are planning suggestions, not automatic schedules.
All Note times use the publication timezone shown on the page. The planner does not
publish a Note immediately or edit an existing Note's text.

Search posts and Notes from the header. The activity selector offers 7, 30, 90, 180, or
365 days. It controls publication traffic, discovery, and the Notes list. Post metrics
and individual Note reach are lifetime totals; the **Published in selected period**
filter narrows posts by publication date. The Briefing compares equal-length current
and preceding periods. Today may be incomplete.

### Reading the charts and tables

The Posts chart compares several outcomes: **Staying power** compares first-week reach with the
share earned on days 2–7; **Subscriber yield** compares first-week signups per 1,000
views; **Reader sharing** compares recorded share actions per 1,000 lifetime views;
**Reader response** compares likes, comments, or restacks per 1,000 lifetime views; and
**Later discovery** shows how many additional views accumulated after week one.
The first two use equal seven-day windows. The others use lifetime totals, so
check publication dates when comparing older and newer posts. The post portfolio and
MCP `post_portfolio` tool share these figures.

The Posts table shows lifetime likes, comments, and restacks as separate sortable
columns. Share actions remain in the Reader sharing chart, post story, and CSV export.
On narrow screens, those columns become labeled post cards with direct sort controls
and 10 posts per page. Selecting two chart dots shows compact comparisons beside the
chart on wider screens.
Likes and comments come from the authenticated
published post index. Restacks come from paginated public archive results and may be
unavailable for a post that is absent from that archive. The archive is fetched in
batches when the published index refreshes, then reused from the 15-minute cache.

A post's Distribution section identifies Notes that explicitly attached that post and
shows the Note's lifetime link clicks. Those clicks are Note interactions, not
attributed post views or subscriber conversions. The link comes from the local
published Notes backup; update it with
`./substack-notes-pull public pull --profile @yourhandle --directory substack/published-notes/yourhandle`
for your profile. Source labels expand Substack's ambiguous terms, including
Direct (which can include unidentified visits) and Direct to App (an external link
opened in the app with an unidentified origin).

Tables sort by clicking their headers. Posts can be filtered by date or minimum views,
and the Posts, Discovery, and Notes views can export their visible rows to CSV. The Notes
table lists every published Note in the selected period before its stats are loaded.
Selecting a Note in the table opens its details without moving the page. In the Notes
chart, select up to two dots to compare their reach and reader outcomes side by side;
the chart stays on the Notes page. Analyze Notes shows a spinner while the shared
analytics service fills the performance map and comparison columns.
Search filters the table and highlights matching Note text in the map. Reader
rates need at least 100 impressions; audience-share comparisons need at least 100 people.
Reach comparison uses Substack's typical Note at the same age. Reader actions and
audience are lifetime totals. CSV comparison columns remain blank until the analysis
finishes. Individual Note stats are reused from the one-hour cache when available.

Discovery’s source lines use the same date range and source-series request as Substack’s
growth page. Choose up to five top-level sources to compare their timing; select a post
or Note marker to open that piece's performance. Lines are separate attributions, and
source counts may overlap, so do not add them into a publication total. Parent growth
sources also include their child sources. Signup ratios describe Substack's attribution
and are directional, especially for small sources. The selected calendar range can differ
slightly from Substack's rolling “30d views” card. Note publication markers show timing,
not causation.

### Cache and refresh

The dashboard and MCP share normalized disk caches in the ignored
`substack/.analytics-cache/` directory. The caches never store the session cookie.

| Cached data | Reuse window |
| --- | --- |
| Publication traffic, growth, and sources | 5 minutes per activity period |
| Published post index | 15 minutes |
| Individual post and Note analytics | 1 hour |
| Completed first-week post comparisons | 24 hours |

The backend also keeps completed Notes and Posts comparison responses in memory for
five minutes. Reopening those charts in the same dashboard or MCP process reuses the
assembled cohort; the individual Note and post caches still share fetched data across
processes. A refresh of the relevant publication, post, or Note data invalidates the
corresponding comparison in that process. Another process may retain its comparison
for up to five minutes. **Retry unavailable** on the Notes comparison bypasses the
assembled cohort cache so temporarily missing Notes can be checked again.

A publication snapshot from a previous New York calendar day is never reused. The
first-week comparison needs one detail request per uncached post. Expired and invalid
cache files are pruned at service startup and on access at most once per hour, including
older session caches for the same publication. Post and Note backups are unaffected.
In-memory fallbacks expire and are capped at 64 records per type.

The backend calculates comparison cohorts, medians, sample eligibility, subscriber
yield, source attribution rates, and age-matched post summaries. The browser handles
formatting, sorting and filtering visible rows, chart layout, and interaction. It
renders the active view on demand; large secondary referrer lists are built only when
opened. The Notes table renders 50 rows at a time while search, sorting, and CSV export
continue to cover all matching Notes.

**Refresh publication** fetches a new publication snapshot and post index. **Refresh post**
and **Refresh Note** bypass their respective detail caches. MCP
`publication_summary`, `publication_timeline`, `publication_sources`, `list_posts`,
`post_performance`, and `note_performance` accept `refresh=true`. Publication tools
return `refreshed_at` to show when their shared snapshot was fetched. Published post
content has a separate incremental backup managed by `substack-pull`. Substack's
analytics endpoints are undocumented and may change.

## MCP server for Codex

The MCP server and dashboard call the same analytics service and shared disk cache;
the browser does not need the MCP server running. MCP calls the bundled post and Note
puller functions directly in its own Python process, without starting CLI subprocesses.
The dashboard planner and MCP Note actions use the same Note draft and scheduling
functions. MCP runs over local standard input/output and has no network listener. Pull
tools write to the ignored local backup directories; their Substack requests are
read-only.

The `publication_sources` tool includes the same dated subscriber source lines shown on
Discovery. The `post_portfolio` tool returns the same completed first-week cohort and
lifetime context used by the Posts comparison. The `compare_notes` tool returns the
Notes page's age-matched reach, reader-outcome rankings, medians, and rows for a selected
activity period.

On a Mac with this repository and a saved Substack session, run:

```sh
python3 -m venv "$HOME/.codex/substack-analytics-mcp-venv"
"$HOME/.codex/substack-analytics-mcp-venv/bin/python" -m pip install -r requirements-analytics-mcp.txt
python3 register-analytics-mcp.py
```

Reconnect MCP servers in Codex after registration. The tools cover publication trends,
source attribution, post and Note performance, local backup status, pulling, searching,
and reading. `workspace_info` identifies the publication and directories this MCP
instance uses; the bundled skills check it before using the tools. Pull before searching
when you need the newest local copy. MCP also previews and applies unpublished Note draft
creation and Note scheduling through the same verified operations as the Notes CLI. For
multiple drafts, the MCP batch tools use one preflight read and one final verification
sync instead of repeating both for every Note.
Neither operation publishes a Note immediately or edits an existing Note body.
Backup searches return at most 100 items per call and include `total` and `next_offset`
for paging. Draft and scheduled Note previews are optional; published Note search omits
full bodies so `read_published_note` can retrieve just the Note you need.
`published_notes_status` reports a public profile's local crawl state. Post and public
Note searches can include locally preserved copies no longer present remotely.

See [`mcp.json`](mcp.json) for the stdio launch configuration.

## Use as Codex skills

The skill instructions and compatibility commands live in `skills/`. Their shared
implementation lives in `substack_local/pullers/`, so use the skills from a full
checkout of this repository. Installing either skill directory alone does not
include the puller code. The MCP tools are the normal path for supported work.

The skill instructions are here:

- [Post pull skill](skills/substack-pull/SKILL.md)
- [Notes pull skill](skills/substack-notes-pull/SKILL.md)

Each person saves their own Substack session in their own Keychain. Installing a skill
does not share credentials or publication content.

## Code and tests

The user-facing commands are at the repository root. Post and Note puller
implementations are in `substack_local/pullers/`; the skill scripts forward to
them. The dashboard and MCP implementation are mapped in the
[local code guide](substack_local/README.md).

The tests use local fixtures and do not contact Substack or read Keychain:

```sh
python3 -m unittest discover -s tests -v
```
