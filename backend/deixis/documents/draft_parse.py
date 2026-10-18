"""Verify Citations (V1, D86): read a draft and find its citation markers. Code only, no model, deterministic.

The draft is untrusted data. Accepted: pasted text, `.txt`, `.md`, `.tex`, `.docx` (paragraph text only: footnotes,
comments, field codes and deleted text are not read). The file is at most `MAX_DRAFT_BYTES`, the text at most
`MAX_TEXT_CHARS`, and a `.docx` body part at most `MAX_DOCX_XML_BYTES` unpacked; XML with a DOCTYPE or an entity
declaration is refused before it is parsed.

Markers, each with the sentence it sits in:
- LaTeX `\\cite{a,b}` and the natbib/biblatex forms (`\\citep`, `\\citet`, `\\parencite`, …, with up to two optional
  arguments such as `\\cite[p.~3]{a}`), in every format;
- IEEE numeric `[3]`, `[3]–[5]`, `[3-5]`, `[3, 7]`, `[3], [4]`, outside `.tex` (where brackets are LaTeX arguments);
- author–year `(Zeng et al., 2022)`, `(Zeng and Li, 2022; Kim, 2021)`, `Zeng et al. (2022)`, `2022a/b`.
A bracket that is not a numeric list but holds a digit, an `@` or a single word is `unrecognized`, as is a `\\cite` whose
keys cannot be read and a parenthesis that starts like an author–year citation but does not parse. Whether an
author–year item names exactly one entry is decided later against the bibliography (`workflow/citation_check.py`);
nothing here guesses. Known limits: a bracketed interval such as `[0, 1]` reads as two numeric citations; superscript
and footnote citations are not read; a capitalised word before a bare year, `Results (2022)`, reads as an author.

The reference list at the end of a draft (a `References`, `Bibliography`, `Kaynaklar` or `Kaynakça` heading, or a
LaTeX `thebibliography` environment) is cut from the body, so its `[n]` lines are not read as markers, and kept as
the draft's own entries.
"""

from __future__ import annotations

import bisect
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree
from xml.parsers import expat

from deixis.imports import bibtex_ris

Format = Literal["text", "md", "tex", "docx"]

