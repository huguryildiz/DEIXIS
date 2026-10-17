import pytest

from deixis.workflow import formula_passages as fp
from deixis.workflow import result_passages as rp

OUTCOMES = rp.compile_terms(["packet delivery ratio", "energy consumption"])


def passage(pid, text):
    return {"id": pid, "text": text}


# DVOR page 7 (psg_jUAnJnPb5AFpzeZJUA3f on the K copy, 17 Oct 2026): the simulation setup. It names energy consumption
# and carries a dozen numbers with units, none of them a reported outcome.
DVOR_P7 = ("D. Extension to Multisink Case\n\nIt is worthwhile to mention that the DVOR protocol can\nbe extended readily "
           "to the multiple sonobuoys (sinks) case. In\nthis case, multiple sonobuoys are required to send the querypackets. "
           "The underwater sensors need to record the hop-count\nof the shortest path to any of the sonobuoy. When a packet\n"
           "arrives at an intermediate node, it is still processed in the same\nway as in the single sonobuoy case.\n\n"
           "IV. SIMULATIONS AND DISCUSSIONS\n\nIn this section, using NS2 simulator, we evaluates the\nperformance of the "
           "proposed DVOR protocol by comparing\nit with those of DBR and DUOR, which were proposed in\n\n[26] and [30], "
           "respectively.\nSensor nodes are randomly deployed in a 3-D area of\n500 m × 500 m × 500 m.\nThe maximum range "
           "of one-hop transmission is set as\n100 m. The propagation loss model for UWA channels is\nThorp [31]. We set the "
           "link data rate to 10 kb/s and the datapacket size to 128 Bytes. In each sensor node, data packets\nare generated "
           "randomly and follow a Poisson distribution. The\naverage package-generating rate is set as 1 packet per second. "
           "The initial energy of the sink node is 10 000 J and the\ninitial energy of the sensor nodes are 400 J. The values "
           "of\nenergy consumption are set as Pt = 2 W, Pr = 0.75 W, and\nPi = 0.08 W for packet transmissions, packets "
           "reception, and\nidle states, respectively. On the water surface, there are three\nsink nodes.")
RESULT = ("The proposed protocol gains 7% higher packet delivery ratio and 25% lower energy consumption than VBF. "
          "Energy consumption is reduced by up to 30%.")
FORMULA = ("The holding time is defined as f(d) = 2τ / δ · (R − d), δ ∈ (0, R], where τ = R / v0 is the propagation "
           "delay, and α = −2τ / δ (4).")
TOPIC = "Depth-based and vector-based routing for underwater acoustic sensor networks: an introduction."
REFERENCES = ("[12] H. Yan, Z. Shi, and J. Cui, DBR, vol. 4982, pp. 72-86. [13] P. Xie et al., VBF, pp. 1216-1221. "
              "[14] N. Chirdchoo et al., Sector-based routing, vol. 5, pp. 1-6.")


def test_reported_outcome_values_count():
    assert rp.score("Table 3 shows energy consumption decreased from 12 J to 8 J.", OUTCOMES) == 2
    assert rp.score(RESULT, OUTCOMES) == 3
    assert rp.score("The packet delivery ratio is 4 percent higher than in DBR.", OUTCOMES) == 1
    # A range or a ± value is one reported value.
    assert rp.score("Energy consumption is 15 J–60 J lower than HH-VBF and 0.8 ± 0.1 mJ lower than VBF.", OUTCOMES) == 2
    assert rp.score("Energy consumption was 3 to 5 J lower than DBR.", OUTCOMES) == 1


def test_a_sentence_broken_across_pdf_lines_still_counts():
    assert rp.score("The energy\nconsumption of EEDBR is 20%\nlower than DBR and 12 %\nlower than VBF.", OUTCOMES) == 2


def test_the_dvor_setup_page_scores_zero():
    assert rp.score(DVOR_P7, OUTCOMES) == 0


