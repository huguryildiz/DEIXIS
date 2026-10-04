"""Regenerate .local/INDEX.md: one line per run directory."""
from __future__ import annotations

import datetime as dt
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1] / ".local"


def human(size: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if size < 1024 or unit == "G":
            return f"{size:.0f}{unit}" if unit != "G" else f"{size:.1f}G"
        size /= 1024
    return f"{size:.0f}G"


def headline(d: pathlib.Path) -> str:
    for md in sorted(d.rglob("*.md"))[:3]:
        for line in md.read_text(errors="ignore").splitlines():
            if line.startswith("#"):
                return line.lstrip("# ").strip()[:90]
    return ""


def du(d: pathlib.Path) -> int:
    out = subprocess.run(["du", "-sk", str(d)], capture_output=True, text=True).stdout
    return int(out.split()[0]) * 1024


ARCHIVE = ROOT / "archive"
dirs = [p for p in ROOT.iterdir() if p.is_dir() and p != ARCHIVE]
if ARCHIVE.is_dir():
    dirs += [p for g in ARCHIVE.iterdir() if g.is_dir() for p in g.iterdir() if p.is_dir()]

rows = []
for d in sorted(dirs, key=lambda p: (p.parent != ROOT, str(p.relative_to(ROOT)))):
    stamp = dt.date.fromtimestamp(d.stat().st_mtime).isoformat()
    rows.append((str(d.relative_to(ROOT)), stamp, human(du(d)), sum(1 for _ in d.rglob("*") if _.is_file()), headline(d)))

lines = [
    "# .local dizini",
    "",
    f"Otomatik üretildi: {dt.date.today().isoformat()} — `uv run python scripts/local_index.py`",
    "",
    "Üstte süren işler (P6, P9). `archive/sw/` kapanan SW izi (D114), `archive/early/` 16–20 Eylül deneyleri.",
    "",
    "| Klasör | Tarih | Boyut | Dosya | Not |",
    "| --- | --- | --- | --- | --- |",
]
lines += [f"| `{n}` | {s} | {sz} | {c} | {h} |" for n, s, sz, c, h in rows]
(ROOT / "INDEX.md").write_text("\n".join(lines) + "\n")
print(f"{len(rows)} klasör yazıldı")
