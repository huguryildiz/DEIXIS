"""BibTeX and RIS files into the Library (UI parity S19b, F14).

Parsing is fail-closed per entry: an entry the parser cannot read completely (an unclosed brace, a field without a
value, an undefined @string, a RIS record without `ER`, no title, a malformed DOI) is reported with its position and
left out; the entries around it still import. No new dependency: the subset read is the one reference managers write
(Zotero, JabRef, Mendeley, EndNote exports), with LaTeX accents turned into Unicode. Known limits: an entry starts
at any `@type{` (as in BibTeX), so a field value that holds `@word{` literally is read as unclosed; `@comment(…)`
skips only its keyword; only `@string` macros and the month names are expanded.

Parsing is bounded: the file is at most `MAX_FILE_BYTES`, both parsers stop with a refusal once entries and errors
together pass `MAX_ENTRIES` (successful @string definitions count too), a field value never scans past the next entry
head, and line numbers are counted in one pass. @string expansion is measured before it is copied: a value over
`MAX_VALUE_CHARS` is an error of its entry (or @string), and a file whose values together pass `EXPANSION_FACTOR` times
its length is refused whole (`import_expansion_too_large`). The route runs it off the event loop.

An entry's DOI is resolved through the existing lookups: OpenAlex `works_by_dois` for up to 100 DOIs a request, then
Crossref `crossref_work` one DOI at a time for the DOIs OpenAlex did not confirm (at most `CROSSREF_FALLBACK_MAX`). A
confirmed DOI stores the provider's record, merged by DOI with a stored record under the existing rules
(`Store.upsert_provider_source`), and the entry's own fields are not written. A record a DOI names is used only when
its title and year agree exactly with the entry's (`titles_agree`); otherwise a mistyped DOI would put another paper, and its abstract,
under the entry. An entry whose DOI no provider confirmed reuses a stored record with that DOI that agrees the same way,
else becomes a record of its own under the `reference_file` mapping that never merges by DOI (as a Zotero item does
not); its identity is DOI, title, year and first author together (`identity`), never the DOI alone, and a record made
before for the same entry is reused as it stands, never filled from a later entry. So a mistyped DOI cannot take over
another work's record, nor join one as its version through an arXiv DOI
(`store.UNVERIFIED_DOI_PROVIDERS`). Its metadata
stays `user_supplied` until a provider confirms it. Versions are never merged: one entry is one source version.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from deixis.providers import crossref, lookup, openalex
from deixis.providers.common import ProviderRecord, normalize_doi, year_of
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import new_id, transaction
from deixis.workflow import library_items
from deixis.workflow.store import Store

Format = Literal["bibtex", "ris"]

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 500
# @string expansion is bounded before anything is copied: one field value (macros joined with `#`) holds at most
# MAX_VALUE_CHARS characters, else that entry (or @string) is an error; all values of the file together hold at most
# EXPANSION_FACTOR times the file's length (at least MIN_EXPANSION_BUDGET), else the whole file is refused.
MAX_VALUE_CHARS = 64 * 1024
MAX_KEY_CHARS = 200  # a citation key or RIS ID as reported back
EXPANSION_FACTOR = 4
MIN_EXPANSION_BUDGET = 1024 * 1024
CROSSREF_FALLBACK_MAX = 20
PROVIDER = "reference_file"  # one of store.UNVERIFIED_DOI_PROVIDERS and library_items.USER_SUPPLIED_PROVIDERS
ORIGINS = {"bibtex": "bibtex_import", "ris": "ris_import"}
ABSTRACT_ORIGINS = {"bibtex": "user_bibtex_abstract", "ris": "user_ris_abstract"}
_DOI = re.compile(r"10\.\d{4,9}/\S+")


class ImportRefused(Exception):
    """The whole file is refused; `code` lets the page translate the sentence."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass(frozen=True)
class Entry:
    index: int  # 1-based position among the file's entries
    key: str | None  # the BibTeX citation key or the RIS `ID`
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    publication_type: str | None
    doi: str | None
    url: str | None
    abstract: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    fields: dict[str, Any] = field(default_factory=dict, repr=False)  # the entry as read, kept as the record's payload


@dataclass(frozen=True)
class EntryError:
    index: int | None  # the entry's position among the file's entries; None for text that is no entry
    line: int  # where the entry or the text starts in the file, from 1
    key: str | None
    code: str
    message: str

    def view(self) -> dict[str, Any]:
        return {"index": self.index, "line": self.line, "key": self.key, "code": self.code, "message": self.message}


class _Malformed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------------------------- text

