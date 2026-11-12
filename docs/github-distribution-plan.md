# Clearview download and distribution plan

**Status:** Release contract on main · **Decision owner:** publication owner · **Updated:** November 12, 2026

## The intended download

Use GitHub Pages for a simple Clearview website and GitHub Releases for the actual
Mac and Windows downloads. The app, dashboard server, data engine, and MCP server
run on the writer's computer. GitHub hosts files; it does not host a running MCP
service or anyone's publication data.

The normal path should be: download → install or extract → open Clearview → connect
Substack → use the dashboard. MCP is optional. A compatible AI client launches the
MCP executable from the installed bundle and reads the same local data. The website
must not imply that every ChatGPT or Claude installation supports that local MCP
setup until the exact client flow has been tested.

## Fixed product decision: keep the Substack dependency

Clearview will continue to use its existing authenticated, undocumented Substack
endpoints. Replacing them with an export, an official connector, or a different data
source is **not** part of this packaging plan and is **not** a prerequisite for this
beta. This supersedes the access-route recommendation in the older
[desktop app plan](desktop-app-plan.md).

This decision carries real limits: Substack can change the endpoints, invalidate a
session, rate-limit requests, or restrict this kind of access. Packaging and signing
do not solve those risks. The product should explain the dependency plainly and
show a useful cached view or an actionable error when live data is unavailable.
Avoid promises of permanent compatibility or a fixed refresh cadence.

Manage the dependency responsibly without disguising traffic:

- Keep existing disk caches and share them between the dashboard and MCP.
- Send requests conservatively through the shared request gate; respect rate
  limits and stop on a requested long pause.
- Fetch detail when needed, avoid duplicate refreshes, and make manual refresh
  explicit. Do not add aggressive background polling to the first download.
- Keep the session in macOS Keychain or Windows Credential Manager. Never include
  credentials, private data, or user caches in a release artifact or diagnostic log.
- Distinguish “cached,” “updating,” “needs reconnection,” and “Substack unavailable”
  in the UI. Make it possible to disconnect and remove local data.

## Build and release status

