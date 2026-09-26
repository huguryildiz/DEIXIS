"""Equations from the authors' arXiv LaTeX source (slice 22, D104).

Only with `DEIXIS_ARXIV_SOURCE=auto`, only on POSIX and only while the equation reader (Marker) is neither installed nor
installing (D3): a PDF that is an arXiv version, attached to a record naming the same preprint version, gets that version's
source from `https://arxiv.org/e-print/<id>v<N>`. The archive is read in memory in a bounded subprocess, its macros are
expanded, and each numbered display equation is matched to its number on the PDF page by letters (decision 4). A match
that passes the rule replaces the page's garbled text-layer lines with the authors' LaTeX as `$$…$$ (n)`; everything else
on the page stays the PDF's own text. "Passes the rule" is an operational rule chosen on one library after its image
sample was seen, not an accuracy guarantee (D104 Limits). Nothing compiles the source; nothing checks that it produced
this PDF.

Version (decision 1): the file's own version comes from `retrieved_from` and the page-1/2 margin stamp; the record must
carry the same arXiv id and label the same preprint version. The source of another version is never used.

Fetch (decision 2): at least 3 s between the server-side arrivals of any two of this route's HTTP requests to arxiv.org,
redirect hops included, across every process using the same data directory (an `fcntl.flock` held for the whole fetch
and a durable start stamp written before each request). Other data directories and DEIXIS's arXiv search are outside this
count. At most 3 normal fetch attempts per version and one repair attempt for a corrupted stored file.

Archive (decision 3): untrusted data. Nothing is extracted to disk, member names are never used as paths, and the reading
runs in its own process with time, memory and output limits.
"""

from __future__ import annotations

import asyncio
import bisect
import gzip
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import tarfile
import time
import weakref
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SOURCE_VERSION = "arxiv-latex-v1"
ENGINE = "arxiv_source"

# Matching (decision 4). Chosen on one library after its image sample was seen; slice 24 looks at them again.
MIN_RECALL = 0.90
MIN_MARGIN = 0.20
PROSE_WORDS = 3
MAX_REGION_LINES = 12
ORDER_SCORE_OFFSET = 0.5  # the assignment maximises the sum of F1 minus this
ABSORB_OVERLAP = 0.5  # a line before the region joins it when it overlaps the region's box by this share of its height

# The archive (decision 3).
MAX_UNPACKED_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 1000
MAX_TEXT_MEMBER_BYTES = 5 * 1024 * 1024
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_INCLUDE_DEPTH = 5
MAX_MACRO_DEPTH = 8
MAX_EXPANDER_CALLS = 20_000
MAX_GROUP_CHARS = 4000
CHILD_TIMEOUT_SECONDS = 60
MAX_CHILD_STDOUT = 5 * 1024 * 1024
OUTPUT_TAIL_CHARS = 4000
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
TEXT_SUFFIXES = (".tex", ".sty", ".def")

# Fetching (decision 2).
SOURCE_MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=10)
RATE_SECONDS = 3.0
FETCH_DEADLINE_SECONDS = 30.0
STALE_START_WAIT = FETCH_DEADLINE_SECONDS + RATE_SECONDS  # a start stamp with no end: the request may have run to its deadline
LOCK_BUDGET_SECONDS = 120.0
LOCK_POLL_SECONDS = 0.1
PART_MAX_AGE_SECONDS = 3600
E_PRINT_URL = "https://arxiv.org/e-print/{key}"
MEDIA_TYPES = ("application/gzip", "application/pdf")

PARAMS = {"min_recall": MIN_RECALL, "min_margin": MIN_MARGIN, "prose_words": PROSE_WORDS, "max_region_lines": MAX_REGION_LINES,
          "order_score_offset": ORDER_SCORE_OFFSET, "absorb_overlap": ABSORB_OVERLAP, "max_group_chars": MAX_GROUP_CHARS,
          "max_macro_depth": MAX_MACRO_DEPTH, "max_expander_calls": MAX_EXPANDER_CALLS}

ELIGIBILITY_REFUSALS = ("no_version", "version_conflict", "record_identity_unknown", "record_identity_conflict",
                        "record_version_conflict")

# Clock and sleep, replaced by tests; every wait and every stamp of this module reads them.
clock: Callable[[], float] = time.time
sleep = asyncio.sleep


def posix_available() -> bool:
    """The route needs `fcntl` (file locks); on Windows it is off whatever the flag says (as slice 21)."""
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return False
    return True


def iso(seconds: float | None = None) -> str:
    return datetime.fromtimestamp(clock() if seconds is None else seconds, tz=timezone.utc).isoformat(timespec="milliseconds")


def seconds_of(value: str | None) -> float | None:
    return datetime.fromisoformat(value).timestamp() if value else None


# ---- version identity (decision 1) -------------------------------------------------------------------------------------
ARXIV_ID = r"(\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[A-Z]{2})?/\d{7})"
URL_VERSION = re.compile(r"^https?://(?:www\.)?arxiv\.org/pdf/" + ARXIV_ID + r"v(\d+)(?:\.pdf)?/?$")
STAMP = re.compile(r"arXiv:" + ARXIV_ID + r"v(\d+)\s*\[[^\]\n]{1,40}\]")
RECORD_ID = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)" + ARXIV_ID, re.I)
LABEL_VERSION = re.compile(r"^arXiv v(\d+)$")


def make_key(arxiv_id: str, version: int | str) -> str:
    return f"{arxiv_id}v{int(version)}"


def split_key(key: str) -> tuple[str, int]:
    arxiv_id, version = re.fullmatch(r"(.+)v(\d+)", key).groups()
    return arxiv_id, int(version)


def file_name(key: str) -> str:
    """A stored file's name: an old-style identifier's slash is not a path separator."""
    return key.replace("/", "_")


def url_key(retrieved_from: str | None) -> str | None:
    m = URL_VERSION.match(retrieved_from or "")
    return make_key(m.group(1), m.group(2)) if m else None


def stamp_key(path: Path) -> str | None:
    """The version arXiv stamps along the margin of page 1 or 2 (a rotated line, so read from the plain page text)."""
    import pymupdf

    with pymupdf.open(path, filetype="pdf") as doc:
        for index in range(min(2, doc.page_count)):
            if m := STAMP.search(doc[index].get_text()):
                return make_key(m.group(1), m.group(2))
    return None


def record_ids(record: dict[str, Any]) -> set[str]:
    return {m.group(1).lower() for field in ("doi", "landing_url", "oa_pdf_url") if record.get(field)
            for m in RECORD_ID.finditer(record[field])}


def record_eligibility(key: str, record: dict[str, Any]) -> str:
    """Rows 3–7 of decision 1's table for a file whose own version is `key`."""
    arxiv_id, version = split_key(key)
    ids = record_ids(record)
    if len(ids) > 1:
        return "record_identity_conflict"
    if not ids:
        return "record_identity_unknown"
    if ids != {arxiv_id.lower()}:
        return "record_version_conflict"
    label = record.get("version_label") or ""
    if (m := LABEL_VERSION.match(label)) and int(m.group(1)) == version:
        return "eligible"
    if label == "submittedVersion":
        return "eligible"
    return "record_version_conflict"


def eligibility(from_url: str | None, from_stamp: str | None, record: dict[str, Any]) -> dict[str, Any]:
    """Decision 1's table, first matching row: {eligibility, arxiv_key, version_from, record_label}."""
    label = record.get("version_label")
    if from_url and from_stamp and from_url != from_stamp:
        return {"eligibility": "version_conflict", "arxiv_key": None, "version_from": None, "record_label": label}
    if not (from_url or from_stamp):
        return {"eligibility": "no_version", "arxiv_key": None, "version_from": None, "record_label": label}
    key = from_url or from_stamp
    source = "both" if from_url and from_stamp else "url" if from_url else "stamp"
    return {"eligibility": record_eligibility(key, record), "arxiv_key": key, "version_from": source, "record_label": label}


def disposition_names(content_disposition: str | None, key: str) -> bool:
    """Whether the response's file name names this version (`arXiv-2005.00948v1.tar.gz`)."""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition or "", re.I)
    if not m:
        return False
    name = m.group(1).replace("/", "").replace("_", "")
    wanted = key.replace("/", "")
    return re.search(re.escape(wanted) + r"(?!\d)", name) is not None