def decode(data: bytes) -> str:
    """UTF-8 (with or without a BOM) or UTF-16 with a BOM; anything else is read as Windows-1252, which every byte
    decodes in, so an older Latin export still reads. Binary content (a NUL byte in an 8-bit file) is refused."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            raise ImportRefused(422, "import_not_text", "The file is not readable text") from None
    if b"\x00" in data:
        raise ImportRefused(422, "import_not_text", "The file is not readable text")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def detect_format(filename: str | None, text: str) -> Format:
    suffix = Path(filename or "").suffix.lower()
    if suffix in (".bib", ".bibtex"):
        return "bibtex"
    if suffix == ".ris":
        return "ris"
    head = text.lstrip()
    if re.match(r"TY  -", head):
        return "ris"
    # An entry head anywhere, as the parser reads one; a search that starts only at '@' signs stays linear (a
    # line-anchored `^\s*@` would rescan every run of blank lines once per line).
    if _HEAD.search(text):
        return "bibtex"
    raise ImportRefused(422, "import_unknown_format", "The file is neither BibTeX (.bib) nor RIS (.ris)")


_ACCENTS = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303", "=": "\u0304", ".": "\u0307",
            "u": "\u0306", "v": "\u030c", "H": "\u030b", "r": "\u030a", "c": "\u0327", "k": "\u0328", "d": "\u0323",
            "b": "\u0331"}
_LETTERS = {"ss": "ß", "o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "aa": "å",
            "AA": "Å", "i": "ı", "j": "ȷ"}
_WORDS = {"LaTeX": "LaTeX", "TeX": "TeX", "textendash": "–", "textemdash": "—", "ldots": "…", "dots": "…",
          "textquoteright": "’", "textquoteleft": "‘", "textquotedblleft": "“", "textquotedblright": "”",
          "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^", "textregistered": "®",
          "texttrademark": "™", "textcopyright": "©", "textdegree": "°", "S": "§", "P": "¶"}
# Escaped specials survive brace removal as private-use characters until the end.
_ESCAPES = {c: chr(0xE000 + i) for i, c in enumerate("&%$#_{}")}


def _accented(base: str, mark: str) -> str:
    base = {"\\i": "i", "\\j": "j"}.get(base, base)
    return unicodedata.normalize("NFC", base + mark)


def _plain(segment: str) -> str:
    s = re.sub(r"\\([&%$#_{}])", lambda m: _ESCAPES[m.group(1)], segment)
    s = re.sub(r"\\([\"'`^~=.])\s*(?:\{\s*(\\[ij]|[A-Za-z])\s*\}|(\\[ij](?![A-Za-z])|[A-Za-z]))",
               lambda m: _accented(m.group(2) or m.group(3), _ACCENTS[m.group(1)]), s)
    s = re.sub(r"\\([uvHrckdb])(?:\s*\{\s*(\\[ij]|[A-Za-z])\s*\}|\s+(\\[ij](?![A-Za-z])|[A-Za-z]))",
               lambda m: _accented(m.group(2) or m.group(3), _ACCENTS[m.group(1)]), s)
    s = re.sub(r"\\(ss|ae|AE|oe|OE|aa|AA|o|O|l|L|i|j)(?![A-Za-z])\s*(?:\{\})?", lambda m: _LETTERS[m.group(1)], s)
    s = re.sub(r"\\([A-Za-z]+)\s*(?:\{\})?", lambda m: _WORDS.get(m.group(1), ""), s)
    s = s.replace("\\\\", " ").replace("\\ ", " ")
    s = s.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”").replace("~", " ")
    s = s.replace("{", "").replace("}", "")
    for char, mark in _ESCAPES.items():
        s = s.replace(mark, char)
    return s


def latex_to_text(value: str) -> str:
    """A BibTeX field as plain Unicode text. Math between unescaped `$` stays as written, delimiters included."""
    parts = re.split(r"((?<!\\)\$[^$]*(?<!\\)\$)", value)
    text = "".join(part if part.startswith("$") and part.endswith("$") and len(part) > 1 else _plain(part)
                   for part in parts)
    return re.sub(r"\s+", " ", text).strip()


def _person(parts: list[str], suffix_last: bool = False) -> str:
    """A name in parts as a display name (`First Last`, `First Last Jr`); one part stays as written. BibTeX writes
    `Last, Jr, First`; RIS writes `Last, First, Jr` (`suffix_last`)."""
    parts = [p.strip() for p in parts]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[1]} {parts[0]}".strip()
    last, first, suffix = (parts[0], parts[1], " ".join(parts[2:])) if suffix_last else \
        (parts[0], " ".join(parts[2:]), parts[1])
    return re.sub(r"\s+", " ", f"{first} {last} {suffix}").strip()


def _split_top(value: str, separator: re.Pattern[str]) -> list[str]:
    """Split where `separator` matches at brace depth 0."""
    out, depth, start, i = [], 0, 0, 0
    while i < len(value):
        char = value[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0:
            match = separator.match(value, i)
            if match:
                out.append(value[start:i])
                start = i = match.end()
                continue
        i += 1
    out.append(value[start:])
    return out


def _bibtex_authors(value: str) -> list[str]:
    names = []
    # Whitespace collapsed first: the separator is tried at every position, and `\s+` over a long run would rescan it.
    for raw in _split_top(re.sub(r"\s+", " ", value), re.compile(r" and ", re.IGNORECASE)):
        raw = raw.strip()
        if not raw or raw.lower() == "others":
            continue
        if raw.startswith("{") and raw.endswith("}") and _balanced(raw[1:-1]):
            names.append(latex_to_text(raw))  # a braced corporate name, as written
            continue
        name = _person([latex_to_text(p) for p in _split_top(raw, re.compile(r","))])
        if name:
            names.append(name)
    return names


def _balanced(value: str) -> bool:
    depth = 0
    for i, char in enumerate(value):
        if char in "{}" and i and value[i - 1] == "\\":
            continue
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


def _verbatim(value: str | None) -> str | None:
    """A DOI or URL field: escapes undone and grouping braces dropped, nothing else changed (`--` stays `--`)."""
    if value is None:
        return None
    text = re.sub(r"\\([&%$#_{}~])", lambda m: _ESCAPES[m.group(1)] if m.group(1) in "{}" else m.group(1), value)
    text = text.replace("{", "").replace("}", "")
    for char, mark in _ESCAPES.items():
        text = text.replace(mark, char)
    return text.strip() or None


def _doi(value: str | None, url: str | None) -> tuple[str | None, bool]:
    """The entry's DOI, and whether a DOI given in the DOI field is malformed."""
    raw = (value or "").strip()
    if raw:
        doi = normalize_doi(raw)
        return (doi, False) if doi and _DOI.fullmatch(doi) else (None, True)
    found = re.match(r"https?://(dx\.)?doi\.org/(10\.\S+)$", (url or "").strip(), re.IGNORECASE)
    return (normalize_doi(found.group(2)), False) if found else (None, False)


