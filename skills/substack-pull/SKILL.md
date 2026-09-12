---
name: substack-pull
description: Pull, back up, find, and inspect any Substack publication's public posts without authentication, or an authorized publication's drafts, scheduled posts, and published posts through a read-only incremental local sync on macOS. Use for requests about public Substack posts or the newest local version of Substack writing. Do not use for publishing, editing, deleting, paywall bypass, or subscriber management.
---

# Substack Pull

Use the bundled CLI to maintain and inspect a local copy of a Substack
publication. The API is undocumented; keep every operation read-only and report
endpoint failures plainly. Choose between these modes:

- For another publication's anonymously visible posts, use public mode. It never
  reads or sends a session cookie and syncs only the public archive.
- For a publication the user owns or edits, use authenticated mode to include
  drafts and scheduled posts as well as published posts.

## Authenticated workflow

Resolve `scripts/substack_pull.py` relative to this file. Run it with Python 3
from the user's workspace and pass the workspace's absolute config path. When a
configured `.substack-pull.json` is present, pull immediately; do not run
`doctor` or ask setup questions on every use.

```bash
python3 /absolute/path/to/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json pull
```

`pull` downloads only new or changed bodies and reports:

- the absolute backup directory;
- counts for every category; and
- each fetched post's title, timestamp, JSON path, and readable Markdown path.

`sync` remains an alias for `pull`. With the repository wrapper, running
`./substack-pull` with no subcommand also pulls.

## Public published-post workflow

For a public publication that the user does not own, pass `--public`, the
publication URL, and a separate backup directory. Do this immediately; public
mode needs neither `doctor` nor `auth` and must not access Keychain.

```bash
python3 /absolute/path/to/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json \
  pull --public \
  --publication https://name.substack.com \
  --directory /absolute/path/to/name-substack
```

Public mode downloads only items listed in Substack's anonymous public archive
and stores only the body returned to an anonymous request. Never use credentials
to expand public-mode access or work around a subscription, paywall, invitation,
geoblock, or other restriction. It is lossless for the response Substack exposes,
but it may contain only a preview when that is all the public endpoint returns.

Use `--refresh-published` when the user requests a full reconciliation or a body
edit is not detected from archive metadata. Normal public pulls are incremental.

## Finding writing

When the user asks for a post, the newest version, or analysis of current
writing, pull first in the matching public or authenticated mode. Then search
the local index by title or post ID:

```bash
python3 /absolute/path/to/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json \
  list --query "words from the title" --limit 10
```

Use `--category drafts`, `scheduled`, or `published` when the user specifies
one. Results are newest first. Prefer the returned `readable_file`; it is a
Markdown rendering of either Substack HTML or its ProseMirror document format.
Open the lossless JSON only when exact structure or metadata matters. If the
title is unknown, list recent posts without `--query`, then choose the newest
plausible match or compare candidates.

Downloaded drafts and scheduled posts are private. Read, quote, or summarize
their contents only when the user asks about them.

## First-time setup

This setup applies only to authenticated mode. If no usable config exists, run
`doctor` once. Determine the canonical public `*.substack.com` publication URL
and the intended backup directory. A custom reader domain is not accepted
because credentials are sent only to Substack hosts.

Authentication requires macOS Keychain. Give the user an `auth` command to run
in their own terminal; never execute the interactive secret-entry step for
them. They must copy only the cookie value and paste it at the hidden Keychain
prompt:

- Safari: `connect.sid` under Web Inspector → Storage → Cookies.
- Chrome, Chromium, Brave, or Edge: `substack.sid` under DevTools → Application
  → Storage → Cookies.

```bash
python3 /absolute/path/to/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json \
  auth --publication https://name.substack.com \
  --directory /absolute/path/to/substack-backup
```

Never ask the user to paste the cookie into chat, a prompt, a file, an
environment variable, or an agent-controlled command. Never print or inspect a
value retrieved from Keychain.

If the backup is inside a Git worktree, verify its exact directory is ignored.
Prefer `.git/info/exclude` for a new local exclusion; ask before changing a
tracked `.gitignore`.

## Safety and recovery

- Use only the bundled read-only commands: `auth`, `pull`, `sync`, `list`,
  `status`, `configure`, and `doctor`. Public mode is `pull --public` or
  `sync --public`.
- In public mode, never retrieve a Keychain session or send a `Cookie` header.
- Never add publishing, scheduling, editing, deletion, subscriber, or settings
  requests.
- Never delete local files when an item disappears remotely. The manifest marks
  it missing and preserves the backup.
- On `401` or `403`, explain that the browser session expired and provide the
  `auth` command again. Preserve the old Keychain item and local files.
- On a publication/directory mismatch, choose a separate directory instead of
  overwriting another publication's manifest.
- Use `pull --refresh-published` only when the user requests reconciliation or
  a published edit appears absent; normal pulls already detect new drafts,
  scheduling changes, and exposed editorial changes.
