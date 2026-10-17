"""D80: the evidence ledger of a grounded answer, its split before validation, its checks and its repair hints.

SYNTHETIC fixtures only: these show what the code keeps, drops and reports, not whether a model's reason is right.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from deixis.domain import contracts
from deixis.models import prompt

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research"
SI = json.loads((FIXTURES / "step-inputs.json").read_text())["A_answer"]
VALID = next(c for c in json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"] if c["name"] == "answer_valid")["output"]
A1, A2, A3PRE, A3PUB, A5 = "srv_SYNA1pub01", "srv_SYNA2pub01", "srv_SYNA3pre01", "srv_SYNA3pub01", "srv_SYNA5pub01"
A2_TEXT = next(p["text"] for p in SI["passages"] if p["passage_id"] == "psg_SYNA2abs01")


def entry(source, reason="no_answering_content", passage=None, quote=None, same_as=None, note="SYNTHETIC: left out."):
    return {"source_id": source, "reason": reason, "note": note, "passage_id": passage, "quote": quote,
            "same_as_source_id": same_as}


def ledger_of(entries=None, answer=None):
    answer = copy.deepcopy(answer or VALID)
    if entries is not None:
        answer["excluded_sources"] = entries
    links = contracts.derive_evidence_links(SI, answer)
    return contracts.answer_ledger(SI, answer, links, [])


def codes(ledger):
    return [(d["source_id"], d["code"]) for d in ledger["dropped"]]


def test_a_full_ledger_takes_the_cited_set_from_the_links_and_is_complete():
    ledger = ledger_of()
    assert ledger["version"] == 1 and ledger["given"] == [s["source_id"] for s in SI["sources"]]
    assert ledger["cited"] == [A1, A3PRE]
    assert [e["source_id"] for e in ledger["excluded"]] == [A2, A3PUB, A5]
    assert all(e["anchor_text"] is None and e["anchor_match"] is None for e in ledger["excluded"])
    assert ledger["unaccounted"] == [] and ledger["dropped"] == [] and ledger["complete"] is True


def test_a_source_with_no_entry_is_unaccounted_and_the_answer_stays_valid():
    answer = copy.deepcopy(VALID)
    answer["excluded_sources"] = answer["excluded_sources"][:2]
    assert contracts.validate_model_output(SI, answer).ok
    ledger = ledger_of(answer=answer)
    assert ledger["unaccounted"] == [A5] and ledger["complete"] is False


def test_an_entry_for_a_cited_source_is_dropped_and_the_citation_stands():
    ledger = ledger_of(VALID["excluded_sources"] + [entry(A1)])
    assert codes(ledger) == [(A1, "entry_for_cited_source")]
    assert ledger["cited"] == [A1, A3PRE] and ledger["complete"] is True


def test_an_unknown_source_and_a_repeated_source_are_dropped_and_the_first_entry_is_kept():
    ledger = ledger_of([entry("srv_SYNZZZZZZZ"), entry(A2, note="SYNTHETIC: first."), entry(A2, note="SYNTHETIC: second."),
                        entry(A3PUB), entry(A5)])
    assert codes(ledger) == [("srv_SYNZZZZZZZ", "entry_unknown_source"), (A2, "entry_duplicate_source")]
    assert [e["note"] for e in ledger["excluded"] if e["source_id"] == A2] == ["SYNTHETIC: first."]
    assert [d["index"] for d in ledger["dropped"]] == [0, 2]


def test_a_quote_from_another_source_or_outside_the_allowlist_is_dropped():
    other = entry(A2, "different_conditions", "psg_SYNA1abs01", "We formulate release-time scheduling")
    outside = entry(A5, "different_conditions", "psg_SYNB1pg001", "Nodes carry hydrophones.")
    ledger = ledger_of([other, entry(A3PUB), outside])
    assert codes(ledger) == [(A2, "entry_passage_other_source"), (A5, "entry_passage_unknown")]
    assert ledger["unaccounted"] == [A2, A5]


def test_a_quote_is_located_with_the_claim_anchor_matcher_and_ratio():
    fuzzy = "We study how relay bacteria shar a limited nutrient supply among forwarding tasks."  # one letter dropped
    assert contracts.locate_anchor(fuzzy, A2_TEXT).kind == "fuzzy"
    kept = ledger_of([entry(A2, "different_conditions", "psg_SYNA2abs01", fuzzy), entry(A3PUB), entry(A5)])
    assert kept["dropped"] == [] and kept["excluded"][0]["anchor_match"] == "fuzzy"
    assert kept["excluded"][0]["anchor_text"] == contracts.locate_anchor(fuzzy, A2_TEXT).text
    missing = ledger_of([entry(A2, "different_conditions", "psg_SYNA2abs01", "A sentence the passage never states at all.")])
    assert codes(missing) == [(A2, "entry_quote_not_located")]


def test_a_reason_that_needs_a_quote_without_one_is_dropped_and_a_quote_on_other_reasons_is_optional():
    ledger = ledger_of([entry(A2, "claim_limit"), entry(A5, "different_conditions", "psg_SYNA5abs01")])
    assert codes(ledger) == [(A2, "entry_claim_limit_not_reached"), (A5, "entry_quote_missing")]
    ignored = ledger_of([entry(A2, "off_topic", "psg_SYNA2abs01", "A sentence the passage never states at all.")])
    assert ignored["dropped"] == [] and ignored["excluded"][0]["anchor_text"] is None
    located = ledger_of([entry(A2, "off_topic", "psg_SYNA2abs01", "share a limited nutrient supply")])
    assert located["excluded"][0]["anchor_match"] == "exact"


def test_same_as_must_name_a_cited_source_and_claim_limit_needs_thirty_claims():
    quote = "share a limited nutrient supply"
    ledger = ledger_of([entry(A2, "same_finding_as_cited", "psg_SYNA2abs01", quote, same_as=A5),
                        entry(A5, "same_finding_as_cited", "psg_SYNA5abs01", None, same_as=None),
                        entry(A3PUB, "off_topic", same_as=A2)])
    assert codes(ledger) == [(A2, "entry_same_as_not_cited"), (A5, "entry_same_as_not_cited"),
                             (A3PUB, "entry_same_as_not_cited")]
    assert ledger_of([entry(A2, "same_finding_as_cited", "psg_SYNA2abs01", quote, same_as=A1)])["dropped"] == []
    limit = entry(A2, "claim_limit", "psg_SYNA2abs01", quote)
    for count, dropped in ((29, [(A2, "entry_claim_limit_not_reached")]), (30, [])):
        answer = copy.deepcopy(VALID) | {"excluded_sources": [limit]}
        links = contracts.derive_evidence_links(SI, answer)
        answer["claims"] = (answer["claims"] * count)[:count]
        assert codes(contracts.answer_ledger(SI, answer, links, [])) == dropped


def test_handles_in_all_three_id_fields_resolve_and_round_trip():
    handles = contracts.citation_handles(SI)
    shown = {"excluded_sources": [
        {"source_id": handles[A2], "passage_id": "psg_P3", "same_as_source_id": "srv_S00000001"},
        {"source_id": "srv_S5", "passage_id": None, "same_as_source_id": None}]}
    data = contracts.resolve_citation_handles(SI, json.dumps(shown))
    assert data["excluded_sources"] == [{"source_id": A2, "passage_id": "psg_SYNA2abs01", "same_as_source_id": A1},
                                        {"source_id": A5, "passage_id": None, "same_as_source_id": None}]
    answer = copy.deepcopy(VALID)
    answer["excluded_sources"][0] |= {"reason": "same_finding_as_cited", "passage_id": "psg_SYNA2abs01",
                                      "quote": "share a limited nutrient supply", "same_as_source_id": A1}
    written = contracts.answer_with_handles(SI, answer)
    first = json.loads(written)["excluded_sources"][0]
    assert [first[key] for key in contracts.LEDGER_ID_FIELDS] == [handles[A2], handles["psg_SYNA2abs01"], handles[A1]]
    assert contracts.resolve_citation_handles(SI, written) == answer


@pytest.mark.parametrize("value", [None, "srv_SYNA2pub01", [1, "x", None],
                                   [{"source_id": [A2], "passage_id": {"p": "psg_SYNA2abs01"}, "same_as_source_id": 3}]])
def test_answer_with_handles_leaves_malformed_ledger_values_as_they_are(value):
    answer = copy.deepcopy(VALID) | {"excluded_sources": value}
    assert json.loads(contracts.answer_with_handles(SI, answer))["excluded_sources"] == value


def test_the_resolver_leaves_malformed_ledger_values_for_the_split():
    raw = {"excluded_sources": [1, "srv_S1", {"source_id": ["srv_S1"], "passage_id": {"x": "psg_P1"}, "same_as_source_id": 3}]}
    assert contracts.resolve_citation_handles(SI, json.dumps(raw)) == raw
    assert contracts.resolve_citation_handles(SI, json.dumps({"excluded_sources": "srv_S1"})) == {"excluded_sources": "srv_S1"}


@pytest.mark.parametrize("value, expected", [
    (None, [("ledger_field_malformed", "/excluded_sources")]),
    ("srv_SYNA2pub01", [("ledger_field_malformed", "/excluded_sources")]),
    ([entry(A2) | {"why": "x"}], [("ledger_entry_malformed", "/excluded_sources/0")]),
    ([entry(A2), entry(A5, "irrelevant")], [("ledger_entry_malformed", "/excluded_sources/1")]),
    ([entry(A2, note="n" * 301)], [("ledger_entry_malformed", "/excluded_sources/0")]),
    ([entry(A2, "different_conditions", "psg_SYNA2abs01", "too short")], [("ledger_entry_malformed", "/excluded_sources/0")]),
    ([entry(A2)] * 201, [("ledger_too_many_entries", "/excluded_sources")]),
])
def test_the_split_removes_every_ledger_defect_and_the_answer_validates_on_its_claims(value, expected):
    draft = copy.deepcopy(VALID)
    if value is None:
        del draft["excluded_sources"]
    else:
        draft["excluded_sources"] = value
    kept, diagnostics = contracts.split_ledger(draft)
    assert draft["excluded_sources"] == [] and contracts.validate_model_output(SI, draft).ok
    assert [(d["code"], d["path"]) for d in diagnostics] == expected
    assert all(d["message"] for d in diagnostics)
    if isinstance(value, list):
        assert len(kept) == min(len(value), 200) - (len(expected) if expected[0][0] == "ledger_entry_malformed" else 0)
    if len(value or []) == 201:
        assert diagnostics[0]["count"] == 201


def test_hints_on_a_draft_with_an_unknown_claim_passage_and_a_missing_anchor_do_not_crash_or_change_its_issues():
    broken = copy.deepcopy(VALID)
    broken["claims"].append({"claim_label": "c4", "section": "Formulations", "text": "It has been reported that X.",
                             "support_type": "source_stated", "passage_ids": ["psg_SYNUNKNOWN1"]})
    broken["citation_anchors"] = broken["citation_anchors"][1:]
    with pytest.raises(KeyError):
        contracts.derive_evidence_links(SI, broken)  # why the hints never derive links
    bare = copy.deepcopy(broken) | {"excluded_sources": []}
    with_ledger = copy.deepcopy(broken) | {"excluded_sources": [entry(A1), entry(A2, "claim_limit")]}
    hints = contracts.ledger_hints(SI, with_ledger)
    assert any(A1 in h and "cites" in h for h in hints) and any(A2 in h and "claim_limit" in h for h in hints)
    assert any(h.startswith(f"{A5} is given") for h in hints)
    issues = lambda d: sorted((i.code, i.path) for i in contracts.validate_model_output(SI, d).issues)
    assert issues(with_ledger) == issues(bare)
    assert {"unknown_passage_id", "missing_citation_anchor"} <= {code for code, _ in issues(bare)}
    for odd in ("not json", None, [], {"claims": "x", "excluded_sources": [1]}):
        assert isinstance(contracts.ledger_hints(SI, odd), list)
    assert len(contracts.ledger_hints(SI, {"excluded_sources": [1] * 30})) == contracts.LEDGER_MAX_HINTS


def test_the_transport_schema_stays_strict_and_the_canonical_schema_accepts_a_stored_v4_draft():
    schema = contracts.model_output_schema("grounded_answer")
    assert contracts.strict_compatibility_issues(schema) == []
    assert schema["required"].count("excluded_sources") == 1
    contracts.canonical_validator("GroundedAnswerDraft").validate(VALID)
    assert VALID["schema_version"] == contracts.SCHEMA_VERSIONS["GroundedAnswerDraft"] == "deixis.grounded_answer_draft.v4"
    item = contracts.load_schema("GroundedAnswerDraft")["properties"]["excluded_sources"]["items"]
    assert item["additionalProperties"] is False and sorted(item["required"]) == sorted(item["properties"])

    def refs(node):
        if isinstance(node, dict):
            if "$ref" in node:
                yield node
            for value in node.values():
                yield from refs(value)
        elif isinstance(node, list):
            for value in node:
                yield from refs(value)
    assert all(len(node) == 1 for node in refs(item))
    Draft202012Validator.check_schema(schema)


def test_handles_in_a_note_become_source_titles():
    answer = copy.deepcopy(VALID)
    answer["excluded_sources"][0]["note"] = "SYNTHETIC: reports what srv_S0000001 already reports."
    named = contracts.name_sources_in_prose(SI, answer)
    assert named["excluded_sources"][0]["note"] == f"SYNTHETIC: reports what “{SI['sources'][0]['title']}” already reports."


def test_hints_print_under_their_own_heading_after_the_blocking_issues():
    issues = [{"code": "anchor_not_in_passage", "path": "/citation_anchors/0/quote", "message": "c1"}]
    plain = prompt.repair_message(SI, issues, None)
    assert prompt.repair_message(SI, issues, None, hints=[]) == plain
    hinted = prompt.repair_message(SI, issues, None, hints=["srv_S0000005 is given but neither cited nor listed."])
    assert hinted.startswith(plain) and prompt.LEDGER_HINTS_HEADING in hinted
    assert hinted.index("anchor_not_in_passage") < hinted.index(prompt.LEDGER_HINTS_HEADING)
    resplit = prompt.resplit_message(SI, issues, "{}", ["c2"], hints=["a hint"])
    assert resplit.index("anchor_not_in_passage") < resplit.index("- a hint") < resplit.index("Previous output")