# ------------------------------------------------------------------------------------------------------------- BibTeX

_BIBTEX_TYPES = {"article": "journalArticle", "inproceedings": "conferencePaper", "conference": "conferencePaper",
                 "incollection": "bookSection", "inbook": "bookSection", "book": "book", "phdthesis": "thesis",
                 "mastersthesis": "thesis", "thesis": "thesis", "techreport": "report", "report": "report"}
_BIBTEX_VENUES = ("journal", "journaltitle", "booktitle", "school", "institution", "publisher", "organization")
_MONTHS = {m: m.capitalize() for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")}
_HEAD = re.compile(r"@[ \t\r\n]*([A-Za-z]+)[ \t\r\n]*([{(])")
_KEY = re.compile(r"\s*([^\s,{}()=\"#%@]+)\s*,")
_NAME = re.compile(r"\s*([A-Za-z][\w\-:.+]*)\s*=\s*")
_IDENT = re.compile(r"[A-Za-z_][\w\-:.+]*")
_NUMBER = re.compile(r"\d+")
_WS = re.compile(r"\s*")
_VALUE_STOP = re.compile(r'[\\{}"@]')
_BRACES = re.compile(r"[{}]")


class _Budget:
    """The characters every field value of the file may still hold, macros expanded."""

    def __init__(self, text: str):
        self.remaining = max(EXPANSION_FACTOR * len(text), MIN_EXPANSION_BUDGET)

    def take(self, size: int) -> None:
        if size > self.remaining:
            raise ImportRefused(422, "import_expansion_too_large",
                                "The file's @string definitions expand to far more text than the file holds")
        self.remaining -= size


class _BibReader:
    def __init__(self, text: str, start: int, macros: dict[str, str], budget: _Budget):
        self.text, self.pos, self.macros, self.budget = text, start, macros, budget
        self.reach = start  # the furthest position read; a failed entry is never read again up to it
        self._scanned = start

    def resume(self) -> int:
        return max(self.pos, self.reach)

    def ws(self) -> None:
        self.pos = _WS.match(self.text, self.pos).end()

    def delimited(self, opening: str) -> str:
        """A `{…}` or `"…"` value without its delimiters; braces inside must balance. A value never runs into the
        next entry head (`@type{`), so one broken entry cannot swallow the entries after it."""
        try:
            return self._delimited(opening, self.pos + 1)
        finally:
            # Every way out, value or error, leaves `reach` past all this read scanned, so resume() never goes back.
            self.reach = max(self.reach, self._scanned)

    def _delimited(self, opening: str, start: int) -> str:
        text, depth, i = self.text, 0, start
        self._scanned = start
        while (stop := _VALUE_STOP.search(text, i)) is not None:
            i, char = stop.start(), stop.group(0)
            self._scanned = i  # an error below leaves reach here; the next head is looked for from this point on
            if char == "\\":
                i += 2
                continue
            if char == "@":
                if _HEAD.match(text, i):
                    raise _Malformed("unclosed_value", "a field value is not closed before the next entry")
            elif char == "{":
                depth += 1
            elif char == "}":
                if depth == 0:
                    if opening == "{":
                        self.pos = i + 1
                        return text[start:i]
                    raise _Malformed("unbalanced_braces", "a field value has a closing brace without an opening one")
                depth -= 1
            elif opening == '"' and depth == 0:
                self.pos = i + 1
                return text[start:i]
            i += 1
        # Read to the end (an escaped `\@type{` is not an entry head inside a value): nothing after it is read again.
        self._scanned = len(text)
        raise _Malformed("unclosed_value", "a field value is not closed before the end of the file")

    def value(self) -> str:
        """One field value with its `#` parts joined. Each part is measured against MAX_VALUE_CHARS before it is kept
        and the whole value against the file's budget before it is joined, so a macro that doubles itself never grows
        past the limit and nothing is copied for a value that is refused."""
        parts, size = [], 0
        while True:
            self.ws()
            char = self.text[self.pos:self.pos + 1]
            if char in ("{", '"'):
                part = self.delimited(char)
            elif (match := _NUMBER.match(self.text, self.pos)):
                part = match.group(0)
                self.pos = match.end()
            elif (match := _IDENT.match(self.text, self.pos)):
                name = match.group(0).lower()
                if name not in self.macros:
                    raise _Malformed("undefined_string", f"@string {match.group(0)[:80]} is not defined")
                part = self.macros[name]
                self.pos = match.end()
            else:
                raise _Malformed("missing_value", "a field has no value")
            if size + len(part) > MAX_VALUE_CHARS:
                raise _Malformed("value_too_long", f"a field value is longer than {MAX_VALUE_CHARS} characters")
            size += len(part)
            parts.append(part)  # a reference to the macro's string, not a copy
            self.ws()
            if self.text[self.pos:self.pos + 1] != "#":
                self.budget.take(size)  # the join below is the only copy
                return "".join(parts)
            self.pos += 1

    def fields(self, closing: str) -> dict[str, str]:
        found: dict[str, str] = {}
        while True:
            self.ws()
            if self.text[self.pos:self.pos + 1] == closing:
                self.pos += 1
                return found
            match = _NAME.match(self.text, self.pos)
            if not match:
                raise _Malformed("malformed_field", "a field name or its `=` is missing")
            self.pos = match.end()
            value = self.value()
            found.setdefault(match.group(1).lower(), value)  # the first of a repeated field stands
            self.ws()
            char = self.text[self.pos:self.pos + 1]
            if char == ",":
                self.pos += 1
            elif char != closing:
                raise _Malformed("unclosed_entry", "the entry is not closed")


def _group_end(text: str, opening: int) -> int | None:
    """The position after the brace that closes the `{` at `opening`, or None when it never closes."""
    depth = 0
    for match in _BRACES.finditer(text, opening):
        if match.start() and text[match.start() - 1] == "\\":
            continue
        depth += 1 if match.group(0) == "{" else -1
        if depth == 0:
            return match.end()
    return None


class _Lines:
    """Line numbers of increasing positions, counted in one pass over the file."""

    def __init__(self, text: str):
        self.text, self.pos, self.line = text, 0, 1

    def at(self, pos: int) -> int:
        self.line += self.text.count("\n", self.pos, pos)
        self.pos = pos
        return self.line


def _over_cap(entries: list[Entry], errors: list[EntryError], strings: int = 0) -> None:
    if len(entries) + len(errors) + strings > MAX_ENTRIES:
        raise ImportRefused(422, "import_too_many_entries",
                            f"The file holds more than {MAX_ENTRIES} entries; import it in parts")


def parse_bibtex(text: str) -> tuple[list[Entry], list[EntryError]]:
    """Read the file the way BibTeX does: an entry starts at any `@type{` or `@type(`, anywhere on a line, and text
    between entries is a comment. `@comment{…}` and `@preamble{…}` are skipped with their whole braced body, so an
    entry commented out inside one is not imported; a body that never closes ends the file (one error).

    Stops with `ImportRefused` as soon as entries, errors and @string definitions together pass `MAX_ENTRIES`, before
    reading further, and when the file's values expand past its budget (`_Budget`)."""
    entries: list[Entry] = []
    errors: list[EntryError] = []
    macros = dict(_MONTHS)
    lines = _Lines(text)
    budget = _Budget(text)
    index, pos, strings = 0, 0, 0
    while (head := _HEAD.search(text, pos)) is not None:
        start, kind, closing = head.start(), head.group(1).lower(), "}" if head.group(2) == "{" else ")"
        line = lines.at(start)
        pos = start + 1  # where the next entry is looked for when this one reads nothing further
        if kind in ("comment", "preamble"):
            if head.group(2) == "(":
                continue
            end = _group_end(text, head.end() - 1)
            if end is None:
                errors.append(EntryError(None, line, None, "unclosed_comment",
                                         f"@{kind} is not closed; the rest of the file is part of it"))
                _over_cap(entries, errors, strings)
                break
            pos = end
            continue
        if kind == "string":
            reader = _BibReader(text, head.end(), macros, budget)
            try:
                macros.update(reader.fields(closing))
                strings += 1
            except _Malformed as exc:
                errors.append(EntryError(None, line, None, exc.code, f"@string: {exc}"))
            pos = max(pos, reader.resume())
            _over_cap(entries, errors, strings)
            continue
        index += 1
        key_match = _KEY.match(text, head.end())
        if key_match is None:
            errors.append(EntryError(index, line, None, "missing_key", "the entry has no citation key"))
        else:
            key = key_match.group(1)[:MAX_KEY_CHARS]
            reader = _BibReader(text, key_match.end(), macros, budget)
            try:
                raw = reader.fields(closing)
                entries.append(_bibtex_entry(index, key, kind, raw))
            except _Malformed as exc:
                errors.append(EntryError(index, line, key, exc.code, str(exc)))
            # Recovery never reads a region twice: the next head is looked for after everything this entry read (a
            # value stops at the next head, so a well-formed entry after a broken one is still found).
            pos = max(pos, reader.resume())
        _over_cap(entries, errors, strings)
    return entries, errors


def _bibtex_entry(index: int, key: str, kind: str, raw: dict[str, str]) -> Entry:
    def text(name: str) -> str | None:
        return latex_to_text(raw[name]) or None if name in raw else None

    title = text("title")
    if not title:
        raise _Malformed("no_title", "the entry has no title")
    url = _verbatim(raw.get("url"))
    doi, bad_doi = _doi(_verbatim(raw.get("doi")), url)
    if bad_doi:
        raise _Malformed("invalid_doi", "the DOI field does not hold a DOI")
    pages = text("pages")
    return Entry(
        index=index, key=key, title=title, authors=_bibtex_authors(raw.get("author", "")),
        year=year_of(text("year")) or year_of(text("date")),
        venue=next((v for v in (text(f) for f in _BIBTEX_VENUES) if v), None),
        publication_type=_BIBTEX_TYPES.get(kind), doi=doi, url=url, abstract=text("abstract"),
        volume=text("volume"), issue=text("number") or text("issue"),
        pages=re.sub(r"\s*[–—]\s*", "-", pages) if pages else None,
        fields={"type": kind, "key": key, **raw},
    )


# ---------------------------------------------------------------------------------------------------------------- RIS

_RIS_TYPES = {"JOUR": "journalArticle", "JFULL": "journalArticle", "EJOUR": "journalArticle", "INPR": "journalArticle",
              "ABST": "journalArticle", "MGZN": "magazineArticle", "CONF": "conferencePaper",
              "CPAPER": "conferencePaper", "CHAP": "bookSection", "BOOK": "book", "EBOOK": "book", "EDBOOK": "book",
              "THES": "thesis", "RPRT": "report"}
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9]) {1,2}-(?: (.*))?$")
_RIS_VENUES = ("T2", "JF", "JO", "JA", "J2", "BT", "PB")