MAX_DRAFT_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_DOCX_XML_BYTES = 50 * 1024 * 1024
MAX_MARKERS = 2000
MAX_LIST_ENTRIES = bibtex_ris.MAX_ENTRIES
MAX_RANGE = 100  # `[3–103]` is the widest numeric range read; a wider one is unrecognized
SUFFIXES = {".txt": "text", ".text": "text", "": "text", ".md": "md", ".markdown": "md", ".tex": "tex", ".docx": "docx"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DraftRefused(Exception):
    """The whole draft is refused; `code` lets the page translate the sentence."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass(frozen=True)
class Target:
    """What one marker names: a citation `key`, a reference `number`, or an `author_year` item (surnames as written,
    `et_al`, year and its letter suffix)."""

    kind: Literal["key", "number", "author_year"]
    value: str
    names: tuple[str, ...] = ()
    et_al: bool = False
    year: int | None = None
    suffix: str | None = None

    def view(self) -> dict:
        return {"kind": self.kind, "value": self.value, "names": list(self.names), "et_al": self.et_al,
                "year": self.year, "suffix": self.suffix}


@dataclass
class Marker:
    start: int
    end: int
    raw: str
    style: Literal["latex", "numeric", "author_year"]
    status: Literal["recognized", "unrecognized"]
    targets: list[Target] = field(default_factory=list)
    sentence_start: int = 0
    sentence_end: int = 0
    claim: str = ""  # what the check reads: the sentence (or table row) with markers cut, as plain text (D105)
    reason: str | None = None  # why an unrecognized marker was not read (`table_layout_not_read`)
    claim_context: str | None = None  # a table row's caption, shown to the model, never part of the claim


@dataclass(frozen=True)
class ListEntry:
    """One entry of the draft's own reference list, as written."""

    ordinal: int
    raw: str
    number: int | None = None
    key: str | None = None


@dataclass
class Draft:
    format: Format
    text: str  # the body markers and sentences point into
    markers: list[Marker]
    list_entries: list[ListEntry]
    list_origin: Literal["draft_list", "bibitem"] | None


# --------------------------------------------------------------------------------------------------------- reading

def detect_format(filename: str | None) -> Format:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUFFIXES:
        raise DraftRefused(415, "draft_unknown_format", "The draft must be text, .md, .tex or .docx")
    return SUFFIXES[suffix]  # type: ignore[return-value]


def read_draft(data: bytes | None, filename: str | None, pasted: str | None) -> tuple[Format, str]:
    """The draft's format and text, from a file or from pasted text (exactly one of them)."""
    if (data is None) == (pasted is None):
        raise DraftRefused(422, "draft_missing", "Give a draft file or paste its text")
    if pasted is not None:
        fmt: Format = "text"
        text = pasted
    else:
        if len(data) > MAX_DRAFT_BYTES:
            raise DraftRefused(413, "draft_too_large", "Draft larger than 10 MB")
        fmt = detect_format(filename)
        if fmt == "docx":
            text = docx_text(data)
        else:
            try:
                text = bibtex_ris.decode(data)
            except bibtex_ris.ImportRefused:
                raise DraftRefused(422, "draft_not_text", "The draft is not readable text") from None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT_CHARS:
        raise DraftRefused(413, "draft_too_large", "Draft longer than 2,000,000 characters")
    if not text.strip():
        raise DraftRefused(422, "draft_empty", "The draft has no text")
    return fmt, text


class _Declaration(Exception):
    pass


def _declared(*_args) -> None:
    raise _Declaration


def _refuse_dtd(xml: bytes) -> None:
    """A first pass with expat, which reads the XML declaration and byte-order mark itself (UTF-8, UTF-16 …): any
    DOCTYPE, entity, notation or external-entity reference refuses the file before ElementTree sees it, so no entity is
    ever expanded, whatever the encoding."""
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _declared
    parser.EntityDeclHandler = _declared
    parser.UnparsedEntityDeclHandler = _declared
    parser.NotationDeclHandler = _declared
    parser.ExternalEntityRefHandler = _declared
    try:
        parser.Parse(xml, True)
    except (_Declaration, expat.ExpatError, ValueError):
        raise DraftRefused(422, "draft_unreadable", "The .docx file could not be read") from None


def docx_text(data: bytes) -> str:
    """The paragraphs of `word/document.xml`, one per line pair, from `w:t` runs (tabs as tabs, breaks as spaces)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise DraftRefused(413, "draft_too_large", "The .docx body is too large")
            with archive.open(info) as part:
                xml = part.read(MAX_DOCX_XML_BYTES + 1)
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError, NotImplementedError):
        raise DraftRefused(422, "draft_unreadable", "The .docx file could not be read") from None
    if len(xml) > MAX_DOCX_XML_BYTES:
        raise DraftRefused(413, "draft_too_large", "The .docx body is too large")
    _refuse_dtd(xml)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise DraftRefused(422, "draft_unreadable", "The .docx file could not be read") from None
    body = root.find(f"{_W}body")
    paragraphs = []
    for paragraph in (body.iter(f"{_W}p") if body is not None else ()):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append(" ")
        paragraphs.append("".join(parts))
    return "\n\n".join(p for p in paragraphs if p.strip())


# ---------------------------------------------------------------------------------------------- the reference list

_HEADING = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*|\\(?:section|chapter)\*?\{)?[ \t]*(?:\d+\.?[ \t]+)?"
                      r"(references|bibliography|works cited|kaynaklar|kaynakça|kaynakca)[ \t]*\}?[ \t]*:?[ \t]*$",
                      re.IGNORECASE | re.MULTILINE)
_NUMBERED = re.compile(r"^[ \t]*\[(\d{1,4})\][ \t]*", re.MULTILINE)
_BIBLIOGRAPHY_ENV = re.compile(r"\\begin\{thebibliography\}.*?(?:\\end\{thebibliography\}|\Z)", re.DOTALL)
_BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
_LIST_PREFIX = re.compile(r"^[ \t]*(?:[-*+•][ \t]+|\d{1,4}\.[ \t]+)")


_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%[^\n]*")


def strip_comments(text: str) -> str:
    r"""LaTeX comments removed: a `%` starts one when an even number of backslashes (0, 2, …) stands right before it, so
    `\\%` is a line break and then a comment, while `\%` and `\\\%` are a literal percent sign (Sol round 3, D105)."""
    return _COMMENT.sub(r"\1", text)


def _check_list_size(count: int) -> None:
    """A reference list over the cap is refused whole: a cut list could leave out the one entry a marker names, or the
    second entry with its number, and a match on what is left would look exact."""
    if count > MAX_LIST_ENTRIES:
        raise DraftRefused(413, "draft_list_too_long",
                           f"The draft's reference list has more than {MAX_LIST_ENTRIES} entries")


def _tex_body(text: str) -> tuple[str, list[ListEntry], str | None]:
    text = strip_comments(text)  # before any marker or table is read
    begin = re.search(r"\\begin\{document\}", text)
    if begin:
        text = text[begin.end():]
    end = re.search(r"\\end\{document\}", text)
    if end:
        text = text[:end.start()]
    environment = _BIBLIOGRAPHY_ENV.search(text)
    if not environment:
        return text, [], None
    block = environment.group(0)
    heads = list(_BIBITEM.finditer(block))
    _check_list_size(len(heads))
    entries = []
    for i, head in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(block)
        raw = re.sub(r"\\end\{thebibliography\}", "", block[head.end():stop])
        entries.append(ListEntry(ordinal=i + 1, raw=re.sub(r"\s+", " ", raw).strip(), key=head.group(1).strip()))
    return text[:environment.start()] + text[environment.end():], entries, "bibitem"


def _cut_list(text: str) -> tuple[str, list[ListEntry], str | None]:
    """The body before the last reference heading, and the entries after it."""
    headings = list(_HEADING.finditer(text))
    if not headings:
        return text, [], None
    heading = headings[-1]
    body, tail = text[:heading.start()], text[heading.end():]
    numbered = list(_NUMBERED.finditer(tail))
    entries: list[ListEntry] = []
    if numbered:
        _check_list_size(len(numbered))
        for i, head in enumerate(numbered):
            stop = numbered[i + 1].start() if i + 1 < len(numbered) else len(tail)
            raw = re.sub(r"\s+", " ", tail[head.end():stop]).strip()
            if raw:
                entries.append(ListEntry(ordinal=len(entries) + 1, raw=raw, number=int(head.group(1))))
    else:
        blocks = [b for b in re.split(r"\n[ \t]*\n", tail) if b.strip()]
        lines = blocks if len(blocks) > 1 else [line for line in tail.split("\n") if line.strip()]
        _check_list_size(len(lines))
        for line in lines:
            raw = re.sub(r"\s+", " ", _LIST_PREFIX.sub("", line)).strip()
            if raw:
                entries.append(ListEntry(ordinal=len(entries) + 1, raw=raw))
    return body, entries, "draft_list"


# ------------------------------------------------------------------------------------------------------- sentences

_ABBREVIATIONS = {"al", "e.g", "i.e", "eg", "ie", "cf", "vs", "etc", "fig", "figs", "eq", "eqs", "ref", "refs", "sec",
                  "secs", "no", "nos", "vol", "vols", "pp", "p", "ch", "tab", "approx", "ca", "resp", "dr", "mr", "mrs",
                  "ms", "prof", "inc", "jr", "sr", "st", "ed", "eds"}
_BOUNDARY = re.compile(r"[.!?][)\"”’']*\s+(?=[A-Z0-9\[\\\"“‘'(]|[^\W\d_])")


def sentences(text: str, protected: list[tuple[int, int]] = ()) -> list[tuple[int, int]]:
    """Sentence spans of `text`. A blank line always ends one; inside a block a `.`, `!` or `?` followed by space ends
    one unless the word before it is a single letter (an initial) or on the abbreviation list, or the point falls
    inside a protected span (a marker). Lowercase after the point never starts a sentence."""
    spans: list[tuple[int, int]] = []
    for block in re.finditer(r"[^\n]+(?:\n(?![ \t]*\n)[^\n]*)*", text):
        start = block.start()
        for boundary in _BOUNDARY.finditer(text, block.start(), block.end()):
            point = boundary.start()
            following = text[boundary.end():boundary.end() + 1]
            if following.islower():
                continue
            word = re.search(r"([^\s(\[]+)$", text[start:point])
            token = word.group(1).lower().rstrip(".") if word else ""
            if text[point] == "." and (len(token) == 1 and token.isalpha() or token in _ABBREVIATIONS):
                continue
            if any(a <= point < b for a, b in protected):
                continue
            spans.append((start, boundary.start() + 1))
            start = boundary.end()
        spans.append((start, block.end()))
    trimmed = []
    for a, b in spans:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            trimmed.append((a, b))
    return trimmed


# --------------------------------------------------------------------------------------------------------- markers

_CITE_COMMANDS = ("cite", "citep", "citet", "citealp", "citealt", "citeauthor", "citeyear", "parencite", "textcite",
                  "autocite", "footcite", "smartcite", "Cite", "Citep", "Citet", "Parencite", "Textcite", "Autocite")
_CITE = re.compile(r"\\(?:" + "|".join(_CITE_COMMANDS) + r")\*?((?:\s*\[[^\[\]{}]*\]){0,2})\s*\{([^{}]*)\}")
_CITE_HEAD = re.compile(r"\\(?:" + "|".join(_CITE_COMMANDS) + r")\*?(?![A-Za-z@])")  # `\cite@x` is another macro
_CITE_KEY = re.compile(r"[^\s{}\\,%#~]+")
_GROUP = re.compile(r"\[[^\[\]\n]{1,80}\](?:[ \t]*(?:,|;|–|—|-|−)[ \t]*\[[^\[\]\n]{1,80}\])*")
_DASH = "-–—−"
_NUMBER_ITEM = re.compile(rf"^\s*(\d{{1,4}})\s*(?:[{_DASH}]\s*(\d{{1,4}})\s*)?$")
_IGNORED_BRACKETS = {"sic", "...", "…", "x", "X", " ", ""}
_YEAR = r"(?:1[5-9]\d\d|20\d\d)"
PARTICLES = ("van", "von", "de", "der", "den", "del", "della", "di", "da", "du", "des", "le", "la", "dos", "das", "ten",
             "ter", "al", "el", "bin", "ibn")
_NAME = rf"(?:(?i:{'|'.join(PARTICLES)})\s+)*[^\W\d_][\w'’\-]*"  # `Van Berg` and `van Berg` are one surname
_NAMES = (rf"(?P<names>{_NAME}(?:\s*,\s*{_NAME})*(?:\s*,?\s*(?:and|&)\s+{_NAME})?)"
          r"(?P<etal>\s+et\s+al\.?)?")
_ITEM = re.compile(rf"^{_NAMES}\s*,?\s+(?P<years>{_YEAR}[a-z]?(?:\s*,\s*{_YEAR}[a-z]?)*)"
                   r"(?:\s*,\s*(?:p|pp|ch|sec)\.\s*[\w–\-]+)?$")
_ITEM_START = re.compile(rf"(?:^|;)\s*(?:(?:e\.g\.|i\.e\.|see also|see|cf\.)\s*,?\s*)?{_NAMES}\s*,?\s+{_YEAR}[a-z]?\b",
                         re.IGNORECASE)
_PREFIX = re.compile(r"^\s*(?:(?:e\.g\.|i\.e\.|see also|see|cf\.)\s*,?\s*)", re.IGNORECASE)
_PAREN = re.compile(r"\(([^()\n]{1,300})\)")
_YEARS_ONLY = re.compile(rf"\(\s*({_YEAR}[a-z]?(?:\s*,\s*{_YEAR}[a-z]?)*)\s*\)")
_NARRATIVE_NAMES = re.compile(rf"{_NAMES}\s*$")
# Capitalised words that may stand right before a narrative citation's names without being one of them.
_LEAD_WORDS = {"in", "as", "by", "see", "following", "unlike", "like", "per", "from", "with", "both", "while", "whereas",
               "then", "also", "thus", "hence", "here", "recently", "similarly", "however", "later", "earlier", "but",
               "for", "when", "after", "before", "since", "although", "though", "yet", "so", "the", "this",
               "that", "these", "those", "our", "their", "his", "her", "its", "we", "they", "it"}


def _unclear_lead(before: str) -> bool:
    """Whether the word right before a narrative citation's names could belong to the author phrase: a connector
    (`and`, `&`, `et`, a trailing comma), a particle in any case, or a capitalised word that is not a common sentence
    opener. Then the parsed names may be only the tail of the phrase (`Smith and Van Berg` read as `Berg`)."""
    word = re.search(r"(\S+)\s*$", before)
    if word is None:
        return False
    token = word.group(1)
    bare = token.rstrip(".,;:").casefold()
    if token.endswith(",") or bare in ("and", "&", "et", "und") or bare in PARTICLES:
        return True
    return token[:1].isupper() and bare not in _LEAD_WORDS


def _capitalised(names: list[str]) -> bool:
    return all(name.split()[-1][:1].isupper() for name in names)


def _split_names(text: str) -> list[str]:
    return [n.strip() for n in re.split(r"\s*,?\s*(?<![^\s,])(?:and|&)\s+|\s*,\s*", text.strip()) if n.strip()]


def _year_targets(names: list[str], et_al: bool, years: str, value_names: str) -> list[Target]:
    targets = []
    for token in re.split(r"\s*,\s*", years.strip()):
        year, suffix = int(token[:4]), token[4:] or None
        targets.append(Target("author_year", f"{value_names}{' et al.' if et_al else ''}, {token}",
                              names=tuple(names), et_al=et_al, year=year, suffix=suffix))
    return targets


class _Markers(list):
    """Marker candidates as they are found; one past `MAX_MARKERS` refuses the draft before any later pass runs.
    Overlapping candidates count too, so the cap is on what was scanned, never a cut list."""

    def append(self, marker: Marker) -> None:
        if len(self) >= MAX_MARKERS:
            raise DraftRefused(413, "draft_too_many_markers", f"The draft has more than {MAX_MARKERS} citation markers")
        super().append(marker)


def _latex(text: str, markers: _Markers) -> None:
    for match in _CITE.finditer(text):
        keys = [k.strip() for k in match.group(2).split(",")]
        ok = bool(keys) and all(_CITE_KEY.fullmatch(k) for k in keys)
        markers.append(Marker(match.start(), match.end(), match.group(0), "latex", "recognized" if ok else "unrecognized",
                              [Target("key", k) for k in dict.fromkeys(keys)] if ok else []))
    covered = sorted((m.start, m.end) for m in markers if m.style == "latex")
    starts = [a for a, _ in covered]
    for head in _CITE_HEAD.finditer(text):  # a cite command whose braces could not be read
        i = bisect.bisect_right(starts, head.start()) - 1
        if i < 0 or not covered[i][0] <= head.start() < covered[i][1]:
            markers.append(Marker(head.start(), head.end(), head.group(0), "latex", "unrecognized"))


def _numbers(content: str) -> list[int] | None:
    numbers: list[int] = []
    for item in re.split(r"[,;]", content):
        match = _NUMBER_ITEM.match(item)
        if not match:
            return None
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        if first < 1 or last < first or last - first > MAX_RANGE:
            return None
        numbers.extend(range(first, last + 1))
    return numbers


def _numeric(text: str, markers: _Markers) -> None:
    for match in _GROUP.finditer(text):
        raw, after = match.group(0), text[match.end():match.end() + 1]
        if after in ("(", ":") or raw.startswith("[^"):
            continue  # a Markdown link, link definition or footnote
        brackets = list(re.finditer(r"\[([^\[\]]*)\]", raw))
        separators = [raw[a.end():b.start()].strip() for a, b in zip(brackets, brackets[1:])]
        numbers: list[int] | None = []
        for i, bracket in enumerate(brackets):
            got = _numbers(bracket.group(1))
            if got is None:
                numbers = None
                break
            if i and separators[i - 1] and separators[i - 1] in _DASH:  # `[3]–[5]`
                if len(got) != 1 or len(_numbers(brackets[i - 1].group(1)) or []) != 1:
                    numbers = None
                    break
                first, last = numbers[-1], got[0]
                if last <= first or last - first > MAX_RANGE:
                    numbers = None
                    break
                numbers.extend(range(first + 1, last + 1))
            else:
                numbers.extend(got)
        if numbers is not None:
            markers.append(Marker(match.start(), match.end(), raw, "numeric", "recognized",
                                  [Target("number", str(n)) for n in dict.fromkeys(numbers)]))
            continue
        content = " ".join(b.group(1) for b in brackets).strip()
        if content in _IGNORED_BRACKETS:
            continue
        if re.search(r"[\d@]", content) or re.fullmatch(r"\S{1,30}", content):
            markers.append(Marker(match.start(), match.end(), raw, "numeric", "unrecognized"))


def _author_year(text: str, markers: _Markers) -> None:
    for match in _YEARS_ONLY.finditer(text):  # narrative: `Zeng et al. (2022)`
        before = text[max(0, match.start() - 160):match.start()]
        names, position = None, 0
        # The longest run of capitalised names that ends right before the parenthesis.
        while (candidate := _NARRATIVE_NAMES.search(before, position)) is not None:
            if _capitalised(_split_names(candidate.group("names"))):
                names = candidate
                break
            position = candidate.start() + 1
        if names is None:
            continue
        found = _split_names(names.group("names"))
        start = match.start() - (len(before) - names.start())
        # The names may begin before the look-back window, or the word before them may be part of the phrase.
        if (names.start() == 0 and match.start() > len(before)) or _unclear_lead(before[:names.start()]):
            markers.append(Marker(start, match.end(), text[start:match.end()], "author_year", "unrecognized"))
            continue
        markers.append(Marker(start, match.end(), text[start:match.end()], "author_year", "recognized",
                              _year_targets(found, bool(names.group("etal")), match.group(1), names.group("names").strip())))
    for match in _PAREN.finditer(text):  # parenthetical: `(Zeng et al., 2022; Kim, 2021)`
        content = match.group(1)
        if _YEARS_ONLY.fullmatch(match.group(0)) or not any(
                _capitalised(_split_names(m.group("names"))[:1]) for m in _ITEM_START.finditer(content)):
            continue  # a year in parentheses, or a parenthesis that does not start like a citation
        targets: list[Target] | None = []
        for item in content.split(";"):
            parsed = _ITEM.match(_PREFIX.sub("", item).strip())
            if not parsed:
                targets = None
                break
            found = _split_names(parsed.group("names"))
            if not _capitalised(found):
                targets = None
                break
            targets.extend(_year_targets(found, bool(parsed.group("etal")), parsed.group("years"),
                                         parsed.group("names").strip()))
        markers.append(Marker(match.start(), match.end(), match.group(0), "author_year",
                              "recognized" if targets else "unrecognized", targets or []))


def find_markers(text: str, fmt: Format) -> list[Marker]:
    """Every marker in draft order; where two overlap, LaTeX wins over numeric, numeric over author–year, and the
    earlier start over the later."""
    found = _Markers()
    _latex(text, found)
    if fmt != "tex":
        _numeric(text, found)
    _author_year(text, found)
    rank = {"latex": 0, "numeric": 1, "author_year": 2}
    kept: list[Marker] = []
    for marker in sorted(found, key=lambda m: (rank[m.style], m.start)):
        if not any(marker.start < k.end and k.start < marker.end for k in kept):
            kept.append(marker)
    kept.sort(key=lambda m: m.start)
    return kept


def parse_draft(fmt: Format, text: str) -> Draft:
    if fmt == "tex":
        body, entries, origin = _tex_body(text)
        if not entries:
            body, entries, origin = _cut_list(body)
    else:
        body, entries, origin = _cut_list(text)
    markers = find_markers(body, fmt)
    marker_spans = [(m.start, m.end) for m in markers]
    spans = sentences(body, marker_spans)
    tables = _tables(body) if fmt == "tex" or any(m.style == "latex" for m in markers) else []
    for marker in markers:
        sentence = next(((a, b) for a, b in spans if a <= marker.start < b), (marker.start, marker.end))
        marker.sentence_start, marker.sentence_end = sentence
        latex = fmt == "tex" or marker.style == "latex"
        table = _innermost(tables, marker.start) if latex else None
        if table is not None:
            row = next((r for r in table.rows if r.start <= marker.start < r.end), None)
            claim = _row_claim(body, table, row, marker_spans)
            if row is not None:
                marker.sentence_start, marker.sentence_end = row.text_start, row.end
            if claim is None:  # fail-closed: no claim, no pair, nothing sent
                marker.status, marker.targets, marker.reason = "unrecognized", [], TABLE_LAYOUT_NOT_READ
            else:
                marker.claim, marker.claim_context = claim, table.caption
        else:
            cut = cut_markers(body, marker.sentence_start, marker.sentence_end, marker_spans)
            # A sentence that holds nothing but LaTeX commands keeps its text as written, never an empty claim.
            marker.claim = (plain_latex(cut) if latex else "") or re.sub(r"\s+", " ", cut).strip()
    return Draft(fmt, body, markers, entries, origin if entries else None)


def cut_markers(text: str, start: int, end: int, spans: list[tuple[int, int]]) -> str:
    """`text[start:end]` with every marker span inside it cut out, so a key, a number or a cited name never ranks a
    passage or becomes a part of the claim."""
    pieces, at = [], start
    for left, right in sorted(spans):
        if start <= left and right <= end and left >= at:
            pieces.append(text[at:left])
            at = right
    pieces.append(text[at:end])
    return "".join(pieces)


# ------------------------------------------------------------------------------------------------- the plain claim
#
# V5 pilot (D105): a LaTeX sentence is given to the model and to the coverage and span checks as plain text, so a part
# copied from it never has to copy LaTeX. The rules, applied the same way everywhere:
# - comments, `\label`, `\ref`-like commands, sectioning commands and spacing commands go with their arguments
#   (a footnote's and a caption's text stay); `\begin{…}` and `\end{…}` go and their content stays;
# - a command whose arguments are text (`\emph`, `\textbf`, `\textit`, any unknown one with brace arguments) keeps the
#   text of its arguments; `\textcolor{c}{x}` and `\href{u}{x}` keep x; an unknown command without arguments (a
#   person's tag macro such as `\tP`) goes;
# - a check mark (`\cmark`, `\checkmark`, `\ding{51}`, ✓, ✔) is the word "yes", a cross (`\xmark`, `\ding{55}`, ✗, ✘)
#   the word "no";
# - `~` is a space, `--` an en dash, `---` an em dash, `\%` `\&` `\$` `\#` `\_` the character, ``…'' curly quotes,
#   accents (`\'e`, `\"{o}`) the accented letter;
# - inline math (`$…$`, `\(…\)`) that converts one way (`simple_math`: letters, digits, simple operators, Greek
#   letters and relations as Unicode, one-token scripts) is written plain without delimiters; every other math (a
#   `\frac`, `\sqrt`, a grouped script of more than one token, `\left`, any other command, display math and math
#   environments) stays verbatim as `$…$` with its spaces collapsed, never a reading that two sources could share;
# - spaces are collapsed, with none before , . ; : ) ] and none after ( [.

_SECTIONING = {"part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph"}
_DROP_WITH_ARGS = {"label", "ref", "eqref", "autoref", "cref", "Cref", "pageref", "nameref", "footnotemark", "index",
                   "vspace", "hspace", "color", "pagecolor", "phantom", "hphantom", "vphantom",
                   "bibliographystyle", "bibliography", "includegraphics", "input", "include", "newcommand",
                   "renewcommand", "setlength", "addtolength", "arraystretch", "rule", "captionsetup",
                   "cline", "cmidrule", "addlinespace", "rowcolor", "cellcolor", "columncolor", "arrayrulecolor"
                   } | _SECTIONING
_LAST_ARG = {"textcolor", "colorbox", "href", "fcolorbox"}  # keep only the last argument
_WORDS = {"ldots": "…", "dots": "…", "textellipsis": "…", "textendash": "–", "textemdash": "—", "LaTeX": "LaTeX",
          "TeX": "TeX", "S": "§", "P": "¶", "textasciitilde": "~", "textbackslash": "\\", "textbar": "|",
          "textless": "<", "textgreater": ">", "copyright": "©", "textdegree": "°", "degree": "°", "times": "×",
          "textperthousand": "‰", "ss": "ß", "o": "ø", "O": "Ø", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
          "aa": "å", "AA": "Å", "l": "ł", "L": "Ł", "i": "ı"}
_MATH = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ",
         "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
         "xi": "ξ", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
         "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
         "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ",
         "Omega": "Ω", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠", "pm": "±", "mp": "∓",
         "times": "×", "cdot": "·", "approx": "≈", "sim": "∼", "simeq": "≃", "equiv": "≡", "propto": "∝",
         "infty": "∞", "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒", "in": "∈", "notin": "∉",
         "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩", "ll": "≪", "gg": "≫", "partial": "∂",
         "nabla": "∇", "sum": "∑", "prod": "∏", "int": "∫", "ell": "ℓ", "hbar": "ℏ", "star": "⋆", "ast": "∗",
         "circ": "∘", "prime": "′", "lvert": "|", "rvert": "|", "vert": "|", "lVert": "‖", "rVert": "‖",
         "langle": "⟨", "rangle": "⟩", "dagger": "†", "ldots": "…", "cdots": "⋯", "dots": "…"}
_MATH_SIZING = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr",
                "Biggl", "Biggr", "middle", "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits"}
_SPACING = {",": " ", ";": " ", ":": " ", " ": " ", "!": "", "/": "", "-": "", "quad": " ", "qquad": " ", "enspace": " ",
            "thinspace": " ", "medspace": " ", "thickspace": " ", "noindent": "", "par": " ", "newline": " ",
            "linebreak": " ", "centering": "", "raggedright": "", "raggedleft": "", "smallskip": " ",
            "medskip": " ", "bigskip": " ", "item": " ", "toprule": " ", "midrule": " ", "bottomrule": " ",
            "hline": " ", "tabularnewline": " "}
_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304", ".": "\u0307",
            "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "k": "\u0328", "r": "\u030a", "d": "\u0323"}
_YES_MACROS = {"cmark", "checkmark", "tick", "yes", "ok", "correct"}
_NO_MACROS = {"xmark", "cross", "crossmark", "no", "wrong"}
_YES_CHARS, _NO_CHARS = "✓✔☑🗸", "✗✘☒"
_MATH_ENVS = ("equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "displaymath",
              "math", "eqnarray", "eqnarray*", "flalign", "flalign*", "alignat", "alignat*")
_MATH_SPLIT = re.compile(r"\$\$(.+?)\$\$|(?<!\\)\$(.+?)(?<!\\)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]|"
                         r"\\begin\{(" + "|".join(re.escape(e) for e in _MATH_ENVS) + r")\}(.*?)\\end\{\5\}", re.DOTALL)


def _group(text: str, i: int, open_: str = "{", close: str = "}") -> int | None:
    """The index just past the balanced group that starts at `text[i]` (`{…}` or `[…]`), else None."""
    if i >= len(text) or text[i] != open_:
        return None
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def _args(text: str, i: int, spaces: bool) -> tuple[list[str], int]:
    """The brace arguments right after a command name ending at `i` (an optional `[…]` and a star skipped), and where
    they end. With `spaces`, spaces may stand before an argument."""
    args = []
    while True:
        j = i
        while spaces and j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] == "[" and (end := _group(text, j, "[", "]")) is not None:
            i = end
            continue
        if (end := _group(text, j)) is None:
            return args, i
        args.append(text[j + 1:end - 1])
        i = end


def _marks(text: str) -> str:
    """Check marks and crosses as the words yes and no, before any other rule reads the text."""
    text = re.sub(r"\\ding\s*\{\s*5[12]\s*\}", " yes ", text)
    text = re.sub(r"\\ding\s*\{\s*5[5-8]\s*\}", " no ", text)
    text = re.sub(r"\\(" + "|".join(_YES_MACROS) + r")(?![A-Za-z])(?:\s*\{\s*\})?", " yes ", text)
    text = re.sub(r"\\(" + "|".join(_NO_MACROS) + r")(?![A-Za-z])(?:\s*\{\s*\})?", " no ", text)
    text = re.sub(f"[{_YES_CHARS}]", " yes ", text)
    return re.sub(f"[{_NO_CHARS}]", " no ", text)


def _commands(text: str, math: bool) -> str:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        name_match = re.match(r"[A-Za-z@]+\*?|.", text[i + 1:], re.DOTALL)
        if not name_match:
            i += 1
            continue
        name = name_match.group(0)
        end = i + 1 + len(name)
        bare = name.rstrip("*")
        if name in _ACCENTS and not math:  # `\'e`, `\"{o}`, `\c c`
            j = end + (1 if name.isalpha() and end < len(text) and text[end] == " " else 0)
            if (stop := _group(text, j)) is not None:
                base, i = text[j + 1:stop - 1], stop
            else:
                base, i = text[j:j + 1], j + 1
            out.append(unicodedata.normalize("NFC", (base[:1] + _ACCENTS[name] + base[1:]) if base else ""))
            continue
        if name == "\\":  # a line break; a word hyphenated across it is joined
            i = end
            if end < len(text) and text[end] == "[" and (stop := _group(text, end, "[", "]")) is not None:
                i = stop
            if not (out and out[-1] == "-"):
                out.append(" ")
            continue
        if not name.isalpha() and not bare.isalpha():
            if name in _SPACING:
                out.append(_SPACING[name])
            else:  # `\%`, `\&`, `\{` … the character itself; an escaped brace outlives the grouping braces removed later
                out.append({"{": _OPEN, "}": _CLOSE}.get(name, name))
            i = end
            continue
        if bare in ("begin", "end"):
            _, i = _args(text, end, True)  # the environment's name and arguments (a tabular's width and columns)
            out.append(" ")
            continue
        if bare in _SPACING:
            out.append(_SPACING[bare])
            _, i = _args(text, end, False) if bare in ("toprule", "midrule", "bottomrule") else ([], end)
            continue
        if bare in _DROP_WITH_ARGS:
            _, i = _args(text, end, True)
            out.append(" ")
            continue
        if math and bare in _MATH_SIZING:
            i = end
            continue
        if math and bare in ("frac", "tfrac", "dfrac", "cfrac"):
            j = end
            parts = []
            for _ in range(2):
                while j < len(text) and text[j] == " ":
                    j += 1
                if (stop := _group(text, j)) is not None:
                    parts.append(_commands(text[j + 1:stop - 1], True))
                    j = stop
                elif j < len(text):
                    parts.append(text[j])
                    j += 1
            out.append("/".join(parts))
            i = j
            continue
        if math and bare == "sqrt":
            args, i = _args(text, end, True)
            out.append("√" + "".join(_commands(a, True) for a in args))
            continue
        args, i_after = _args(text, end, bare in ("emph", "textbf", "textit", "text", "mathrm"))
        if bare in _LAST_ARG and args:
            out.append(_commands(args[-1], math))
            i = i_after
            continue
        table = _MATH if math else _WORDS
        if bare in table:
            out.append(table[bare])
            i = end
            continue
        if args:
            out.append(" ".join(_commands(a, math) for a in args))
            i = i_after
            continue
        if math:
            out.append(bare)  # an operator name or a person's symbol macro: `\exp`, `\Reta`
        i = end
    return "".join(out)


_OPEN, _CLOSE = "\x00(", "\x00)"  # an escaped brace while the grouping braces are removed


def _ungroup(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace(_OPEN, "{").replace(_CLOSE, "}")


def _text_rules(text: str) -> str:
    text = text.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”")
    text = _commands(text, False)
    return _ungroup(text.replace("~", " "))


_MATH_SPACES = {",", ";", ":", " ", "quad", "qquad"}
_MATH_PLAIN = set("+-=<>/*,.()|!'")


def _math_script(inner: str) -> str | None:
    """A sub- or superscript that is one token: one ASCII letter or digit, or one command of `_MATH`."""
    inner = inner.strip()
    if len(inner) == 1 and inner.isascii() and inner.isalnum():
        return inner
    command = re.fullmatch(r"\\([A-Za-z]+)", inner)
    return _MATH[command.group(1)] if command and command.group(1) in _MATH else None


def simple_math(body: str) -> str | None:
    """Inline math as plain text, only when it converts one way (Sol round 1, D105): ASCII letters and digits, spaces,
    `+ - = < > / * , . ( ) | ! '`, the commands of `_MATH` (Greek letters, relations) and math spacing, and a sub- or
    superscript of one token (`x^2`, `x_{i}`, `e^{\\tau}`). Anything else (`\\frac`, `\\sqrt`, `\\left`, a grouped script
    of more than one token, braces, any other command or character) gives None, and the math stays verbatim."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            command = re.match(r"\\([A-Za-z]+|[,;: ])", body[i:])
            if command is None:
                return None
            name = command.group(1)
            if name in _MATH:
                out.append(_MATH[name])
            elif name in _MATH_SPACES:
                out.append(" ")
            else:
                return None
            i += command.end()
            continue
        if c in "^_":
            j = i + 1
            if j < len(body) and body[j] == "{":
                stop = _group(body, j)
                script = _math_script(body[j + 1:stop - 1]) if stop is not None else None
                if script is None:
                    return None
                out.append(c + script)
                i = stop
                continue
            command = re.match(r"\\[A-Za-z]+", body[j:])
            script = _math_script(command.group(0) if command else body[j:j + 1])
            if script is None:
                return None
            out.append(c + script)
            i = j + (command.end() if command else 1)
            continue
        if c.isspace():
            out.append(" ")
        elif (c.isascii() and c.isalnum()) or c in _MATH_PLAIN:
            out.append(c)
        else:
            return None
        i += 1
    return " ".join("".join(out).split())


def plain_latex(text: str) -> str:
    """A LaTeX sentence as plain text, by the rules above; the same text gives the same result. Math that does not
    convert one way (`simple_math`), display math and math environments stay verbatim between `$…$`, with only their
    spaces collapsed: the model copies that span whole, and the coverage and span checks read it as one token."""
    text = strip_comments(text)
    pieces, kept, at = [], [], 0
    for match in _MATH_SPLIT.finditer(text):
        pieces.append(_text_rules(_marks(text[at:match.start()])))
        body = next(g for g in (match.group(1), match.group(2), match.group(3), match.group(4), match.group(6))
                    if g is not None)
        inline = match.group(2) is not None or match.group(3) is not None
        plain = simple_math(body) if inline else None
        if plain is None:
            kept.append("$" + " ".join(body.split()) + "$")
            pieces.append(f"\x00{len(kept) - 1}\x00")  # left alone by the spacing rules below
        else:
            pieces.append(plain)  # inline math stays attached: `m$^2$` is m^2
        at = match.end()
    pieces.append(_text_rules(_marks(text[at:])))
    plain = re.sub(r"\s+", " ", "".join(pieces))
    plain = re.sub(r"\s+([,.;:!?)\]])", r"\1", plain)
    plain = re.sub(r"([(\[])\s+", r"\1", plain)
    plain = unicodedata.normalize("NFC", plain).strip()
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], plain)


