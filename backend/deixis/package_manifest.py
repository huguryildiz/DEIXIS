"""Every file the running app reads from disk besides its importable Python code, for a packaged build (pre-P10 A1).

`DATAS` pairs a path or glob under the repository root with the folder it lands in under `paths.RESOURCE_ROOT` (the
unpacked bundle, `sys._MEIPASS`, in a frozen build). Repository folders keep their layout; files the code finds next to
its own module (`Path(__file__)`) go under `deixis/`, where a frozen module's `__file__` points. P10d passes `datas()`
to PyInstaller as `datas`, adds `copy_metadata("deixis")` (protocols and PRISMA-S exports name
`importlib.metadata.version("deixis")`), and first runs `write_build_identity` (read by `workflow/prisma_s.py`).
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

DATAS = (
    ("contracts/research/*.schema.json", "contracts/research"),  # domain/contracts.py
    ("methods/deixis-research", "methods/deixis-research"),  # domain/skill.py, checked at startup
    ("apps/web/dist", "apps/web/dist"),  # config.Settings.web_dist; built by `npm run build` first
    ("backend/deixis/storage/migrations/*.sql", "deixis/storage/migrations"),
    ("backend/deixis/documents/embedding-requirements.txt", "deixis/documents"),
    ("backend/deixis/documents/katex_commands.json", "deixis/documents"),
    ("backend/deixis/documents/latex_kernel_names.json", "deixis/documents"),
    # Scripts run by another Python (the built-in model's and the equation reader's own environments), so read as files.
    ("backend/deixis/documents/embedding_runner.py", "deixis/documents"),
    ("backend/deixis/documents/marker_runner.py", "deixis/documents"),
    ("backend/deixis/workflow/report/latex_names.json", "deixis/workflow/report"),
    ("backend/deixis/exports/deixis-mark.png", "deixis/exports"),
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
    package = repo_root / "backend" / "deixis"
    files = {path.relative_to(repo_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(package.rglob("*.py")) if "__pycache__" not in path.parts}
    out = out_dir / BUILD_IDENTITY
    out.write_text(json.dumps({"identity": "build_sha256", "version": version("deixis"), "files": files},
                              indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out
