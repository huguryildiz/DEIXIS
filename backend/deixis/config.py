"""Runtime settings. The active database stays in local app data, not the repository or a synced folder."""

from __future__ import annotations

import os
import sys
import warnings
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
    # Whether a completed `sw` discovery run is followed by a full-text retrieval run (D83, slice 10). `auto` is the
    # product's behavior; `off` leaves the corpus where the discovery run left it, for a measurement or a test that
    # needs no second run.
    fulltext_fetch: str = "auto"
    # Whether a valid `sw` answer is followed by the study table (proposed columns added without review, then filled).
    # The dataclass default is `off` so a test that builds Settings by hand sees no extra runs; `load_settings` defaults to `auto`.
    study_table: str = "off"
    # Whether a completed `sw` full-text retrieval run is followed by a full-text reading run (D85, slice 12).
    # `auto` is the product's behavior; `off` leaves the fetched works at `not_read_yet`, for a measurement or a
    # test that needs no second model run.
    fulltext_adjudication: str = "auto"
    # Who writes an sw discovery run's keyword query (D92, slice 13h). `model` is the product's behavior: a model
    # writes it once per scope revision and the code's own query is searched beside it. `code` is the query of
    # slice 13g alone, with no model call, for a measurement or a test that needs the code path only.
    search_query: str = "model"
    # Whether PDFs that are arXiv versions get the numbered display equations of their authors' LaTeX source while the
    # equation reader (Marker) is not installed (D104, slice 22). `off` in this dataclass and in `load_settings` until
    # slice 24 measures it; `auto` turns the route on (POSIX only). With `off` no source is requested and no PDF
    # extraction changes; readings already stored stay.
    arxiv_source: str = "off"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.sqlite"

    @property
    def papers_dir(self) -> Path:
        return self.data_dir / "papers"

    @property
    def recovery_dir(self) -> Path:
        return self.data_dir / "recovery"

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
    if "DEIXIS_SEARCH_WORKFLOW" in os.environ:
        warnings.warn("DEIXIS_SEARCH_WORKFLOW is ignored; new researches use sw", UserWarning, stacklevel=2)
    fulltext_fetch = os.environ.get("DEIXIS_FULLTEXT_FETCH", "auto")
    if fulltext_fetch not in ("auto", "off"):
        raise ValueError("DEIXIS_FULLTEXT_FETCH must be auto or off")
    study_table = os.environ.get("DEIXIS_STUDY_TABLE", "auto")
    if study_table not in ("auto", "off"):
        raise ValueError("DEIXIS_STUDY_TABLE must be auto or off")
    fulltext_adjudication = os.environ.get("DEIXIS_FULLTEXT_ADJUDICATION", "auto")
    if fulltext_adjudication not in ("auto", "off"):
        raise ValueError("DEIXIS_FULLTEXT_ADJUDICATION must be auto or off")
    search_query = os.environ.get("DEIXIS_SEARCH_QUERY", "model")
    if search_query not in ("model", "code"):
        raise ValueError("DEIXIS_SEARCH_QUERY must be model or code")
    arxiv_source = os.environ.get("DEIXIS_ARXIV_SOURCE", "off")
    if arxiv_source not in ("auto", "off"):
        raise ValueError("DEIXIS_ARXIV_SOURCE must be auto or off")
    return Settings(
        data_dir=default_data_dir(),
        host=os.environ.get("DEIXIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEIXIS_PORT", "8765")),
        model_concurrency=max(1, int(os.environ.get("DEIXIS_MODEL_CONCURRENCY", "6") or "6")),
        fulltext_fetch=fulltext_fetch,
        study_table=study_table,
        fulltext_adjudication=fulltext_adjudication,
        search_query=search_query,
        arxiv_source=arxiv_source,
    )