# ------------------------------------------------------------------------------------------------------- tables
#
# A citation inside a `tabular` (also `tabular*`, `tabularx`, `tabulary`, `longtable`) is checked against the row it
# sits in of its innermost table, never the whole table. The row is written as "Header: cell" pairs, each header from
# the first row of the same tabular, cells by the plain-claim rules above (so a check mark reads "yes" and a cross
# "no"), joined by "; ". The first column's pair comes first, then every other column with a value, in table order,
# then the columns whose cell is "no", in table order: a cross claims nothing the passages could state, and grouped at
# the end one claim part can hold them all. An empty cell is left out; a header missing for a column reads "Column n".
# The table's caption, when it has at most `MAX_CAPTION_CHARS` characters (else its first sentence, when that does), is
# given to the model as context: it says what the columns and the marks mean, and no part copies it.
#
# Whitelist (D105, Sol round 2): a row is read only when its innermost tabular is simple, and a layout that is not is
# never guessed. Simple means: no `\multicolumn`, `\multirow`, `\cline`, `\cmidrule`, nested tabular or `\\[…]` row
# split anywhere in that tabular's body, and it is inside no other tabular; the header is exactly its first row with text, and the next row starts with a
# rule (`\hline` or `\midrule`; a `\toprule` before the header is fine), so there is no second header line; the citation
# sits in a data row after that rule; and the row, its leading rule and spacing commands stripped, has exactly as many
# cells as the header. Only the commands of an explicit allowlist may stand in the tabular's body (`_BODY_COMMANDS`, the
# citation markers themselves, and inside math `_MATH`, math spacing and `_TABLE_MATH`) and in its column spec and width
# (`_SPEC_COMMANDS`); any other command, a user macro above all, could hide a cell or a row. In a draft that is not
# `.tex` (where comments are not removed) a comment `%` in the body also refuses the table. Anything else makes the
# marker `unrecognized` with the reason `table_layout_not_read`: no claim, no pair, nothing reaches a model.