def parse_ris(text: str) -> tuple[list[Entry], list[EntryError]]:
    entries: list[Entry] = []
    errors: list[EntryError] = []
    record: list[tuple[str, list[str]]] | None = None  # each tag with its value's lines, joined once at the end
    index, record_line, stray = 0, 0, False

    def close(problem: tuple[str, str] | None) -> None:
        tags: dict[str, list[str]] = {}
        for tag, parts in record or []:
            tags.setdefault(tag, []).append(" ".join(parts).strip())
        key = ((tags.get("ID") or [None])[0] or None) and tags["ID"][0][:MAX_KEY_CHARS]
        if problem:
            errors.append(EntryError(index, record_line, key, *problem))
        else:
            try:
                entries.append(_ris_entry(index, key, tags))
            except _Malformed as exc:
                errors.append(EntryError(index, record_line, key, exc.code, str(exc)))
        _over_cap(entries, errors)

    def outside(number: int, what: str) -> None:
        nonlocal stray
        if not stray:  # one error for a run of stray lines
            stray = True
            errors.append(EntryError(None, number, None, "outside_record", f"{what} stands outside a TY … ER record"))
            _over_cap(entries, errors)

    # Read lazily: a file of millions of short lines never becomes a list of them. Universal newlines, so CRLF and a
    # lone CR end a line as LF does.
    for number, line in enumerate(io.StringIO(text, newline=None), start=1):
        line = line.rstrip("\n")
        match = _RIS_LINE.match(line)
        if match is None:
            if not line.strip():
                continue
            if record is not None:
                record[-1][1].append(line.strip())  # a wrapped value continues the tag before it
            else:
                outside(number, "text")
            continue
        tag, value = match.group(1), match.group(2) or ""
        if tag == "TY":
            if record is not None:
                close(("unclosed_record", "the record is not closed with ER before the next TY"))
            index += 1
            record, record_line, stray = [(tag, [value])], number, False
        elif record is None:
            outside(number, tag)
        elif tag == "ER":
            close(None)
            record = None
        else:
            record.append((tag, [value]))
    if record is not None:
        close(("unclosed_record", "the record is not closed with ER"))
    return entries, errors


