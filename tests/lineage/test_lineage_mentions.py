"""Synthetic mention cases; these do not measure recall on real passages."""

import ast
import copy
import json
from pathlib import Path
import random
import sys

from deixis.workflow.lineage import mentions
from deixis.workflow.lineage.mentions import (
    MentionTarget, PassageText, find_mentions, mention_rules, normalize_tokens,
    prepare_passages, surname_tokens,
)
from deixis.workflow.source_keys import _TITLE_STOPWORDS


def target(**changes):
    return MentionTarget(**dict({"source_version_id": "earlier", "title": "Short title",
                                 "authors": ("Ada Smith",), "year": 2015, "years": ()}, **changes))


def find(text, record=None):
    return find_mentions(prepare_passages((PassageText("p", "pdf_page", text, 1),)), record or target())


def test_surname_year_mention_found_in_common_citation_forms():
    for text in ("Smith (2015)", "(Smith et al., 2015)", "Smith and Jones, 2015", "Smith 2015a"):
        result = find(text)
        assert result.total == 1
        assert result.basis == ("surname_year",)
    for gap in (60, 61):
        text = "Smith " + "x" * (gap - 2) + " 2015"
        prepared = prepare_passages((PassageText("p", "section", text, None),))[0]
        assert prepared.normalized_text == text.casefold()
        assert prepared.normalized_text.index("2015") - len("smith") == gap
        assert (find(text) is not None) == (gap == 60)
    # Multiple eligible years after one occurrence still count that occurrence once.
    assert find("Smith 2015 2015a").total == 1


def test_year_must_follow_surname_and_match_a_known_year():
    assert find("2015 Smith") is None
    assert find("Smith 2016") is None
    assert find("Smith 2016", target(years=(2016,))).total == 1
    assert find("Smith 2015", target(year=2015, years=())).total == 1
    assert find("Waals 1873", target(authors=("Johannes van der Waals",), year=1873)).total == 1
    assert find("Smith 0999", target(year=999)).total == 1
    for bad in ("Smith 20150", "Smith 2015ab", "Smith x2015", "Smith 2015α"):
        assert find(bad) is None
    assert find("Smith 2015", target(year=None)) is None


def test_surname_normalization_particles_suffixes_hyphen_and_accents():
    cases = (("de la Cruz", ("cruz",), "Cruz 2015"),
             ("van der Berg", ("berg",), "Berg 2015"),
             ("Smith Jr.", ("smith",), "Smith 2015"),
             ("Smith-Jones", ("smith", "jones"), "Smith–Jones 2015"),
             ("Müller", ("muller",), "Muller 2015"),
             ("Nakano, H.", ("nakano",), "Nakano 2015"),
             ("de la Cruz, Ana", ("cruz",), "Cruz 2015"))
    for author, expected, text in cases:
        assert surname_tokens(author) == expected
        assert find(text, target(authors=(author,))).total == 1
    assert surname_tokens("van, Given") == ("van",)
    assert find("Smith unrelated Jones 2015", target(authors=("Smith-Jones",))) is None
    assert find("Smith 2015", target(authors=("Smith-Jones",))) is None
    assert find("Wojciechowski (2019)", target(authors=("Wojciechowski",), year=2019)).total == 1
    assert find("Wojciechow 2019", target(authors=("Wojciechowski",), year=2019)) is None
    assert normalize_tokens("Müller._Smith–Jones [2015a]") == ("muller", "smith", "jones", "2015a")


def test_token_boundaries_no_inside_token_matches():
    for text in ("Lin 2015", "Liu 2015"):
        assert find(text, target(authors=("Li",))) is None
    assert find("Smithson 2015") is None
    assert find("Li 2015", target(authors=("Li",))).total == 1


def test_title_fragment_five_consecutive_significant_tokens():
    record = target(title="Alpha beta gamma delta epsilon zeta", authors=())
    assert find("alpha beta gamma delta epsilon", record).hits[0].title_fragment == 1
    assert find("alpha beta gamma delta", record) is None
    assert find("alpha beta gamma delta epsilon zeta", record).total == 1
    stopped = target(title="Alpha of beta the gamma delta epsilon", authors=())
    assert find("the alpha beta of gamma delta the epsilon", stopped).total == 1
    assert find("alpha beta gamma delta epsilon", stopped).total == 1
    assert find("alpha beta gamma delta", target(title="Alpha of beta the gamma delta", authors=())) is None
    assert find("alpha beta gamma delta epsilon unrelated alpha beta gamma delta epsilon", record).total == 2
    assert find("alpha beta gamma intruder delta epsilon", record) is None
    # Two crossing runs at different title offsets must not become one invented run.
    crossing = target(title="Alpha beta gamma delta epsilon theta beta gamma delta epsilon zeta", authors=())
    assert find("alpha beta gamma delta epsilon zeta", crossing).total == 2
    repeated = target(title="Alpha beta gamma delta epsilon alpha beta gamma delta epsilon", authors=())
    assert find("alpha beta gamma delta epsilon", repeated).total == 1


def test_work_without_authors_is_searched_by_title_only_and_without_surname_by_no_surname_search():
    for authors in ((), ("", "...", "Jr.")):
        record = target(authors=authors, title="Alpha beta gamma delta epsilon")
        assert find("Smith 2015", record) is None
        assert find("alpha beta gamma delta epsilon", record).basis == ("title_fragment",)
    assert find("Smith 2015", target(authors=("...", "Ada Smith"))).total == 1
    both = find("Smith 2015 alpha beta gamma delta epsilon",
                target(title="Alpha beta gamma delta epsilon"))
    assert both.basis == ("surname_year", "title_fragment")
    assert both.hits[0].count == 2


