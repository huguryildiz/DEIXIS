# DEIXIS

A local research workspace for scientific literature. You ask a question; DEIXIS searches OpenAlex and Semantic Scholar, reads abstracts and full texts, and writes an answer in which every citation points to a located passage you can open. It runs on your computer (Python backend, React UI on `127.0.0.1`); searches and model calls go to the providers you connect. Code checks that each citation points to a real passage; it does not check that the passage supports the claim, and no search result proves a question is new.

## Install the Mac app

For Apple Silicon Macs (M1 and newer) with macOS 13 or later; so far tried only on macOS 27. Intel Macs, Windows and Linux are not packaged yet.

1. Download `DEIXIS_<version>_aarch64.dmg` from [Releases](https://github.com/huguryildiz/DEIXIS/releases). Its SHA-256 is listed on the release page: `shasum -a 256 DEIXIS_*.dmg`.
2. Open the DMG and drag DEIXIS into Applications.
3. The app is not signed with an Apple Developer ID, so the first launch is blocked. Open DEIXIS once, then go to System Settings → Privacy & Security, find "DEIXIS was blocked" and choose Open Anyway. Or run this in Terminal once:

   ```sh
   xattr -dr com.apple.quarantine /Applications/DEIXIS.app
   ```

DEIXIS opens in its own window. Closing the window keeps it running in the menu bar, where Quit stops it and everything it started. Your library stays in `~/Library/Application Support/DEIXIS` when you update or delete the app. There is no automatic update: download the newer DMG and replace the app.

Model connections are separate programs or keys: install Codex, Claude Code or Gemini CLI yourself, or paste an API key in Settings. Optical character recognition (OCR) for scanned PDFs still needs Tesseract (`brew install tesseract`) in this version.

## Run from source

Supported: macOS on Apple Silicon, native arm64 Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 22 with npm 10.

```sh
uv sync
cd web && npm ci && npm run build && cd ..
uv run python -m deixis serve        # opens http://127.0.0.1:8765/
uv run pytest                        # model-free tests
```

Connect a model and sources in Settings; keys go to the system keychain ([`providers.env.example`](providers.env.example) lists the names). Data lives in `~/Library/Application Support/DEIXIS` (or `DEIXIS_DATA_DIR`), never in the repository.

The working agreement, layout and commands are in [CLAUDE.md](CLAUDE.md); decisions in [docs/decisions.csv](docs/decisions.csv), how search, ranking and reading work in [docs/search.md](docs/search.md), search benchmark results in [docs/benchmark.md](docs/benchmark.md), project status in [STATUS.md](STATUS.md).

License: [AGPL-3.0-or-later](LICENSE).