def _ris_entry(index: int, key: str | None, tags: dict[str, list[str]]) -> Entry:
    def first(*names: str) -> str | None:
        return next((v for name in names for v in tags.get(name, []) if v), None)

    title = first("TI", "T1", "CT")
    if not title:
        raise _Malformed("no_title", "the record has no title")
    url = first("UR")
    doi, bad_doi = _doi(first("DO"), url)
    if bad_doi:
        raise _Malformed("invalid_doi", "the DO field does not hold a DOI")
    start, end = first("SP"), first("EP")
    pages = (f"{start}-{end}" if start and end and "-" not in start else start) or None
    return Entry(
        index=index, key=key, title=title,
        authors=[_person(a.split(","), suffix_last=True) for a in tags.get("AU", []) + tags.get("A1", []) if a.strip()],
        year=year_of(first("PY", "Y1", "DA")), venue=first(*_RIS_VENUES),
        publication_type=_RIS_TYPES.get((first("TY") or "").upper()), doi=doi, url=url, abstract=first("AB", "N2"),
        volume=first("VL"), issue=first("IS"), pages=pages,
        fields={tag: values if len(values) > 1 else values[0] for tag, values in tags.items()},
    )


def read_file(data: bytes, filename: str | None, fmt: Format | None = None
              ) -> tuple[Format, list[Entry], list[EntryError]]:
    """The file's format (given, else from its name or its first entry), its readable entries and the entry errors."""
    if len(data) > MAX_FILE_BYTES:
        raise ImportRefused(413, "import_too_large", "Reference file larger than 5 MB")
    text = decode(data)
    fmt = fmt or detect_format(filename, text)
    # Both parsers stop as soon as entries and errors together pass MAX_ENTRIES.
    entries, errors = parse_bibtex(text) if fmt == "bibtex" else parse_ris(text)
    return fmt, entries, errors