# ---- the archive (decision 3) ------------------------------------------------------------------------------------------
@dataclass
class Archive:
    content: str  # tex, pdf_only, no_tex, too_large, unreadable
    files: dict[str, str]
    error: str | None = None


class _TooLarge(Exception):
    pass


def _gunzip(data: bytes) -> bytes:
    """The gzip stream unpacked through a counting reader; more than MAX_UNPACKED_BYTES is too large."""
    if data[:2] != b"\x1f\x8b":
        return data
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        while chunk := stream.read(1 << 20):
            out += chunk
            if len(out) > MAX_UNPACKED_BYTES:
                raise _TooLarge("unpacked archive over 64 MB")
    return bytes(out)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_archive(data: bytes) -> Archive:
    """The archive's text members in memory: regular files only (links, devices and FIFOs are skipped), names used only
    as keys to resolve `\\input`, never as paths."""
    if data[:5] == b"%PDF-":
        return Archive("pdf_only", {})
    try:
        raw = _gunzip(data)
    except _TooLarge as exc:
        return Archive("too_large", {}, str(exc))
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        return Archive("unreadable", {}, f"gzip: {type(exc).__name__}")
    if raw[:5] == b"%PDF-":
        return Archive("pdf_only", {})
    files: dict[str, str] = {}
    try:
        tar = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except tarfile.TarError:
        tar = None
    if tar is None:
        text = _decode(raw)
        if not re.search(r"\\documentclass|\\documentstyle|\\begin\{document\}", text):
            return Archive("no_tex", {})
        if len(raw) > MAX_TEXT_MEMBER_BYTES:
            return Archive("too_large", {}, "text over 5 MB")
        return Archive("tex", {"main.tex": text})
    total, members = 0, 0
    try:
        with tar:
            while (member := tar.next()) is not None:
                members += 1
                if members > MAX_MEMBERS:
                    return Archive("too_large", {}, "more than 1000 members")
                name = posixpath.normpath(member.name)
                if not member.isreg() or not name.lower().endswith(TEXT_SUFFIXES) or name.startswith("/") or ".." in name.split("/"):
                    continue
                if member.size > MAX_TEXT_MEMBER_BYTES:
                    return Archive("too_large", {}, "a text member over 5 MB")
                total += member.size
                if total > MAX_TEXT_BYTES:
                    return Archive("too_large", {}, "text members over 5 MB")
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                files[name] = _decode(stream.read(member.size))
    except (tarfile.TarError, OSError, EOFError) as exc:
        return Archive("unreadable", {}, f"tar: {type(exc).__name__}")
    if not any(name.lower().endswith(".tex") for name in files):
        return Archive("no_tex", {})
    return Archive("tex", files)


VERBATIM_ENVS = ("verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment")
STRIP_TOKEN = re.compile(r"\\verb\*?([^\sA-Za-z*])([^\n]*?)\1|\\begin\{(" + "|".join(re.escape(e) for e in VERBATIM_ENVS)
                         + r")\}|(\\verb(?![A-Za-z]))|\\.|%", re.S)


def strip_comments(tex: str, problems: list[str] | None = None) -> str:
    """`%` to the end of the line, unless escaped (`\\%`; `\\\\%` is a line break followed by a comment), and the content
    of `\\verb|…|`, `\\verb*|…|` and verbatim-like environments blanked with spaces (newlines kept): TeX reads none of it
    as commands or comments, so neither does anything after this. A `\\verb` not closed on its line or a verbatim
    environment never ended is added to `problems` when given (the macro scan then fails closed)."""
    out, i = [], 0
    for m in STRIP_TOKEN.finditer(tex):
        if m.start() < i:
            continue
        token = m.group(0)
        if m.group(1) is not None:  # \verb<d>…<d> on one line
            out.append(tex[i:m.start(2)] + " " * len(m.group(2)) + m.group(1))
            i = m.end()
        elif m.group(3) is not None:  # \begin{verbatim} … \end{verbatim}
            end = tex.find(f"\\end{{{m.group(3)}}}", m.end())
            if end < 0 and problems is not None:
                problems.append(f"unclosed {m.group(3)}")
            end = len(tex) if end < 0 else end
            out.append(tex[i:m.end()] + re.sub(r"[^\n]", " ", tex[m.end():end]))
            i = end
        elif m.group(4) is not None:  # \verb whose delimiter never closes on its line
            if problems is not None:
                problems.append("unclosed \\verb")
        elif token == "%":
            out.append(tex[i:m.start()])
            newline = tex.find("\n", m.end())
            i = len(tex) if newline < 0 else newline
        # a control word or symbol (`\\%`, `\\\\`): kept as it is
    out.append(tex[i:])
    return "".join(out)


INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]*)\}|\\input\s+([^\s{}\\]+)")
PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
LOADS = re.compile(INCLUDE.pattern + "|" + PACKAGE.pattern)
# A load counts as executed only at the top level of its file: outside every brace group (a macro body, an argument of
# \\AtBeginDocument or \\@ifpackageloaded) and every TeX conditional (\\iffalse, \\ifdefined, \\if@…, \\ifx … \\fi).
# Control words that start with "if" but take braced arguments and no \\fi are not conditionals; the name after \\newif
# is a definition. A file whose conditionals do not balance leaves every later load undetermined, and an undetermined
# load reads nothing: its macros stay undefined and a group using them fails the KaTeX gate.
LEVEL_TOKEN = re.compile(r"\\newif\s*\\[A-Za-z@]+|\\([A-Za-z@]+)|\\.|[{}]", re.S)
BRACED_IFS = {"iff", "ifthenelse", "ifdef", "ifndef", "ifundef", "ifdefmacro", "ifcsdef", "ifcsundef", "ifcsmacro", "ifstrequal",
              "ifstrempty", "iftoggle", "ifbool", "ifblank", "ifnumcomp", "ifdimcomp", "ifdefstring", "ifcsstring", "ifdefempty",
              "ifdefvoid", "ifcsempty", "ifcsvoid", "ifnumequal", "ifnumodd", "ifdimequal", "ifdefequal", "ifcsequal",
              "iffieldundef", "ifpackageloaded", "ifclassloaded"}


def top_level_positions(text: str) -> tuple[list[int], list[bool]]:
    """Token end positions and, after each, whether a load there runs: brace and conditional depth 0."""
    ends, top, brace, cond = [0], [True], 0, 0
    for m in LEVEL_TOKEN.finditer(text):
        token = m.group(0)
        if token == "{":
            brace += 1
        elif token == "}":
            brace = max(brace - 1, 0)
        elif (word := m.group(1)) is not None:
            if word == "fi":
                cond -= 1
            elif word.startswith("if") and word not in BRACED_IFS:
                cond += 1
        ends.append(m.end())
        top.append(brace == 0 and cond == 0)
    return ends, top


def executed(levels: tuple[list[int], list[bool]], position: int) -> bool:
    ends, top = levels
    return top[bisect.bisect_right(ends, position) - 1]


def flatten(files: dict[str, str]) -> tuple[str | None, list[str]]:
    """(main file's text with comments stripped, its inputs inlined to depth 5 and the archive's own packages inlined
    where `\\usepackage` / `\\RequirePackage` load them, the package files inlined) or (None, []). A package is inlined
    once, at its first load, so its definitions take effect in TeX's load order; a `.sty` the main file never loads is not
    read, and a `.def` counts only where an `\\input` reaches it."""
    stripped = {name: strip_comments(text) for name, text in files.items()}
    mains = [n for n, t in stripped.items() if n.lower().endswith(".tex") and "\\begin{document}" in t]
    if not mains:
        return None, []
    main = max(mains, key=lambda n: len(stripped[n]))
    loaded: list[str] = []

    def resolve(target: str, base: str, suffix: str) -> str | None:
        target = target.strip()
        for candidate in (target, target + suffix, posixpath.join(base, target), posixpath.join(base, target + suffix)):
            candidate = posixpath.normpath(candidate)
            if candidate in stripped:
                return candidate
        return None

    def inline(name: str, depth: int) -> str:
        levels = top_level_positions(stripped[name])

        def load(m: re.Match) -> str:  # inputs and packages in one pass, in the order TeX meets them
            if m.group(3) is None:
                if depth >= MAX_INCLUDE_DEPTH:
                    return ""
                found = resolve(m.group(1) or m.group(2), posixpath.dirname(name), ".tex")
                if found and not executed(levels, m.start()):
                    return ""  # an \\input inside a conditional or a brace group may never run: read nothing of it
                return inline(found, depth + 1) if found else ""
            if not executed(levels, m.start()):
                return m.group(0)  # a load inside a conditional or a brace group: not counted as run
            parts = []
            for item in m.group(3).split(","):
                found = resolve(item, posixpath.dirname(name), ".sty") if item.strip() else None
                if found is None or not found.lower().endswith(".sty"):
                    continue  # a package of the TeX distribution: nothing of it is read
                if found in loaded or depth >= MAX_INCLUDE_DEPTH:
                    continue
                loaded.append(found)
                parts.append(inline(found, depth + 1))
            return m.group(0) + "\n" + "\n".join(parts) if parts else m.group(0)
        return LOADS.sub(load, stripped[name])

    return inline(main, 0), loaded


