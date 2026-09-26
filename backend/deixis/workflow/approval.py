"""The user's correction of the proposed vocabulary and criterion, before the protocol is frozen (SW2.6, SW15.3).

Pure: no network, no store, no clock. A correction is a small list of operations on phrases the proposal already
holds, plus an optional replacement for the whole criterion. Nothing is edited in place: the proposal stays in the
approval step's output as it was and the approved form is written beside it (SW14.2).

The user's correction stands above the code rule and above the model's labelling (SW17.2, AGENTS.md "User
Authority"): a phrase the user moved or added carries `user` as its block origin and no later step takes it back.
What the user adds is still checked against the literature by the same count probe every other term met (SW2.1), so
a phrase no record holds drops here exactly as it would have dropped in the first round.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.domain.canonical import sha256_hex
from deixis.domain.vocabulary import BLOCK_NAMES, Extraction
from deixis.workflow.criterion import MAX_EXCLUSION_TITLE_WORDS, MAX_PHRASE_WORDS, PARTS_PER_PROPOSAL, norm
from deixis.workflow.vocabulary import LABELS

MAX_TERM_EDITS = 40  # operations one correction may carry
MAX_TERM_CHARS = 80
MAX_TERM_WORDS = 6
MAX_NOTE_CHARS = 1_000
MAX_CRITERION_CHARS = 600
MAX_PART_NAME_CHARS = 60
MAX_PART_DEFINITION_CHARS = 400
MAX_EXCLUSION_WORD_CHARS = 40
# Saying "this is not a term" is `remove`, so the one label a block edit cannot name is `not_a_term`.
EDIT_BLOCKS = tuple(label for label in LABELS if label != "not_a_term")
OPERATIONS = ("remove", "move", "add")
SIDE_LISTS = {"claim": "claim_words", "exclusion": "exclusion_words", "outcome": "outcome_terms"}


# ---- what the proposal holds ------------------------------------------------------------
def proposal_rows(vocabulary: dict[str, Any]) -> list[dict[str, str]]:
    """Every phrase of the proposal with the block it sits in, in the order the vocabulary was built in.

    A dropped term is here too: it is part of what the user is shown and of what a rebuild probes again, and the
    count that dropped it is already stored, so reading it costs no request.
    """
    default = "key_terms" if vocabulary["block_assignment"] == "user" else "question"
    rows = [{"phrase": term["phrase"], "block": term["block"], "origin": term["origin"]}
            for term in vocabulary["terms"]]
    for block, field in SIDE_LISTS.items():
        # A body rebuilt from a partial record may carry only the fields that body needs, so a missing side list is
        # an empty one here rather than a failure to build the protocol.
        rows += [{"phrase": phrase, "block": block, "origin": default} for phrase in vocabulary.get(field) or []]
    return rows


def proposal_blocks(vocabulary: dict[str, Any]) -> dict[str, str]:
    """The block each normalised phrase of the proposal is in; what a `remove` or a `move` must name."""
    return {norm(row["phrase"]): row["block"] for row in proposal_rows(vocabulary)}


def block_origins(vocabulary: dict[str, Any]) -> dict[str, str]:
    """Who put each phrase in its block: the code rule, the model's labelling step, the model that wrote the query
    (D92) or the user (SW17.6, SW2.6)."""
    default = {"user": "user", "search_query": "search_query"}.get(vocabulary["block_assignment"], "rule")
    origins = {row["phrase"]: default for row in proposal_rows(vocabulary)}
    origins |= {record["phrase"]: record["origin"]
                for record in (vocabulary.get("labelling") or {}).get("phrases", [])}
    # The user's own operation is last and nothing after it moves the phrase back.
    origins |= {edit["phrase"]: "user" for edit in vocabulary.get("user_edits") or [] if edit["op"] != "remove"}
    return origins


def proposal_hash(vocabulary: dict[str, Any], criterion: dict[str, Any] | None) -> str:
    """A digest of what the user was asked about: the phrases, their blocks and the criterion fields.

    The counts are left out on purpose. They are what the literature held on the day of the first run and change on
    their own, so two runs of the same question were asked the same thing even when the numbers moved.
    """
    return sha256_hex({
        "terms": sorted([norm(row["phrase"]), row["block"]] for row in proposal_rows(vocabulary)),
        "criterion": None if criterion is None else {
            "criterion": criterion["criterion"],
            "parts": [[part["name"], part["definition"]] for part in criterion["parts"]],
            "cue_phrases": sorted([norm(c["phrase"]), c["part"] or ""] for c in criterion["cue_phrases"]),
            "exclusion_title_words": sorted(criterion["exclusion_title_words"]),
        },
    })


# ---- checking a correction --------------------------------------------------------------
def _text_error(text: Any, limit: int, words: int, what: str) -> str | None:
    if not isinstance(text, str) or not norm(text):
        return f"{what} is empty"
    value = norm(text)
    if len(value) > limit:
        return f"{what} {value!r} is longer than {limit} characters"
    if words and len(value.split()) > words:
        return f"{what} {value!r} has more than {words} words"
    return None


def check_edits(proposal: dict[str, Any], edits: dict[str, Any]) -> list[str]:
    """Everything wrong with a correction, or an empty list. A refused correction is refused whole.

    An operation that names a phrase the proposal does not hold, or adds one it already holds, is an error and not
    a silently skipped line: the user would otherwise believe a term entered the search that never did.
    """
    errors: list[str] = []
    terms = edits.get("terms") or []
    if not isinstance(terms, list):
        return ["The term edits must be a list"]
    if len(terms) > MAX_TERM_EDITS:
        errors.append(f"At most {MAX_TERM_EDITS} term edits, not {len(terms)}")
    known = proposal_blocks(proposal["vocabulary"])
    seen: set[str] = set()
    for edit in terms:
        if not isinstance(edit, dict) or edit.get("op") not in OPERATIONS:
            errors.append(f"Unknown term edit {edit!r}")
            continue
        operation = edit["op"]
        if problem := _text_error(edit.get("phrase"), MAX_TERM_CHARS, MAX_TERM_WORDS, "The term"):
            errors.append(problem)
            continue
        phrase = norm(edit["phrase"])
        if phrase in seen:
            errors.append(f"Two edits of the term {phrase!r}")
            continue
        seen.add(phrase)
        if operation in ("move", "add") and edit.get("block") not in EDIT_BLOCKS:
            errors.append(f"{edit.get('block')!r} is not a block; use one of {', '.join(EDIT_BLOCKS)}")
            continue
        if operation in ("remove", "move") and phrase not in known:
            errors.append(f"There is no term {phrase!r} to {operation}")
        if operation == "add" and phrase in known:
            errors.append(f"The term {phrase!r} is already in the {known[phrase]} block")
    errors += _criterion_errors(edits.get("criterion"))
    code_query = edits.get("code_query")
    if code_query is not None and (not isinstance(code_query, bool)
                                   or proposal["vocabulary"]["block_assignment"] != "search_query"):
        # The switch exists only on a card whose query a model wrote; the code's query is then offered beside it (D92).
        errors.append("The code query switch is a true or false answer on a card whose query a model wrote")
    elif code_query is True and not proposal["vocabulary"]["code_query"]["searched"]:
        # A code query that could not be searched was never offered; turning it on would be a choice nobody applies.
        errors.append("The code's query cannot be searched on its own, so it cannot be switched on")
    note = edits.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE_CHARS):
        errors.append(f"The note is longer than {MAX_NOTE_CHARS} characters")
    return errors


def _criterion_errors(edited: Any) -> list[str]:
    """The bounds of the criterion contract, applied to what the user wrote instead of to what a model wrote.

    One bound is not applied: the 6 to 15 phrases a proposal must give per part. The consensus does not hold it
    either — it keeps the phrases two runs agreed on — and a user must be able to delete a phrase.
    """
    if edited is None:
        return []
    if not isinstance(edited, dict):
        return ["The criterion must be an object or null"]
    errors: list[str] = []
    if problem := _text_error(edited.get("criterion"), MAX_CRITERION_CHARS, 0, "The criterion"):
        errors.append(problem)
    parts = edited.get("parts")
    low, high = PARTS_PER_PROPOSAL
    if not isinstance(parts, list) or not low <= len(parts) <= high:
        errors.append(f"The criterion needs {low} to {high} parts")
        parts = []
    names: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            errors.append(f"A criterion part must be an object, not {part!r}")
            continue
        for field, limit, what in (("name", MAX_PART_NAME_CHARS, "A part name"),
                                   ("definition", MAX_PART_DEFINITION_CHARS, "A part definition")):
            if problem := _text_error(part.get(field), limit, 0, what):
                errors.append(problem)
        if isinstance(part.get("name"), str):
            names.append(norm(part["name"]))
    if len(set(names)) != len(names):
        errors.append("Two criterion parts have the same name")
    phrases = edited.get("cue_phrases")
    if not isinstance(phrases, list):
        errors.append("The cue phrases must be a list")
        phrases = []
    for phrase in phrases:
        if not isinstance(phrase, dict):
            errors.append(f"A cue phrase must be an object, not {phrase!r}")
            continue
        if problem := _text_error(phrase.get("phrase"), MAX_TERM_CHARS, MAX_PHRASE_WORDS, "A cue phrase"):
            errors.append(problem)
        part = phrase.get("part")
        if part is not None and norm(part or "") not in names:
            errors.append(f"The cue phrase part {part!r} is not one of the criterion's parts")
    words = edited.get("exclusion_title_words")
    if not isinstance(words, list) or len(words) > MAX_EXCLUSION_TITLE_WORDS:
        errors.append(f"At most {MAX_EXCLUSION_TITLE_WORDS} exclusion title words")
        words = []
    for word in words:
        if problem := _text_error(word, MAX_EXCLUSION_WORD_CHARS, 0, "An exclusion title word"):
            errors.append(problem)
    return errors


# ---- applying a correction --------------------------------------------------------------
def canonical_edits(term_edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The operations written one way round: by phrase, which is unique across them (SW14.6)."""
    return sorted(({"op": edit["op"], "phrase": norm(edit["phrase"])}
                   | ({"block": edit["block"]} if edit["op"] in ("move", "add") else {})
                   for edit in term_edits), key=lambda edit: edit["phrase"])


