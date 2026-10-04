"""A research is named from its question's first 15 words until a model title replaces it (D39)."""

import pytest

from deixis.storage import db
from deixis.workflow.store import Store, provisional_title

QUESTION = " ".join(f"w{n}" for n in range(1, 17))  # SYNTHETIC 16-word question


@pytest.mark.parametrize("count, cut", [(14, False), (15, False), (16, True)])
def test_the_title_keeps_15_words_and_marks_a_cut(count, cut):
    words = [f"w{n}" for n in range(1, count + 1)]
    assert provisional_title(" ".join(words)) == " ".join(words[:15]) + ("…" if cut else "")


def test_a_question_over_several_lines_is_one_line_of_its_words():
    assert provisional_title("  How does\nX affect\n\n Y?  ") == "How does X affect Y?"


def test_the_scope_keeps_the_full_question_and_a_model_title_replaces_the_provisional_one(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research(QUESTION, "attached", "quick", [], "fake", "fake-model", None)
    assert store.research(rid)["title"] == " ".join(QUESTION.split()[:15]) + "…"
    assert store.scope(rid)["question"] == QUESTION
    store.set_research_title(rid, 1, "SYNTHETIC model title")
    assert store.research(rid)["title"] == "SYNTHETIC model title"