def _braces(s: str, i: int) -> tuple[str, int]:
    """The contents of the brace group opening at s[i] and the index after it."""
    depth, j = 0, i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        depth += s[j] == "{"
        depth -= s[j] == "}"
        if depth == 0:
            return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


NAME = r"\\(?:[A-Za-z@]+|[^A-Za-z@\s{}])"  # a control word, or a control symbol such as \1
NEWCOMMAND = re.compile(r"\\(newcommand|renewcommand|providecommand)\*?\s*(?:\{\s*(" + NAME + r")\s*\}|(" + NAME + r"))"
                        r"\s*(?:\[(\d)\])?\s*(?:\[([^\]]*)\])?\s*(?=\{)")
DEF = re.compile(r"\\def\s*(" + NAME + r")((?:#\d)*)\s*(?=\{)")
OPERATOR = re.compile(r"\\DeclareMathOperator(\*?)\s*(?:\{\s*(" + NAME + r")\s*\}|(" + NAME + r"))\s*(?=\{)")


def definitions(tex: str) -> list[tuple[int, str, str, tuple[int, str | None, str]]]:
    """Every definition of the five forms in source order: (position, kind, name, (arguments, default of the optional
    first argument, body))."""
    found: list[tuple[int, str, str, tuple[int, str | None, str]]] = []

    def add(m: re.Match, kind: str, name: str, count: int, default: str | None, operator: str | None = None) -> None:
        body, end = _braces(tex, m.end())
        if tex[end - 1:end] != "}" or any(int(k) == 0 or int(k) > count for k in re.findall(r"(?<!#)#(\d)", body)):
            kind = "unreadable"  # a body never closed, or one naming a parameter it does not have: never trusted
        if operator is not None:
            body = f"\\operatorname{operator}{{{body}}}"
        found.append((m.start(), kind, name, (count, default, body)))
    for m in NEWCOMMAND.finditer(tex):
        add(m, m.group(1), m.group(2) or m.group(3), int(m.group(4) or 0), m.group(5))
    for m in DEF.finditer(tex):
        add(m, "def", m.group(1), len(m.group(2)) // 2, None)
    for m in OPERATOR.finditer(tex):
        add(m, "operator", m.group(2) or m.group(3), 0, None, m.group(1))
    return sorted(found, key=lambda item: item[0])


class Expander:
    """Macro expansion to depth 8 with at most 20,000 macro expansions per paper, each use of a macro counted. The group
    whose expansion passes that count is left out (`macro_limit`), and so is any later group that still needs an
    expansion once the count is spent; a group whose text passes 4 × 4,000 characters while it is being expanded is left
    out as `too_long`. Both are checked while the text is produced, so neither can run the child into its own limits."""

    CONTROL = re.compile(r"\\(?:[A-Za-z@]+|[^A-Za-z@])", re.S)  # TeX's tokens: `\\1` is `\\` then `1`, never `\1`

    def __init__(self, defined: dict[str, tuple[int, str | None, str]]):
        self.defined, self.calls, self.used = defined, 0, set()  # `used`: the macros expanded since it was last cleared
        self.unreadable = False  # a macro use whose arguments could not be read since it was last cleared

    def expand(self, s: str) -> tuple[str, str | None]:
        if not self.defined:
            return s, None
        for _ in range(MAX_MACRO_DEPTH):
            s, changed, limit = self._once(s)
            if limit or not changed:
                return s, limit
        return s, ("macro_limit" if any(m.group(0) in self.defined for m in self.CONTROL.finditer(s)) else None)

    def _once(self, s: str) -> tuple[str, bool, str | None]:
        out, i, changed, size = [], 0, False, 0
        for m in self.CONTROL.finditer(s):
            if m.start() < i or m.group(0) not in self.defined:
                continue
            self.calls += 1
            if self.calls > MAX_EXPANDER_CALLS:
                return s, changed, "macro_limit"
            self.used.add(m.group(0))
            count, default, body = self.defined[m.group(0)]
            j, args = m.end(), []
            for k in range(count):
                while j < len(s) and s[j].isspace():
                    j += 1
                if k == 0 and default is not None:
                    if j < len(s) and s[j] == "[":
                        end, depth, e = -1, 0, j + 1
                        while e < len(s):  # the `]` at brace depth 0, as TeX reads it
                            if s[e] == "\\":
                                e += 2
                                continue
                            depth += (s[e] == "{") - (s[e] == "}")
                            if s[e] == "]" and depth == 0:
                                end = e
                                break
                            e += 1
                        if end < 0:
                            self.unreadable, end = True, len(s)
                        if any(t in "{}" for t in re.findall(r"\\.|[{}]", s[j + 1:end], re.S)):  # `\\{` escaped, `\\\\{` not
                            self.unreadable = True  # braces in an optional argument: not read, the group is refused
                        args.append(s[j + 1:end])
                        j = end + 1
                    else:
                        args.append(default)
                    continue
                if j < len(s) and s[j] == "{":
                    start = j
                    arg, j = _braces(s, j)
                    self.unreadable = self.unreadable or s[j - 1] != "}" or j - 1 == start
                elif j < len(s) and s[j] == "\\" and (c := self.CONTROL.match(s, j)):
                    arg, j = c.group(0), c.end()
                elif j < len(s) and s[j] != "}":
                    arg, j = s[j], j + 1
                else:
                    arg, self.unreadable = "", True  # the group ends before the argument: TeX would take what follows
                args.append(arg)
            text = re.sub(r"#(\d)", lambda a: args[int(a.group(1)) - 1] if 0 < int(a.group(1)) <= len(args) else "", body)
            # TeX expands tokens, not strings: a body ending in a control word must not merge with a following letter.
            if re.search(r"\\[A-Za-z@]+$", text) and j < len(s) and s[j].isalpha():
                text += " "
            piece = s[i:m.start()] + text
            size += len(piece)
            if size + len(s) - j > 4 * MAX_GROUP_CHARS:
                return s, changed, "too_long"
            out.append(piece)
            i, changed = j, True
        out.append(s[i:])
        return "".join(out), changed, None


LINE_ENVS = {"align", "gather", "eqnarray", "alignat", "flalign"}
DISPLAY = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray|alignat|flalign|displaymath)(\*?)\}(.*?)\\end\{\1\*?\}"
                     r"|\\\[(.*?)\\\]|\$\$(.*?)\$\$", re.S)
NONUMBER = re.compile(r"\\(nonumber|notag)\b")
TAG = re.compile(r"\\tag\*?\{([^}]*)\}")
REFERENCE = re.compile(r"\\(ref|eqref|pageref|cite[a-z]*)\b")


def _split_lines(body: str) -> list[str]:
    """A line environment's rows: split at top-level `\\\\` only (not inside braces or a nested environment)."""
    parts, depth, env, start, i = [], 0, 0, 0, 0
    while i < len(body):
        if body.startswith("\\begin{", i):
            env += 1
        elif body.startswith("\\end{", i):
            env -= 1
        if body.startswith("\\\\", i) and depth == 0 and env == 0:
            parts.append(body[start:i])
            i += 2
            start = i
            continue
        if body[i] == "\\":
            i += 2
            continue
        depth += body[i] == "{"
        depth -= body[i] == "}"
        i += 1
    parts.append(body[start:])
    return [p for p in parts if p.strip()]


