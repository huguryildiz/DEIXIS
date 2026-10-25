"""Every file the running app reads from disk besides its importable Python code, for a packaged build (pre-P10 A1).

`DATAS` pairs a path or glob under the repository root with the folder it lands in under `paths.RESOURCE_ROOT` (the
unpacked bundle, `sys._MEIPASS`, in a frozen build). Repository folders keep their layout; files the code finds next to
its own module (`Path(__file__)`) go under `deixis/`, where a frozen module's `__file__` points. P10d passes `datas()`
to PyInstaller as `datas`, adds `copy_metadata("deixis")` (protocols and PRISMA-S exports name
`importlib.metadata.version("deixis")`), and first runs `write_build_identity` (read by `workflow/search/prisma_s.py`).
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

DATAS = (
    ("deixis/contracts/research/*.schema.json", "deixis/contracts/research"),  # domain/contracts.py
    ("deixis/methods/deixis-research", "deixis/methods/deixis-research"),  # domain/skill.py, checked at startup
    ("web/dist", "web/dist"),  # config.Settings.web_dist; built by `npm run build` first
    ("deixis/storage/schema.sql", "deixis/storage"),  # storage/db.py makes a new library from it
    ("deixis/documents/katex_commands.json", "deixis/documents"),
    ("deixis/documents/latex_kernel_names.json", "deixis/documents"),
    ("deixis/workflow/features/report/latex_names.json", "deixis/workflow/features/report"),
    ("deixis/models/model_prices.json", "deixis/models"),  # workflow/run/spend.py (F4)
    ("deixis/exports/deixis-mark.png", "deixis/exports"),
    ("THIRD_PARTY_NOTICES", "."),  # api/about_routes.py; written by scripts/licenses/build_notices.py (F2)
)
BUILD_IDENTITY = "build_identity.json"


def datas(repo_root: Path, build_identity: Path | None = None) -> list[tuple[str, str]]:
    """(source file, destination folder) pairs in PyInstaller's `datas` form, one per file; dot files are left out."""
    pairs: list[tuple[str, str]] = []
    for pattern, dest in DATAS:
        base = repo_root / pattern
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                rel = path.relative_to(base)
                if path.is_file() and not any(part.startswith(".") for part in rel.parts):
                    pairs.append((str(path), (Path(dest) / rel.parent).as_posix()))
        else:
            pairs += [(str(path), dest) for path in sorted(repo_root.glob(pattern))]
    if build_identity is not None:
        pairs.append((str(build_identity), "deixis"))
    return pairs


def write_build_identity(repo_root: Path, out_dir: Path) -> Path:
    """Write the sha256 of every Python file of the package as the build read it. A frozen app keeps its code in an
    archive, so `prisma_s` reports these build-time digests, labelled as such, instead of hashing `.py` files."""
    package = repo_root / "deixis"
    files = {path.relative_to(repo_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(package.rglob("*.py")) if "__pycache__" not in path.parts}
    out = out_dir / BUILD_IDENTITY
    out.write_text(json.dumps({"identity": "build_sha256", "version": version("deixis"), "files": files},
                              indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out