MAX_CAPTION_CHARS = 600
TABLE_LAYOUT_NOT_READ = "table_layout_not_read"
_TABULAR_NAMES = r"tabular\*?|tabularx|tabulary|longtable"
_TABULAR = re.compile(r"\\begin\{(" + _TABULAR_NAMES + r")\}")
_TABULAR_EDGE = re.compile(r"\\(begin|end)\{(?:" + _TABULAR_NAMES + r")\}")
_TABLE_ENV = re.compile(r"\\begin\{(table\*?|longtable)\}.*?\\end\{\1\}", re.DOTALL)
_ROW_LEAD = re.compile(r"(?:\s|\\(?:toprule|midrule|bottomrule|hline|headrow|centering)\b|"
                       r"\\(?:cline|cmidrule|rowcolor|addlinespace)\s*(?:\([^)]*\))?\s*(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})*)*")
_BODY_COMMANDS = ({"hline", "midrule", "toprule", "bottomrule", "addlinespace", "rowcolor", "shortstack", "textbf",
                   "textit", "emph", "textsc", "texttt", "underline", "tabularnewline", "ding"}
                  | _YES_MACROS | _NO_MACROS | {"\\", "&", "%", "_", "#", "$", ","})
_SPEC_COMMANDS = {"extracolsep", "fill", "linewidth", "textwidth", "columnwidth", "\\"}
_TABLE_MATH = {"frac", "tfrac", "dfrac", "sqrt", "left", "right", "min", "max", "log", "ln", "exp", "mathrm", "times",
               "cdot", "pm", "approx", "sim", "infty"}
