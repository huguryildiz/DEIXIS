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
from dataclasses import dataclass, field
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


def _check_list_size(count: int) -> None:
    """A reference list over the cap is refused whole: a cut list could leave out the one entry a marker names, or the
    second entry with its number, and a match on what is left would look exact."""
    if count > MAX_LIST_ENTRIES:
        raise DraftRefused(413, "draft_list_too_long",
                           f"The draft's reference list has more than {MAX_LIST_ENTRIES} entries")


def _tex_body(text: str) -> tuple[str, list[ListEntry], str | None]:
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)  # comments
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
_CITE_HEAD = re.compile(r"\\(?:" + "|".join(_CITE_COMMANDS) + r")\*?(?![A-Za-z])")
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
    spans = sentences(body, [(m.start, m.end) for m in markers])
    for marker in markers:
        sentence = next(((a, b) for a, b in spans if a <= marker.start < b), (marker.start, marker.end))
        marker.sentence_start, marker.sentence_end = sentence
    return Draft(fmt, body, markers, entries, origin if entries else None)


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