def test_setting_values_and_values_without_an_outcome_term_or_comparison_do_not_count():
    assert rp.score("The initial energy is 10 J, so energy consumption is lower than 10 J.", OUTCOMES) == 0
    assert rp.score("Simulation parameters: energy consumption per bit is set to 2 W, lower than in [5].", OUTCOMES) == 0
    assert rp.score("Nodes are deployed in an area of 500 m, where energy consumption is higher than 5 J.", OUTCOMES) == 0
    assert rp.score("Throughput is 20% higher and delay 30 ms lower than VBF.", OUTCOMES) == 0  # no outcome term
    assert rp.score("Energy consumption was 12 J and 8 J.", OUTCOMES) == 0  # no change or comparison word
    assert rp.score(RESULT, []) == 0


def test_assignments_and_bare_numbers_are_not_values():
    # A formula's `=` and a ratio without a unit are not reported values; the formula score is a separate count.
    text = "Energy consumption is lower than VBF: E = P · t, and the packet delivery ratio rises to 0.92 from 0.81."
    assert rp.score(text, OUTCOMES) == 0 and fp.score(text) > 0


def test_text_in_another_language_does_not_match_english_terms():
    text = "Le taux de livraison des paquets est 20 % plus élevé et la consommation d'énergie 15 % plus faible."
    assert rp.score(text, OUTCOMES) == 0


def test_reference_list_is_recognised_only_without_an_outcome_term():
    assert rp.reference_list(REFERENCES, OUTCOMES)
    assert not rp.reference_list(REFERENCES + " Energy consumption of DBR [15], [16], [17].", OUTCOMES)
    assert not rp.reference_list(TOPIC, OUTCOMES)


def test_result_passage_takes_the_first_slot_and_formula_keeps_the_second():
    ranked = [passage("topic", TOPIC), passage("refs", REFERENCES), passage("formula", FORMULA), passage("result", RESULT)]
    ordered, moved = rp.order(ranked, OUTCOMES, True)
    assert moved and [p["id"] for p in ordered] == ["result", "formula", "topic", "refs"]
    ordered, moved = rp.order(ranked, OUTCOMES, False)
    assert moved and [p["id"] for p in ordered] == ["result", "topic", "formula", "refs"]


def test_without_outcome_terms_the_order_is_exactly_the_formula_order():
    ranked = [passage("topic", TOPIC), passage("refs", REFERENCES), passage("formula", FORMULA), passage("result", RESULT)]
    for formulas in (True, False):
        ordered, moved = rp.order(ranked, [], formulas)
        assert not moved and ordered == (fp.bring_forward(ranked) if formulas else ranked)


def test_below_the_floor_nothing_but_the_reference_list_moves():
    weak = passage("weak", "Energy consumption is 5% lower than VBF.")
    ranked = [passage("topic", TOPIC), passage("refs", REFERENCES), weak, passage("formula", FORMULA)]
    ordered, moved = rp.order(ranked, OUTCOMES, True)
    assert not moved and [p["id"] for p in ordered] == ["topic", "formula", "weak", "refs"]
    plain = [passage("topic", TOPIC), weak, passage("formula", FORMULA)]
    assert rp.order(plain, OUTCOMES, True) == (fp.bring_forward(plain), False)


def test_ties_keep_the_higher_ranked_passage_and_one_passage_is_unchanged():
    ranked = [passage("topic", TOPIC), passage("first", RESULT), passage("second", RESULT)]
    assert [p["id"] for p in rp.order(ranked, OUTCOMES, False)[0]] == ["first", "topic", "second"]
    best_first = [passage("result", RESULT), passage("topic", TOPIC)]
    assert rp.order(best_first, OUTCOMES, False) == (best_first, False)
    assert rp.order(ranked[:1], OUTCOMES, True) == (ranked[:1], False)



