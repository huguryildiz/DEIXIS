"""The contract changes of slice 22 (D104, decision 7): the `latex_source` value, `report_section_draft.v3` and the
`equation_origin` check. Inputs are SYNTHETIC; no network is used."""

import copy
import json
from deixis.domain import contracts, skill
from arxiv_helpers import no_network  # noqa: F401  (fixtures used by name)


STEP_INPUTS = json.loads((__import__("pathlib").Path(__file__).parent.parent / "fixtures/research/step-inputs.json").read_text())


OLD_HASH = "sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca"


# ---- contracts ------------------------------------------------------------------------------------------------------------
def section_case():
    step_input = copy.deepcopy(STEP_INPUTS["C_report_section_IV"])
    cases = json.loads((__import__("pathlib").Path(__file__).parent.parent / "fixtures/research/fake-outputs.json").read_text())["cases"]
    case = next(c for c in cases if c["step_input"] == "C_report_section_IV" and c["expect_ok"])
    return step_input, copy.deepcopy(case["output"])


def validate(step_input, output):
    return contracts.validate_model_output(step_input, json.dumps(output))


def test_a_step_input_passage_may_carry_latex_source():
    step_input = copy.deepcopy(STEP_INPUTS["A_answer"])
    passage = next(p for p in step_input["passages"] if p["text_source"] == "text_layer")
    passage["text_source"] = "latex_source"
    assert contracts.check_step_input(step_input) == []
    passage["text_source"] = "compiled_source"
    assert [i.code for i in contracts.check_step_input(step_input)] == ["step_input_schema_invalid"]


def test_the_report_section_draft_is_v3_and_its_equation_origin_is_checked():
    assert contracts.SCHEMA_VERSIONS["ReportSectionDraft"] == "deixis.report_section_draft.v3"
    step_input, output = section_case()
    assert output["schema_version"] == "deixis.report_section_draft.v3"
    claim = output["claims"][0]
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    cited = claim["passage_ids"][0]
    passages[cited]["text"] += " $$x=1$$"  # RF4: an equation origin must contain recognized math
    for source in ("latex_source", "marker", "ocr", "text_layer"):
        passages[cited]["text_source"] = source
        claim["equation_origin"] = {"passage_id": cited, "text_source": source}
        assert not [i for i in validate(step_input, output).issues if i.code.startswith("equation_origin")], source
        claim["equation_origin"] = {"passage_id": cited, "text_source": "ocr" if source != "ocr" else "marker"}
        assert "equation_origin_mismatch" in {i.code for i in validate(step_input, output).issues}
    uncited = next(pid for pid in passages if pid not in claim["passage_ids"])
    claim["equation_origin"] = {"passage_id": uncited, "text_source": passages[uncited]["text_source"] or "text_layer"}
    assert "equation_origin_not_cited" in {i.code for i in validate(step_input, output).issues}
    claim["equation_origin"] = {"passage_id": "psg_NOTGIVEN00001", "text_source": "latex_source"}
    assert "unknown_passage_id" in {i.code for i in validate(step_input, output).issues}


def test_a_stored_v2_section_draft_still_revalidates_and_new_output_must_be_v3():
    # Sol r1 finding 4 (D40): the wording rollback re-checks a stored draft with `revalidate_section`.
    from deixis.workflow.report_sections import revalidate_section

    step_input, output = section_case()
    output["schema_version"] = "deixis.report_section_draft.v2"
    assert revalidate_section(step_input, output).ok
    assert output["schema_version"] == "deixis.report_section_draft.v2"  # the stored draft keeps its version
    assert not validate(step_input, output).ok  # a model's new output is held to v3
    output["schema_version"] = "deixis.report_section_draft.v1"
    assert not revalidate_section(step_input, output).ok


def test_the_method_package_names_latex_source_and_its_hash_moved():
    assert skill.package_hash() != OLD_HASH and skill.integrity_issues() == []
    for name in ("source-grounded-answer.md", "evidence-table.md"):
        text = (skill.SKILL_DIR / "references" / name).read_text()
        assert "`latex_source` is the PDF's own text of a passage" in text
        assert "did not check that the source compiles to" in text and "verified" not in text.split("`latex_source`")[1][:600]
