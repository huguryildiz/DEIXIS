"""Repository-relative locations of contracts and the method package."""

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("DEIXIS_REPO_ROOT") or Path(__file__).resolve().parents[2])
CONTRACTS_DIR = REPO_ROOT / "contracts" / "research"
SKILL_DIR = REPO_ROOT / "methods" / "deixis-research"