_COMMAND = re.compile(r"\\([A-Za-z@]+|.)", re.DOTALL)  # a name with `@` is one name (Sol round 4)
_HEADER_RULE = re.compile(r"\\(?:midrule|hline)\b")
_NOT_SIMPLE = re.compile(r"\\(?:multicolumn|multirow|cline|cmidrule)\b|\\begin\{(?:" + _TABULAR_NAMES + r")\}|"
                         r"(?:\\\\|\\tabularnewline)\s*\[")


@dataclass(frozen=True)
class _Row:
    start: int  # where the row's text begins after the separator before it
    text_start: int  # the first cell's text, rule commands before it skipped
    end: int
    cells: tuple[tuple[int, int], ...]
    nested: bool  # a tabular inside the row


@dataclass(frozen=True)
class _Table:
    body: tuple[int, int]  # from `\\begin{…}` to the body's end, for finding the innermost table
    inner: tuple[int, int]  # the body alone, between the column spec and `\\end{…}`
    spec: tuple[int, int]  # the width and column spec after `\\begin{…}`
    rows: tuple[_Row, ...]
    caption: str | None
    enclosed: bool = False  # inside another tabular's body


def _tabular_end(text: str, body_start: int) -> tuple[int, int]:
    """Where the body of a tabular whose head ends at `body_start` ends, nested tabulars skipped, and where its
    `\\end{…}` ends; an unclosed one runs to the end of the text."""
    depth = 0
    for edge in _TABULAR_EDGE.finditer(text, body_start):
        if edge.group(1) == "begin":
            depth += 1
        elif depth:
            depth -= 1
        else:
            return edge.start(), edge.end()
    return len(text), len(text)


