"""Equation reading with Marker, an optional local component (D52).

Marker (GPL-3.0 code, modified OpenRAIL-M model weights) lives in its own Python environment under the data directory,
`tools/marker`, with its models in `tools/marker-models`; DEIXIS never imports it. `install_runtime` creates that
environment with uv. `MathReader` keeps one long-lived `marker_runner.py` process, sends it one PDF at a time and shuts
it down when idle. Only pages that look mathematical (`math_pages`) or carry a table caption (`table_pages`, D54) are read; their Markdown, with math as `$...$` and
`$$...$$` LaTeX, replaces the text-layer page text, and other pages keep it.

Measured on one M1 Pro with another process using a CPU core (2026-09-16): 9.2 s to load the models, then 10 pages in
332 s and 9 pages in 268 s when every page was read. On 50 display equations from 3 papers Marker was exact on 48,
minor on 1 and wrong on 1 (a subscript X_I read as X_T), so a read equation can be wrong without looking wrong.

`check_equations` compares each display equation's letters and digits with the PDF's text layer inside the box Marker
found it in; an equation using a letter or digit the text there does not have is marked to check against the page. On
the same 3 papers (2 pages each, 60 display equations, 2026-09-16) it marked the X_I/X_T error and no other equation,
after its LaTeX cleanup was fitted to those pages. On 2 pages each of 4 other stored papers (29 display equations) it
marked 3: two real misreadings (r_c read as r_s, C_n as C_r, confirmed on 400-dpi crops) and one false alarm (∆ U+2206
against Δ), which the character table now treats as the same letter. Whether the 27 unmarked equations are all correct
was not checked. It does not see an error that only rearranges or drops symbols, checks no inline math, and cannot check
a page without a text layer.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

MARKER_PACKAGE = "marker-pdf==1.10.2"
PYTHON_VERSION = "3.12"
RUNNER = Path(__file__).with_name("marker_runner.py")
IDLE_SECONDS = 600  # the models hold several GB of memory; an idle reader is stopped
READY_TIMEOUT_SECONDS = 600  # the first start downloads about 3.3 GB of models
SECONDS_PER_PAGE_LIMIT = 300

# Fonts that set mathematics (TeX Computer Modern math and AMS fonts, MathTime, STIX/Cambria/Latin Modern math, Symbol)
MATH_FONT = re.compile(r"CMMI|CMSY|CMEX|CMBSY|MSBM|MSAM|EUFM|EUSM|RSFS|Symbol|MTMI|MTSY|MTEX|Math|Euclid", re.I)
MATH_SYMBOL = re.compile(r"[∑∏∫√≤≥∈∉∀∃∂∇±×÷≠≈∞⊂⊆∪∩→⇒⇔αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ]")
# A page is read when it has this many characters in math fonts or this many math symbols. On two stored papers every
# page where Marker found a display equation scored at least 94 math-font characters or 13 symbols (2026-09-16).
MATH_FONT_CHARS = 60
MATH_SYMBOLS = 12
# A table caption opening a line: "TABLE 1 | …" (Frontiers), "TABLE I" (IEEE), "Table 2. …" (Elsevier, Springer). A sentence
# that starts with "Table 1 shows" does not match. Marker writes the table as a Markdown table (D54).
TABLE_CAPTION = re.compile(r"^(?:TABLE|Table)\s+(?:[IVXL]+|[A-Z]?\d{1,3})\s*(?:$|[.:|—–-])", re.M)

# Appended to the text layer's extraction version. v2 also reads pages with a table caption and keeps Marker's tables as
# one-line Markdown rows (D54).
MATH_VERSION = f"marker-{MARKER_PACKAGE.split('==')[1]}-math-v2"


def target_version(base_version: str) -> str:
    return f"{base_version}+{MATH_VERSION}"


@dataclass
class Reading:
    pages: dict[int, str]  # 0-based page index -> cleaned text
    equations: dict[int, list[dict]] = field(default_factory=dict)  # 0-based page index -> [{"bbox", "latex"}]


GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
         "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
         "varpi": "π", "rho": "ρ", "varrho": "ρ", "sigma": "σ", "varsigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
         "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
         "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω", "ell": "ℓ"}
SAME_CHARACTER = {"µ": "μ", "∆": "Δ", "ǫ": "ε", "ϵ": "ε", "ϑ": "θ", "ϕ": "φ", "ϱ": "ρ", "ϖ": "π"}


def _character(c: str) -> str:
    c = unicodedata.normalize("NFKC", c)
    return SAME_CHARACTER.get(c, c)


def _letters(text: str) -> Counter:
    return Counter(c for c in map(_character, text) if c.isalnum())


def latex_letters(latex: str) -> Counter:
    """The letters and digits a LaTeX expression prints: command names, environment names and \\tag numbers removed,
    Greek commands turned into their letters."""
    latex = re.sub(r"\\(begin|end)\{[^}]*\}|\\tag\*?\{[^}]*\}|\\operatorname\*?", " ", latex)
    latex = re.sub(r"\\([A-Za-z]+)", lambda m: GREEK.get(m.group(1), " "), latex)
    return _letters(latex)


def check_equations(path: Path, equations: dict[int, list[dict]]) -> list[dict]:
    """Display equations whose LaTeX has a letter or digit that the PDF's text inside the equation's box does not have,
    as {"page": 1-based, "latex": ...}. Pages without text in the box are not checked."""
    marked = []
    with pymupdf.open(path, filetype="pdf") as doc:
        for index, found in sorted(equations.items()):
            if not 0 <= index < doc.page_count:
                continue
            words = doc[index].get_text("words")
            for equation in found:
                box = pymupdf.Rect(equation["bbox"])
                # A word counts when at least half of it lies in the box.
                inside = " ".join(w[4] for w in words if (pymupdf.Rect(w[:4]) & box).get_area() >= 0.5 * pymupdf.Rect(w[:4]).get_area() > 0)
                if inside.strip() and latex_letters(equation["latex"]) - _letters(inside):
                    marked.append({"page": index + 1, "latex": equation["latex"]})
    return marked


def merge(extraction, pages: dict[int, str], selected: list[int], unchecked: list[dict] | None = None):
    """A new extraction: pages Marker read (0-based keys) replace the text layer's text; every other page is unchanged."""
    from dataclasses import replace

    from deixis.documents.pdf import PageText

    by_page = {page.physical_page: page for page in extraction.pages}
    for index, text in pages.items():
        if text.strip():
            old = by_page.get(index + 1)
            by_page[index + 1] = PageText(index + 1, old.printed_label if old else None, text, "marker")
    merged = [by_page[number] for number in sorted(by_page)]
    status = extraction.status if extraction.status != "no_text" or not merged else "partial"
    math = {"engine": "marker", "version": MARKER_PACKAGE.split("==")[1], "selected_pages": [i + 1 for i in selected],
            "pages_with_text": sorted(i + 1 for i, text in pages.items() if text.strip()),
            # Display equations that do not match the PDF's text layer and should be checked against the page.
            "equations_to_check": unchecked or []}
    return replace(extraction, status=status, pages=merged, math=math,
                   extraction_version=target_version(extraction.extraction_version))


