"""BibTeX and RIS bibliographies of a research's included or cited sources (D16).

Built from stored source records only. Entry types follow Zotero's import translators (BibTeX.js, RIS.js), so a file
opens in Zotero with matching item types. Neither format has a version field, so the source version DEIXIS read goes
into a note.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from deixis.workflow.store import Store
from deixis.workflow.views import research_view

Format = Literal["bibtex", "ris"]
Selection = Literal["included", "cited"]

MEDIA_TYPES = {"bibtex": "application/x-bibtex; charset=utf-8", "ris": "application/x-research-info-systems; charset=utf-8"}

# publication_type values of the providers and Zotero item types, compared in lowercase letters only.
_KINDS = {
    "journal": {"article", "journalarticle", "journal", "journals", "review", "letter", "editorial", "note", "erratum",
                "shortsurvey", "lettersandcomments", "magazines", "magazinearticle", "earlyaccessarticles"},
    "conference": {"proceedingsarticle", "conferencepaper", "conference", "conferences"},
    "chapter": {"bookchapter", "booksection"},
    "book": {"book", "books", "monograph", "editedbook"},
    "thesis": {"dissertation", "thesis"},
    "report": {"report"},
}
# kind: (BibTeX entry type, BibTeX field that holds the venue, RIS type). Preprints and the rest are generic.
_TYPES = {
    "journal": ("article", "journal", "JOUR"),
    "conference": ("inproceedings", "booktitle", "CONF"),
    "chapter": ("incollection", "booktitle", "CHAP"),
    "book": ("book", "publisher", "BOOK"),
    "thesis": ("phdthesis", "school", "THES"),
    "report": ("techreport", "institution", "RPRT"),
    "other": ("misc", "howpublished", "GEN"),
}
_VERSION_NAMES = {"publishedVersion": "published version", "acceptedVersion": "accepted manuscript",
                  "submittedVersion": "submitted manuscript"}
_TEX = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
_KEY_STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "and", "to", "with"}


def export_sources(store: Store, research_id: str, selection: Selection) -> list[dict[str, Any]]:
    """Sources in the order the research lists them: the included ones, or the ones cited in the latest answer."""
    chosen = [s for s in research_view(store, research_id)["sources"]
              if (s["selection"]["state"] == "included" if selection == "included" else s["cited_in_latest_answer"])]
    for source in chosen:
        row = store.conn.execute(
            "SELECT value FROM identifier_mappings WHERE source_version_id = ? AND scheme = 'arxiv' LIMIT 1",
            (source["source_version_id"],),
        ).fetchone()
        source["arxiv_id"] = row["value"] if row else None
    return chosen


def filename(title: str, selection: Selection, fmt: Format) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(title))[:40].strip("-")
    return f"deixis-{slug or 'research'}-{selection}.{'bib' if fmt == 'bibtex' else 'ris'}"


def to_bibtex(sources: list[dict[str, Any]], keys: list[str] | None = None, *, latex_report: bool = False) -> str:
    return bibtex_with_notes(sources, keys, latex_report=latex_report)[0]


def bibtex_with_notes(sources: list[dict[str, Any]], keys: list[str] | None = None, *,
                      latex_report: bool = False, unmapped=None) -> tuple[str, list[str]]:
    """Keep D16 bytes by default; the report path has its own field boundary."""
    from deixis.workflow.report.latex_text import escape_text

    original = sources
    if latex_report:
        # Invalid years must not enter automatic keys, even if the field is omitted.
        sources = [s | {"year": s["year"] if type(s["year"]) is int else None} for s in sources]
    given_keys = keys is not None
    keys = _keys(sources) if keys is None else keys
    if given_keys or latex_report:
        if (len(keys) != len(sources)
                or any(not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", key) is None for key in keys)
                or len({key.lower() for key in keys}) != len(keys)):
            raise ValueError("BibTeX keys must match the source count, be valid and be unique ignoring case")
    notes: list[str] = []

    def tex(value: Any) -> str:
        if not latex_report:
            return _tex(value)
        return escape_text(_line(value), unmapped).replace(r"\{", r"\textbraceleft{}").replace(r"\}", r"\textbraceright{}")

    def author(value: str) -> str:
        return f"{{{tex(value)}}}" if re.search(r"\band\b", value, re.IGNORECASE) else tex(value)

    def raw(value: str | None, field: str, key: str) -> str:
        if latex_report and value is not None and any(
                ch == "\\" or unicodedata.category(ch) in {"Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"}
                for ch in str(value)):
            notes.append(f"Bibliography: omitted {field} of {key} because it holds a backslash or a control character.")
            return ""
        return _raw(value)

    entries = []
    for index, (key, s) in enumerate(zip(keys, sources)):
        if latex_report and original[index]["year"] is not None and type(original[index]["year"]) is not int:
            notes.append(f"Bibliography: omitted year of {key} because it is not a number.")
        entry_type, venue_field, _ = _TYPES[_kind(s["publication_type"])]
        title = tex(s["title"])
        identifiers = {field: raw(s[source_field], field, key) for field, source_field in
                       (("doi", "doi"), ("url", "landing_url"), ("eprint", "arxiv_id"))}
        fields = [
            ("title", "{" + title + "}" if latex_report else title),
            ("author", " and ".join(author(a) for a in s["authors"] if a.strip())),
            ("year", str(s["year"] or "")),
            (venue_field, tex(s["venue"] or "")),
            ("volume", tex(s.get("volume") or "")),
            ("number", tex(s.get("issue") or "")),
            ("pages", tex(s.get("pages") or "")),
            ("doi", identifiers["doi"]),
            ("url", identifiers["url"]),
            ("eprint", identifiers["eprint"]),
            ("eprinttype", "arxiv" if s["arxiv_id"] else ""),
            ("note", tex(_version_note(s["version_label"]))),
        ]
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value)
        entries.append(f"@{entry_type}{{{key},\n{body}\n}}\n")
    return "\n".join(entries), notes


def to_ris(sources: list[dict[str, Any]]) -> str:
    lines = []
    for s in sources:
        tags = [("TY", _TYPES[_kind(s["publication_type"])][2]), ("TI", s["title"]), *(("AU", a) for a in s["authors"]),
                ("PY", s["year"]), ("T2", s["venue"]), ("VL", s.get("volume")), ("IS", s.get("issue")),
                ("SP", s.get("pages")), ("DO", s["doi"]), ("UR", s["landing_url"]),
                ("N1", _version_note(s["version_label"]))]
        lines += [f"{tag}  - {_line(value)}" for tag, value in tags if _line(value)]
        lines += ["ER  - ", ""]
    return "\r\n".join(lines)


def _kind(publication_type: str | None) -> str:
    key = re.sub(r"[^a-z]", "", (publication_type or "").lower())
    return next((kind for kind, names in _KINDS.items() if key in names), "other")


def _version_note(label: str | None) -> str:
    return f"Source version read in DEIXIS: {_VERSION_NAMES.get(label, label)}" if label else ""


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _keys(sources: list[dict[str, Any]]) -> list[str]:
    """Author-year-word keys such as `floudas2009global`, made unique within the file with b, c, ... suffixes."""
    keys: list[str] = []
    for s in sources:
        first = s["authors"][0].split() if s["authors"] else []
        family = re.sub(r"[^a-z0-9]", "", _fold(first[-1])) if first else ""
        word = next((w for w in (re.sub(r"[^a-z0-9]", "", _fold(w)) for w in s["title"].split()) if w and w not in _KEY_STOPWORDS), "")
        base = f"{family or 'anon'}{s['year'] or ''}{word}"
        key, n = base, 1
        while key in keys:
            n += 1
            key = base + (chr(ord("a") + n - 1) if n <= 26 else str(n))
        keys.append(key)
    return keys


def _tex(text: str) -> str:
    return "".join(_TEX.get(c, c) for c in _line(text))


def _author(name: str) -> str:
    # BibTeX splits the author list on "and"; a name containing the word is kept whole.
    return f"{{{_tex(name)}}}" if re.search(r"\band\b", name, re.IGNORECASE) else _tex(name)


def _raw(value: str | None) -> str:
    # doi, url and eprint are read verbatim by BibTeX tools; only braces would break the field.
    return re.sub(r"[{}\s]", "", value or "")


def _line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
