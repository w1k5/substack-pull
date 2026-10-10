# substack-notes-pull

`substack-notes-pull` is a read-only, incremental local backup of the public
Notes authored by a Substack profile. It is the Notes-only companion to
`substack-pull`: no posts, replies, or other people's restacked Notes are added
to the collection.

It uses Substack's public profile feed and does **not** use browser cookies,
Keychain, or authentication. The API is undocumented and may change.

## Configure and pull

```bash
./substack-notes-pull configure \
  --profile @prettyhostile \
  --directory substack-notes/prettyhostile

./substack-notes-pull
```

You can also run without saving a config:

```bash
./substack-notes-pull pull \
  --profile https://substack.com/@prettyhostile \
  --directory substack-notes/prettyhostile
```

The first pull walks the complete public history. It saves a checkpoint after
every page, so rerunning the command resumes after rate limiting, a network
failure, or an interruption. Later pulls are incremental: they scan from the
newest Note until reaching 24 unchanged authored Notes. Change that overlap
with `--overlap`.

Use a full refresh when you need older edits, removals, or current engagement
counts across the whole history:

```bash
./substack-notes-pull pull --refresh
```

The default 1.25-second request delay is intentionally conservative. `429` and
temporary server errors use `Retry-After` or exponential backoff before the
checkpointed pull gives up safely.

## Local files

```text
substack-notes/
├── notes/
│   ├── 123.json   # lossless public feed item and metadata
│   └── 123.md     # readable body, attachments, permalink, and counts
└── .sync/
    └── state.json
```

Files are written atomically. A Note that disappears during a completed
`--refresh` is marked `missing` in `state.json`; its local files are preserved.

## Search and rank

```bash
./substack-notes-pull list --query "blue-collar" --limit 20
./substack-notes-pull list --sort reactions --limit 50
./substack-notes-pull list --sort restacks --limit 50
./substack-notes-pull list --sort replies --limit 50
./substack-notes-pull status
```

`list` searches the complete local Note body and returns both JSON and readable
Markdown paths.

## Tests

The tests use a local HTTP server. They do not contact Substack or inspect a
browser profile:

```bash
python3 -m unittest tests.test_substack_notes_pull -v
python3 -m unittest discover -s tests -v
```
