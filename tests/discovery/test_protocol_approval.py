"""What the protocol approval records about the proposed vocabulary and criterion (slice 08a, SW2.6, SW14.2).

Pure: no store, no network, no flow. Nobody corrects the proposal since the clean start (decision B); what is checked
is what the approval step still computes from it: who placed each phrase in its block, the proposal's digest, and the
exclusion words the question itself uses. Every phrase, question and criterion here is SYNTHETIC and from more than
one field.
"""

import asyncio
import copy

from deixis.providers.query_compiler import compile_block_queries
from deixis.workflow import approval
from deixis.workflow.vocabulary import MAX_PROBES, build_vocabulary
from deixis.domain.vocabulary import Extraction

# SYNTHETIC: a soil science question and a clinical one, so no product rule can be tuned to one field.
SOIL = "How does biochar addition change nitrous oxide emissions in arable soils?"
COUNTS = {
    '"arable soils"': 900, '"biochar addition"': 400, '"nitrous oxide emissions"': 700,
    "arable": 4_000, "soils": 60_000, "biochar": 1_200, "addition": 90_000,
    "nitrous": 2_000, "oxide": 80_000, "emissions": 150_000,
    "(arable) AND (biochar OR nitrous)": 300,
    '"cover crops"': 800, "cover": 70_000, "crops": 50_000,
    "(arable) AND (biochar OR nitrous OR cover)": 420,
    "(arable) AND (nitrous)": 260, "(arable) AND (biochar)": 180,
    "(arable OR biochar) AND (nitrous)": 520,
    '"no such phrase anywhere"': 0,
}


class Probe:
    """A count probe that answers from a fixed table and records every query it was really asked."""

    def __init__(self, counts=None):
        self.asked, self.counts = [], counts if counts is not None else COUNTS

    async def __call__(self, query):
        self.asked.append(query)
        return self.counts.get(query)


def extraction(origins=None):
    return Extraction(language="en",
                      blocks={"setting": ["arable soils"], "task": ["biochar addition", "nitrous oxide emissions"],
                              "outcome": []},
                      claim_words=[], exclusion_words=[], block_assignment="rule", origins=origins or {})


def proposal(probe=None, criterion=None):
    """The vocabulary a first round would have built for the soil question, with a criterion beside it."""
    built = asyncio.run(build_vocabulary(extraction(), probe or Probe()))
    built["labelling"] = {"runs_ok": 3, "skipped": None, "failures": [], "phrases": [
        {"phrase": "arable soils", "rule_block": "setting", "runs": ["setting"] * 3, "block": "setting",
         "origin": "model"},
        {"phrase": "biochar addition", "rule_block": "task", "runs": ["task"] * 3, "block": "task",
         "origin": "model"},
        {"phrase": "nitrous oxide emissions", "rule_block": "task", "runs": ["task"] * 2, "block": "task",
         "origin": "rule"},
    ]}
    return {"vocabulary": built, "queries": compile_block_queries(built, ["openalex"], 4),
            "criterion": criterion, "criterion_failures": []}


CRITERION = {
    "criterion": "SYNTHETIC: the paper reports a field trial of a soil amendment and its measured gas flux.",
    "parts": [{"name": "field trial", "definition": "SYNTHETIC: the study was run on a real plot."},
              {"name": "gas flux", "definition": "SYNTHETIC: a flux was measured, not modelled."}],
    "cue_phrases": [{"phrase": "static chamber", "part": "gas flux", "runs": [1, 2]},
                    {"phrase": "randomised plots", "part": "field trial", "runs": [2, 3]}],
    "exclusion_title_words": ["editorial", "review"],
    "dropped_exclusion_title_words": ["soils"],
    "base_run": 2, "runs_ok": [1, 2, 3], "sought_term_in_criterion": True, "origin": "model",
    "question_elements": [{"role": "population", "words": "SYNTHETIC plots", "part": "field trial"}],
    "required_roles": ["population"],
}


def test_an_exclusion_word_the_question_itself_uses_is_marked_and_not_removed():
    """SW5.1 drops such a word from a proposal; the approval only marks one the question itself uses."""
    marked = CRITERION | {"exclusion_title_words": ["biochar", "editorial"]}
    assert approval.exclusion_words_in_question(SOIL, marked) == ["biochar"]
    assert approval.exclusion_words_in_question(SOIL, CRITERION) == []
    assert approval.exclusion_words_in_question(SOIL, None) == []


def test_a_cached_count_spends_none_of_the_probe_budget():
    """A count the vocabulary builder is given is not asked again and spends none of the probe allowance."""
    made = proposal()
    known = {p["query"]: p["count"] for p in made["vocabulary"]["probes"]}
    known |= {f"synthetic filler {i}": 1 for i in range(MAX_PROBES * 2)}
    filler = Extraction(language="en", blocks={"setting": ["arable soils"], "task": ["cover crops"], "outcome": []},
                        claim_words=[], exclusion_words=[], block_assignment="rule", origins={})
    probe = Probe()
    built = asyncio.run(build_vocabulary(filler, probe, known=known))
    assert built["probes_skipped"] == 0 and len(probe.asked) < MAX_PROBES


def test_the_block_origin_of_a_phrase_is_what_placed_it():
    made = proposal()
    origins = approval.block_origins(made["vocabulary"])
    # The labelling step's word stands where it gave one; the rule's elsewhere.
    assert origins["arable soils"] == "model" and origins["nitrous oxide emissions"] == "rule"
    keyed = made["vocabulary"] | {"block_assignment": "user", "labelling": None}
    assert set(approval.block_origins(keyed).values()) == {"user"}


def test_the_proposal_hash_names_the_phrases_and_the_criterion_and_not_the_counts():
    made = proposal()
    other = proposal(Probe({**COUNTS, '"arable soils"': 12}))
    assert approval.proposal_hash(made["vocabulary"], CRITERION) == approval.proposal_hash(other["vocabulary"], CRITERION)
    moved = copy.deepcopy(made["vocabulary"])
    next(t for t in moved["terms"] if t["phrase"] == "biochar addition")["block"] = "claim"
    assert approval.proposal_hash(moved, CRITERION) != approval.proposal_hash(made["vocabulary"], CRITERION)
    assert approval.proposal_hash(made["vocabulary"], None) != approval.proposal_hash(made["vocabulary"], CRITERION)