def applicable(vocabulary: dict[str, Any], term_edits: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """An earlier approval's operations split into the ones this vocabulary can still take, and the rest.

    A second discovery run of the same question reads the same records, but not necessarily the same phrases: the
    question is unchanged, the extraction is not re-run against other text, yet a term the first run dropped or a
    block the labelling moved may differ. An operation whose phrase is no longer where it was is skipped rather than
    refused — the run must not stop again for a question the user already answered — and it stays on record.
    """
    known = proposal_blocks(vocabulary)
    kept, skipped = [], []
    for edit in canonical_edits(term_edits):
        gone = (edit["phrase"] not in known if edit["op"] in ("remove", "move")
                else edit["phrase"] in known)
        (skipped if gone else kept).append(edit | ({"reason": "phrase_not_in_proposal"} if gone else {}))
    return kept, skipped


def edited_extraction(vocabulary: dict[str, Any], term_edits: list[dict[str, Any]],
                      model_phrases: frozenset[str] | set[str] = frozenset()) -> Extraction:
    """The corrected phrases as an `Extraction`, so one code path builds every vocabulary.

    The corrected vocabulary is never patched into the proposal's term dictionaries: it is rebuilt from here by
    `vocabulary.build_vocabulary`, which is what decides the root or phrase form, the AND-only mark, the gate
    narrowing and `too_broad`. Patching would give a corrected vocabulary those decisions took no part in.

    `model_phrases` are this approval's stored suggestions (slice 08c). A phrase the user added carries the term
    origin `model` when it is one of them and `user` otherwise; the origin is derived here, on the server, and is
    never read from the `add` operation, whose shape did not change. The block origin stays `user` either way: it
    was the user who put the phrase in that block. With no suggestions the result is byte for byte what it was.
    """
    operations = {edit["phrase"]: edit for edit in canonical_edits(term_edits)}
    rows: list[dict[str, str]] = []
    for row in proposal_rows(vocabulary):
        edit = operations.get(norm(row["phrase"]))
        if edit is None:
            rows.append(row)
        elif edit["op"] == "move":
            rows.append(row | {"block": edit["block"]})
    # Added phrases come last, in their canonical order, so the probe order of an approval does not follow the order
    # the user happened to type them in.
    rows += [{"phrase": edit["phrase"], "block": edit["block"],
              "origin": "model" if edit["phrase"] in model_phrases else "user"}
             for edit in operations.values() if edit["op"] == "add"]
    return Extraction(
        language=vocabulary["language"],
        blocks={name: [row["phrase"] for row in rows if row["block"] == name] for name in BLOCK_NAMES},
        claim_words=[row["phrase"] for row in rows if row["block"] == "claim"],
        exclusion_words=[row["phrase"] for row in rows if row["block"] == "exclusion"],
        block_assignment=vocabulary["block_assignment"],
        origins={row["phrase"]: row["origin"] for row in rows},
    )


def apply_criterion(proposed: dict[str, Any] | None, edited: dict[str, Any] | None) -> dict[str, Any] | None:
    """The criterion the research searches under: the proposal as it was, or the user's replacement.

    A phrase the proposal also held keeps the runs that wrote it; one the user added has no run behind it and says
    so with an empty list. The record of how the proposal was made (`base_run`, `runs_ok` and the rest) travels with
    the corrected criterion: the user corrected that proposal, and dropping its provenance would hide which one.
    """
    if edited is None:
        return proposed
    runs_of = {norm(phrase["phrase"]): phrase["runs"] for phrase in (proposed or {}).get("cue_phrases", [])}
    parts = [{"name": part["name"].strip(), "definition": part["definition"].strip()} for part in edited["parts"]]
    # A phrase names its part the way the part is written above, however the user spelled it in the phrase row.
    named = {norm(part["name"]): part["name"] for part in parts}
    return {
        "criterion": edited["criterion"].strip(),
        "parts": parts,
        "cue_phrases": [{"phrase": norm(phrase["phrase"]), "part": named.get(norm(phrase["part"] or "")),
                         "runs": runs_of.get(norm(phrase["phrase"]), [])} for phrase in edited["cue_phrases"]],
        "exclusion_title_words": [norm(word) for word in edited["exclusion_title_words"]],
        "dropped_exclusion_title_words": (proposed or {}).get("dropped_exclusion_title_words", []),
        "base_run": (proposed or {}).get("base_run"),
        "runs_ok": (proposed or {}).get("runs_ok", []),
        "sought_term_in_criterion": (proposed or {}).get("sought_term_in_criterion"),
        # What the proposal named as the question's population and comparator (SW23). It is the proposal's record and
        # is not checked again against the user's parts: the user may delete such a part, and the user's word stands.
        "question_elements": (proposed or {}).get("question_elements", []),
        "required_roles": (proposed or {}).get("required_roles", []),
        "origin": "user",
    }


def exclusion_words_in_question(question: str, criterion: dict[str, Any] | None) -> list[str]:
    """Exclusion title words the question itself uses. It is a mark on the approval, never a removal.

    SW5.1 has code drop such a word from a *proposal*: a research asking about surveys may not exclude "survey"
    from its own titles. It is not applied to what the user wrote, because the user wrote it knowing the question.
    """
    asked = norm(question)
    return sorted(word for word in (criterion or {}).get("exclusion_title_words", [])
                  if all(re.search(rf"\b{re.escape(part)}\b", asked) for part in word.split()))
