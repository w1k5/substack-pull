---
name: substack-notes-pull
description: Pull, back up, search, and rank the public Notes authored by a Substack profile through a read-only incremental local sync. Use for requests about a profile's Notes or popular Note history. Do not use for posts, replies, private content, publishing, reactions, or account management.
---

# Substack Notes Pull

Use the bundled CLI to maintain and inspect a local copy of the public,
top-level Notes authored by a Substack profile. It uses an undocumented public
feed endpoint, so keep every operation read-only and report endpoint changes
plainly.

Resolve `scripts/substack_notes_pull.py` relative to this file. No login,
browser cookie, Keychain entry, or Python package is required. Never request or
retrieve authentication for this workflow.

## Pull Notes

When a usable `.substack-notes-pull.json` already exists in the workspace, pull
immediately:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json pull
```

For a one-off public profile, provide a handle or profile URL and a separate
directory:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  pull --profile @handle \
  --directory /absolute/path/to/handle-notes
```

The first pull scans the complete history. It checkpoints after every page and
resumes an interrupted initial crawl on the next run. Later pulls stop after a
safe overlap with unchanged local Notes while still updating engagement counts
for the pages they visit. Use `pull --refresh` for a complete reconciliation of
older edits or removals.

The puller ignores posts, replies, and restacks of other people's Notes. Each
authored Note is saved as lossless JSON plus readable Markdown. Items absent
during a completed refresh are marked missing in the manifest and never deleted
locally.

## Configure a Default

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  configure --profile @handle \
  --directory /absolute/path/to/handle-notes
```

The config contains only the public profile handle and local directory.

## Find or Rank Notes

Pull before analyzing current Notes, then query the local copy:

```bash
python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  list --query "words in the note" --limit 20

python3 /absolute/path/to/scripts/substack_notes_pull.py \
  --config /absolute/path/to/.substack-notes-pull.json \
  list --sort reactions --limit 50
```

Sorting options are `recent`, `reactions`, `restacks`, and `replies`. Prefer the
returned `readable_file` for prose analysis and the JSON file when exact
attachments or metadata matter.

## Safety and Recovery

- Use only `pull`, `sync`, `list`, `status`, `configure`, and `doctor`.
- Never add a cookie or authorization header, or use credentials to expand what
  the public endpoint exposes.
- Never add publishing, replying, reacting, following, deletion, subscriber, or
  settings requests.
- Treat `401`/`403` as a public-access restriction, not an authentication task.
- On repeated `429` or server errors, keep the checkpoint and report that the
  next pull will resume.
- Choose a separate directory when the manifest belongs to another profile.
