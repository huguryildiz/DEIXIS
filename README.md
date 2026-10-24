# DEIXIS

A local research workspace for scientific literature. You ask a question; DEIXIS searches OpenAlex and Semantic Scholar, reads abstracts and full texts, and writes an answer in which every citation points to a located passage you can open. It runs on your computer (Python backend, React UI on `127.0.0.1`); searches and model calls go to the providers you connect. Code checks that each citation points to a real passage; it does not check that the passage supports the claim, and no search result proves a question is new.

Supported: macOS on Apple Silicon, native arm64 Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 22 with npm 10.

```sh
uv sync
cd web && npm ci && npm run build && cd ..
uv run python -m deixis serve        # opens http://127.0.0.1:8765/
uv run pytest                        # model-free tests
```

Connect a model and sources in Settings; keys go to the system keychain ([`providers.env.example`](providers.env.example) lists the names). Data lives in `~/Library/Application Support/DEIXIS` (or `DEIXIS_DATA_DIR`), never in the repository.

The working agreement, layout and commands are in [CLAUDE.md](CLAUDE.md); decisions in [docs/decisions.md](docs/decisions.md), search benchmark results in [docs/benchmark.md](docs/benchmark.md), project status in [STATUS.md](STATUS.md).

License: [AGPL-3.0-or-later](LICENSE).
