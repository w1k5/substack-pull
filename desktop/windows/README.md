# Windows beta

This is a thin Windows window around the shared Python dashboard. The app opens
Substack sign-in in WebView2, checks editor access, saves the resulting session in
Windows Credential Manager, and starts the dashboard on a random loopback port.
The app closes its local server when it exits. The MCP process is optional and
starts separately from an AI client.

## Build on Windows

Install Python 3.11+, the .NET 8 SDK, and PowerShell. Run `./build.ps1` from this
directory. It creates `.build/Clearview-Windows-beta.zip`. Extract the whole ZIP
before launching `Clearview.Windows.exe`; the `engine` folder must stay beside it.
The repository also has a manually triggered **Windows beta build** GitHub Actions
workflow, which uploads this ZIP as an artifact.
The build includes Python, the shared data engine, dashboard assets, `tzdata`, and
the MCP dependencies. Test the ZIP on a clean Windows 11 machine before giving it
to beta testers. The app requires the Microsoft Edge WebView2 Evergreen Runtime;
the setup machine should install it if absent.

This build is not signed and has no installer or automatic updates. Sign the app
and package it with a per-user installer before distributing it beyond a small,
known beta group. A new unsigned Windows download may trigger SmartScreen.

## Saved data and MCP

Settings, backup files, and analytics cache live under `%LOCALAPPDATA%\Clearview`.
The session lives in Windows Credential Manager under
`com.local.substack-pull:<publication host>`, never in a JSON file. The app clears
its sign-in WebView browsing data after a successful connection.

The ZIP also contains `engine\clearview-engine.exe`. For an AI client that can
launch a local MCP server, configure that executable with the single argument
`mcp`. It uses the same saved connection and data directory. This step is
optional; opening the desktop dashboard does not launch the MCP server.

## Current beta limits

The Windows window and Credential Manager calls must be tested on Windows; a
cross-compiled .NET build on macOS does not validate those runtime behaviors.
The embedded Substack sign-in relies on an undocumented browser session, so this
remains a private beta while a supported authorization route is pursued.