The release contract and version wiring are on `main` in `2ecc55c`. The
remaining Clearview code, tests, and documentation followed in `9eff5d7`.
Both commits passed the Python test workflow on GitHub. [Release contract CI](https://github.com/w1k5/substack-pull/actions/runs/43320073952) · [Clearview CI](https://github.com/w1k5/substack-pull/actions/runs/43320515084)

The first beta targets **macOS 13 or later on Apple Silicon** and
**Windows 11 x64**. [The shared release metadata](../desktop/release.json)
currently specifies `0.1.0-beta.1`, build `1`. It drives the Mac bundle
version and Windows package naming. CI checks that a version tag matches
the configured version. App identities, preview isolation, and the
decision to reconnect once on first install are recorded in the
[release contract](packaging-todo.md#clearview-release-contract).

| Platform | Present state | Packaging gap |
| --- | --- | --- |
| Mac | `./substack-desktop` builds the Swift shell from the checkout. The generated bundle metadata passed local validation. | Bundle the engine and assets in a standalone app, apply the release identity, and test the download on a clean Mac. |
| Windows | The packager and manual **Windows beta build** workflow are on `main`. The updated version and ZIP naming need a Windows build run. | Run the workflow, then test its artifact on a clean Windows 11 x64 machine. Publish the validated ZIP through GitHub Releases. |
| MCP | The local server uses the shared engine and saved connection. | Verify that both packages expose a usable MCP launch command, then test it with the supported AI clients. |

**Next milestone:** Build a standalone Mac app and run the Windows beta
workflow. Test both artifacts before publishing the first GitHub prerelease.
The signing publisher, Clearview distribution terms, and bundled dependency
license review remain open. Track individual tasks in the
[packaging checklist](packaging-todo.md).

### Download page

The public address is [Clearview downloads](https://w1k5.github.io/substack-pull/).
The static site lives in [site/](../site/) and the [Pages workflow](../.github/workflows/pages.yml)
publishes that directory. The page initially shows that beta downloads are in
preparation. After validating a published package, add its direct GitHub Release
asset URL to [downloads.js](../site/downloads.js). Each platform's button appears
when its URL is configured. Check the live download links in a signed-out browser.

The existing source archives that GitHub automatically adds to every Release are
**not** app downloads. Name the attached binaries clearly by OS and architecture.

## Build sequence

### 1. Make each download self-contained

- Mac: build a standalone engine, place it and the dashboard assets in
  `Clearview.app`, and have the Swift shell launch that bundled engine. Store
  settings and caches in the user's application-data directory, outside the app.
- Windows: keep the bundled engine beside the .NET shell. Confirm the app can
  locate it after extraction into an arbitrary folder. Check the WebView2 runtime
  experience and provide an understandable prompt if it is missing.
- Include the local MCP executable or launch entry point in both packages. Opening
  Clearview should start the dashboard, not an unnecessary always-on MCP process.
- Choose initial architectures deliberately. Label an Apple Silicon-only Mac beta
  or Windows x64-only beta honestly; add other builds only after testing them.

**Done when:** A fresh computer can open Clearview and connect without a terminal,
source checkout, Python, .NET SDK, or Xcode tools.

### 2. Test the whole user journey on clean machines

Test download, first launch, Substack sign-in and email-code paste, dashboard load,
refresh, draft/schedule preview, reconnection after session expiry, offline or
rate-limited behavior, optional MCP setup, restart, upgrade, and uninstall. Verify
that the bundle contains no developer session or publication cache. Test macOS and
Windows separately; a cross-build alone does not validate either platform.

**Done when:** Someone unfamiliar with the code can complete setup from the
download page alone, and failures tell them what to do next.

### 3. Publish a controlled beta entirely through GitHub

- Use a version tag such as `v0.1.0-beta.1`. Run the repository tests and platform
  builds in GitHub Actions on that tag. Upload the completed packages to a GitHub
  **pre-release** with release notes and SHA-256 checksums.
- Use the versioned asset names in the [release contract](packaging-todo.md#clearview-release-contract),
  such as `Clearview-0.1.0-beta.1-macos-arm64.zip` and
  `Clearview-0.1.0-beta.1-windows-x64.zip`.
- Make a small GitHub Pages site with two download buttons, screenshots, a
  three-step setup guide, privacy and data-storage explanation, known beta
  limitations, and a support/issue link. During beta, link to the current
  pre-release or Releases page; do not rely on `releases/latest` for a pre-release.
- Keep release files in GitHub Releases. Actions artifacts are temporary build
  outputs, not the public distribution channel. Pages is static and should not
  attempt to run the app's Python server.
- Start with a small, known tester group and collect installation and sign-in
  failures before opening the download page more widely.

**Done when:** Each Pages download button leads to a tested, versioned Release
asset, and a tester can verify what they downloaded.

### 4. Add platform trust before a broad, nontechnical launch

This step can follow packaging and private testing, but cannot be skipped if the
goal is a calm first-launch experience. Sign and notarize the Mac app with an Apple
Developer ID. Sign the Windows app or installer with a trusted publisher identity.
New Windows builds can still show SmartScreen warnings while reputation develops;
unsigned builds are more likely to alarm users. An unsigned Mac build may require
an “Open Anyway” override. Do not tell people to disable their OS security controls.

Until this is done, describe downloads as a limited unsigned beta and show the
expected warning honestly. Do not market them as a frictionless installation.

**Done when:** Clean-machine tests show the intended publisher identity and the
expected first-run prompts on both operating systems.

### 5. Maintain releases

Every release should have a version, changelog, compatible OS/architecture,
download assets, checksums, and a tested upgrade path. Keep the previous working
release available for rollback. In-app updates are optional initially; a visible
“new version available” link to GitHub Releases is enough for the beta.

## Release checklist

- [ ] No credentials, private caches, or publication data in either package.
- [ ] Mac and Windows packages launch without development tools.
- [ ] Dashboard and bundled MCP work from the installed location.
- [ ] Clean-machine sign-in, refresh, reconnection, and offline tests pass.
- [ ] Rate limiting does not cause rapid retries or a request burst.
- [ ] Pages explains local storage, optional AI access, and endpoint fragility.
- [ ] GitHub Release contains versioned packages, checksums, and known issues.
- [ ] Signing/notarization complete before a broad, nontechnical launch.

## References

- [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) and [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [Apple: notarizing Mac software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Microsoft: SmartScreen reputation](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation)
