---
name: substack-notes-pull
description: Pull and inspect an account's draft and scheduled Substack Notes, create new unpublished standalone text Note drafts, generate a rolling schedule runway, and explicitly schedule or reschedule a Note. Use for Note drafts, scheduled Notes, schedule density, spacing, and future allocation. Also supports published Note history when explicitly requested. Do not use for publication posts, immediate publishing, editing existing Note bodies, deleting, replies, reactions, attachments, or account management.
---

# Substack Notes Pull

Use the local `substack-analytics-local` MCP tools for all supported Note work.
Call the MCP tools directly; do not invoke the bundled scripts when the MCP is
available for the requested workspace and operation. Use the CLI fallback below
only when the MCP is unavailable, points at another workspace, or cannot use a
caller-chosen local directory. Resolve `scripts/substack_notes_pull.py` relative
to this file and use the workspace's absolute config path for fallback commands.

## MCP workflow

Call `workspace_info` once and verify its workspace. For private Notes, also
verify its Note backup directory matches the requested local copy. For public
Note history, use the MCP only when its per-profile directory is acceptable.
If the MCP is unavailable or points elsewhere, use the CLI fallback below. Do
not run both paths for the same operation.

- Call `pull_notes` to refresh draft and scheduled Notes. It also rebuilds the
  overview and runway. Use `find_note_copies(status=...)` to locate Notes;
  previews are hidden by default. Call `read_note_copy(note_id=...)` only when
  the user asks to inspect a Note's body. `backup_status` reports local counts
  and sync time.
- Call `note_schedule_runway(days=..., minimum_spacing=...)` to rebuild the
  visual from local files without a Substack request.
- For a new text draft, call `preview_note_draft(text=...)` and show the exact
  normalized body. Only after approval of that body, call
  `create_note_draft(text=...)` with the approved text. The tool checks for an
  existing identical draft, refreshes the local backup, and verifies the new
  unpublished draft. After an uncertain result, pull and search for the exact
  body before retrying.
- For multiple text drafts, call `preview_note_drafts(texts=[...])` and show
  every normalized body in order. After approval of that exact set, call
  `create_note_drafts(texts=[...])` once with the same values. The batch accepts
  1–20 distinct bodies, reads the remote draft list once before sequential POSTs,
  and refreshes it once afterward to verify each result. Check every item's
  `applied`, `duplicate`, or `uncertain` status. If `incomplete` is true, stop;
  inspect the local and remote Notes before any retry. Never send the whole
  batch again blindly. Do not run multiple batches in parallel.
- For scheduling, call `preview_note_schedule(note_id=..., at=...)` and show the
  Note ID, current schedule, proposed time, and time zone. Only after approval
  of that Note and time, call `schedule_note(note_id=..., at=...)` with the same
  values. A time without an offset uses the configured time zone. The tool
  re-reads the Note, preserves its body and attachments, refreshes the local
  backup and runway, and verifies the new schedule.
- Only when the user explicitly requests published Note history, call
  `pull_published_notes(profile=...)` and then
  `find_published_notes(profile=..., sort_by=...)`. Each profile gets a separate
  ignored directory. Use the CLI for a caller-chosen history directory.

The MCP uses the same saved session as `substack-pull`. Never treat a local pull
as approval to create or schedule a Note. If the draft or schedule MCP
tools are missing, reconnect the MCP server before using the CLI fallback.
If an MCP tool reports no session after a recent successful local pull, follow
the Keychain-access recovery below before asking for new authentication.

## CLI fallback: private Note backup and planning

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

## CLI fallback: draft creation

Create only a new standalone, text-only, unpublished, unscheduled Note draft.
Substack's endpoint is:

```text
POST https://substack.com/api/v1/comment/draft
```

The request sends the Note as a ProseMirror `bodyJson`, sets the reply role to
`everyone`, and sends `trigger_at: null`. It does not publish the Note.

Preview the exact body first; this never contacts Substack or writes anything:

```bash
./substack-notes-pull create-draft --text "Exact Note text"
```

For multiline text, prefer a UTF-8 file so shell quoting cannot alter it:

```bash
./substack-notes-pull create-draft --file /absolute/path/to/note.txt
```

Substack stores each non-empty input line as a paragraph and discards blank
lines, so the preview shows the normalized text that will actually be stored.
The maximum input length is 5,000 characters. Only after the user explicitly
approves that exact preview, repeat the same command with `--apply`:

```bash
./substack-notes-pull create-draft --file /absolute/path/to/note.txt --apply
```

