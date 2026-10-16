"""D51 report writing warnings: a claim keeping its anchor's words, and experiment wording for a simulation."""

import pytest

from deixis.domain import contracts
from test_report_rf4 import packet

LONG = "SYNTHETIC routing lowers the end to end delay of every packet sent across the dense simulated network"


def section(passage_text, claim_text, language="en"):
    si, draft = packet()
    si["question"]["language_hint"] = language
    si["passages"][0]["text"] = passage_text
    draft["citation_anchors"][0]["quote"] = passage_text
    draft["claims"][0]["text"] = claim_text
    result = contracts.validate_model_output(si, draft)
    return [i.code for i in result.issues], [w.code for w in result.warnings]


def test_a_claim_keeping_a_long_run_of_its_anchor_is_a_warning_not_an_issue():
    issues, warnings = section(LONG + ".", LONG + ".")
    assert "claim_copies_anchor" in warnings and "claim_copies_anchor" not in issues


def test_a_claim_in_its_own_words_gets_no_copy_warning():
    _, warnings = section(LONG + ".", "SYNTHETIC routing shortens packet delay when the simulated network is dense.")
    assert "claim_copies_anchor" not in warnings


@pytest.mark.parametrize("claim", ["A SYNTHETIC field trial showed a lower delay.",
                                   "SYNTHETIC experimental results show a lower delay."])
def test_experiment_wording_for_a_simulation_only_source_is_a_warning(claim):
    issues, warnings = section("SYNTHETIC NS-3 simulations of 200 nodes show a lower delay.", claim)
    assert "experiment_wording_for_simulation" in warnings and "experiment_wording_for_simulation" not in issues


@pytest.mark.parametrize("passage,claim", [
    ("SYNTHETIC NS-3 simulations of 200 nodes show a lower delay.", "SYNTHETIC simulation experiments show a lower delay."),
    ("SYNTHETIC simulations and a sea trial show a lower delay.", "A SYNTHETIC sea trial showed a lower delay."),
    ("SYNTHETIC analysis shows a lower delay.", "A SYNTHETIC field trial showed a lower delay."),
])
def test_no_experiment_warning_when_the_source_names_one_or_the_claim_names_a_simulation(passage, claim):
    _, warnings = section(passage, claim)
    assert "experiment_wording_for_simulation" not in warnings


def test_turkish_experiment_wording_for_a_simulation_is_a_warning():
    _, warnings = section("SYNTHETIC benzetim sonuçları daha düşük gecikme gösteriyor.",
                          "SYNTHETIC deneysel sonuçlar daha düşük gecikme gösteriyor.", language="tr")
    assert "experiment_wording_for_simulation" in warnings