# ---------------------------------------------------------------------------------------------------- DOI resolution

@dataclass
class Resolution:
    status: Literal["confirmed", "not_found", "failed"]
    provider: str | None = None
    record: ProviderRecord | None = None
    payload_path: str | None = None
    # What each provider answered: {"provider", "outcome": "found" | "not_found" | "error" | "not_asked", "reason"}.
    attempts: list[dict[str, Any]] = field(default_factory=list)


def _attempt(provider: str, outcome: str, reason: str | None = None) -> dict[str, Any]:
    return {"provider": provider, "outcome": outcome, "reason": reason}


def _failure(outcome) -> str:
    return f"HTTP {outcome.http_status}" if outcome.http_status else (outcome.error or outcome.status)[:200]


async def resolve_dois(http: httpx.AsyncClient, dois: list[str], contact_email: str | None,
                       write_payload) -> dict[str, Resolution]:
    """Each DOI confirmed by exactly one OpenAlex work with that DOI, else by Crossref's record of it.

    `failed` means no provider confirmed the DOI and at least one could not be asked or did not answer readably;
    `not_found` means every provider asked answered without it. `attempts` says what each provider did, with the
    reason. `write_payload(provider, payload)` stores an answer and returns its path.
    """
    results = {doi: Resolution("failed") for doi in dois}
    asked = [d for d in dois if "|" not in d and "," not in d]  # the OpenAlex filter cannot hold these two
    for doi in dois:
        if doi not in asked:
            results[doi].attempts.append(_attempt("openalex", "not_asked", "doi_not_filterable"))
    connector = CONNECTORS["openalex"]
    for i in range(0, len(asked), openalex.MAX_IDS_PER_REQUEST):
        batch = asked[i:i + openalex.MAX_IDS_PER_REQUEST]
        outcome = await openalex.works_by_dois(http, batch, api_key=connector.api_key(), contact_email=contact_email,
                                               per_page=openalex.MAX_IDS_PER_REQUEST)
        if outcome.status not in ("completed", "zero_results"):
            for doi in batch:
                results[doi].attempts.append(_attempt("openalex", "error", _failure(outcome)))
            continue
        # A page that may have left works out cannot say a DOI has none, or that its one work is the only one.
        complete = isinstance(outcome.provider_total, int) and outcome.provider_total <= len(outcome.records)
        by_doi: dict[str, list[ProviderRecord]] = {}
        for record in outcome.records:
            if record.doi:
                by_doi.setdefault(record.doi, []).append(record)
        path = write_payload("openalex", outcome.raw_payload) if outcome.records else None
        for doi in batch:
            found, result = by_doi.get(doi, []), results[doi]
            if len(found) == 1 and complete:
                result.status, result.provider, result.record, result.payload_path = "confirmed", "openalex", found[0], path
                result.attempts.append(_attempt("openalex", "found"))
            elif not complete:
                result.attempts.append(_attempt("openalex", "error", "incomplete_answer"))
            elif found:
                result.attempts.append(_attempt("openalex", "error", "several_works"))
            else:
                result.attempts.append(_attempt("openalex", "not_found"))
    open_dois = [d for d in dois if results[d].status != "confirmed"]
    for doi in open_dois[CROSSREF_FALLBACK_MAX:]:
        results[doi].attempts.append(_attempt("crossref", "not_asked", "crossref_limit"))
    for doi in open_dois[:CROSSREF_FALLBACK_MAX]:
        result = results[doi]
        answer, outcome = await lookup.crossref_work(http, doi, contact_email)
        if answer.status == "found":
            try:
                record = crossref.record_from_item(outcome.raw_payload)
            except (AttributeError, KeyError, TypeError, IndexError):
                record = None
            if record is not None and record.doi == doi:
                result.status, result.provider, result.record = "confirmed", "crossref", record
                result.payload_path = write_payload("crossref", outcome.raw_payload)
                result.attempts.append(_attempt("crossref", "found"))
            else:
                result.attempts.append(_attempt("crossref", "error", "unreadable_record"))
        elif answer.status == "not_found":
            result.attempts.append(_attempt("crossref", "not_found"))
        else:
            result.attempts.append(_attempt("crossref", "error", _failure(outcome)))
    for result in results.values():
        if result.status != "confirmed" and all(a["outcome"] == "not_found" for a in result.attempts):
            result.status = "not_found"
    return results