class MathReaderUnavailable(Exception):
    """The Marker environment is not installed, or its process could not start."""


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @property
    def env(self) -> Path:
        return self.root / "marker"

    @property
    def models(self) -> Path:
        return self.root / "marker-models"

    @property
    def python(self) -> Path:
        return self.env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    def installed(self) -> bool:
        return self.python.exists()


def runtime_paths(data_dir: Path) -> RuntimePaths:
    return RuntimePaths(data_dir / "tools")


def install_runtime(paths: RuntimePaths) -> None:
    """Create the Marker environment with uv; models download on the first read. Raises on failure."""
    uv = shutil.which("uv")
    if uv is None:
        raise MathReaderUnavailable("uv is not installed; see https://docs.astral.sh/uv/")
    paths.root.mkdir(parents=True, exist_ok=True)
    subprocess.run([uv, "venv", "--python", PYTHON_VERSION, str(paths.env)], check=True)
    subprocess.run([uv, "pip", "install", "--python", str(paths.python), MARKER_PACKAGE], check=True)


def remove_runtime(paths: RuntimePaths) -> None:
    shutil.rmtree(paths.env, ignore_errors=True)
    shutil.rmtree(paths.models, ignore_errors=True)


def math_pages(path: Path) -> list[int]:
    """0-based indices of pages set with enough mathematics to be worth reading with Marker."""
    found = []
    with pymupdf.open(path, filetype="pdf") as doc:
        for index, page in enumerate(doc):
            font_chars = symbols = 0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        text = span["text"].strip()
                        font_chars += len(text) if MATH_FONT.search(span["font"]) else 0
                        symbols += len(MATH_SYMBOL.findall(text))
            if font_chars >= MATH_FONT_CHARS or symbols >= MATH_SYMBOLS:
                found.append(index)
    return found