def _tabular_rows(text: str, start: int, end: int) -> list[_Row]:
    """The rows of a tabular body: row and cell separators count only outside braces and outside nested tabulars."""
    rows, cells = [], []
    row_start = cell_start = start
    depth, i, nested, row_nested = 0, start, 0, False
    while i < end:
        c = text[i]
        if c == "\\":
            edge = _TABULAR_EDGE.match(text, i)
            if edge:
                nested += 1 if edge.group(1) == "begin" else -1
                row_nested = True
                i = edge.end()
                continue
            if depth == 0 and nested == 0 and (text.startswith("\\\\", i) or text.startswith("\\tabularnewline", i)):
                cells.append((cell_start, i))
                rows.append((row_start, i, tuple(cells), row_nested))
                i += 2 if text.startswith("\\\\", i) else len("\\tabularnewline")
                if i < end and text[i] == "[" and (stop := _group(text, i, "[", "]")) is not None:
                    i = stop
                row_start = cell_start = i
                cells, row_nested = [], False
                continue
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "&" and depth == 0 and nested == 0:
            cells.append((cell_start, i))
            cell_start = i + 1
        i += 1
    cells.append((cell_start, end))
    rows.append((row_start, end, tuple(cells), row_nested))
    out = []
    for a, b, row_cells, has_nested in rows:
        lead = _ROW_LEAD.match(text, a, b)
        text_start = lead.end() if lead else a
        if has_nested or any(plain_latex(text[x:y]) for x, y in row_cells):
            out.append(_Row(a, max(text_start, a), b, row_cells, has_nested))
    return out


