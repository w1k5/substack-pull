# Clearview packaging and distribution checklist

This checklist adapts FluidVoice's three delivery paths to Clearview's Swift shell, Windows .NET shell, and shared Python engine. GitHub Pages is the download page, GitHub Releases holds the packages, and Clearview and its optional MCP run locally. See the [distribution plan](github-distribution-plan.md) for the existing product decisions.

## 1. Set the release contract

- [x] Keep the existing authenticated, undocumented Substack endpoints and shared cache. Test how packaged builds handle session expiry, rate limits, and endpoint failures.
- [x] Start from the Swift Mac shell, the Windows x64 build script and manual Actions artifact workflow, and the existing push and pull request test workflow. Their presence does not certify the packaged user experience.
- [x] Define the app identities, platform targets, version mapping, and beta migration policy below.
- [ ] Before publishing packages, confirm the actual Windows signing publisher and audit redistribution terms for the bundled software. Record the owner's approved Clearview distribution terms and include the required third-party notices.

### Clearview release contract

| Area | Decision |
| --- | --- |
| Official app | Clearview. macOS bundle ID `io.github.w1k5.clearview`. Windows product name and display publisher `Clearview`. The signing publisher must match the legal identity on the certificate once issued. |
| PR previews | `Clearview Preview <PR>`. Mac bundle ID `io.github.w1k5.clearview.preview.pr<PR>`. Use a per-PR app data directory, credential namespace, and browser profile on both platforms. |
| Beta migration | Keep the checkout launcher on its current identity. Official packages get their own storage and ask users to connect Substack once. No automatic import of checkout credentials or caches. |
| Platform targets | macOS 13 or later, Apple Silicon first. Add Intel coverage once the bundled engine and shell both pass testing. Target a universal bundle if both can ship together. Windows 11 x64 first. Evaluate native ARM64 separately. These are build and test targets. |
| Version source | [desktop/release.json](../desktop/release.json) stores the full version and an increasing numeric build. Tags match `v<version>` exactly. CI rejects mismatched tags. The checkout Mac launcher stamps the numeric core into `CFBundleShortVersionString`, the build into `CFBundleVersion`, and the full version into `ClearviewReleaseVersion`. Windows uses the full product version and a numeric `major.minor.patch.build` file version. |
| Official assets | `Clearview-<version>-macos-<arch>.zip`, `Clearview-<version>-macos-<arch>.dmg`, `Clearview-<version>-windows-x64.zip`, and `Clearview-<version>-windows-x64-setup.exe`. Use `arm64`, `x64`, or `universal` as applicable. The tagged release workflow must verify the version, identity, architecture, and exact filenames from the finished artifacts before upload. |
| Licensing | The repository currently has no Clearview license file. Treat distribution terms as pending owner approval. Review the exact packaged dependency inventory before publishing and record each license and notice obligation. |

## 2. Build standalone packages

- [ ] Bundle the Python engine, dashboard assets, icons, and local MCP entry point in `Clearview.app`. Make the Swift launcher resolve them relative to the bundle and verify all nested dependencies and architectures.
- [ ] Validate the existing Windows build on a clean machine. Bundle the required engine, assets, and MCP entry point, verify WebView2 detection and setup, and produce a Windows ZIP plus a signed installer for the public release.
- [ ] Resolve writable paths outside the install directory. Preserve macOS Keychain and Windows Credential Manager storage, bind the dashboard to localhost, and verify the dashboard and MCP can use the same connection and cache.
- [ ] Document the bundled MCP launch command and test setup for each Claude and ChatGPT client we intend to list. Record the exact client and setup flow that worked.

## 3. Run CI and build PR previews

- [ ] Add macOS and Windows build checks alongside the Python tests. Pin build inputs and upload diagnostics on failure.
- [ ] Add a PR preview workflow with read-only repository permissions and no release credentials. Build the intended PR revision, use a separate preview identity, and verify the unpacked payload.
- [ ] Ad hoc sign the Mac preview app and nested code. Package the preview app and, where useful, its build archive. Upload short-lived Mac and Windows artifacts with a manifest, checksums, and first-launch instructions. Use a trusted workflow if posting artifact links to PRs.

## 4. Sign, notarize, and verify official builds

- [ ] Obtain an Apple Developer ID Application certificate and notarization credentials and a trusted Windows code-signing identity. Store release credentials in a protected GitHub Actions environment available to trusted release jobs.
- [ ] Produce the macOS release build. Sign nested helpers, executables, and frameworks first, then sign the app with Hardened Runtime, the intended entitlements, and a secure timestamp.
- [ ] Notarize and staple the Mac app. Build an updater ZIP containing `Clearview.app` and a DMG containing the app and an Applications shortcut. Sign, notarize, and staple the DMG as part of the release process.
- [ ] Sign and timestamp the Windows binaries and installer. Verify the installed publisher identity and record actual SmartScreen behavior.
- [ ] Verify the extracted Mac ZIP and mounted DMG for signature, notarization, Gatekeeper acceptance, bundle ID, version, and architectures. Verify Windows signatures and installed payload. Generate SHA-256 checksums from the final assets.
- [ ] Test downloads on clean machines. Cover install, launch, sign-in and confirmation-code paste, dashboard refresh, draft and schedule previews, reconnect, offline and rate-limited behavior, optional MCP setup, upgrade, rollback, and uninstall. Check packages and diagnostics for credentials, private caches, and publication data.

## 5. Publish through GitHub

- [ ] Add a trusted release workflow triggered by a version tag. Run tests, package both platforms, verify the assets, and assemble a draft release with versioned binaries, checksums, supported systems, release notes, and known issues.
- [ ] Publish beta tags as GitHub prereleases. Promote a tested stable release separately. Retain the previous working release for rollback.
- [ ] Publish GitHub Pages with Mac and Windows download buttons, install steps, optional MCP setup, local data and privacy details, and a support link. Point beta downloads to the tested prerelease and stable downloads to the stable release assets.
- [ ] Verify every Pages link from a signed-out browser and have a small group complete installation using the published instructions.

## 6. Ship updates and Homebrew distribution

- [ ] Define stable and opt-in beta updater channels. Make GitHub release selection, semantic version comparison, and exact asset naming part of the release contract.
- [ ] Implement Mac update verification for the expected bundle ID, version, build number, Developer ID team, and nested signatures. Stage the update, replace the bundle atomically, relaunch, and retain a bounded rollback copy. Test interrupted downloads, wrong signatures, downgrades, and failed launches.
- [ ] Define and test the Windows update path using signed installers. Document the manual upgrade and rollback steps while the in-app path is being built.
- [ ] Publish a Homebrew cask for the stable Mac DMG through a tap. Pin the version, URL, and SHA-256. Test install, upgrade, and uninstall, and make any optional data removal explicit. Keep prereleases out of the stable cask and automate version and checksum updates after stable releases.