def table_pages(path: Path) -> list[int]:
    """0-based indices of pages with a table caption in their text layer."""
    with pymupdf.open(path, filetype="pdf") as doc:
        return [index for index, page in enumerate(doc) if TABLE_CAPTION.search(page.get_text())]


def _table_row(line: str) -> str:
    """A Markdown table row on one line with its cell padding removed; a separator row becomes |---|."""
    cells = [re.sub(r"\s*<br\s*/?>\s*", " ", cell).strip() for cell in line.strip().strip("|").split("|")]
    if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
        cells = ["---"] * len(cells)
    return "| " + " | ".join(cells) + " |"


def clean_markdown(markdown: str) -> str:
    """Marker Markdown as passage text: math and paragraphs kept, layout markup removed."""
    text = re.sub(r"<span id=\"[^\"]*\"></span>", "", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # image references; images are not extracted
    text = re.sub(r"<sup>(.*?)</sup>", r"$^{\1}$", text)
    text = re.sub(r"<sub>(.*?)</sub>", r"$_{\1}$", text)
    text = re.sub(r"^\|.*\|[ \t]*$", lambda m: _table_row(m.group(0)), text, flags=re.M)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)  # headings become plain paragraphs, as in the text layer
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = html.unescape(re.sub(r"<br\s*/?>", "\n", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class MathReader:
    """One Marker process shared by every caller; requests are served one at a time."""

    def __init__(self, paths: RuntimePaths, idle_seconds: float = IDLE_SECONDS):
        self.paths, self.idle_seconds = paths, idle_seconds
        self.process: asyncio.subprocess.Process | None = None
        self.marker_version: str | None = None
        self.lock = asyncio.Lock()
        self._idle: asyncio.TimerHandle | None = None
        self._requests = 0

    def available(self) -> bool:
        return self.paths.installed()

    async def _start(self) -> None:
        if not self.available():
            raise MathReaderUnavailable("the equation reader (Marker) is not installed")
        env = {**os.environ, "MODEL_CACHE_DIR": str(self.paths.models), "PYTHONUNBUFFERED": "1"}
        if sys.platform == "darwin":
            env.setdefault("TORCH_DEVICE", "mps")
        self.process = await asyncio.create_subprocess_exec(
            str(self.paths.python), str(RUNNER), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env, limit=64 * 1024 * 1024,
        )
        try:
            ready = json.loads(await asyncio.wait_for(self.process.stdout.readline(), READY_TIMEOUT_SECONDS))
        except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
            await self.close()
            raise MathReaderUnavailable("the equation reader did not start") from exc
        self.marker_version = ready.get("marker_version")

    async def read(self, path: Path, pages: list[int]) -> Reading:
        """Marker Markdown for the given 0-based pages, cleaned for passages, with the display equations Marker found.
        Raises MathReaderUnavailable or RuntimeError."""
        if not pages:
            return Reading({})
        async with self.lock:
            if self._idle:
                self._idle.cancel()
            if self.process is None or self.process.returncode is not None:
                await self._start()
            self._requests += 1
            request = {"id": self._requests, "path": str(path), "pages": pages}
            self.process.stdin.write((json.dumps(request) + "\n").encode())
            await self.process.stdin.drain()
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), SECONDS_PER_PAGE_LIMIT * len(pages))
            except asyncio.TimeoutError:
                await self.close()
                raise RuntimeError("the equation reader timed out") from None
            if not line:
                await self.close()
                raise RuntimeError("the equation reader stopped")
            reply = json.loads(line)
            self._idle = asyncio.get_running_loop().call_later(self.idle_seconds, lambda: asyncio.ensure_future(self.close()))
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return Reading({int(index): clean_markdown(text) for index, text in reply["pages"].items()},
                       {int(index): found for index, found in reply.get("equations", {}).items()})

    @property
    def version(self) -> str:
        return f"marker-{self.marker_version or MARKER_PACKAGE.split('==')[1]}"

    async def close(self) -> None:
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except asyncio.TimeoutError:
                process.kill()