def groups(tex: str) -> list[dict[str, Any]]:
    """Display equation groups in source order. `equation` and `multline` are one group; in a line environment a number
    covers the rows after the environment's previous numbered row. Starred environments, `\\[…\\]`, `$$…$$` and
    `\\nonumber`/`\\notag` rows are unnumbered; `\\tag{…}` numbers. A numbered group whose environment goes on with
    unnumbered rows after it is marked `continues` (its number is not on the equation's last row)."""
    offset = max(tex.find("\\begin{document}"), 0)
    body = tex[offset:]
    out: list[dict[str, Any]] = []
    for env_id, m in enumerate(DISPLAY.finditer(body)):
        env, star = m.group(1), m.group(2) == "*" or m.group(1) == "displaymath"
        text = m.group(3) if env else (m.group(4) if m.group(4) is not None else m.group(5))
        rows = _split_lines(text) if env in LINE_ENVS else [text]
        pending: list[str] = []
        for position, row in enumerate(rows):
            tag = TAG.search(row)
            numbered = (bool(env) and not star and not NONUMBER.search(row)) or bool(tag)
            if env == "alignat" and position == 0:
                row = re.sub(r"^\s*\{\d+\}", "", row)  # alignat's column count
            pending.append(row)
            if numbered or env not in LINE_ENVS:
                out.append({"raw": " \\\\ ".join(pending), "numbered": numbered, "tag": tag.group(1) if tag else None,
                            "env": env or "display", "env_id": env_id, "continues": False})
                pending = []
        if pending:
            for group in reversed(out):
                if group["env_id"] != env_id:
                    break
                if group["numbered"]:
                    group["continues"] = True
                    break
            out.append({"raw": " \\\\ ".join(pending), "numbered": False, "tag": None, "env": env or "display",
                        "env_id": env_id, "continues": False})
    for index, group in enumerate(out):
        group["index"] = index
    return out


LAYOUT = re.compile(r"\\label\s*\{[^}]*\}|\\(?:hspace|vspace)\*?\s*\{[^}]*\}|\\setcounter\s*\{[^}]*\}\s*\{[^}]*\}"
                    r"|\\tag\*?\{[^}]*\}|\\(?:nonumber|notag|allowbreak)\b|\\displaybreak(?:\[\d\])?")
# The rewrite table (seven rules) for package commands KaTeX lacks, measured on the plan's library (number 6).
REWRITES = (
    (re.compile(r"\\mbox\b"), r"\\text"),
    (re.compile(r"\\mathds\b"), r"\\mathbb"),
    (re.compile(r"\\buildrel\b"), r"\\overset"),
    (re.compile(r"\\(?:mathlarger|mathsmaller|lefteqn|sl|em|hfill|hfil|displaybreak)\b"), ""),
    (re.compile(r"\\iffalse\b[\s\S]*?\\fi\b"), ""),
    (re.compile(r"\\cite[a-z]*\s*(?:\[[^\]]*\])?\s*\{[^}]*\}"), ""),
    (re.compile(r"\\ding\s*\{[^}]*\}"), ""),
)


def clean(latex: str) -> str:
    """Layout commands removed, the rewrite table applied, whitespace collapsed; `&` or `\\\\` wrapped in `aligned`."""
    latex = LAYOUT.sub(" ", latex)
    for pattern, replacement in REWRITES:
        latex = pattern.sub(replacement, latex)
    latex = re.sub(r"\s+", " ", latex).strip()
    if (len(latex) - len(latex.rstrip("\\"))) % 2:  # a trailing control space (`\` then a newline) left a lone backslash
        latex = latex[:-1].rstrip()
    if "&" in latex.replace("\\&", "") or "\\\\" in latex:
        latex = f"\\begin{{aligned}}{latex}\\end{{aligned}}"
    return latex


_katex: dict[str, set[str]] | None = None


def katex_known() -> dict[str, set[str]]:
    """Commands and environments of the web app's KaTeX (`scripts/katex_commands.mjs` writes the file)."""
    global _katex
    if _katex is None:
        data = json.loads(Path(__file__).with_name("katex_commands.json").read_text(encoding="utf-8"))
        _katex = {"commands": set(data["commands"]), "environments": set(data["environments"]), "symbols": set(data["symbols"]),
                  "version": {data["katex_version"]}}
    return _katex


def katex_unknown(latex: str) -> list[str]:
    """Control words, control symbols (`\\1`) and environments the web app's KaTeX does not know."""
    known = katex_known()
    names = [f"\\{c}" for c in re.findall(r"\\([A-Za-z]+|[^A-Za-z\s])", latex)
             if c not in (known["commands"] if c[0].isalpha() else known["symbols"])]
    names += [f"{{{e}}}" for e in re.findall(r"\\(?:begin|end)\{([^}]*)\}", latex) if e not in known["environments"]]
    return sorted(set(names))


# Any control word that can (re)define the name after it. Only `\\newcommand`, `\\renewcommand`, `\\providecommand`,
# `\\def` with undelimited parameters and `\\DeclareMathOperator` are parsed (`definitions`); every other one makes its
# target unsafe. Words ending in "def" or "let", containing "command" / "Command" / "cmd", or starting with "Declare" are
# all counted, so a test like `\\ifdef\\x` also marks `\\x`: that can only drop a placement.
DEFINER = re.compile(r"\\([A-Za-z@]+)\*?")
PARSED_DEFINERS = {"newcommand", "renewcommand", "providecommand", "def", "DeclareMathOperator"}
CS_DEFINERS = {"csdef", "csgdef", "csedef", "csxdef", "cslet", "csletcs", "csundef", "@namedef", "@namelet"}
LET_DEFINERS = {"let", "futurelet", "glet", "letcs", "cslet", "csletcs", "@namelet"}
LITERAL_NAME = re.compile(r"\s*([^\\#{}]*?)\s*$")  # a name built from plain characters only: no \\, #, { or }
LETTER_RUN = re.compile(r"[A-Za-z@]+")
TARGET_PREFIX = re.compile(r"(?:\s|\{|\\expandafter(?![A-Za-z@]))*")


def _is_definer(word: str) -> bool:
    return (word.endswith("def") or word in LET_DEFINERS or "command" in word or "Command" in word or "cmd" in word
            or word.startswith("Declare") or word in CS_DEFINERS)


def _name_of(literal: str) -> str | None:
    """The control word or symbol a plain `\\csname` / `\\@namedef` name can be written as, if any (`ul9@Scale` has none)."""
    if re.fullmatch(r"[A-Za-z@]+", literal) or len(literal) == 1:
        return "\\" + literal
    return None


# LaTeX3 code can define any name with its own definers (`\\cs_set:Npn`, `\\tl_set:Nn \\alpha …`): a source that turns
# the syntax on or uses one is unbounded rather than parsed.
EXPL3 = re.compile(r"ExplSyntaxOn|ProvidesExpl(?:Package|Class|File)|\\cs_(?:new|set|gset|generate)")


def _built(content: str, unsafe: set[str], prefixes: set[str]) -> bool:
    """Record the names a `\\csname` / `\\@namedef` argument can build; False when they cannot be bounded. Plain
    characters (no `\\`, `#` or brace) are one name. Plain letters followed by a parameter (`keycolor#1`) are a prefix
    every built name starts with. Anything else holding a control sequence or `#` is computed (`\\pick` may expand to
    any name) and cannot be bounded."""
    literal = LITERAL_NAME.match(content)
    if literal:
        unsafe.add(_name_of(literal.group(1)) or "")
        return True
    prefix = re.match(r"\s*([A-Za-z@]+)#\d", content)
    if prefix is None:
        return False
    prefixes.add(prefix.group(1))
    return True


# Constructs that build or test a name from characters: `\\csname … \\endcsname` (a bare one makes an undefined name
# `\\relax`), `\\ifcsname`, `\\@ifundefined{…}`, `\\@nameuse{…}`, `\\@namedef{…}`, `\\@ifdefinable\\x` and etoolbox's `\\cs…`
# / `\\ifcs…` forms. The name they give is unsafe wherever they stand; one they compute is bounded by its prefix or leaves
# the source unbounded.
CSNAME = re.compile(r"\\(?:if)?csname(?![A-Za-z@])")
ETOOLBOX_CS = ("csdef", "csgdef", "csedef", "csxdef", "protected@csdef", "protected@csgdef", "protected@csedef",
               "protected@csxdef", "cslet", "csletcs", "csundef", "csshow", "csuse", "csappto", "cspreto", "cseappto",
               "csepreto", "csgappto", "csgpreto", "csxappto", "csxpreto", "ifcsdef", "ifcsundef", "ifcsmacro", "ifcsparam",
               "ifcsprefix", "ifcsprotected", "ifcsltxprotect", "ifcsempty", "ifcsvoid", "ifcsequal", "ifcsstring",
               "ifcsstrequal", "ifcsbool", "ifcstoggle", "letcs", "csnumdef", "csgnumdef")