# Every counterexample found in review (Sol code review rounds 1-3) and the cases they must not break.
MERGED = "Energy consumption can be reduced by optimizing routing. 500 m × 500 m × 500 m is the simulated volume."
APPROX = "Energy consumption is approx. 20% lower than DBR and 15% lower than VBF."
BLANK = "Energy consumption can be reduced using protocol X.\n\n500 m × 500 m × 500 m is the simulated volume."
DBR_P13 = ("For example, in a network with 200 nodes, DBR with five sinks has a packet delivery ratio of around 70%, which "
           "is more than four times larger than 15%, the delivery ratio of VBF.")
REFS_EQUATIONS = (REFERENCES + " [15] A. B. et al., Equations of state; equations of motion; formulas, vol. 2, pp. 1-9."
                  " [16] C. Lee et al., Wave equations, pp. 3-4.")
WEAK_FORMULA = "The holding time is defined as f(d) = 2τ / δ · (R − d), δ ∈ (0, R] (4)."
SCORES = [
    ("dvor_setup_page", DVOR_P7, 0),
    ("number_start_sentence", MERGED, 0),
    ("approx_before_number", APPROX, 2),
    ("blank_line_after_single_letter", BLANK, 0),
    ("blank_line_with_spaces", BLANK.replace("\n\n", "\n  \t\n"), 0),
    ("table_3_change", "Table 3 shows energy consumption decreased from 12 J to 8 J", 2),
    ("dbr_200_nodes", DBR_P13, 2),
    ("fig_decimal_line_wrap", "As Fig. 7 shows, energy consumption is 12.5 J lower than VBF\nand 3.5 J lower than DBR.", 2),
    ("capital_after_abbreviation_splits", "Energy consumption is lower than DBR, cf. Table 3. Delay is 20 ms and 15 ms.", 0),
    *((f"abbreviation_{before}", f"Energy consumption is lower than DBR, {before} 20% and 15% lower than VBF.", 2)
      for before in ("approx.", "ca.", "e.g.", "i.e.", "cf.", "vs.", "resp.", "al.", "Figs.", "Eq.", "No.", "vol.", "pp.",
                     "Sec.", "Tab.", "Ref.", "max.", "min.", "avg.", "x.", "U.S.")),
]
ORDERS = [
    ("result_before_formula", [("topic", TOPIC), ("formula", FORMULA), ("result", APPROX)], ["result", "formula"]),
    ("number_start_does_not_outrank_a_result", [("topic", TOPIC), ("merged", MERGED), ("genuine", APPROX)],
     ["genuine", "topic"]),
    ("blank_line_does_not_outrank_a_result", [("topic", TOPIC), ("formula", FORMULA), ("setup", BLANK), ("result", APPROX)],
     ["result", "formula"]),
    ("references_never_promoted", [("topic", TOPIC), ("refs", REFS_EQUATIONS), ("formula", WEAK_FORMULA), ("result", RESULT)],
     ["result", "formula"]),
]


@pytest.mark.parametrize("kind, case, given, expected", [("score", *row) for row in SCORES] + [("order", *row) for row in ORDERS],
                         ids=lambda value: value if isinstance(value, str) and len(value) < 60 and " " not in value else None)
def test_review_counterexamples(kind, case, given, expected):
    if kind == "score":
        assert rp.score(given, OUTCOMES) == expected
    else:
        ordered, _ = rp.order([passage(pid, text) for pid, text in given], OUTCOMES, True)
        assert [p["id"] for p in ordered][:2] == expected
        refs = [pid for pid, text in given if rp.reference_list(text, OUTCOMES)]
        assert [p["id"] for p in ordered][len(given) - len(refs):] == refs  # reference lists stay last


def test_the_reference_fixture_outscores_the_real_formula():
    assert rp.reference_list(REFS_EQUATIONS, OUTCOMES) and fp.score(REFS_EQUATIONS) > fp.score(WEAK_FORMULA) >= fp.MIN_SCORE
