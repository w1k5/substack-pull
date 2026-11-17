# Substack Pull

Local tools for backing up Substack posts and Notes, exploring publication analytics,
and giving Codex access to the same data through MCP. For your own publication,
authenticate once; then MCP is the normal path for pulling, searching, reading, and
planning. The CLI remains available for setup and manual use.

| What you want to do | Start here |
| --- | --- |
| Connect your Substack account on a Mac | [Desktop sign-in prototype](#desktop-sign-in-prototype) |
| Build the Windows beta | [Windows beta build](desktop/windows/README.md) |
| Work with analytics, backups, drafts, or schedules in Codex | [Set up the MCP server](#mcp-server-for-codex) |
| Explore the visual dashboard and Note planner | Run `./substack-analytics` |
| Run a manual post or Note backup | Run `./substack-pull pull` or `./substack-notes-pull pull` |

The post puller and analytics views read Substack data. The Notes CLI, MCP Note tools,
and dashboard Note planner can also create a draft or change a schedule after a preview
and confirmation step. They do not publish immediately.

For the GitHub-hosted download path and current Substack access decision, see the
[distribution plan](docs/github-distribution-plan.md) and
[packaging checklist](docs/packaging-todo.md). The broader product design
is in the [desktop app plan](docs/desktop-app-plan.md).

## Requirements

- macOS for the source-checkout authenticated tools and dashboard. The packaged
  Windows beta uses Windows Credential Manager; see its [build guide](desktop/windows/README.md).
- Python 3.10 or newer for the CLIs and dashboard; Python 3.11 or newer for the
  MCP registration command, which uses `tomllib`.
- For your own publication: a browser signed in to a Substack account that can edit it.
- For the MCP server only: the Python package in `requirements-analytics-mcp.txt`.

The macOS source-checkout CLIs and dashboard need no third-party Python packages.
The Windows beta bundle includes its own Python runtime, time-zone data, and local
MCP dependencies. The unauthenticated public post and Note pullers do not need a
Substack login or OS credential store.

## Desktop sign-in prototype

On macOS, run `./substack-desktop` from this checkout. It builds and opens a small
Clearview app. Select **Sign in to Substack** and sign in on Substack's page with
your usual email code or password. Clearview opens your publication automatically
if it finds one, or asks you to choose if you manage several. You can enter the
publication address if discovery fails. Clearview checks editor access, remembers
your publication for reconnects, saves the session in macOS Keychain, and opens
the dashboard. The same saved connection is used by the CLI and MCP tools. Use
**Clearview → Change Publication…** to select another publication with your saved
session, or **Clearview → Reconnect Substack…** if the session expires.
The Mac menu bar also provides the usual Edit, View, Window, and Help menus.
**View → Reload** reloads the current page; use **Refresh publication** in the
dashboard to request newer analytics.

This is a developer-run Mac beta prototype, not an installer for other writers. It needs
Xcode command line tools and Python 3.10 or newer. A separate [Windows beta
build](desktop/windows/README.md) uses the same data engine and dashboard.
The sign-in window uses a private WebKit session; the publication settings file stores
the address and backup directory, never the session value. It handles one publication
at a time. The app does not publish posts or Notes during sign-in.

The normal browser dashboard remains available with `./substack-analytics` after
connecting in the app. The access route for a broadly distributed Mac and Windows app
is still under review; see the [desktop app plan](docs/desktop-app-plan.md).

## Developer fallback: manual session setup

1. In Safari or a Chromium-based browser, sign in to Substack.
2. Open the browser's developer tools and find the Substack session cookie:
   - **Safari:** Develop → Show Web Inspector → Storage → Cookies → `substack.com`.
     If the Develop menu is hidden, enable **Show features for web developers** in
     Safari Settings → Advanced ([Apple's guide](https://support.apple.com/en-qa/guide/safari/sfri20948/mac)).
   - **Chrome, Edge, Brave, or Chromium:** DevTools → Application → Storage → Cookies →
     the Substack origin ([Chrome's guide](https://developer.chrome.com/docs/devtools/application/cookies)).
   Look for `connect.sid` or `substack.sid`; the name can differ by browser session.
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
├── drafts/          # JSON; readable Markdown and HTML when available
├── scheduled/
├── published/
├── archive/         # local copies of posts no longer listed remotely
└── .sync/state.json # sync state
```

JSON preserves the returned post data; Markdown is generated when its body can be
rendered. A post that disappears from Substack's indexes is moved to `archive/`, not
deleted locally.

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

The dashboard uses the publication and session from the app or developer setup. It listens
only on `127.0.0.1`; the session stays in Keychain and is not sent to the page. Keep the
terminal open while using the dashboard, then stop it with Control-C. This command does
not install a background service.

### Views and time ranges

Use the sidebar to move between these writer-focused views:

| View | What it answers |
| --- | --- |
| Briefing | Current reach and subscriber growth, one supported observation, the latest writing, and a publication timeline. Detailed period figures stay available on demand. |
| Posts | Compare posts in a chart, select two dots, then use the exact-figures table or open a post for sources, direct Note shares, and reader response. |
| Discovery | When did each subscriber source contribute, and which Note or post links inside the Notes surface received subscriber credit? A compact split and ranked links sit above the broader source and traffic views. |
| Notes | Compare Notes in a chart, select two dots, then use the exact-figures table or open a Note for its detailed results. Note reach is compared with a typical Note at the same age. |
| Note planner | When are Notes scheduled, where is there room, and which unpublished draft should go next? Create drafts and schedule or reschedule Notes from the calendar. |

The [Note planner](http://127.0.0.1:8765/planner) opens from the sidebar. Its 90-day calendar
and unscheduled draft list use the local Notes backup, so opening it does not contact
Substack. **Sync Notes** refreshes that backup on demand. Select a date to inspect its
scheduled Notes, choose a draft, then preview and confirm a future schedule. You can
also write and preview a new draft before saving it. The calendar marks days that have
room at the selected spacing; those are planning suggestions, not automatic schedules.
All Note times use the configured Notes time zone shown on the page. The planner does not
publish a Note immediately or edit an existing Note's text.

Search posts and Notes from the header. The activity selector offers 7, 14, 30, 90, or 180 days. It controls publication traffic, discovery, and the Notes list. Published post
index metrics and individual Note reach are lifetime totals; the Posts chart also
offers first-week comparisons. The **Published in selected period** filter narrows
posts by publication date. The Briefing compares equal-length current
and preceding periods. Today may be incomplete.

Switch between **Totals** and **Per 1,000** in the Posts and Notes tables.
Rates use views for Posts and impressions for Notes. Select a column heading
to rank by that metric. Individual Note signups are unavailable.
The Briefing shows one measured observation with a link
to its evidence. It does not infer a cause; the available data does not support reliable
topic or tone conclusions.

The analytics logic works across authorized Substack publications, but the source APIs,
Post and Note metric definitions, and authentication are specific to Substack. A
publication without Notes, per-piece signups, or enough historical detail will have
fewer comparisons. Clearview is
not a generic analytics dashboard for other publishing platforms.

### Reading the charts and tables

The Posts chart compares several outcomes: **Staying power** compares first-week reach with the
share earned on days 2–7; **Subscriber yield** compares first-week signups per 1,000
views; **Reader sharing** compares recorded shares per 1,000 lifetime views;
**Reader response** compares likes, comments, or restacks per 1,000 lifetime views; and
**Later discovery** shows how many additional views accumulated after week one.
The first two use equal seven-day windows. The others use lifetime totals, so
check publication dates when comparing older and newer posts. The post portfolio and
MCP `post_portfolio` tool share these figures.

The Posts table shows lifetime views, signups, likes, comments, restacks, and shares as
separate sortable columns.
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
published Notes backup; refresh it with MCP `pull_published_notes(profile="@yourhandle")`.
The CLI equivalent is
`./substack-notes-pull public pull --profile @yourhandle --directory substack/published-notes/yourhandle`.
Source labels expand Substack's ambiguous terms, including
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
audience are lifetime totals. The comparison appears when the full cohort is ready;
CSV includes those completed results. Individual Note stats are
reused from the one-hour cache when available.
The Notes chart compares each action per 1,000 impressions; the table leads with
the raw number of likes, replies, restacks, and shares. These are separate outcomes,
not a single success score.

Discovery’s source lines use the same date range and source-series request as Substack’s
growth page. Choose up to five top-level sources to compare their timing; select a post
or Note marker to open that piece's performance. Lines are separate attributions, and
source counts may overlap, so do not add them into a publication total. Parent growth
sources also include their child sources. Signup ratios describe Substack's attribution
and are directional, especially for small sources. The selected calendar range can differ
slightly from Substack's rolling “30d views” card. Note publication markers show timing,
not causation.

### Cache and refresh

On macOS, use the **Clearview** menu to open the data folder, export writing
backups, or clear the temporary cache. On Windows and in the browser dashboard,
use **Options**. Exports include an index and relative links. The ZIP is saved in
the local `exports/` folder and can include private drafts.

Saved measurements live separately in `substack/.analytics-history/` under
the current publication and session. Clearview saves Note reach at 6, 24, and
48 hours when those points are available, completed first-week post results,
and subscriber sources by date range from normal reads. Read records using the MCP
`saved_analytics` tool. The post comparison can
reuse a saved week after the temporary cache expires. Clearing the temporary
cache leaves the writing backups and saved measurements in place.

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

The Posts and Notes comparisons send progress updates to the dashboard as they are
assembled. The dashboard shows a percentage as each piece is processed, then reveals
the completed comparison at once. Initial publication loads and other requests keep
a spinner because their total work is not known in advance. A same-period comparison
refresh leaves the last complete result visible until the new one arrives. Progress
updates do not make extra Substack requests. Real Substack requests from the dashboard,
MCP, and pull commands
share a local request gate. They run one at a time with at least one second between
starts, and the gate honors rate-limit pauses. Cached responses do not use the gate
or contact Substack. To inspect upstream wait and response times locally, start the
app with `CLEARVIEW_REQUEST_TIMING=1`; diagnostic lines omit query values, IDs,
cookies, and response bodies.

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

## Software updates

In the desktop app, choose **Clearview → Software Updates → Automatically
Check for Updates** to check GitHub at launch, at most once a day. Automatic
checks are off by default. **Check for Updates…** checks immediately. When
there’s a newer compatible release, Clearview offers the Mac DMG or Windows
ZIP. Install the download using the same steps as the original beta.

## Connect a desktop assistant

Install Clearview and sign into Substack first. On Mac and Windows, open
**Clearview → AI Connections**.

- **Install Claude Extension…** creates a local extension and opens it for
  installation. If needed, select `Clearview.mcpb` from the Clearview data folder
  using Claude Desktop’s **Install Extension…** command.
- **Connect to Codex…** adds Clearview to Codex’s local MCP settings. Restart
  Codex after connecting.

Choose **Copy Test Prompt** from the same menu and paste it into your desktop
assistant. Both clients start the bundled engine locally and use the publication
saved in Clearview. Keep the app in its installed location and reconnect if
you move it.

## MCP server for Codex

The MCP server and dashboard call the same analytics service and shared disk cache;
the browser does not need the MCP server running. MCP calls the shared post and Note
puller functions directly in its own Python process, without starting CLI subprocesses.
The dashboard planner and MCP Note actions use the same Note draft and scheduling
functions. MCP runs over local standard input/output and has no network listener. Pull
tools write to the ignored local backup directories; their Substack requests are
read-only.

For a post's Note conversation, call `pull_post_conversation(post=...)` with a numeric
post ID or a `https://substack.com/@handle/note/p-ID` URL. It uses the saved Substack
session to page through the replies and saves the raw pages plus a searchable local
copy in `substack/post-conversations/`. Use `post_conversation_status`,
`find_post_replies`, `read_post_reply`, and `read_post_thread` to inspect that copy.
The status includes child-count gaps when Substack reports replies that its reader
endpoint did not return. Pulling again refreshes the saved conversation.

The `publication_sources` tool includes dated subscriber source lines and a breakdown
of Substack's **Notes** source into credits from Note links, post links shared in Notes,
and an unclassified remainder. Its item IDs and counts come from the same source
response, without extra requests. Source credits are period bound and can include
other writers' links; they are not the same as a post's lifetime signups and should
not be added to those counts. Discovery removes the publication prefix from your
own item titles and offers an expandable list of other writer labels and trackbacks
when Substack reports them. Those labels identify credited items, not every person
who reshared a post. The `post_portfolio` tool returns the same completed
first-week cohort and lifetime context used by the Posts comparison. The
`compare_notes` tool returns the Notes page's age-matched reach, reader-outcome
rankings, medians, and rows for a selected activity period.

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
include the puller code. In a fresh checkout, make both skills discoverable to Codex
by running from the repository root:

```sh
mkdir -p .agents/skills
ln -s ../../skills/substack-pull .agents/skills/substack-pull
ln -s ../../skills/substack-notes-pull .agents/skills/substack-notes-pull
```

The MCP tools are the normal path for supported work.

The skill instructions are here:

- [Post pull skill](skills/substack-pull/SKILL.md)
- [Notes pull skill](skills/substack-notes-pull/SKILL.md)

Each person saves their own Substack session in their own Keychain. Using the skills
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


## Demo screenshots

Capture Briefing, Discovery, Notes, and the Note planner using a fictional
publication. The capture runs the real dashboard against local sample data
without reading Substack credentials or backups. It blocks external browser
requests and does not allow writes.

Run **Clearview UX screenshots** in GitHub Actions and download the
`clearview-ux-screenshots` artifact. To run it from the checkout:

```sh
python3 -m pip install -r tools/screenshots/requirements.txt
python3 -m playwright install chromium
python3 -m tools.screenshots.capture
```

The PNGs are written to `output/ux-screenshots/`. Use `--output` to choose
another directory.

The [product tour](https://w1k5.github.io/substack-pull/tour.html) uses the same
captures as lossless WebP files. To update the published images with `cwebp`
installed:

```sh
for shot in output/ux-screenshots/*.png; do
  name=${shot##*/}
  cwebp -lossless "$shot" -o "site/screenshots/${name%.png}.webp"
done
```