def _caption(block: str) -> str | None:
    head = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*(?=\{)", block)
    if head is None or (stop := _group(block, head.end())) is None:
        return None
    caption = plain_latex(block[head.end() + 1:stop - 1])
    if len(caption) <= MAX_CAPTION_CHARS:
        return caption or None
    first = sentences(caption)
    return caption[first[0][0]:first[0][1]] if first and first[0][1] - first[0][0] <= MAX_CAPTION_CHARS else None


def _tables(text: str) -> list[_Table]:
    blocks = [(m.start(), m.end()) for m in _TABLE_ENV.finditer(text)]
    tables = []
    for head in _TABULAR.finditer(text):
        _, body_start = _args(text, head.end(), True)
        body_end, _ = _tabular_end(text, body_start)
        block = next(((a, b) for a, b in blocks if a <= head.start() < b), None)
        tables.append(_Table((head.start(), body_end), (body_start, body_end), (head.end(), body_start),
                             tuple(_tabular_rows(text, body_start, body_end)),
                             _caption(text[block[0]:block[1]]) if block else None))
    return [replace(t, enclosed=any(o is not t and o.inner[0] <= t.body[0] < o.inner[1] for o in tables))
            for t in tables]


def _innermost(tables: list[_Table], at: int) -> _Table | None:
    holding = [t for t in tables if t.body[0] <= at < t.body[1]]
    return min(holding, key=lambda t: t.body[1] - t.body[0]) if holding else None


def _commands_allowed(text: str, table: _Table, markers: list[tuple[int, int]]) -> bool:
    for command in _COMMAND.finditer(text, table.spec[0], table.spec[1]):
        if command.group(1) not in _SPEC_COMMANDS:
            return False
    body = text[table.inner[0]:table.inner[1]]
    math = [(m.start() + table.inner[0], m.end() + table.inner[0]) for m in _MATH_SPLIT.finditer(body)]
    for command in _COMMAND.finditer(text, table.inner[0], table.inner[1]):
        at, name = command.start(), command.group(1)
        if name in _CITE_COMMANDS and any(a <= at < b for a, b in markers):
            continue  # the command of a citation marker the parser found; anything else in a marker is checked
        if any(a <= at < b for a, b in math):
            if name not in _MATH and name not in _MATH_SPACES and name not in _TABLE_MATH:
                return False
        elif name not in _BODY_COMMANDS:
            return False
    return True


def _simple(text: str, table: _Table, markers: list[tuple[int, int]]) -> bool:
    """The whitelist above, for the table as a whole."""
    if table.enclosed or _NOT_SIMPLE.search(text, table.inner[0], table.inner[1]) or len(table.rows) < 2:
        return False
    if _COMMENT.search(text, table.inner[0], table.inner[1]) or not _commands_allowed(text, table, markers):
        return False
    after_header = table.rows[1]
    return _HEADER_RULE.search(text, after_header.start, after_header.text_start) is not None


def _row_claim(text: str, table: _Table, row: _Row | None, markers: list[tuple[int, int]]) -> str | None:
    """The row's claim, or None when the table is not simple or the citation is not in one of its data rows."""
    if row is None or not _simple(text, table, markers) or row is table.rows[0]:
        return None
    headers = [plain_latex(cut_markers(text, a, b, markers)) for a, b in table.rows[0].cells]
    if len(row.cells) != len(headers):
        return None
    first, rest, crosses = [], [], []
    for k, (a, b) in enumerate(row.cells):
        value = plain_latex(cut_markers(text, max(a, row.text_start) if k == 0 else a, b, markers))
        if value:
            pair = f"{headers[k] or f'Column {k + 1}'}: {value}"
            (first if k == 0 else crosses if value == "no" else rest).append(pair)
    return "; ".join(first + rest + crosses) or None


# ---------------------------------------------------------------------------------------- fields of a written entry

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
_ARXIV = re.compile(r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))"
                    r"(?:v\d+)?", re.IGNORECASE)
