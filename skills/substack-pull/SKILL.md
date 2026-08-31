---
name: substack-pull
description: Synchronize a Substack publication's drafts, scheduled posts, and published posts into a read-only incremental local backup on macOS. Use when the user asks to pull, back up, sync, inspect, or configure local Substack content. Do not use for publishing, editing, deleting, or subscriber management.
---

# Substack Pull

Use the bundled CLI to maintain a lossless local copy of a publication without
changing anything on Substack. The API is undocumented, so preserve the CLI's
read-only boundary and report endpoint failures plainly.

## Runtime

Resolve `scripts/substack_pull.py` relative to this `SKILL.md` and invoke it with
Python 3. Do not assume the skill's installation directory is the user's backup
directory. Run from the user's chosen workspace or pass absolute `--config` and
`--directory` paths.

The workflow requires macOS because authentication uses Safari and macOS
Keychain. It does not require an additional browser or Python package.

## Safety invariants

- Only use the bundled read-only commands: `auth`, `sync`, `status`,
  `configure`, and `doctor`.
- Never add publishing, scheduling, editing, deletion, subscriber, or settings
  requests to the workflow.
- Never ask the user to paste `connect.sid` into chat, a prompt, a source file,
  an environment variable, or an agent-controlled command.
- Never print, inspect, or relay a value returned by macOS Keychain.
- The user must paste the cookie directly into the interactive Keychain prompt
  in their own terminal. It is expected that no characters appear while they
  type or paste.
- Treat downloaded drafts and scheduled posts as private. Never commit, upload,
  quote, or summarize their contents unless the user explicitly asks.
- Never delete local files because an item disappeared remotely. The CLI marks
  it missing in the manifest and preserves the file.

## Workflow

1. Determine the public `*.substack.com` publication URL and the desired local
   backup directory. A custom reader domain is not accepted because the session
   credential must only be sent to Substack hosts.
2. Resolve stable absolute paths for the config and backup. If the destination
   is inside a Git worktree, verify it is ignored with `git check-ignore`. If it
   is not ignored, prefer adding the exact directory to `.git/info/exclude`, or
   ask before changing a tracked `.gitignore`.
3. Run `doctor` before first-time setup.
4. If authentication is not configured, give the user the `auth` command to run
   in their own terminal. Explain how to copy only the `connect.sid` value from
   Safari Web Inspector under Storage > Cookies. Do not execute the interactive
   secret-entry step through an agent command.
5. Run `sync`, then `status`. Report the absolute backup path and the per-category
   fetched, unchanged, missing-preserved, and failure counts.

Use commands shaped like:

```bash
python3 /absolute/path/to/skill/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json doctor

python3 /absolute/path/to/skill/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json \
  auth --publication https://name.substack.com \
  --directory /absolute/path/to/substack-backup

python3 /absolute/path/to/skill/scripts/substack_pull.py \
  --config /absolute/path/to/.substack-pull.json sync
```

The auth command stores the session in Keychain under the publication hostname.
The config contains only the publication URL and directory.

## Incremental behavior

Every sync refreshes all three remote indexes. Draft and scheduled bodies are
downloaded again when `draft_updated_at` changes; scheduling changes are also
detected through `trigger_at`. Published bodies are fetched when new or when an
editorial marker changes. Use `--refresh-published` only when the user requests
a reconciliation or a published edit appears to be missing.

On `401` or `403`, explain that the Safari session expired and provide the auth
command again. Do not remove the old Keychain item or local backup. On a
publication/directory mismatch, choose a separate directory rather than
overwriting another publication's manifest.
