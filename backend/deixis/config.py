"""Runtime settings. The active database stays in local app data, not the repository or a synced folder."""

from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable


def default_data_dir() -> Path:
    """DEIXIS_DATA_DIR, else the folder chosen in Settings (the pointer file, D32), else the platform default."""
    if env := os.environ.get("DEIXIS_DATA_DIR"):
        return Path(env).expanduser()
    from deixis import data_location

    if (chosen := data_location.pointer_path()) is not None:
        return chosen
    return platform_data_dir()


def platform_data_dir() -> Path:
    """The platform's default data folder; it also holds the pointer file, so it never moves."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DEIXIS"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DEIXIS"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "deixis"


CONTACT_EMAIL_SETTING = "contact_email"
# Settings → General → Research: values the person set in the app. Each one, when stored, comes before the value this
# process started with (its environment variable or default); unset, the start value stays.
DEFAULT_EFFORT_SETTING = "default_effort"
FULLTEXT_FETCH_SETTING = "fulltext_fetch"
ARXIV_SOURCE_SETTING = "arxiv_source"
MODEL_CONCURRENCY_SETTING = "model_concurrency"
MODEL_CONCURRENCY_MAX = 16


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
    # equation reader (Marker) is not installed (D104, slice 22). `load_settings` defaults to `auto` (D36), which turns
    # the route on (POSIX only); this dataclass stays `off` so tests that build Settings by hand request no source. With
    # `off` no source is requested and no PDF extraction changes; readings already stored stay.
    arxiv_source: str = "off"
    # Reads one `app_settings` value by key; `create_app` binds it to the store so the contact email the person set
    # in Settings is found before the environment variable. Unset (tests that build Settings by hand): env only.
    setting_reader: Callable[[str], Any] | None = field(default=None, compare=False, repr=False)

    def bound_to(self, setting_reader: Callable[[str], Any]) -> "Settings":
        return replace(self, setting_reader=setting_reader)

    def _stored(self, key: str, allowed: tuple[str, ...]) -> str | None:
        value = self.setting_reader(key) if self.setting_reader else None
        return value if value in allowed else None

    def effective_fulltext_fetch(self) -> str:
        return self._stored(FULLTEXT_FETCH_SETTING, ("auto", "off")) or self.fulltext_fetch

    def effective_arxiv_source(self) -> str:
        return self._stored(ARXIV_SOURCE_SETTING, ("auto", "off")) or self.arxiv_source

    def effective_model_concurrency(self) -> int:
        value = self.setting_reader(MODEL_CONCURRENCY_SETTING) if self.setting_reader else None
        return value if isinstance(value, int) and 1 <= value <= MODEL_CONCURRENCY_MAX else self.model_concurrency

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
        from deixis.paths import RESOURCE_ROOT

        return RESOURCE_ROOT / "apps" / "web" / "dist"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "worker.lock"

    @property
    def contact_email(self) -> str | None:
        """The address set in Settings (F15), else DEIXIS_CONTACT_EMAIL."""
        stored = self.setting_reader(CONTACT_EMAIL_SETTING) if self.setting_reader else None
        return (stored if isinstance(stored, str) and stored else None) or os.environ.get("DEIXIS_CONTACT_EMAIL") or None


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
    from deixis.paths import RESOURCE_ROOT, is_frozen

    from deixis import credentials

    # Only a run from the repository reads `.env` (A2): a packaged app never reads or writes its install folder.
    if not is_frozen():
        credentials.mark_dotenv(load_dotenv(RESOURCE_ROOT / ".env"), RESOURCE_ROOT / ".env")
    credentials.set_data_dir(default_data_dir())  # where the opted-in key file lives (A6)
    credentials.move_dotenv_keys_to_keychain()
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
    arxiv_source = os.environ.get("DEIXIS_ARXIV_SOURCE", "auto")
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
