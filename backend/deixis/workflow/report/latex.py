"""Pure IEEEtran report assembly from one recorded read model (synthetic-tested).

The export carries text and bibliography, not the inspectable evidence library.
Math safety and compatibility remain the separate X2 conversion boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any

from deixis.domain.rules import RevisionConflict
from deixis.workflow.report import export_text, latex_math, latex_text, latex_preamble
from deixis.workflow.report.store import DISPLAY_ORDER

MAX_DATA_COLUMNS = 7
SOURCE_COLUMN_WIDTH = "1.0in"
HEADING_THRESHOLD = 400
CELL_THRESHOLD = 400
SOURCE_THRESHOLD = 200
MIDDLE_DOT = latex_text.escape_text(" · ")
TRACEABILITY_LIMIT = (
    "This export carries the report text and its bibliography. The quoted passages, the table cell evidence "
    "and the located citation anchors stay in DEIXIS.",
    "Bu çıktı raporun metnini ve kaynakçasını taşır. Alıntı pasajları, tablo hücresi kanıtları ve konumlanmış "
    "atıf çapaları DEIXIS'te kalır.",
)
_BIB_FIELDS = frozenset({"source_version_id", "title", "authors", "year", "venue", "publication_type", "doi",
                         "landing_url", "version_label", "arxiv_id"})


@dataclass(frozen=True)
class LatexBundle:
    stem: str
    tex: str
    bib: str
    notes: tuple[str, ...]

    @property
    def note_count(self) -> int:
        return len(self.notes)


def _text_of(value: Any) -> str:
    return "" if value is None else str(value)


def _join(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    boundary = re.search(r"\\end\s*\{[A-Za-z*]+\}$", a) or re.match(r"\\begin\s*\{", b)
    return a + ("\n" if boundary else " ") + b


def _guard(text: str) -> str:
    return "{}" + text if text.startswith(("[", "*")) else text


def _itemize(items: list[str]) -> str:
    return "\n".join([r"\begin{itemize}", *(r"\item " + _guard(item) for item in items), r"\end{itemize}"]) if items else ""


def _claims(section: dict) -> list[dict]:
    claims = section["claims"]
    return [claim for paragraph in dict.fromkeys(c["paragraph"] for c in claims)
            for claim in claims if claim["paragraph"] == paragraph]


def _references(view: dict, bib_sources: list[dict]) -> tuple[dict[int, str], list[dict], list[str]]:
    refs = view["references"]
    by_number: dict[int, dict] = {}
    by_version: dict[str, dict] = {}
    for ref in refs:
        number = ref["number"]
        if type(number) is not int or number < 1:
            raise RevisionConflict("Reference numbers must be positive integers")
        if number in by_number:
            raise RevisionConflict("Reference numbers must be unique")
        version = ref["source_version_id"]
        if version in by_version:
            raise RevisionConflict("Reference source versions must be unique")
        by_number[number], by_version[version] = ref, ref
    for section in view["sections"]:
        for claim in section["claims"]:
            for link in claim["evidence"]:
                number, version = link.get("ref_number"), link.get("source_version_id")
                ref = by_number.get(number) if type(number) is int else None
                if ref is None or "source_version_id" not in link or ref["source_version_id"] != version:
                    raise RevisionConflict("A claim citation does not resolve to the same reference number and source version")
    table = view.get("table_i")
    if table:
        for row in table["rows"]:
            ref = by_version.get(row["source_version_id"])
            expected = ref["number"] if ref else None
            number = row.get("ref_number")
            if number != expected or number is not None and type(number) is not int:
                raise RevisionConflict("A table row's reference number does not match its source version")
    by_bib: dict[str, dict] = {}
    for row in bib_sources:
        if not _BIB_FIELDS <= row.keys():
            raise RevisionConflict("A bibliography source is missing a required field")
        version = row["source_version_id"]
        if version in by_bib:
            raise RevisionConflict("Bibliography source versions must be unique")
        by_bib[version] = row
    if any(ref["source_version_id"] not in by_bib for ref in refs):
        raise RevisionConflict("A reference has no bibliography source")
    keys: dict[int, str] = {}
    holders: dict[str, int] = {}
    notes: list[str] = []
    for ref in refs:
        number, base = ref["number"], ref.get("source_key")
        usable = isinstance(base, str) and re.fullmatch(r"[A-Za-z0-9]+", base) is not None
        if usable:
            holders[base.lower()] = holders.get(base.lower(), 0) + 1
            n = holders[base.lower()]
            key = base if n == 1 else f"{base}-{n}"
            if n > 1:
                notes.append(f"Reference [{number}] shares a source key with an earlier reference; cite key {key} was used.")
        else:
            key = f"ref{number}"
            notes.append(f"Reference [{number}] has no usable source key; cite key {key} was used.")
        keys[number] = key
    if len({key.lower() for key in keys.values()}) != len(keys):
        raise RevisionConflict("Cite keys collide ignoring case")
    return keys, [by_bib[ref["source_version_id"]] for ref in refs], notes


@dataclass(frozen=True)
class _Target:
    claim: int
    piece: int
    label: str


def _equations(sections: list[dict]) -> tuple[dict[str, _Target | None], list[str]]:
    targets: dict[str, _Target | None] = {}
    displays: dict[int, bool] = {}
    claims = [claim for section in sections if section["section_id"] in export_text.HEADINGS
              and section["section_id"] != "index_terms" for claim in _claims(section)]
    for claim in claims:
        ref = claim.get("equation_ref")
        if ref and ref not in targets:
            targets[ref] = None
        math_index = 0
        displays[id(claim)] = False
        for kind, piece in latex_math.split_text(_text_of(claim["text"])):
            if kind != "math":
                continue
            m = latex_math.classify(piece, cell=False)
            displays[id(claim)] |= m.kind.startswith("display_")
            if ref and targets[ref] is None and m.labelable:
                rank = list(targets).index(ref) + 1
                if rank <= 999:
                    targets[ref] = _Target(id(claim), math_index, f"eq:EQ{rank}")
            math_index += 1
    missing = sum(target is None for target in targets.values())
    own = sum(bool(claim.get("equation_ref") and targets[claim["equation_ref"]] is not None
                   and targets[claim["equation_ref"]].claim != id(claim) and displays[id(claim)]) for claim in claims)
    notes = []
    if missing:
        notes.append("1 equation reference has no numberable display expression; no cross-reference was written for it."
                     if missing == 1 else f"{missing} equation references have no numberable display expression; no cross-reference was written for them.")
    if own:
        notes.append("1 claim cites an equation reference and holds a display expression of its own; no cross-reference was written for it."
                     if own == 1 else f"{own} claims cite an equation reference and hold a display expression of their own; no cross-reference was written for them.")
    return targets, notes


def _normalise_notes(notes: list[str]) -> tuple[str, ...]:
    clean = ("".join(ch if " " <= ch <= "~" else "?" for ch in " ".join(note.split())).strip() for note in notes)
    return tuple(dict.fromkeys(clean))


def _comment_block(stem: str, notes: tuple[str, ...]) -> str:
    lines = ["% DEIXIS evidence report, IEEEtran export for XeLaTeX.", f"% Compile with: latexmk -xelatex {stem}.tex",
             "% Needs XeLaTeX, BibTeX and the IEEEtran class and IEEEtran.bst style; they are not included.",
             f"% Export notes: {len(notes) if notes else 'none'}"]
    lines.extend(f"% {i}. {note}"[:200] for i, note in enumerate(notes[:20], 1))
    if len(notes) > 20:
        lines.append(f"% and {len(notes) - 20} more")
    return "\n".join(lines)


class _Writer:
    def __init__(self, tr: bool, keys: dict[int, str], targets: dict[str, _Target | None]):
        self.tr, self.keys, self.targets = tr, keys, targets
        self.um = latex_text.Unmapped()
        self.notes: list[str] = []
        self.cited: dict[int, None] = {}
        self.long_values: list[tuple[str, str | None, str]] = []

    def fixed(self, value: Any) -> str:
        return latex_text.escape_text(_text_of(value), self.um)

    def line(self, value: Any) -> str:
        text, notes = latex_math.convert_text(_text_of(value), cell=True, unmapped=self.um)
        self.notes.extend(notes)
        return text.strip()

    def body(self, value: Any, label_for: Callable | None) -> str:
        text, notes = latex_math.convert_text(_text_of(value), cell=False, label_for=label_for, unmapped=self.um)
        self.notes.extend(notes)
        return text.strip()

    def fragment(self, claim: dict, *, keyword: bool = False) -> str:
        target = self.targets.get(claim.get("equation_ref"))
        def label_for(index, m):
            return target.label if target and target.claim == id(claim) and target.piece == index else None
        text = self.line(claim["text"]) if keyword else self.body(claim["text"], label_for)
        if not keyword and target and target.claim != id(claim):
            has_display = any(latex_math.classify(piece, cell=False).kind.startswith("display_")
                              for kind, piece in latex_math.split_text(_text_of(claim["text"])) if kind == "math")
            if not has_display:
                text = _join(text, f"\\eqref{{{target.label}}}")
        links = list(dict.fromkeys(link["ref_number"] for link in claim["evidence"]))
        if links:
            for number in links:
                self.cited.setdefault(number, None)
            text = _join(text, "\\cite{" + ",".join(self.keys[number] for number in links) + "}")
        return text

    def unchecked(self, view: dict) -> list[str]:
        tr, fixed, line = self.tr, self.fixed, self.line
        blocks = [r"\noindent " + fixed(export_text.report_identity(view, tr))]
        draft = export_text.draft_line(view, tr)
        if draft is not None:
            blocks.append(r"\noindent " + line(draft))
        missing = view.get("missing_rows")
        if missing:
            blocks.append(r"\noindent " + fixed(export_text.missing_rows_sentence(missing, tr)))
            blocks.append(_itemize([": ".join(export_text.missing_row_fields(row, tr, line)) for row in missing["failed_rows"]]))
        edit = export_text.edit_note(view, tr, line)
        if edit is not None:
            blocks.append(r"\noindent " + edit.paragraph)
            if edit.not_checked_heading is not None:
                blocks.append(_itemize([f"{sid}{MIDDLE_DOT}{rule} ({severity}): {detail}" for sid, rule, severity, detail in edit.items]))
                blocks.append(r"\noindent " + edit.not_checked_heading)
                blocks.append(_itemize([f"{sid}{MIDDLE_DOT}{key}: {rule} ({reason})" for sid, key, rule, reason in edit.skipped_rules]
                                       + list(edit.not_checked)))
        if view.get("evidence_changes", {}).get("any"):
            blocks.append(r"\noindent " + fixed(export_text.evidence_changed_sentence(tr)))
        freshness = view.get("passage_freshness", {})
        if freshness.get("affected") or freshness.get("unresolved"):
            blocks.append(r"\noindent " + fixed(export_text.passage_freshness_sentence(
                tr, len(freshness["affected"]), len(freshness["unresolved"]))))
        return blocks

    def empty(self, section: dict) -> list[str]:
        reasons = (section.get("draft") or {}).get("insufficient_evidence") or []
        return [self.fixed(export_text.not_enough_evidence_label(self.tr)) + ": " + self.line(entry["reason"]) for entry in reasons
                ] if reasons else [self.fixed(export_text.no_text_sentence(self.tr))]

    def section(self, section: dict, table: dict | None) -> list[str]:
        sid, tr = section["section_id"], self.tr
        environment = {"abstract": "abstract", "index_terms": "IEEEkeywords"}.get(sid)
        heading = self.line(export_text.heading(sid, tr))
        notice = self.fixed(export_text.section_unvalidated_note(tr))
        blocks = []
        if environment:
            if section["status"] in ("draft", "failed"):
                blocks.append(f"\\noindent\\textit{{{heading}: {notice}}}")
            blocks.append(f"\\begin{{{environment}}}")
        else:
            blocks.append(f"\\section*{{{heading}}}")
            if section["status"] in ("draft", "failed"):
                blocks.append(f"\\noindent\\textit{{{notice}}}")
        if sid == "VI":
            blocks.append(self.fixed(export_text.vi_preface(tr)))
        claims = _claims(section)
        has_table_ref = any(c.get("table_ref") == "TABLE_I" for c in claims)
        if table and not has_table_ref:
            blocks.append(self.table(table))
        draft_text = (section.get("draft") or {}).get("text") if sid in ("II", "VIII") else None
        if draft_text:
            blocks.append(self.body(draft_text, None))
        if sid == "index_terms" and claims:
            blocks.append(", ".join(self.fragment(c, keyword=True) for c in claims))
        else:
            first_table = next((c["paragraph"] for c in claims if c.get("table_ref") == "TABLE_I"), None)
            for paragraph in dict.fromkeys(c["paragraph"] for c in claims):
                text = ""
                for claim in (c for c in claims if c["paragraph"] == paragraph):
                    text = _join(text, self.fragment(claim))
                blocks.append(text)
                if table and paragraph == first_table:
                    blocks.append(self.table(table))
        if not claims and not draft_text:
            blocks.extend(self.empty(section))
        if environment:
            blocks.append(f"\\end{{{environment}}}")
        return blocks

    def table(self, table: dict) -> str:
        tr, columns, rows = self.tr, table["columns"], table["rows"]
        caption = export_text.table_caption(table, tr)
        prefix = "TABLO I. " if tr else "TABLE I. "
        assert caption.startswith(prefix), "Table caption prefix is missing"
        caption = self.fixed(caption.removeprefix(prefix))
        groups = [columns[i:i + MAX_DATA_COLUMNS] for i in range(0, len(columns), MAX_DATA_COLUMNS)] or [[]]
        if len(groups) > 1:
            self.notes.append(f"Table I was split into {len(groups)} column groups of at most 7 data columns.")
        # Position, not text equality, owns the pointer; repeated groups reuse it.
        moved: list[tuple[str, str | None, str]] = []
        def value(raw: str, threshold: int, position: str, label: str | None = None) -> str:
            if len(raw) > threshold:
                moved.append((position, label, raw))
                n = len(moved)
                return self.fixed(f"{n} numaralı nota bakın" if tr else f"see note {n}")
            return self.line(raw)
        headings = [value(c["name"], HEADING_THRESHOLD, f"Sütun {i} başlığı" if tr else f"Column {i} heading")
                    for i, c in enumerate(columns, 1)]
        cells = {(c["source_version_id"], c["column_id"]): c for c in table["cells"]}
        rendered = []
        for r, row in enumerate(rows, 1):
            number, key = row.get("ref_number"), row.get("source_key")
            label = (f"[{number}]" + (f" {key}" if key is not None else "")) if number is not None else (f"satır {r}" if tr else f"row {r}")
            source_pos = f"Satır {r} kaynağı" if tr else f"Row {r} source"
            # Defer escaping long-value labels and full text to their document position.
            source_raw = export_text.source_cell(row, tr, str)
            source = value(source_raw, SOURCE_THRESHOLD, source_pos, label)
            values = []
            for c, column in enumerate(columns, 1):
                cell = cells.get((row["source_version_id"], column["column_id"]))
                raw = export_text.cell_text(cell, column, tr, str)
                position = f"Satır {r}, sütun {c}" if tr else f"Row {r}, column {c}"
                values.append(self.fixed(raw) if cell is None else value(raw, CELL_THRESHOLD, position, label))
            rendered.append((source, values))
        self.long_values.extend(moved)
        if moved:
            self.notes.append("1 table value was moved to the Long table values list in Report notes." if len(moved) == 1
                              else f"{len(moved)} table values were moved to the Long table values list in Report notes.")
        blocks = [r"\onecolumn"]
        for g, group in enumerate(groups):
            if g:
                blocks.append(r"\addtocounter{table}{-1}")
            n, start = len(group), g * MAX_DATA_COLUMNS
            width = f"\\dimexpr(\\textwidth-{SOURCE_COLUMN_WIDTH}-2\\tabcolsep)/{n}-2\\tabcolsep\\relax" if n else ""
            spec = f">{{\\raggedright\\arraybackslash}}p{{{SOURCE_COLUMN_WIDTH}}}" + f">{{\\raggedright\\arraybackslash}}p{{{width}}}" * n
            suffix = (f" ({len(columns)} sütundan {start + 1}–{start + n})" if tr else f" (columns {start + 1}–{start + n} of {len(columns)})") if len(groups) > 1 else ""
            continued = " (devamı)" if tr else " (continued)"
            header = " & ".join([_guard(self.line(export_text.source_heading(tr))), *headings[start:start + n]]) + r" \\"
            lines = [r"{\scriptsize", f"\\begin{{longtable}}{{{spec}}}", f"\\caption{{{caption}{suffix}}}\\\\", r"\toprule", header,
                     r"\midrule", r"\endfirsthead", f"\\caption[]{{{caption}{suffix}{continued}}}\\\\", r"\toprule", header,
                     r"\midrule", r"\endhead", r"\bottomrule", r"\endlastfoot"]
            lines.extend(" & ".join([_guard(source), *values[start:start + n]]) + r" \\" for source, values in rendered)
            lines.append(r"\end{longtable}}")
            blocks.append("\n".join(lines))
        blocks.append(r"\twocolumn")
        return "\n".join(blocks)

    def report_notes(self, view: dict, corpus: dict | None) -> list[str]:
        tr, fixed, line = self.tr, self.fixed, self.line
        blocks = ["\\section*{" + fixed("Rapor notları" if tr else "Report notes") + "}",
                  fixed(export_text.corpus_footer(corpus, tr)),
                  fixed(export_text.anchor_note(view, tr)) + " " + export_text.review_note(view, tr, line)]
        review = view.get("review")
        if review and review["status"] == "reviewed" and review["findings"]:
            blocks.append("\\noindent\\textbf{" + fixed(export_text.findings_heading(tr)) + "}")
            blocks.append(_itemize([MIDDLE_DOT.join(export_text.finding_fields(f, tr, line)) for f in review["findings"]]))
        if self.long_values:
            blocks.append("\\noindent\\textbf{" + fixed("Uzun tablo değerleri" if tr else "Long table values") + "}")
            # Labels and full values are separate stored contexts: their dollar
            # delimiters must never pair across the generated position prefix.
            items = [f"\\item[{i}.] " + fixed(position) + (" (" + line(label) + ")" if label is not None else "")
                     + ": " + line(raw) for i, (position, label, raw) in enumerate(self.long_values, 1)]
            blocks.append("\n".join([r"\begin{itemize}", *items, r"\end{itemize}"]))
        blocks.append(fixed(TRACEABILITY_LIMIT[int(tr)]))
        return blocks


def to_latex(view: dict[str, Any], *, title: str, corpus: dict[str, int] | None,
             bib_sources: list[dict]) -> LatexBundle:
    """Assemble without renumbering, dropping evidence links or changing inputs."""
    edited = view.get("edited_after_version")
    if edited is not None and type(edited) is not int:
        raise RevisionConflict("The edited-after version must be an integer or null")
    check = view.get("edit_check")
    if check is not None and any(type(check.get(name)) is not int for name in ("errors", "warnings")):
        raise RevisionConflict("Edit-check error and warning counts must be integers")
    stem = export_text.report_stem(view, _text_of(title))
    if re.fullmatch(r"report-[a-z0-9-]+-(draft|v[0-9]+)", stem) is None:
        raise RevisionConflict("The report filename stem is invalid")
    keys, sources, key_notes = _references(view, bib_sources)
    sections = sorted(view["sections"], key=lambda s: DISPLAY_ORDER.index(s["section_id"])
                      if s["section_id"] in DISPLAY_ORDER else len(DISPLAY_ORDER))
    targets, equation_notes = _equations(sections)
    writer = _Writer(export_text.is_turkish(view), keys, targets)
    blocks = [latex_preamble.PREAMBLE.rstrip("\n"), r"\begin{document}"]
    if writer.tr:
        blocks.append("\n".join([r"\renewcommand{\abstractname}{Özet}", r"\renewcommand{\IEEEkeywordsname}{Dizin Terimleri}", r"\renewcommand{\refname}{Kaynaklar}"]))
    blocks.extend(["\\title{" + writer.line(title) + "}", r"\maketitle", *writer.unchecked(view)])
    for section in sections:
        blocks.extend(writer.section(section, view.get("table_i") if section["section_id"] == "IV" else None))
    blocks.extend(writer.report_notes(view, corpus))
    if writer.cited:
        blocks.extend([r"\bibliographystyle{IEEEtran}", "\\bibliography{" + stem + "}"])
    blocks.append(r"\end{document}")
    order_notes = []
    if any(position != number for position, number in enumerate(writer.cited, 1)):
        order_notes.append("Reference numbers in the PDF follow the order of first citation and differ from the numbers in DEIXIS.")
    order_notes.extend(f"Reference [{ref['number']}] is not cited in the text and BibTeX will not print it."
                       for ref in view["references"] if ref["number"] not in writer.cited)
    if not writer.cited:
        order_notes.append("The report holds no citations; the bibliography commands were left out.")
    # bibliography imports views at module level; lazy import keeps this writer out
    # of the view/bibliography initialization path when X4 imports it.
    from deixis.workflow.bibliography import bibtex_with_notes
    bib, bib_notes = bibtex_with_notes(sources, list(keys.values()), latex_report=True, unmapped=writer.um)
    notes = _normalise_notes(key_notes + order_notes + equation_notes + writer.notes + bib_notes
                             + ([writer.um.note()] if writer.um.note() else []))
    tex = _comment_block(stem, notes) + "\n\n" + "\n\n".join(block for block in blocks if block) + "\n"
    return LatexBundle(stem, tex, bib, notes)