# -------------------------------------------------------------------------------------------------------- the import

def _fold(value: str | None) -> str:
    """NFKC and casefold, keeping the letters and digits of every script; spacing and punctuation drop out. Accents
    are kept, so `Müller` and `Muller` are different names."""
    text = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value or "").casefold())
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LN" or unicodedata.category(ch) in ("Mn", "Mc"))


def _identity_fold(value: str | None) -> str:
    """Stricter than `_fold` for record identity: NFKC and casefold with whitespace, dashes and quotation marks
    dropped, every other character kept, so `C++` and `C#` stay apart from `C` while `--` against `–` or a capital
    letter does not split one entry in two."""
    text = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value or "").casefold())
    return "".join(ch for ch in text if not (ch.isspace() or ch in "\"'`" or unicodedata.category(ch) in ("Pd", "Pi", "Pf")))


def identity(entry: Entry) -> str:
    """The same entry imported again, from either format, finds the record it made the first time. An unconfirmed DOI
    is never an identity on its own: two entries naming one DOI with a different title, year or first author are two
    records."""
    basis = "\x1f".join((entry.doi or "", _identity_fold(entry.title), str(entry.year or ""),
                          _identity_fold(entry.authors[0] if entry.authors else "")))
    return "entry:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
_QUOTES = "\u2018\u2019\u201a\u201b\u2032\u0060\u00b4"
_DOUBLE_QUOTES = "\u201c\u201d\u201e\u201f\u2033\u00ab\u00bb"


def strict_title(title: str) -> str:
    """NFKC and casefold, whitespace collapsed, dash and quotation-mark variants made one; every other character,
    `+`, `#` and `&` included, kept as it is."""
    text = unicodedata.normalize("NFKC", title).casefold()
    text = text.translate({**{ord(c): "-" for c in _DASHES}, **{ord(c): "'" for c in _QUOTES},
                           **{ord(c): '"' for c in _DOUBLE_QUOTES}})
    return re.sub(r"\s+", " ", text).strip()