NAME_BUILDER = re.compile(r"\\(" + "|".join(ETOOLBOX_CS) + r"|@ifundefined|@nameuse|@namedef|@namelet|@ifdefinable)(?![A-Za-z@])")
TWO_NAME_BUILDERS = {"letcs", "csletcs", "@namelet"}
ARGUMENT = re.compile(r"\s*(?:\{([^{}]*)\}|(\\(?:[A-Za-z@]+|[^A-Za-z@])))")


def _named(text: str, unsafe: set[str], prefixes: set[str]) -> bool:
    """Mark every name a name-building construct in `text` gives (`CSNAME`, `NAME_BUILDER`); False when one is computed
    and cannot be bounded."""
    # every \\csname / \\ifcsname needs its own \\endcsname: a missing or a stray one leaves the names unknown
    bounded = len(CSNAME.findall(text)) == len(re.findall(r"\\endcsname(?![A-Za-z@])", text))
    for m in CSNAME.finditer(text):
        end = text.find("\\endcsname", m.end(), m.end() + 400)
        bounded = end >= 0 and _built(text[m.end():end], unsafe, prefixes) and bounded
    for m in NAME_BUILDER.finditer(text):
        i = m.end()
        for k in range(2 if m.group(1) in TWO_NAME_BUILDERS else 1):
            arg = ARGUMENT.match(text, i)
            if arg is None:  # no readable name argument (nested braces, `\\@nameuse{\\pick{foo}}`, or none at all)
                bounded = False
                break
            i = arg.end()
            if arg.group(2) and (m.group(1) == "@ifdefinable" or (m.group(1) == "letcs" and k == 0)):
                unsafe.add(arg.group(2))  # an argument that is a control sequence by design (`\\@ifdefinable\\x`, `\\letcs\\x`)
            elif arg.group(2):
                bounded = False  # `\\@nameuse\\pick`: the name is whatever \\pick expands to
            else:
                bounded = _built(arg.group(1), unsafe, prefixes) and bounded
    return bounded


_kernel: set[str] | None = None


def known_names() -> set[str]:
    """Names a paper may use without defining them: the web app's KaTeX commands and symbols, and what the LaTeX kernel,
    article.cls and the AMS packages define (`latex_kernel_names.json`, written by `scripts/latex_kernel_names.py`)."""
    global _kernel
    if _kernel is None:
        data = json.loads(Path(__file__).with_name("latex_kernel_names.json").read_text(encoding="utf-8"))
        known = katex_known()
        _kernel = {"\\" + n for n in set(data["names"]) | known["commands"] | known["symbols"]}
    return _kernel


def unsafe_macros(files: dict[str, str], tex: str) -> tuple[set[str], set[str], bool]:
    """(unsafe names, unsafe name prefixes, unbounded) for the source. Position plays no part: every text file of the
    archive (loaded or not) is scanned whole, inside conditionals, groups and macro bodies or not.

    A name is safe only when it is not a known name (`known_names`: KaTeX's, or the LaTeX kernel's, article.cls's and the
    AMS packages'), every parsed definition of it has one and the same body, none of them is `\\providecommand`, it is not
    renewed without a `\\newcommand`, `\\def` or `\\DeclareMathOperator` of it, and no other construct targets it:
    `\\let` and its forms, `\\gdef` / `\\edef` / `\\xdef`, a `\\def` with delimited parameters, `\\DeclareRobustCommand`,
    the document-command forms, a `\\csname … \\endcsname` target or any definer not parsed. A source that compiles uses
    a user macro only where it is defined, and there it has that one body; a known name may be used where the archive's
    definition is not in force (a group, a macro-opened group), so its definition is never trusted.

    Definers are recognised broadly (a word ending in "def", a `\\let` form, one containing "command" / "Command" /
    "cmd", one starting with "Declare"), so a test such as `\\ifdef\\x` also marks `\\x`. A `\\csname` or etoolbox
    `\\cs…` target of plain characters is that one name; one that starts with plain letters before a `#` or `\\`
    (`\\@namedef{keycolor#1}`) makes every name with that prefix unsafe; a declaration whose argument is plain text marks
    each letter run in it. Any other built name, a target reached through `\\expandafter`, or LaTeX3 code leaves the
    source unbounded: then every group that holds a control word or symbol is refused. Only the archive's own text is
    scanned: a name that a package outside the archive also defines, and what a command derives from a name
    (`\\newtheorem{thm}` defining `\\thethm`), are not seen."""
    bodies: dict[str, set] = {}
    kinds: dict[str, set[str]] = {}
    unsafe: set[str] = set()
    prefixes: set[str] = set()
    unbounded = False
    problems: list[str] = []
    for text in [strip_comments(text, problems) for text in files.values()] + [tex]:
        unbounded = unbounded or bool(EXPL3.search(text)) or bool(problems)
        unbounded = not _named(text, unsafe, prefixes) or unbounded
        found = definitions(text)
        parsed = {position for position, *_ in found}
        for _, kind, name, definition in found:
            bodies.setdefault(name, set()).add(definition)
            kinds.setdefault(name, set()).add(kind)
        for m in DEFINER.finditer(text):
            word = m.group(1)
            if not _is_definer(word) or (word in PARSED_DEFINERS and m.start() in parsed):
                continue
            through_expandafter = text[max(0, m.start() - 40):m.start()].rstrip().endswith("\\expandafter")
            rest = text[m.end():m.end() + 400]
            prefix = TARGET_PREFIX.match(rest).group(0)
            through_expandafter = through_expandafter or "\\expandafter" in prefix
            rest = rest[len(prefix):]
            if rest.startswith("\\csname"):
                end = rest.find("\\endcsname")
                if end < 0 or not _built(rest[len("\\csname"):end], unsafe, prefixes):
                    unbounded = True
                continue
            arg = re.match(r"\*?\s*\{([^{}]*)\}", text[m.end():m.end() + 400])
            literal = LITERAL_NAME.match(arg.group(1)) if arg else None
            if word in CS_DEFINERS:
                if not arg or not _built(arg.group(1), unsafe, prefixes):
                    unbounded = True
                continue
            target = Expander.CONTROL.match(rest)
            if target is None and not through_expandafter and literal and not (LET_DEFINERS | PARSED_DEFINERS) & {word}:
                # a declaration with a plain-text argument (`\\DeclareGraphicsExtensions{.pdf,.png}`, `\\DeclareOption{x}`):
                # every letter run in it counts as a name
                unsafe.update("\\" + run for run in LETTER_RUN.findall(literal.group(1)))
                continue
            if target is None or through_expandafter:
                unbounded = True  # the name is built by expansion, or cannot be read
            if target is not None:
                unsafe.add(target.group(0))
    known = known_names()
    for name, found in bodies.items():
        if (name in known or len(found) > 1 or kinds[name] & {"providecommand", "unreadable"}
                or ("renewcommand" in kinds[name] and not kinds[name] & {"newcommand", "def", "operator"})):
            unsafe.add(name)
    unsafe.discard("")
    return unsafe, prefixes, unbounded


