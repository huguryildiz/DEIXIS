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
    def openalex_api_key(self) -> str | None:
        return os.environ.get("OPENALEX_API_KEY") or None

    @property
    def contact_email(self) -> str | None:
        return os.environ.get("DEIXIS_CONTACT_EMAIL") or None


def load_dotenv(path: Path) -> None:
    """Fill unset environment variables from a local KEY=VALUE file. Values are never logged."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    from deixis.paths import REPO_ROOT

    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        data_dir=default_data_dir(),
        host=os.environ.get("DEIXIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEIXIS_PORT", "8765")),
    )