Before writing, the CLI refreshes every remote draft and scheduled Note. If the
same body already exists, it reports the matching Note IDs and creates nothing.
After a successful request, it refreshes the local backup and verifies the new
Note's exact body, draft status, and absent schedule.

For a batch, preview every body and obtain explicit approval for that exact set.
Use the MCP batch tools above when available. With the CLI fallback, create the
drafts sequentially. Stop on the first uncertain result; pull and search for the
exact body before retrying.
Do not create replies, restacks, attachments, scheduled drafts, or edits to
existing drafts through either path.

## CLI fallback: schedule changes

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

Only after the user has explicitly approved that Note and time, send the change
with `--apply`:

```bash
./substack-notes-pull schedule NOTE_ID --at "2026-10-30 09:30" --apply
```

Never call `schedule_note` or use `--apply` speculatively or for a batch the user
has not approved.

## Authentication

Reuse the session already stored by `substack-pull`. Both tools read the same
Keychain item; never ask the user to authenticate twice. The Notes puller finds
the publication host in the workspace's `.substack-pull.json` automatically.

The “No reusable Substack session was found” error can also mean that
the execution sandbox blocked Keychain access. It does not establish that the
user has not authenticated. Before asking them to authenticate again:

1. Call MCP `backup_status` and read `notes.keychain_session_present`. Do not
   read or print the credential itself. If the MCP is unavailable or cannot
   report that field, use the same absolute config path for the CLI fallback:

   ```bash
   ./substack-notes-pull --config /absolute/path/to/.substack-notes-pull.json status
   ```

   Use `status`, not `doctor` (the Notes CLI has no `doctor` command).
2. If the sandbox reports no session, request normal execution escalation for
   that same status check outside the sandbox, where available. If the user
   says they already authenticated, investigate access before repeating the
   authentication instructions. Do not bypass an escalation denial.
3. If the elevated check finds the session, run the already-authorized command
   with the necessary execution permission. Preserve approval of the exact Note
   body or schedule across authentication/access failures; do not ask for the
   same content approval again. An uncertain remote write still requires the
   pull-and-verify recovery below before retrying.

Keychain access can wait for a macOS prompt. Keep the user informed if the check
stalls, and ask whether a prompt is visible only when needed; do not assume
one appeared. Distinguish an inaccessible session from an absent or expired
session in the result you report.

If the accessible Keychain has no shared session, tell the user to authenticate
through `substack-pull` in their own terminal:

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

Only when the user explicitly asks for already-published Notes, call
`pull_published_notes(profile=...)` and then
`find_published_notes(profile=..., sort_by=...)`. Use the CLI fallback when the
user requests a specific history directory. In that case, prefix the command
with `public` **before** `--config` and keep each profile's history separate:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py public \
  --config /absolute/path/to/.substack-notes-pull.json \
  pull --profile @handle --directory /absolute/path/to/published-notes
```

Public history is anonymous and ignores posts, replies, and restacks of other
people's Notes. When the output directory is inside Git, verify that exact
directory is ignored before pulling. A complete first pull reports
`complete: true` and `exhausted_feed: true`. Later pulls are incremental, so use
`public pull --refresh` when older edits, removals, or current engagement
counts matter.

For the CLI fallback, rank the local history with the same profile and directory:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py public \
  --config /absolute/path/to/.substack-notes-pull.json \
  list --profile @handle --directory /absolute/path/to/published-notes \
  --sort restacks --limit 20
```

The public archive records reactions, restacks, and replies, but not impressions
or subscriber conversions. Treat popularity patterns as correlations, not proof
that a Note caused audience growth. Image-only Notes may have an empty text body;
inspect their attachments before describing their content. A profile metadata
parse error can reflect a changed Substack page format, and a DNS error can
reflect restricted network access; neither establishes that the profile is
unavailable.

## Safety and recovery

- Keep all operations read-only except an explicitly approved MCP
  `create_note_draft`, `create_note_drafts`, or `schedule_note` call, or the
  corresponding CLI `--apply` fallback. Never immediately publish, edit an
  existing Note body, delete, reply, restack, react, follow, or change
  subscriber or account settings.
- Do not quote or summarize draft bodies unless the user asks.
- Never delete local files when an item disappears remotely; preserve the
  backup and mark it missing in sync state.
- If the shared session expires, provide the `./substack-pull auth` command again.
- If a create or schedule request has an uncertain network result, pull and
  verify before retrying it.
- On repeated rate limits or server errors, preserve local state and report the
  failure plainly.