def source_groups(files: dict[str, str]) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Every display group with its cleaned LaTeX, letters and, when it cannot be placed, why."""
    from deixis.documents import math_reader

    tex, packages = flatten(files)
    if tex is None:
        return None, {"error": "no main file"}
    # Only safe macros are expanded, each with its one body wherever it is defined in the files the main file reads;
    # a macro defined only in a file never read stays unexpanded and fails the KaTeX gate.
    ambiguous, prefixes, unbounded = unsafe_macros(files, tex)
    defined = {name: definition for _, _, name, definition in definitions(tex) if name not in ambiguous}
    expander = Expander(defined)
    found = groups(tex)
    for group in found:
        expander.used, expander.unreadable = set(), False
        expanded, limit = expander.expand(group["raw"])
        group["refused"] = limit
        used = expander.used | set(Expander.CONTROL.findall(expanded)) | set(Expander.CONTROL.findall(group["raw"]))
        # in an unbounded source any name may have been redefined, a KaTeX command such as \\alpha too: every group
        # that holds a control word or symbol is refused
        names = used if unbounded else used & ambiguous | {n for n in used if any(n[1:].startswith(p) for p in prefixes)}
        if expander.unreadable:  # a macro whose arguments could not be read: the equation is not known
            names = names | expander.used
        if not limit and names:
            group["refused"], group["ambiguous"] = "macro_ambiguous", sorted(names)[:10]
        if not group["refused"] and REFERENCE.search(expanded):
            group["refused"] = "ref_or_cite"
        latex = clean(expanded)
        group["latex"] = latex[: 4 * MAX_GROUP_CHARS]
        if not group["refused"] and len(latex) > MAX_GROUP_CHARS:
            group["refused"] = "too_long"
        if not group["refused"] and (unknown := katex_unknown(latex)):
            group["refused"], group["unknown"] = "katex_unknown", unknown[:10]
        if not group["refused"] and group["continues"]:
            group["refused"] = "continues_after_number"
        group["letters"] = math_reader.latex_letters(group["latex"])
        del group["raw"]
    return found, {"macros": len(defined), "expander_calls": expander.calls, "packages": packages,
                   "ambiguous_macros": sorted(ambiguous)[:50], "ambiguous_prefixes": sorted(prefixes)[:50], "unbounded": unbounded}


# ---- matching (decision 4) ---------------------------------------------------------------------------------------------
NUMBER_ONLY = re.compile(r"^\((\d{1,3}[a-z]?)\)$")
NUMBER_END = re.compile(r"\s\((\d{1,3}[a-z]?)\)$")
PROSE_WORD = re.compile(r"\b[a-z]{3,}\b")


def is_prose(line: str) -> bool:
    return len(PROSE_WORD.findall(line)) >= PROSE_WORDS


def _letters(text: str) -> Counter:
    from deixis.documents import inline_math, math_reader

    return math_reader._letters(text.replace(inline_math.MASK, ""))


def _f1(a: Counter, b: Counter) -> float:
    total = sum(a.values()) + sum(b.values())
    return 2 * sum((a & b).values()) / total if total else 0.0


def _recall(region: Counter, target: Counter) -> float:
    return sum((region & target).values()) / max(1, sum(target.values()))


def foreign_words(lines: list[str], latex: str) -> list[str]:
    """Lowercase words of 3+ letters in the region that are not the group's own: not a substring of the LaTeX's letters
    (with or without command names) and not spelled from the group's letters (scripts print interleaved)."""
    with_commands = re.sub(r"[^a-z]", "", latex.lower())
    without = re.sub(r"[^a-z]", "", re.sub(r"\\[A-Za-z]+", "", latex).lower())
    pool = Counter(without)
    return [w for line in lines for w in PROSE_WORD.findall(line)
            if w not in with_commands and w not in without and not Counter(w) <= pool]


def page_lines(page: Any) -> list[dict[str, Any]]:
    """The page's lines in reading order from `pdf._blocks` (the extraction's own blocks), keyed (block, line)."""
    from deixis.documents import pdf

    out = []
    for b, block in enumerate(pdf._blocks(page)):
        for ln, (text, box) in enumerate(zip(block["masked"], block["line_boxes"])):
            if text.strip():
                out.append({"key": (b, ln), "text": text.strip(), "box": box})
    return out


def match(pdf_path: Path, found: list[dict[str, Any]], skip_pages: set[int]) -> dict[str, Any]:
    """Number lines matched to numbered groups by letters under the order constraint, and the placements that pass."""
    import pymupdf

    from deixis.documents import math_reader, pdf

    numbered = [g for g in found if g["numbered"] and g["letters"]]
    tables = set()
    seq: list[dict[str, Any]] = []
    with pymupdf.open(pdf_path, filetype="pdf") as doc:
        tables = {i + 1 for i, page in enumerate(doc) if i < pdf.MAX_PAGES and math_reader.TABLE_CAPTION.search(page.get_text())}
        for index in range(min(doc.page_count, pdf.MAX_PAGES)):
            lines = page_lines(doc[index])
            stop = -1
            for k, line in enumerate(lines):
                text = line["text"]
                m = NUMBER_ONLY.match(text) or (NUMBER_END.search(text) if not is_prose(text) else None)
                if not m:
                    continue
                first = "" if NUMBER_ONLY.match(text) else text[:m.start()]
                parts = [(k, _letters(first))]
                for x in range(k - 1, max(stop, k - MAX_REGION_LINES - 1), -1):
                    if is_prose(lines[x]["text"]):
                        break
                    parts.append((x, _letters(lines[x]["text"])))
                region = sum((c for _, c in parts), Counter())
                seq.append({"page": index + 1, "n": m.group(1), "line": k, "prev_stop": stop, "parts": parts, "lines": lines,
                            "f1s": [_f1(region, g["letters"]) for g in numbered],
                            "recalls": [_recall(region, g["letters"]) for g in numbered]})
                stop = k
    # Order, not counting: numbers rise with the source order of the groups they are given; the assignment maximising the
    # summed F1 − 0.5 under that constraint is found (dynamic programming; a number may stay unassigned).
    U = len(numbered)
    best, node = [float("-inf")] * U, [None] * U
    for i, item in enumerate(seq):
        updates, prefix, prefix_node = [], 0.0, None
        for j in range(U):
            weight = item["f1s"][j] - ORDER_SCORE_OFFSET
            if weight > 0 and prefix + weight > best[j]:
                updates.append((j, prefix + weight, (i, j, prefix_node)))
            if best[j] > prefix:
                prefix, prefix_node = best[j], node[j]
        for j, value, chain in updates:
            if value > best[j]:
                best[j], node[j] = value, chain
    assigned: dict[int, int] = {}
    if U and max(best) > float("-inf"):
        chain = node[max(range(U), key=lambda k: best[k])]
        while chain is not None:
            i, j, chain = chain
            assigned[i] = j
    order = [assigned.get(i) for i in range(len(seq))]
    rows, placements, not_placed = [], [], Counter()
    for i, item in enumerate(seq):
        row = {"page": item["page"], "n": item["n"], "group": None, "candidate": False, "placed": False, "reason": None}
        rows.append(row)
        j = order[i]
        if j is None:
            row["reason"] = "not_assigned"
            continue
        group = numbered[j]
        lo = max([order[k] for k in range(i) if order[k] is not None], default=-1)
        hi = min([order[k] for k in range(i + 1, len(seq)) if order[k] is not None], default=U)
        f1, recall = item["f1s"][j], item["recalls"][j]
        window = max([item["f1s"][k] for k in range(lo + 1, hi) if k != j], default=0.0)
        paper = max([item["f1s"][k] for k in range(U) if k != j and numbered[k]["latex"] != group["latex"]], default=0.0)
        row.update(group=group["index"], f1=round(f1, 4), recall=round(recall, 4), window_margin=round(f1 - window, 4),
                   paper_margin=round(f1 - paper, 4))
        if not (recall >= MIN_RECALL and (f1 - paper >= MIN_MARGIN or (f1 - window >= MIN_MARGIN and f1 - paper >= 0))):
            row["reason"] = "below_threshold"
            continue
        if group["continues"]:
            row["reason"] = "continues_after_number"
            not_placed[row["reason"]] += 1
            continue
        # Trim: the shortest run back from the number line reaching the group's best recall over the region.
        target, acc, top, length = group["letters"], Counter(), -1.0, 0
        for size, (_, letters) in enumerate(item["parts"], 1):
            acc = acc + letters
            if (r := _recall(acc, target)) > top + 1e-9:
                top, length = r, size
        kept = sorted(x for x, _ in item["parts"][:length])
        lines = item["lines"]
        box = _union([lines[x]["box"] for x in kept])
        # Absorb the lines before it that overlap it vertically: parts of the same equation (a brace, `max`, `lim`).
        x = kept[0] - 1
        while x > item["prev_stop"]:
            text, line_box = lines[x]["text"], lines[x]["box"]
            overlap = min(line_box[3], box[3]) - max(line_box[1], box[1])
            height = max(1e-6, line_box[3] - line_box[1])
            inter = (max(line_box[0], box[0]) < min(line_box[2], box[2])) and overlap > 0
            if is_prose(text) or NUMBER_ONLY.match(text) or NUMBER_END.search(text) or not inter or overlap < ABSORB_OVERLAP * height:
                break
            kept.insert(0, x)
            box = _union([box, line_box])
            x -= 1
        if foreign := foreign_words([lines[x]["text"] for x in kept], group["latex"]):
            row.update(reason="foreign_text", foreign=foreign[:5])
            not_placed["foreign_text"] += 1
            continue
        row["candidate"] = True
        reason = group["refused"] or ("table_or_ocr_page" if item["page"] in tables or item["page"] in skip_pages else None)
        if reason:
            row["reason"] = reason
            not_placed[reason] += 1
            continue
        row["placed"] = True  # asked to be placed; the extraction may still refuse it (not_in_page_text, offsets)
        placements.append({"page": item["page"], "n": item["n"], "latex": group["latex"], "group": group["index"],
                           "number": list(lines[item["line"]]["key"]), "lines": [list(lines[x]["key"]) for x in kept],
                           "box": [round(v, 2) for v in box], "recall": row["recall"], "f1": row["f1"],
                           "window_margin": row["window_margin"], "paper_margin": row["paper_margin"],
                           "order_decided": f1 - paper < MIN_MARGIN})
    return {"number_lines": len(seq), "assigned": sum(o is not None for o in order), "candidates": sum(r["candidate"] for r in rows),
            "placements": placements, "not_placed": dict(not_placed), "rows": rows, "numbered_groups": U}


