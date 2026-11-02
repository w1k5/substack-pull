# Substack Pull

Local tools for backing up Substack posts and Notes, exploring publication analytics,
and giving Codex access to the same data through MCP.

| What you want to do                                                     | Command                                        |
| ----------------------------------------------------------------------- | ---------------------------------------------- |
| Back up your publication's drafts, scheduled posts, and published posts | `./substack-pull pull`                         |
| Back up draft and scheduled Notes                                       | `./substack-notes-pull pull`                   |
| Explore publication, post, and Note analytics                           | `./substack-analytics`                         |
| Use analytics and backups from Codex                                    | Set up the [MCP server](#mcp-server-for-codex) |

The post puller, dashboard, and MCP analytics tools read Substack data. The Notes CLI
can also create a draft or change a schedule when you explicitly run an `--apply`
command.

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

The dashboard uses the publication and session from the first-time setup. It shows
publication views and growth sources, post reach and reader response, and published Note
reach. It listens only on `127.0.0.1`. The session stays in Keychain and is not sent to
the page. Stop the server with Control-C.

The date selector applies to publication traffic and growth; post metrics are lifetime
totals. Parent growth sources already include their child sources, so do not add those
counts together. Signup ratios describe Substack's attribution and are directional,
especially for small sources. The selected calendar range can differ slightly from
Substack's rolling “30d views” card.

**Refresh** forces a new publication fetch. Post details can be cached for up to five
minutes, and Note reach for up to an hour. Substack's analytics endpoints are
undocumented and may change.

## MCP server for Codex

The MCP server shares the dashboard's analytics code and calls the existing puller CLIs
for backups. It runs over local standard input/output, has no network listener, and does
not require the dashboard to be open. Pull tools write to the ignored local backup
directories; their Substack requests are read-only.

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
when you need the newest local copy. The MCP server does not create or schedule Notes;
use the Notes CLI for those actions.

See [`mcp.json`](mcp.json) for the stdio launch configuration.

## Use as Codex skills

The post and Note skills include their own CLIs and can be installed without cloning
this repository. In Codex, ask the skill installer:

```text
Use $skill-installer to install https://github.com/w1k5/substack-pull/tree/main/skills/substack-pull
Use $skill-installer to install https://github.com/w1k5/substack-pull/tree/main/skills/substack-notes-pull
```

The skill instructions are here:

- [Post pull skill](skills/substack-pull/SKILL.md)
- [Notes pull skill](skills/substack-notes-pull/SKILL.md)

Each person saves their own Substack session in their own Keychain. Installing a skill
does not share credentials or publication content.

## Code and tests

The user-facing commands are at the repository root. Post and Note puller
implementations are in `skills/substack-pull/scripts/` and
`skills/substack-notes-pull/scripts/`. The dashboard and MCP implementation are mapped
in the [local code guide](substack_local/README.md).

The tests use local fixtures and do not contact Substack or read Keychain:

```sh
python3 -m unittest discover -s tests -v
```
