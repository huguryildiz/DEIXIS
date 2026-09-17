"""Pure tests for code-owned fields of the frozen report plan."""

from deixis.workflow.report.plan import ALLOWED_SUPPORT, freeze_plan, section_budgets


def test_section_budgets_scale_the_total_and_floor_the_scaled_total_at_1200_words():
    full = section_budgets(5500, 20)
    four_sources = section_budgets(5500, 4)
    one_source = section_budgets(5500, 1)

    assert sum(item["max_words"] for item in full.values()) == 5500
    assert sum(item["max_words"] for item in four_sources.values()) == 2200
    assert sum(item["max_words"] for item in one_source.values()) == 1200


def test_section_budgets_lock_section_priority_and_the_forty_claim_ceiling():
    budgets = section_budgets(5000, 10)

    assert budgets["IV"]["max_words"] > budgets["III"]["max_words"]
    assert budgets["III"]["max_words"] == budgets["V"]["max_words"] > budgets["VI"]["max_words"]
    assert budgets["VI"]["max_words"] > budgets["VIII"]["max_words"]
    assert all(item["min_words"] == int(0.6 * item["max_words"]) for item in budgets.values())
    assert all(item["max_claims"] == 40 for item in budgets.values())


def test_freeze_plan_overrides_all_model_supplied_code_owned_fields_without_mutating_the_draft():
    model_plan = {
        "scope_statement": "SYNTHETIC scope", "research_questions": [], "glossary": [], "axes": [],
        "corpus": {"included": 999}, "section_budgets": {"VI": {"max_words": 999999}},
        "allowed_support": {"VI": ["source_stated"]},
    }
    snapshot = {"corpus": {"found": 40, "unique": 22, "screened": 22, "included": 8, "full_text": 5}}

    frozen = freeze_plan(model_plan, snapshot, included_count=8)

    assert frozen["corpus"] == snapshot["corpus"]
    assert frozen["allowed_support"]["VI"] == ["analyst_inference"]
    assert frozen["section_budgets"] == section_budgets(5500, 8)
    assert model_plan["corpus"] == {"included": 999}
    assert ALLOWED_SUPPORT["VI"] == ("analyst_inference",)
