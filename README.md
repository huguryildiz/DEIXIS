<div align="center">

<img src="desktop/src-tauri/icons/128x128@2x.png" alt="DEIXIS" width="160">

# DEIXIS

### Local Research Workspace

A desktop app that answers questions from the scientific literature, with every citation pointing to a passage you can open.

<img src="https://img.shields.io/badge/Python%20·%20FastAPI-0f1a2e?style=for-the-badge&logo=fastapi&logoColor=009688" alt="Python · FastAPI">
<img src="https://img.shields.io/badge/React%20·%20Vite-0f1a2e?style=for-the-badge&logo=react&logoColor=61DAFB" alt="React · Vite">
<img src="https://img.shields.io/badge/TypeScript-0f1a2e?style=for-the-badge&logo=typescript&logoColor=3178C6" alt="TypeScript">
<img src="https://img.shields.io/badge/Tauri-0f1a2e?style=for-the-badge&logo=tauri&logoColor=FFC131" alt="Tauri">
<img src="https://img.shields.io/badge/OpenAlex-0f1a2e?style=for-the-badge&logo=openaccess&logoColor=F68212" alt="OpenAlex">
<img src="https://img.shields.io/badge/SQLite-0f1a2e?style=for-the-badge&logo=sqlite&logoColor=4FA3D9" alt="SQLite">
<img src="https://img.shields.io/badge/pytest%20·%20Playwright-0f1a2e?style=for-the-badge&logo=pytest&logoColor=0A9EDC" alt="pytest · Playwright">
<br>
<a href="https://deixis.huguryildiz.com"><img src="https://img.shields.io/badge/deixis.huguryildiz.com-0f1a2e?style=for-the-badge&logo=googlechrome&logoColor=white" alt="deixis.huguryildiz.com"></a>
<a href="https://github.com/huguryildiz/DEIXIS/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/huguryildiz/DEIXIS/ci.yml?branch=main&style=for-the-badge&label=checks" alt="checks"></a>
<a href="https://github.com/huguryildiz/DEIXIS/releases"><img src="https://img.shields.io/github/v/release/huguryildiz/DEIXIS?include_prereleases&style=for-the-badge&label=release&color=3f63a8" alt="release"></a>

<h3>
<a href="#install-the-mac-app">Mac</a> ·
<a href="#install-on-windows">Windows</a> ·
<a href="#install-on-linux">Linux</a> ·
<a href="#run-from-source">Run from source</a>
</h3>

</div>

<br>

A local research workspace for scientific literature. You ask a question; DEIXIS searches OpenAlex and Semantic Scholar, reads abstracts and full texts, and writes an answer in which every citation points to a located passage you can open. It runs on your computer (Python backend, React UI on `127.0.0.1`); searches and model calls go to the providers you connect. Code checks that each citation points to a real passage; it does not check that the passage supports the claim, and no search result proves a question is new.

## Install the Mac app

For Apple Silicon Macs (M1 and newer) with macOS 13 or later; so far tried only on macOS 27. Intel Macs are not packaged.

1. Download `DEIXIS_<version>_aarch64.dmg` from [Releases](https://github.com/huguryildiz/DEIXIS/releases). Its SHA-256 is listed on the release page: `shasum -a 256 DEIXIS_*.dmg`.
2. Open the DMG and drag DEIXIS into Applications.
3. The app is not signed with an Apple Developer ID, so the first launch is blocked. Open DEIXIS once, then go to System Settings → Privacy & Security, find "DEIXIS was blocked" and choose Open Anyway. Or run this in Terminal once:

   ```sh
   xattr -dr com.apple.quarantine /Applications/DEIXIS.app
   ```

DEIXIS opens in its own window. Closing the window keeps it running in the menu bar, where Quit stops it and everything it started. Your library stays in `~/Library/Application Support/DEIXIS` when you update or delete the app. There is no automatic update: once a day DEIXIS asks GitHub whether a newer version exists and says so in the sidebar (Settings → About turns this off); download the newer DMG and replace the app.

Model connections are separate programs or keys: install Codex, Claude Code or Gemini CLI yourself, or paste an API key in Settings. Optical character recognition (OCR) of scanned PDFs works out of the box in English and Turkish; nothing else to install.

## Install on Windows

A preview for Windows 10 and 11 on x64 PCs. So far it has been tried on a GitHub Windows Server runner and on Windows 11 for ARM running the x64 build under emulation; not yet on Windows 10 or on an ordinary x64 PC.

1. Download `DEIXIS_<version>_x64-setup.exe` from [Releases](https://github.com/huguryildiz/DEIXIS/releases) and check its SHA-256 against the release page: `Get-FileHash .\DEIXIS_*_x64-setup.exe`.
2. Run it. The installer is not signed, so SmartScreen may stop it: choose More info, then Run anyway. It installs for your user only, without an administrator prompt, into `%LOCALAPPDATA%\Programs\DEIXIS`.

DEIXIS opens in its own window. Closing the window keeps it running in the notification area, where Quit stops it and everything it started. Your library stays in `%LOCALAPPDATA%\DEIXIS` when you update or uninstall the app. There is no automatic update: DEIXIS says when a newer version exists (as on macOS); run the newer installer.

Not in the Windows preview: the built-in local models in Settings (keyword search, the Voyage reranker and API embedding connections work), and reading arXiv LaTeX sources (the PDF is read instead).

## Install on Linux

A preview for 64-bit x86 PCs with Ubuntu 22.04 or newer (or a distribution of the same age). It has been tried on GitHub's Ubuntu 22.04 and 24.04 runners under a virtual display, not yet on a desktop. The Linux packages are built by CI but not yet attached to a release.

- `.deb` (Ubuntu, Debian and their relatives): `sudo apt install ./DEIXIS_<version>_amd64.deb`. apt pulls in WebKitGTK and the tray library. `sudo apt remove deixis` removes the app.
- AppImage (any distribution): `chmod +x DEIXIS_<version>_amd64.AppImage`, then run it. It needs FUSE 2 (`sudo apt install libfuse2`, on Ubuntu 24.04 `libfuse2t64`); without it, start it with `--appimage-extract-and-run`.

DEIXIS opens in its own window; closing the window quits it and everything it started. Your library is in `~/.local/share/deixis` (or `$XDG_DATA_HOME/deixis`) and stays when you remove the app. Keys you save go to a desktop keyring that offers the Secret Service (GNOME Keyring; KWallet on recent KDE); without one, Settings says so and keeps them for the session, or in a file only you can read if you choose that. Downloads go to your Downloads folder. OCR works without installing Tesseract. There is no automatic update: DEIXIS says when a newer version exists (as on macOS).

Not yet checked on Linux: the built-in local models in Settings, and a real desktop session (tray, keyring prompts, file manager).

## Run from source

Supported: macOS on Apple Silicon, native arm64 Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 22 with npm 10.

```sh
uv sync
cd web && npm ci && npm run build && cd ..
uv run python -m deixis serve        # opens http://127.0.0.1:8765/
uv run pytest                        # model-free tests
```

Connect a model and sources in Settings; keys go to the system keychain ([`providers.env.example`](providers.env.example) lists the names). Data lives in `~/Library/Application Support/DEIXIS` (or `DEIXIS_DATA_DIR`), never in the repository.

The working agreement, layout and commands are in [CLAUDE.md](CLAUDE.md); decisions in [docs/decisions.csv](docs/decisions.csv), how search, ranking and reading work in [docs/search.md](docs/search.md) and search benchmark results in [docs/benchmark.md](docs/benchmark.md).

License: [AGPL-3.0-or-later](LICENSE).
