---
name: substack-notes-pull
description: Pull and inspect an account's draft and scheduled Substack Notes, generate a rolling schedule runway, and explicitly schedule or reschedule a Note. Use for Note drafts, scheduled Notes, schedule density, spacing, and future allocation. Also supports published Note history when explicitly requested. Do not use for publication posts, immediate publishing, body editing, deleting, replies, reactions, or account management.
---

# Substack Notes Pull

Use the bundled read-only CLI for Substack Notes. Resolve
`scripts/substack_notes_pull.py` relative to this file and use the workspace's
absolute config path.

## Normal workflow

Pull all draft and scheduled Notes:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json pull
```

This single command also rebuilds:

- `notes.md`, with every Note labeled `Scheduled` or `Draft`;
- `note-runway.html`, a self-contained planning view for the next 90 days;
- lossless JSON and readable Markdown in `note-scheduled/` and `note-drafts/`.

The pull reads `GET https://substack.com/api/v1/feed/drafts?limit=20` and follows
the cursor until every item is collected. Treat a Note with `trigger_at` as
scheduled; otherwise treat it as a draft. Always sort scheduled Notes by
`trigger_at`. Sort drafts by their most recent edit or creation time.

To rebuild the visual from the local files without contacting Substack:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  visualize --days 90 --minimum-spacing 3
```

The runway places scheduled Notes on the calendar and shows drafts only as a
backlog count. It marks same-day clusters, totals each week's load, and suggests
openings that respect the selected 2/3/4-day spacing. Clicking a numbered day
shows the scheduled Notes in time order beneath that day's summary, including
their times, IDs, and text. Draft bodies remain outside the runway.

List the pulled Notes when a text view is more useful:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  list --status all --limit 1000
```

## Schedule changes

Substack's editor updates both draft and scheduled Notes with:

```text
PATCH https://substack.com/api/v1/feed/comment/{note_id}
```

The JSON request preserves the complete `bodyJson`, reply role, and attachment
IDs while setting `trigger_at` to an ISO UTC timestamp. A draft becomes
scheduled when it receives a future `trigger_at`; an already scheduled Note is
rescheduled by changing that value.

Preview a change first. This fetches the current remote Note but does not write:

```bash
./substack-notes-pull schedule NOTE_ID --at "2026-10-30 09:30"
```

A time without an offset uses the configured time zone. Only after the user has
explicitly approved that Note and time, send the change with `--apply`:

```bash
./substack-notes-pull schedule NOTE_ID --at "2026-10-30 09:30" --apply
```

The command refreshes the local Notes, overview, and runway after a successful
request and verifies that Substack returned the requested timestamp. Never use
`--apply` speculatively or for a batch the user has not approved.

## Authentication

Reuse the session already stored by `substack-pull`. Both tools read the same
Keychain item; never ask the user to authenticate twice. The Notes puller finds
the publication host in the workspace's `.substack-pull.json` automatically.

If no shared session exists, tell the user to authenticate through
`substack-pull` in their own terminal:

```bash
./substack-pull auth
```

The user copies only the cookie value into the hidden macOS Keychain prompt:

- Safari: `connect.sid` under Web Inspector → Storage → Cookies.
- Chrome, Chromium, Brave, or Edge: `substack.sid` under DevTools → Application
  → Storage → Cookies.

Never ask the user to paste the cookie into chat, a file, an environment
variable, or an agent-controlled command. Never print or inspect a value read
from Keychain. If the output directory is inside Git, verify that exact
directory is ignored before pulling.

## Published Note history

Only when the user explicitly asks for already-published Notes, prefix the
command with `public` and keep that history in a separate directory:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  public pull --profile @handle --directory /absolute/path/to/published-notes
```

Public history is anonymous and ignores posts, replies, and restacks of other
people's Notes. Use `public pull --refresh` for a full reconciliation.

## Safety and recovery

- Keep all operations read-only except the explicit `schedule --apply` command.
  Never add immediate publishing, body editing, deletion, replying, reacting,
  following, subscriber, or settings requests.
- Do not quote or summarize draft bodies unless the user asks.
- Never delete local files when an item disappears remotely; preserve the
  backup and mark it missing in sync state.
- If the shared session expires, provide the `./substack-pull auth` command again.
- If a schedule request has an uncertain network result, pull and verify before
  retrying it.
- On repeated rate limits or server errors, preserve local state and report the
  failure plainly.