_PAREN_YEAR = re.compile(rf"\(({_YEAR})([a-z])?\)")
_ANY_YEAR = re.compile(rf"(?<![\d/.])({_YEAR})([a-z])?(?![\d])")
_QUOTED = re.compile(r"[“\"]([^”\"]{4,400})[”\"]")
_INITIALS = re.compile(r"^(?:[^\W\d_]\.\s*-?\s*)+$")


def doi_of(text: str) -> str | None:
    match = _DOI.search(text)
    return match.group(0).rstrip(".,;)]}").lower() if match else None


def arxiv_of(text: str) -> str | None:
    match = _ARXIV.search(text)
    if match:
        return match.group(1)
    doi = doi_of(text)
    if doi and doi.startswith("10.48550/arxiv."):
        return doi.removeprefix("10.48550/arxiv.")
    return None


def _fold(word: str) -> str:
    text = unicodedata.normalize("NFKD", word)
    return "".join(c for c in text if c.isalpha() and not unicodedata.combining(c)).casefold()


def surname_fold(surname: str) -> str:
    """A surname the source wrote as one (the part before the comma of `Last, First`): every word kept, folded."""
    return " ".join(f for f in (_fold(w) for w in re.split(r"\s+", surname.strip())) if f)


def surname_key(name: str) -> str:
    """The surname of a name with its particles, accents and case folded, letters only: the last word, and the
    particles (`PARTICLES`, in any case) right before it. `van der Berg`, `Anna van der Berg` and `Van der Berg` give
    `van der berg`, `De Vries` gives `de vries`, and `Berg` or `A. Berg` give `berg`. The same function reads both the
    draft and the bibliography, so a given name that looks like a particle (`Van Morrison`) misses a match rather
    than making a wrong one."""
    words = [w for w in re.split(r"\s+", name.strip()) if w and not _INITIALS.fullmatch(w)]
    if not words:
        return ""
    surname = [words[-1]]
    for i in range(len(words) - 2, -1, -1):
        if words[i].casefold() not in PARTICLES:
            break
        surname.insert(0, words[i])
    return " ".join(f for f in (_fold(w) for w in surname) if f)


def written_entry_fields(raw: str) -> dict:
    """DOI, arXiv id, title, authors and year of an entry of the draft's own list, read only where the entry's form
    makes them clear: the title in quotes (IEEE) or after `(year).` (APA), the authors before it. Missing stays None."""
    text = re.sub(r"\s+", " ", raw).strip()
    without_ids = _DOI.sub(" ", _ARXIV.sub(" ", text))
    year_match = _PAREN_YEAR.search(without_ids)
    if year_match is None:
        years = list(_ANY_YEAR.finditer(without_ids))
        year_match = years[-1] if years else None
    title, authors_part = None, ""
    quoted = _QUOTED.search(text)
    if quoted:
        title, authors_part = quoted.group(1).strip().rstrip(",."), text[:quoted.start()]
    elif year_match is not None and year_match.re is _PAREN_YEAR:
        after = text[text.find(year_match.group(0)) + len(year_match.group(0)):].lstrip(" .")
        head = re.match(r"(.+?[^A-Z])[.?!](?:\s|$)", after)
        title = head.group(1).strip() if head else None
        authors_part = text[:text.find(year_match.group(0))]
    authors = []
    for piece in re.split(r",|\s+and\s+|\s*&\s*", authors_part):
        piece = piece.strip(" .")
        if piece and not _INITIALS.fullmatch(piece + ".") and piece.lower() not in ("et al", "others"):
            authors.append(piece)
    return {"doi": doi_of(text), "arxiv_id": arxiv_of(text), "title": title or None, "authors": authors,
            "year": int(year_match.group(1)) if year_match else None,
            "year_suffix": year_match.group(2) if year_match else None}
