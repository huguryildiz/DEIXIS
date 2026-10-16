"""Writes THIRD_PARTY_NOTICES (pre-P10 F2): the licence of every Python and npm production dependency, with its licence
file text when the package ships one, then the native components listed by hand in `native_components.txt`.

Python: the production closure of `uv.lock` (`uv export --no-dev`), read from the installed distributions' metadata.
npm: the non-dev packages of `apps/web/package-lock.json`, read from `apps/web/node_modules`. A package whose licence
cannot be named from a known list makes the script exit 1 and list it; a licence that is really known is added to
OVERRIDES below with the reason, never skipped. Packages the lock needs only on another platform are not installed here;
they must have an override (Python) or take the lock's licence field without text (npm optional builds).
Run from the repository root after `uv sync` and `cd apps/web && npm ci`:
    uv run python scripts/licenses/build_notices.py            # writes THIRD_PARTY_NOTICES
    uv run python scripts/licenses/build_notices.py --check    # scan only, exit 1 on an unknown licence
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NATIVE = Path(__file__).with_name("native_components.txt")
PLATFORMS = ("darwin", "win32", "linux")  # the three desktop builds P10 makes

# SPDX identifiers the scan accepts. Anything else is "unknown" until someone reads its licence and decides.
KNOWN = {
    "0BSD", "Apache-2.0", "BlueOak-1.0.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "CC-BY-4.0", "ISC", "MIT", "MIT-0",
    "MPL-2.0", "PSF-2.0", "Python-2.0", "Unlicense", "Zlib", "OFL-1.1", "AGPL-3.0-or-later", "AGPL-3.0-only",
}
# Free-text licence names (Python `License` field, classifiers, old npm fields) read as SPDX; lower-cased keys.
ALIASES = {
    "mit license": "MIT", "mit": "MIT", "bsd license": "BSD-3-Clause", "bsd": "BSD-3-Clause", "bsd-3-clause": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause", "apache software license": "Apache-2.0", "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0", "isc license (iscl)": "ISC", "isc": "ISC",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0", "mpl-2.0": "MPL-2.0", "python software foundation license": "PSF-2.0",
    "psf-2.0": "PSF-2.0",
}
# Licences read by hand because the package's own fields do not say them in a form the scan reads. Each entry names why.
OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    # PyMuPDF's License field is a sentence ("Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"). DEIXIS
    # uses it under the AGPL-3.0 option, the same licence as DEIXIS itself.
    ("python", "pymupdf"): ("AGPL-3.0-only", "Dual-licensed by Artifex (AGPL-3.0 or a commercial licence); DEIXIS uses the AGPL-3.0 option."),
    # The lock needs these only on Linux and Windows, so they are not installed on a macOS build machine and their
    # metadata cannot be read here. Licences taken from each project's PyPI page (checked 16 Oct 2026); the licence
    # text is added when P10 runs this script on that platform.
    ("python", "jeepney"): ("MIT", "Linux only; not installed here, licence text not read."),
    ("python", "secretstorage"): ("BSD-3-Clause", "Linux only; not installed here, licence text not read."),
    ("python", "pywin32"): ("PSF-2.0", "Windows only; not installed here, licence text not read."),
    ("python", "pywin32-ctypes"): ("BSD-3-Clause", "Windows only; not installed here, licence text not read."),
}
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice)([.\-_].*)?$", re.I)


def normalize(raw: str) -> tuple[str, list[str]]:
    """(SPDX-style expression, unknown atoms). `MIT OR Apache-2.0` and `(MIT AND BSD-3-Clause)` are split on their
    operators; each atom must be in KNOWN after the alias table, else it is unknown."""
    text = " ".join(raw.replace("\n", " ").split())
    if not text:
        return "", ["(none)"]
    atoms = [a for a in re.split(r"\s+(?:OR|AND|WITH)\s+|[()]", text) if a.strip()]
    unknown = []
    out = text
    for atom in atoms:
        atom = atom.strip()
        mapped = ALIASES.get(atom.lower(), atom)
        if mapped not in KNOWN:
            unknown.append(atom)
        elif mapped != atom:
            out = out.replace(atom, mapped)
    return out, unknown


def _condition_true(marker: str, platform: str) -> bool:
    """Evaluate a uv-export environment marker for one target platform on CPython. Only the variables below appear in this
    lock; anything else raises, so a new marker kind is noticed."""
    values = {"sys_platform": platform, "platform_python_implementation": "CPython", "implementation_name": "cpython"}

    def sub(match: re.Match) -> str:
        name, op, value = match.group(1), match.group(2), match.group(3)
        if name not in values:
            raise ValueError(f"unsupported marker variable {name!r} in {marker!r}")
        return str((values[name] == value) == (op == "=="))
    reduced = re.sub(r"(\w+)\s*(==|!=)\s*'([^']*)'", sub, marker)
    if re.sub(r"\b(True|False|and|or|not)\b|[()\s]", "", reduced):
        raise ValueError(f"unsupported marker {marker!r}")
    return bool(eval(reduced, {"__builtins__": {}}))  # noqa: S307  (only True/False/and/or/not remain)


def python_requirements() -> list[tuple[str, str]]:
    """(name, version) of the packages the DEIXIS app needs on any of the three desktop platforms, from the lock."""
    out = subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    found = []
    for line in out.splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)\s*(?:;\s*(.*))?$", line)
        if match and (not match.group(3) or any(_condition_true(match.group(3), p) for p in PLATFORMS)):
            found.append((match.group(1), match.group(2)))
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def python_entries(requirements: list[tuple[str, str]]) -> list[dict]:
    entries = []
    for name, version in requirements:
        entry = {"ecosystem": "python", "name": name, "version": version, "raw": "", "texts": [], "note": ""}
        override = OVERRIDES.get(("python", name.lower()))
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            dist = None
        if dist is not None:
            meta = dist.metadata
            # License-Expression first (PEP 639), then the License field when it is short, then the classifiers.
            raw = meta.get("License-Expression") or ""
            field = " ".join((meta.get("License") or "").split())
            if not raw and field and len(field) < 60 and "\n" not in (meta.get("License") or ""):
                raw = field
            if not raw:
                raw = " OR ".join(c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")
                                  and "OSI Approved" in c and c.split("::")[-1].strip() != "OSI Approved")
            entry["raw"] = raw
            seen = set()
            for file in dist.files or []:
                if LICENSE_FILE.match(file.name) and file.name not in seen and "test" not in file.parts:
                    seen.add(file.name)
                    entry["texts"].append((file.name, _read(Path(str(dist.locate_file(file))))))
        if override:
            entry["raw"], entry["note"] = override
        elif dist is None:
            entry["raw"] = ""
            entry["note"] = "not installed on this machine and no override"
        entries.append(entry)
    return entries


def npm_entries(web: Path) -> list[dict]:
    lock = json.loads((web / "package-lock.json").read_text(encoding="utf-8"))
    entries = []
    for key, info in sorted(lock["packages"].items()):
        if not key or info.get("dev"):
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        entry = {"ecosystem": "npm", "name": name, "version": info.get("version", ""), "raw": "", "texts": [], "note": ""}
        folder = web / key
        package_json = folder / "package.json"
        raw: object = info.get("license", "")
        if package_json.is_file():
            data = json.loads(package_json.read_text(encoding="utf-8"))
            raw = data.get("license") or data.get("licenses") or raw
            for file in sorted(folder.iterdir()):
                if file.is_file() and LICENSE_FILE.match(file.name):
                    entry["texts"].append((file.name, _read(file)))
        else:
            entry["note"] = "optional build for another platform, not installed here; licence from the lock file, text not read"
        if isinstance(raw, dict):
            raw = raw.get("type", "")
        if isinstance(raw, list):
            raw = " OR ".join(x.get("type", "") if isinstance(x, dict) else str(x) for x in raw)
        entry["raw"] = str(raw)
        override = OVERRIDES.get(("npm", name))
        if override:
            entry["raw"], entry["note"] = override
        entries.append(entry)
    return entries


def resolve(entries: list[dict]) -> list[str]:
    """Fills `license` in place; returns one line per package whose licence is unknown."""
    problems = []
    for entry in entries:
        entry["license"], unknown = normalize(entry["raw"])
        if unknown:
            shown = entry["raw"] or "(no licence field)"
            problems.append(f"{entry['ecosystem']}: {entry['name']} {entry['version']}: {shown} [{', '.join(unknown)}]"
                            + (f" ({entry['note']})" if entry["note"] else ""))
    return problems


def render(entries: list[dict], native: str) -> str:
    out = ["THIRD-PARTY NOTICES", "", "DEIXIS is licensed AGPL-3.0-or-later (see LICENSE). It includes or depends on the software below. "
           "The Python and npm lists are written by scripts/licenses/build_notices.py from uv.lock and apps/web/package-lock.json "
           "(production dependencies only); the npm list includes build tools that the lock declares as dependencies, so it is a "
           "superset of what the web app ships. Native components are listed by hand after them.", "",
           "Contents", "--------"]
    for entry in entries:
        out.append(f"{entry['ecosystem']:6} {entry['name']} {entry['version']}  {entry['license']}")
    out += ["", "", "Licence texts", "============="]
    for entry in entries:
        out += ["", f"{entry['name']} {entry['version']} ({entry['ecosystem']}) - {entry['license']}", "-" * 40]
        if entry["note"]:
            out.append(f"Note: {entry['note']}")
        for filename, text in entry["texts"]:
            out += [f"[{filename}]", text, ""]
        if not entry["texts"] and not entry["note"]:
            out.append("The package ships no licence file; the licence above is from its metadata.")
    out += ["", "", native.strip(), ""]
    return "\n".join(out)


def build(web: Path | None = None) -> tuple[str, list[str]]:
    web = web or REPO / "apps" / "web"
    entries = python_entries(python_requirements()) + npm_entries(web)
    problems = resolve(entries)
    entries.sort(key=lambda e: (e["ecosystem"] != "python", e["name"].lower(), e["version"]))
    return render(entries, NATIVE.read_text(encoding="utf-8")), problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=REPO / "THIRD_PARTY_NOTICES")
    parser.add_argument("--check", action="store_true", help="scan only; write nothing")
    args = parser.parse_args(argv)
    if not (REPO / "apps" / "web" / "node_modules").is_dir():
        print("apps/web/node_modules is missing; run `npm ci` in apps/web first.", file=sys.stderr)
        return 1
    text, problems = build()
    if problems:
        print("Unknown licences; read each licence and add it to OVERRIDES (with the reason) or to KNOWN:", file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        return 1
    if not args.check:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