def _union(boxes: list) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def inspect_and_match(data: bytes, pdf_path: Path, skip_pages: set[int], report: bool = False) -> dict[str, Any]:
    """The child's work: read the archive, build its groups and match them to the PDF's pages."""
    started = time.perf_counter()
    archive = read_archive(data)
    if archive.content != "tex":
        return {"content": archive.content, "error": archive.error}
    found, info = source_groups(archive.files)
    if found is None:
        return {"content": "no_tex", "error": info["error"]}
    result = match(pdf_path, found, skip_pages) if any(g["numbered"] for g in found) else {
        "number_lines": 0, "assigned": 0, "candidates": 0, "placements": [], "not_placed": {}, "rows": [], "numbered_groups": 0}
    result |= {"content": "tex", "groups": len(found), "seconds": round(time.perf_counter() - started, 3), **info,
               "group_reasons": dict(Counter(g["refused"] for g in found if g["numbered"] and g["refused"]))}
    if report:
        result["group_latex"] = {g["index"]: g["latex"] for g in found}
    else:
        del result["rows"]
    return result


# ---- the child process -------------------------------------------------------------------------------------------------
@dataclass
class ChildResult:
    returncode: int | None
    stdout: bytes
    stderr_tail: str
    failure: str | None  # timed_out, output_too_large, memory_limit, exit_<code>, or None


async def run_child(argv: list[str], stdin: bytes = b"", timeout: float = CHILD_TIMEOUT_SECONDS,
                    max_stdout: int = MAX_CHILD_STDOUT, env: dict[str, str] | None = None) -> ChildResult:
    """Run a child, feeding `stdin` and draining stdout and stderr at the same time in their own tasks, so a full pipe
    never stalls it. stdout over `max_stdout` kills the child at once; stderr is read to its end and only its last
    OUTPUT_TAIL_CHARS characters are kept; the whole run is killed after `timeout` seconds."""
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env)
    out, err, failure = bytearray(), "", None

    async def feed() -> None:
        try:
            proc.stdin.write(stdin)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()

    async def read_out() -> None:
        nonlocal failure
        while chunk := await proc.stdout.read(65536):
            out.extend(chunk)
            if len(out) > max_stdout:
                failure = "output_too_large"
                proc.kill()
                return

    async def read_err() -> None:
        nonlocal err
        while chunk := await proc.stderr.read(65536):
            err = (err + chunk.decode("utf-8", "replace"))[-OUTPUT_TAIL_CHARS:]

    tasks = [asyncio.create_task(feed()), asyncio.create_task(read_out()), asyncio.create_task(read_err())]
    try:
        async with asyncio.timeout(timeout):
            await asyncio.gather(*tasks)
            await proc.wait()
    except TimeoutError:
        failure = "timed_out"
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    if failure is None and proc.returncode:
        failure = "memory_limit" if proc.returncode == MEMORY_EXIT_CODE else f"exit_{proc.returncode}"
    return ChildResult(proc.returncode, bytes(out), err, failure)


MEMORY_EXIT_CODE = 3


async def read_source(data: bytes, pdf_path: Path, skip_pages: set[int], report: bool = False) -> dict[str, Any]:
    """Archive inspection and matching in a bounded child process; any limit gives `content = 'unreadable'`."""
    argv = [sys.executable, "-m", "deixis.documents.arxiv_source", str(pdf_path), json.dumps(sorted(skip_pages)),
            "report" if report else "placements", str(MAX_MEMORY_BYTES)]
    started = time.perf_counter()
    result = await run_child(argv, data, env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])})
    seconds = round(time.perf_counter() - started, 3)
    if result.failure:
        return {"content": "unreadable", "error": result.failure, "stderr": result.stderr_tail[-400:], "child_seconds": seconds}
    try:
        return json.loads(result.stdout) | {"child_seconds": seconds}
    except json.JSONDecodeError:
        return {"content": "unreadable", "error": "child output was not JSON", "child_seconds": seconds}


# ---- the rate gate and the stored sources (decision 2) -----------------------------------------------------------------
def _fsync_write(path: Path, data: bytes) -> None:
    """Write through a temporary file, fsync and os.replace, so a reader sees the old or the new file, never a part."""
    part = path.with_name(f"{path.name}.part-{os.getpid()}")
    with open(part, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, path)


def _write_source(path: Path, data: bytes) -> str:
    """The downloaded file's sha256, then the file written durably (run in a worker thread)."""
    digest = hashlib.sha256(data).hexdigest()
    _fsync_write(path, data)
    return digest


def _read_stored(data_dir: Path, storage_path: str | None) -> tuple[bytes | None, str | None]:
    """A stored file's bytes and sha256, or (None, None) when it cannot be read (run in a worker thread)."""
    try:
        data = (data_dir / storage_path).read_bytes()
    except (OSError, TypeError):
        return None, None
    return data, hashlib.sha256(data).hexdigest()


