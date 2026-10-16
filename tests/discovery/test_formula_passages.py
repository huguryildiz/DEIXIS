from deixis.workflow import formula_passages as fp


def passage(pid, text):
    return {"id": pid, "text": text}


DBR_P8 = ("Instead, we use a global parameter δ to replace (d1 −d2) for the holding time calculation. Therefore "
          "α = −2τ / δ. Let the node with the minimal depth have holding time 0. We can compute β by solving the "
          "following equation: −2τ / δ R + β = 0. f(d) = 2τ / δ · (R −d), δ ∈(0, R]. (4)")
RESULTS = "Packet Delivery Ratio is defined as the ratio of the number of distinct packets received at the sinks."
FIGURE = "(a) Packet delivery ratio (b) Energy consumption (c) Average end-to-end delay. Fig. 7. DBR's performance"


def test_formula_questions_and_criterion_phrases_are_recognised():
    assert fp.asks_for_formulas(["What formulas do they use for forwarding decisions?"])
    assert fp.asks_for_formulas(["How is the holding time calculated in DBR?"])
    assert fp.asks_for_formulas(["Does X help?", "energy equation"])
    assert not fp.asks_for_formulas(["How do DBR and VBF compare in delivery ratio?", "energy consumption", ""])
    for question in ("Does infant formula feeding raise obesity risk?", "What biomarkers derived from MRI predict dementia?",
                     "How is gene expression for BRCA1 regulated?", "Which features are derived from EEG?",
                     "Is formula milk safe for preterm infants?", "Are formula-fed infants at higher obesity risk?",
                     "Does baby formula affect gut flora?", "Does formula supplementation shorten breastfeeding?"):
        assert not fp.asks_for_formulas([question]), question


def test_most_formula_dense_passage_takes_the_second_position():
    ranked = [passage("p10", RESULTS), passage("p12", FIGURE), passage("p6", "prose about queues"),
              passage("p8", DBR_P8)]
    assert [p["id"] for p in fp.bring_forward(ranked)] == ["p10", "p8", "p12", "p6"]


def test_nothing_moves_without_a_formula_or_when_the_first_passage_is_the_formula():
    prose = [passage("a", RESULTS), passage("b", FIGURE), passage("c", "α is a parameter")]
    assert fp.bring_forward(prose) == prose
    first = [passage("p8", DBR_P8), passage("p10", RESULTS), passage("p9", DBR_P8)]
    assert fp.bring_forward(first) == first
    assert fp.bring_forward(first[:1]) == first[:1]


def test_equal_scores_keep_the_higher_ranked_passage():
    ranked = [passage("top", RESULTS), passage("x", FIGURE), passage("first_eq", DBR_P8), passage("second_eq", DBR_P8)]
    assert [p["id"] for p in fp.bring_forward(ranked)] == ["top", "first_eq", "x", "second_eq"]


def test_latex_and_broken_text_layer_equations_both_score():
    latex = (r"$$\beta = \frac{E_{current} - E_{min}}{E_{initial}} \tag{3}$$ The holding time is calculated as"
             r" $$T = \sqrt{\alpha} \cdot T_{delay} \tag{4}$$")
    broken = "the desirableness factor, α, of a node A, is defined as α = / p / W + (R−d×cosθ) / R"
    assert fp.score(latex) >= fp.MIN_SCORE and fp.score(broken) >= fp.MIN_SCORE
    assert fp.score(RESULTS) < fp.MIN_SCORE and fp.score(FIGURE) < fp.MIN_SCORE


def test_reported_values_and_units_are_not_formulas():
    statistics = "SD = 7.1; n = 120; OR = 1.4 (95% CI 1.1-1.8), p = 0.02, p = .03; HR = 0.8; PDR = 0.92; 5 µJ, 2 µs"
    assert fp.score(statistics) == 0
    assert fp.score("Ω = Φ + Γ") == 4