def titles_agree(entry_title: str, entry_year: int | None, record_title: str, record_year: int | None) -> bool:
    """Whether a record a DOI names is the work the entry names: the same `strict_title`, and the same year when both
    have one. Nothing looser (no subtitle, word-share or symbol-blind rule): a disagreement keeps the entry as the
    person's own record, which loses nothing, while a false agreement would put another paper's record and abstract
    under the entry."""
    if entry_year is not None and record_year is not None and entry_year != record_year:
        return False
    a, b = strict_title(entry_title), strict_title(record_title)
    return bool(a) and a == b


def user_record(entry: Entry, fmt: Format) -> ProviderRecord:
    return ProviderRecord(
        provider_record_id=identity(entry), title=entry.title, authors=entry.authors, year=entry.year,
        venue=entry.venue, publication_type=entry.publication_type, doi=entry.doi, landing_url=entry.url,
        oa_pdf_url=None, oa_pdf_version=None,
        version_label=None,  # a reference file does not say which version of a paper an entry names
        abstract=entry.abstract, abstract_origin=ABSTRACT_ORIGINS[fmt] if entry.abstract else None,
        identifiers={}, raw={"format": fmt, "entry": entry.fields},
        # No provider confirmed the DOI: the entry never takes over the record another source stored under it.
        merge_by_doi=False, volume=entry.volume, issue=entry.issue, pages=entry.pages,
    )


async def import_entries(store: Store, http: httpx.AsyncClient, payloads_dir: Path, contact_email: str | None,
                         entries: list[Entry], fmt: Format, file_payload: str) -> dict[str, Any]:
    """Resolve the entries' DOIs, then store and save every entry in one transaction (no await inside it)."""
    payloads_dir.mkdir(parents=True, exist_ok=True)

    def write_payload(provider: str, payload: Any) -> str:
        name = f"{new_id(provider[:3])}.json"
        (payloads_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return name

    dois = list(dict.fromkeys(e.doi for e in entries if e.doi))
    resolved = await resolve_dois(http, dois, contact_email, write_payload) if dois else {}
    rows: list[dict[str, Any]] = []
    with transaction(store.conn):
        for entry in entries:
            found = resolved.get(entry.doi) if entry.doi else None
            confirmed_by, svid, mismatch = None, None, None
            existing = store.find_source_by_identifier("doi", entry.doi) if entry.doi else None
            if found is not None and found.status == "confirmed":
                if titles_agree(entry.title, entry.year, found.record.title, found.record.year):
                    svid, _ = store.upsert_provider_source(found.provider, found.record, found.payload_path)
                    confirmed_by, record = found.provider, "provider"
                else:
                    mismatch = found.record.title
            elif existing is not None:
                stored_record = store.source(existing)
                stored = stored_record["title"]
                if titles_agree(entry.title, entry.year, stored, stored_record["year"]):
                    mapping = store.conn.execute(
                        "SELECT provider FROM identifier_mappings WHERE source_version_id = ? AND scheme = 'doi'"
                        " ORDER BY id LIMIT 1", (existing,)).fetchone()
                    # The stored record is that provider's own, from an earlier lookup or search.
                    svid, record, confirmed_by = existing, "existing", mapping["provider"] if mapping else None
                else:
                    mismatch = stored
            if svid is None:
                # The person's own record. One made before for the same entry is reused as it stands: a second entry
                # never fills its fields or adds its abstract.
                own = user_record(entry, fmt)
                svid = (store.find_source_by_identifier(PROVIDER, own.provider_record_id)
                        or store.upsert_provider_source(PROVIDER, own, file_payload)[0])
                record = "user_supplied"
            rows.append({"index": entry.index, "key": entry.key, "title": entry.title, "doi": entry.doi,
                         "lookup": found.status if found is not None else "no_doi",
                         "lookups": found.attempts if found is not None else [], "record": record,
                         # The title of the record the DOI named when it is not the entry's work.
                         "title_mismatch": mismatch,
                         "source_version_id": svid, "work_id": store.source(svid)["work_id"],
                         "confirmed_by": confirmed_by})
        svids = [row["source_version_id"] for row in rows]
        added = library_items.save(store, svids, ORIGINS[fmt])
        for row in rows:
            if row["confirmed_by"] is not None:
                library_items.confirm(store, row["source_version_id"], row["confirmed_by"])
    first: dict[str, int] = {}
    for row in rows:
        row["duplicate_of"] = first.setdefault(row["source_version_id"], row["index"])
        if row["duplicate_of"] == row["index"]:
            row["duplicate_of"] = None
    return {"entries": rows, "saved": added, "already_saved": [s for s in dict.fromkeys(svids) if s not in added]}