async def acquire_file_lock(path: Path) -> int:
    """An exclusive `fcntl.flock`, tried without blocking and awaited with `asyncio.sleep` between tries (no thread, so
    a cancelled wait never takes the lock later). The caller bounds the wait and releases with `release_file_lock`."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                await sleep(LOCK_POLL_SECONDS)
    except BaseException:
        os.close(fd)
        raise


def release_file_lock(fd: int | None) -> None:
    if fd is None:
        return
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class RateGate:
    """The per-hop part of the 3 s rule, used while `.rate.lock` is held: wait for the previous request's end + 3 s (or
    its start + 33 s when it never wrote an end), stamp the start durably, send; stamp the end durably."""

    def __init__(self, directory: Path, on_first_request: Callable[[], None] | None = None):
        self.path = directory / ".rate"
        self.on_first_request = on_first_request
        self.hops = 0
        self._open = False

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    async def before(self) -> None:
        stamp = self._read()
        now = clock()
        if stamp.get("ended_at") is not None:
            until = float(stamp["ended_at"]) + RATE_SECONDS
        elif stamp.get("started_at") is not None:
            until = float(stamp["started_at"]) + STALE_START_WAIT
        else:
            until = now
        wait = min(max(0.0, until - now), STALE_START_WAIT)
        if wait > 0:
            await sleep(wait)
        if self.hops == 0 and self.on_first_request is not None:
            self.on_first_request()  # the attempt is counted only now: both locks held and the first wait over
        await asyncio.to_thread(_fsync_write, self.path, json.dumps({"started_at": clock(), "ended_at": None}).encode())
        self._open = True
        self.hops += 1

    def after(self) -> None:
        if self._open:
            stamp = self._read()
            _fsync_write(self.path, json.dumps({"started_at": stamp.get("started_at"), "ended_at": clock()}).encode())
            self._open = False


_key_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()


def _key_lock(directory: Path, key: str) -> asyncio.Lock:
    locks = _key_locks.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(f"{directory}\0{key}", asyncio.Lock())


class SourceStore:
    """The `arxiv_sources` rows and the files under `<data dir>/arxiv-sources/`, one per arXiv version."""

    def __init__(self, store: Any, data_dir: Path, fetch_file: Callable[..., Any] | None = None, client: Any = None):
        from deixis.documents import fetch

        self.store, self.data_dir = store, data_dir
        self.directory = data_dir / "arxiv-sources"
        self.fetch_file = fetch_file or fetch.fetch_file
        self.client = client

    def remove_stale_parts(self) -> int:
        """`.part-*` files older than one hour: left by a fetch cancelled or killed while writing."""
        removed = 0
        if self.directory.exists():
            for path in self.directory.glob("*.part-*"):
                try:
                    if time.time() - path.stat().st_mtime > PART_MAX_AGE_SECONDS:
                        path.unlink()
                        removed += 1
                except OSError:
                    pass
        return removed

    def row(self, key: str) -> dict[str, Any] | None:
        row = self.store.conn.execute("SELECT * FROM arxiv_sources WHERE arxiv_key = ?", (key,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def exhausted(row: dict[str, Any]) -> bool:
        return row["status"] == "not_settled" and row["attempts"] >= SOURCE_MAX_ATTEMPTS and row["repairs"] != 1

    @staticmethod
    def waiting_until(row: dict[str, Any]) -> float | None:
        """When a not-settled source may be asked again, if that is still ahead."""
        if row["status"] != "not_settled" or row["repairs"] == 1 or row["attempts"] >= SOURCE_MAX_ATTEMPTS:
            return None
        last = seconds_of(row["last_attempt_at"])
        until = (last or 0) + RETRY_AFTER.total_seconds()
        return until if last is not None and until > clock() else None

    def needs_fetch(self, row: dict[str, Any] | None) -> bool:
        if row is None:
            return True
        if row["status"] != "not_settled":
            return False
        if row["repairs"] == 1:
            return True
        return not self.exhausted(row) and self.waiting_until(row) is None

    def _count_attempt(self, key: str, repair: bool) -> None:
        from deixis.storage.db import transaction

        arxiv_id, version = split_key(key)
        with transaction(self.store.conn):
            if repair:
                self.store.conn.execute("UPDATE arxiv_sources SET repairs = 2, last_attempt_at = ? WHERE arxiv_key = ?", (iso(), key))
            else:
                self.store.conn.execute(
                    "INSERT INTO arxiv_sources (arxiv_key, arxiv_id, version, status, attempts, last_attempt_at)"
                    " VALUES (?, ?, ?, 'not_settled', 1, ?) ON CONFLICT(arxiv_key) DO UPDATE SET attempts = attempts + 1,"
                    " last_attempt_at = excluded.last_attempt_at", (key, arxiv_id, version, iso()))

    def _set(self, key: str, **fields: Any) -> None:
        from deixis.storage.db import transaction

        with transaction(self.store.conn):
            self.store.conn.execute(f"UPDATE arxiv_sources SET {', '.join(f'{k} = ?' for k in fields)} WHERE arxiv_key = ?",
                                    (*fields.values(), key))

    async def ensure(self, key: str) -> dict[str, Any]:
        """The version's row, fetching it first when the row allows. Locks: the in-process per-version lock, the
        per-version file lock and the rate lock are all taken within one 120 s budget; past it nothing is requested,
        written or counted and the outcome is `rate_gate_busy`."""
        row = self.row(key)
        if row is not None and row["status"] != "not_settled":
            return row  # settled for good; a not-settled row may be another task's attempt in flight, decided under the locks
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = _key_lock(self.directory, key)
        held, key_fd, rate_fd = False, None, None
        try:
            try:
                async with asyncio.timeout(LOCK_BUDGET_SECONDS):
                    await lock.acquire()
                    held = True
                    key_fd = await acquire_file_lock(self.directory / f"{file_name(key)}.lock")
                    row = self.row(key)  # another process or task may have fetched it meanwhile
                    if not self.needs_fetch(row):
                        return row
                    rate_fd = await acquire_file_lock(self.directory / ".rate.lock")
            except TimeoutError:
                return {"arxiv_key": key, "outcome": "rate_gate_busy"}
            return await self._fetch(key, row)
        finally:
            release_file_lock(rate_fd)
            release_file_lock(key_fd)
            if held:
                lock.release()

    async def _fetch(self, key: str, row: dict[str, Any] | None) -> dict[str, Any]:
        repair = row is not None and row["status"] == "not_settled" and row["repairs"] == 1
        gate = RateGate(self.directory, on_first_request=lambda: self._count_attempt(key, repair))
        result = await self.fetch_file(E_PRINT_URL.format(key=key), MEDIA_TYPES, gate=gate, client=self.client,
                                       deadline=FETCH_DEADLINE_SECONDS)
        if gate.hops == 0:
            return self.row(key) or {"arxiv_key": key, "outcome": "not_requested"}
        status, http_status = result.status, result.http_status
        if status == "ok":
            if not disposition_names(result.content_disposition, key):
                self._set(key, status="version_mismatch", content=None, http_status=http_status,
                          error=f"file name {result.content_disposition!r}"[:300])
                return self.row(key)
            # Hashing and the durable write of a file up to 30 MB run in a worker thread, off the event loop; the row is
            # written on the loop, after the file is in place.
            digest = await asyncio.to_thread(_write_source, self.directory / f"{file_name(key)}.src", result.data)
            self._set(key, status="downloaded", content=None, sha256=digest, byte_size=len(result.data),
                      storage_path=f"arxiv-sources/{file_name(key)}.src", http_status=http_status, error=None,
                      fetched_at=iso(), inspected_at=None)
            return self.row(key)
        if status == "too_large":
            outcome = "too_large"
        elif status in ("timeout", "failed") or (status == "http_error" and http_status is not None
                                                 and (http_status in (403, 406, 429) or http_status >= 500)):
            outcome = "not_settled"
        else:
            outcome = "unreadable"  # another media type, another 4xx, a blocked address or too many redirects
        self._set(key, status=outcome, http_status=http_status, error=(result.error or status)[:300])
        return self.row(key)

    async def read(self, key: str) -> tuple[bytes | None, str | None]:
        """The stored file checked against its sha256: (bytes, None), or (None, 'repair') after a first corruption (one
        more fetch attempt is allowed), or (None, 'cache_corrupt') after a second (permanent), or (None, 'busy') when the
        version's locks were not free within the lock budget. The check and the row's transition happen under the
        version's in-process and file locks (the ones `ensure` takes), from the row read after the file: two readers of
        one corrupt file open one repair between them, and a reader never reopens a repair another one already used.
        The file is read and hashed in a worker thread; the row is read and written on the event loop."""
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = _key_lock(self.directory, key)
        held, key_fd = False, None
        try:
            try:
                async with asyncio.timeout(LOCK_BUDGET_SECONDS):
                    await lock.acquire()
                    held = True
                    key_fd = await acquire_file_lock(self.directory / f"{file_name(key)}.lock")
            except TimeoutError:
                return None, "busy"
            row = self.row(key)
            if row is None:
                return None, "cache_corrupt"
            if row["status"] == "not_settled" and row["repairs"] == 1:
                return None, "repair"  # another reader found the corruption first; its repair is still to be fetched
            if row["status"] != "downloaded":
                return None, "cache_corrupt"
            data, digest = await asyncio.to_thread(_read_stored, self.data_dir, row["storage_path"])
            if data is not None and digest == row["sha256"]:
                return data, None
            if row["repairs"] == 0:
                self._set(key, status="not_settled", content=None, repairs=1, error="stored file missing or changed")
                return None, "repair"
            self._set(key, status="unreadable", content=None, error="cache_corrupt")
            return None, "cache_corrupt"
        finally:
            release_file_lock(key_fd)
            if held:
                lock.release()

    def reset(self, key: str) -> None:
        """The person's retry: an unreadable archive is inspected again, an unreadable or exhausted download fetched again."""
        row = self.row(key)
        if row is None:
            return
        if row["status"] == "downloaded" and row["content"] == "unreadable":
            self._set(key, content=None, inspected_at=None)
        elif row["status"] == "unreadable" or self.exhausted(row):
            self._set(key, status="not_settled", content=None, attempts=0, repairs=0, error=None)


# ---- the child's entry point -------------------------------------------------------------------------------------------
if __name__ == "__main__":
    import pymupdf

    from deixis.documents import pdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    pdf._watch_memory(int(sys.argv[4]))
    try:
        out = inspect_and_match(sys.stdin.buffer.read(), Path(sys.argv[1]), set(json.loads(sys.argv[2])), sys.argv[3] == "report")
    except MemoryError:
        sys.exit(MEMORY_EXIT_CODE)
    except Exception as exc:  # noqa: BLE001 - untrusted input: any failure is an unreadable source, reported to the parent
        out = {"content": "unreadable", "error": f"{type(exc).__name__}: {exc}"[:300]}
    json.dump(out, sys.stdout, default=lambda v: sorted(v) if isinstance(v, set) else str(v))
