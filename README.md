# substack-pull

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
Use $substack-pull to sync my publication into a local backup.
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

## Sync

```bash
./substack-pull sync
./substack-pull status
```

The first sync downloads every currently listed item. Later syncs always fetch
the three remote indexes, but downloads a full body only when:

- the post ID is new;
- an editorial timestamp/title/slug changed;
- its local file is missing; or
- `--refresh-published` was requested.

Substack's draft and scheduled indexes expose `draft_updated_at`; scheduled
items also expose `trigger_at`. Changes to either cause the complete draft and
its current scheduling metadata to be downloaded again on the next pull.

```bash
./substack-pull sync --refresh-published
```

Run that occasionally if you edit published posts and Substack does not expose
an updated timestamp in its list response.

## Local files

```text
substack/
├── drafts/
│   ├── 123.json
│   └── 123.html       # when Substack returned an HTML body
├── scheduled/
├── published/
└── .sync/
    └── state.json
```

JSON files are the lossless source of truth. HTML companions are convenience
copies. Items that disappear remotely are marked `missing` in `state.json` and
are **not deleted locally**.

## Other commands and options

```bash
./substack-pull doctor
./substack-pull sync --request-delay 0.5
./substack-pull sync --directory /absolute/backup/path
./substack-pull sync -d /absolute/backup/path
./substack-pull --config /path/to/config.json sync
```

`--directory` on `sync` overrides the location for one run. To save a new
default without re-entering authentication:

```bash
./substack-pull configure --directory /absolute/backup/path
./substack-pull sync
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