def test_numbered_citations_are_missed():
    # The reference list is outside the supplied passage snapshot.
    assert find("as shown in [12]") is None
    # Reference-list passages are not filtered when the caller does supply them.
    assert find_mentions(prepare_passages((PassageText("ref", "section", "[12] Smith 2015", 9),)), target()).total == 1


def test_mention_passages_are_at_most_three_never_empty_and_stably_ordered():
    passages = [PassageText(pid, "abstract" if page is None else "pdf_page", "Smith 2015", page)
                for pid, page in (("e", 5), ("b", 1), ("a", 1), ("z", None), ("c", 2))]
    original = find_mentions(prepare_passages(passages), target())
    assert original.mention_passage_ids == ("z", "a", "b")
    assert original.total == sum(hit.count for hit in original.hits) == 5
    assert len(original.hits) == 5
    for seed in range(5):
        shuffled = list(passages)
        random.Random(seed).shuffle(shuffled)
        assert find_mentions(prepare_passages(shuffled), target()) == original
    passages.append(PassageText("more", "pdf_page", "Smith 2015 Smith 2015", 99))
    assert find_mentions(prepare_passages(passages), target()).mention_passage_ids == ("more", "z", "a")


def test_mention_rules_record_is_pinned():
    rules = mention_rules()
    assert rules == {"normalization_version": "lineage-mentions-v1",
                     "text_definition": "source_keys._ascii, casefold, split on runs of non-alphanumeric characters; "
                     "tokens joined by one space; gap counts characters strictly between surname end and year start",
                     "gap_chars": 60, "min_title_tokens": 5, "max_mention_passages": 3,
                     "year_position": "after_surname", "stopwords": sorted(_TITLE_STOPWORDS)}
    assert json.loads(json.dumps(rules)) == rules
    rules["stopwords"].clear()
    assert mention_rules()["stopwords"] == sorted(_TITLE_STOPWORDS)


def _import_paths(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (name.name for name in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "use explicit absolute imports for the auditable allow-list"
            yield node.module
            yield from (f"{node.module}.{name.name}" for name in node.names)


def test_package_imports_no_database_provider_or_model():
    forbidden = ("sqlite3", "httpx", "deixis.providers", "deixis.models", "deixis.workflow.store",
                 "deixis.workflow.flow", "deixis.storage", "deixis.api")
    # Storage, planning and views read the database; assembly remains pure.
    modules = tuple(p for p in Path(mentions.__file__).parent.glob("*.py") if p.stem not in ("store", "run", "view"))
    assert {path.stem for path in modules} == {"__init__", "mentions", "edges", "candidates", "baseline", "assembly"}
    for path in modules:
        tree = ast.parse(path.read_text())
        for name in _import_paths(tree):
            assert not any(name == bad or name.startswith(bad + ".") for bad in forbidden), (path, name)
            assert (name.split(".")[0] in sys.stdlib_module_names
                    or name.startswith("deixis.workflow.source_keys")
                    or name.startswith("deixis.workflow.lineage.")), (path, name)
        # No dynamic import escape through otherwise allowed stdlib modules.
        assert not any(isinstance(n, ast.Call) and
                       ((isinstance(n.func, ast.Name) and n.func.id == "__import__") or
                        (isinstance(n.func, ast.Attribute) and n.func.attr == "import_module"))
                       for n in ast.walk(tree))
    for syntax in ("import deixis.providers.openalex", "from deixis import models",
                   "from deixis.workflow import store", "from sqlite3 import connect"):
        paths = tuple(_import_paths(ast.parse(syntax)))
        assert any(name == bad or name.startswith(bad + ".") for name in paths for bad in forbidden)


def test_functions_do_not_mutate_inputs_and_are_deterministic():
    from deixis.workflow.lineage.baseline import BaselineVersion, field_baseline
    from deixis.workflow.lineage.candidates import LineageWork, find_candidates, pack_candidates, passage_budget_fits
    from deixis.workflow.lineage.edges import EdgeFrom, EdgeTo, derive_edges, edge_counts, unassessed_edges

    passages = [PassageText("p", "pdf_page", "Smith 2015", 1)]
    record = target()
    works = [LineageWork("a", "wa", 0, "Short", ("Smith",), 2015, (), True, frozenset(), frozenset({"W1"}), ()),
             LineageWork("b", "wb", 1, "Short", ("Jones",), 2020, (), True, frozenset({"W1"}), frozenset(), tuple(passages))]
    versions = [BaselineVersion(w.source_version_id, w.work_id, True, False, "2026", 0, None, "review",
                                w.references_read, w.referenced_ids, w.openalex_ids) for w in works]
    lengths = {"p": 10}
    before = copy.deepcopy((passages, record, works, versions, lengths))

    def run():
        prepared = prepare_passages(passages)
        found = find_candidates(works)
        edges = derive_edges([EdgeTo(w.source_version_id, w.work_id, w.references_read, w.referenced_ids) for w in works],
                             [EdgeFrom(w.source_version_id, w.work_id, w.openalex_ids) for w in works])
        return (find_mentions(prepared, record), found, pack_candidates(found.candidates, passage_budget_fits(lengths)),
                edges, edge_counts(edges), unassessed_edges(edges, frozenset(), frozenset(found.scanned_targets)),
                field_baseline(versions), mention_rules())

    assert run() == run()
    assert (passages, record, works, versions, lengths) == before
