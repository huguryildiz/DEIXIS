"""Runtime settings. The active database stays in local app data, not the repository or a synced folder."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_data_dir() -> Path:
    if env := os.environ.get("DEIXIS_DATA_DIR"):
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DEIXIS"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DEIXIS"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "deixis"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    model_concurrency: int = 6
    query_strategy: str = "legacy"
    search_workflow: str = "legacy"
    # Whether an sw discovery run stops for the user before it freezes its protocol (SW2.6, slice 08a). `ask` is the
    # product's behavior; `as_proposed` approves the proposal without stopping, for a measurement or a test that
    # needs a run nobody attends, and says so in the protocol body rather than looking like a user's approval.
    protocol_approval: str = "ask"
    # Whether a completed `sw` discovery run is followed by a full-text retrieval run (D83, slice 10). `auto` is the
    # product's behavior; `off` leaves the corpus where the discovery run left it, for a measurement or a test that
    # needs no second run. A `legacy` research queues nothing either way.
    fulltext_fetch: str = "auto"
    # Whether a completed `sw` full-text retrieval run is followed by a full-text reading run (D85, slice 12).
    # `auto` is the product's behavior; `off` leaves the fetched works at `not_read_yet`, for a measurement or a
    # test that needs no second model run. A `legacy` research queues nothing either way.
    fulltext_adjudication: str = "auto"
    # Who writes an sw discovery run's keyword query (D92, slice 13h). `model` is the product's behavior: a model
    # writes it once per scope revision and the code's own query is searched beside it. `code` is the query of
    # slice 13g alone, with no model call, for a measurement or a test that needs the code path only.
    search_query: str = "model"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.sqlite"

    @property
    def papers_dir(self) -> Path:
        return self.data_dir / "papers"

    @property
    def payloads_dir(self) -> Path:
        return self.data_dir / "provider-payloads"

    @property
    def codex_home(self) -> Path:
        return Path(os.environ["DEIXIS_CODEX_HOME"]).expanduser() if os.environ.get("DEIXIS_CODEX_HOME") else self.data_dir / "codex-home"

    @property
    def web_dist(self) -> Path:
        from deixis.paths import REPO_ROOT

        return REPO_ROOT / "apps" / "web" / "dist"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "worker.lock"

    @property
    def contact_email(self) -> str | None:
        return os.environ.get("DEIXIS_CONTACT_EMAIL") or None


def load_dotenv(path: Path) -> set[str]:
    """Fill unset environment variables from a local KEY=VALUE file and return the names it set. Values are never logged."""
    loaded: set[str] = set()
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value
            loaded.add(key)
    return loaded


def load_settings() -> Settings:
    from deixis.paths import REPO_ROOT

    from deixis import credentials

    credentials.mark_dotenv(load_dotenv(REPO_ROOT / ".env"), REPO_ROOT / ".env")
    credentials.load_into_environment()
    query_strategy = os.environ.get("DEIXIS_QUERY_STRATEGY", "legacy")
    if query_strategy not in ("legacy", "compact_openalex_v1"):
        raise ValueError("DEIXIS_QUERY_STRATEGY must be legacy or compact_openalex_v1")
    search_workflow = os.environ.get("DEIXIS_SEARCH_WORKFLOW", "legacy")
    if search_workflow not in ("legacy", "sw"):
        raise ValueError("DEIXIS_SEARCH_WORKFLOW must be legacy or sw")
    protocol_approval = os.environ.get("DEIXIS_PROTOCOL_APPROVAL", "ask")
    if protocol_approval not in ("ask", "as_proposed"):
        raise ValueError("DEIXIS_PROTOCOL_APPROVAL must be ask or as_proposed")
    fulltext_fetch = os.environ.get("DEIXIS_FULLTEXT_FETCH", "auto")
    if fulltext_fetch not in ("auto", "off"):
        raise ValueError("DEIXIS_FULLTEXT_FETCH must be auto or off")
    fulltext_adjudication = os.environ.get("DEIXIS_FULLTEXT_ADJUDICATION", "auto")
    if fulltext_adjudication not in ("auto", "off"):
        raise ValueError("DEIXIS_FULLTEXT_ADJUDICATION must be auto or off")
    search_query = os.environ.get("DEIXIS_SEARCH_QUERY", "model")
    if search_query not in ("model", "code"):
        raise ValueError("DEIXIS_SEARCH_QUERY must be model or code")
    return Settings(
        data_dir=default_data_dir(),
        host=os.environ.get("DEIXIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEIXIS_PORT", "8765")),
        model_concurrency=max(1, int(os.environ.get("DEIXIS_MODEL_CONCURRENCY", "6") or "6")),
        query_strategy=query_strategy,
        search_workflow=search_workflow,
        protocol_approval=protocol_approval,
        fulltext_fetch=fulltext_fetch,
        fulltext_adjudication=fulltext_adjudication,
        search_query=search_query,
    )
