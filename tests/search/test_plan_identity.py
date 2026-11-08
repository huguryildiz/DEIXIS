"""What a search plan was written from (its fingerprint) and what changed between two plans.

No database, no model and no network: every case is a function of a stored StepInput payload and two plan answers.
SYNTHETIC records. Passing shows the fingerprint tells the inputs apart and the comparison names the right terms; it
says nothing about whether a model writes steady plans, which only the measurement can.
"""

from deixis.workflow.search import plan_identity

RULE = "search_plan_v1"


def payload(records=(("srv_1", "SYNTHETIC routing paper", ("energy",), "SYNTHETIC abstract one"),),
            question="SYNTHETIC: how does depth-based routing spend energy?", model="gpt-6-luna"):
    return {"task_type": "search_plan", "skill_package_hash": "sha-package",
            "question": {"text": question, "language": "en"},
            "model": {"connection": "codex", "requested_model": model},
            "sources": [{"source_id": sid, "title": title, "index_keywords": list(keywords), "year": 2026}
                        for sid, title, keywords, _ in records],
            "passages": [{"passage_id": f"psg_{sid}", "source_id": sid, "text": text}
                         for sid, _, _, text in records]}


def record(model="gpt-6-luna-2026-11-01", package="sha-package"):
    return {"resolved_model": model, "skill_package_hash": package,
            "answer": {"schema_version": "deixis.search_plan.v2"}}


def plan(setting=("underwater sensor network",), task=("routing protocol",), setting_backup=(), task_backup=()):
    def terms(values):
        return [{"term": value, "kind": "topic", "why": "SYNTHETIC", "evidence": []} for value in values]
    return {"schema_version": "deixis.search_plan.v2", "setting": terms(setting), "task": terms(task),
            "setting_backup": terms(setting_backup), "task_backup": terms(task_backup)}


def test_the_same_inputs_give_the_same_fingerprint():
    first = plan_identity.fingerprint(payload(), record(), RULE)
    second = plan_identity.fingerprint(payload(), record(), RULE)
    assert first == second and first["rule"] == plan_identity.RULE and first["records"] == 1


def test_another_record_another_order_or_another_abstract_is_another_fingerprint():
    two = (("srv_1", "SYNTHETIC routing paper", ("energy",), "SYNTHETIC abstract one"),
           ("srv_2", "SYNTHETIC relay paper", (), "SYNTHETIC abstract two"))
    base = plan_identity.fingerprint(payload(), record(), RULE)
    more = plan_identity.fingerprint(payload(two), record(), RULE)
    swapped = plan_identity.fingerprint(payload(two[::-1]), record(), RULE)
    retitled = plan_identity.fingerprint(payload((("srv_1", "SYNTHETIC other title", ("energy",), "SYNTHETIC abstract one"),)),
                                         record(), RULE)
    # The order the call read the records in is part of what it read, so swapping two records is another reading.
    assert len({base["inputs_sha256"], more["inputs_sha256"], swapped["inputs_sha256"], retitled["inputs_sha256"]}) == 4
    assert more["records"] == 2


def test_the_same_reading_answered_by_another_writer_keeps_its_inputs_hash():
    """A newer model, package or rule is a new fingerprint over the same reading: the halves say which changed."""
    base = plan_identity.fingerprint(payload(), record(), RULE)
    newer = plan_identity.fingerprint(payload(), record(model="gpt-6-luna-2026-12-01"), RULE)
    packaged = plan_identity.fingerprint(payload(), record(package="sha-other"), RULE)
    ruled = plan_identity.fingerprint(payload(), record(), "search_plan_v2")
    assert all(other["inputs_sha256"] == base["inputs_sha256"] for other in (newer, packaged, ruled))
    assert len({base["sha256"], newer["sha256"], packaged["sha256"], ruled["sha256"]}) == 4
    assert base["versions"]["resolved_model"] == "gpt-6-luna-2026-11-01"


def test_every_field_the_call_was_sent_is_part_of_what_it_read():
    """The hash is taken over the payload as it was sent, so a field this module does not name on its own — a
    record's year, the question's language, a steering note — still changes the fingerprint."""
    base = plan_identity.fingerprint(payload(), record(), RULE)
    for change in ({"question": {"text": payload()["question"]["text"], "language": "tr"}},
                   {"user_steering": "SYNTHETIC: compare the two protocols"},
                   {"sources": [dict(payload()["sources"][0], year=2025)]},
                   {"allowlist": {"source_ids": ["srv_1"]}}):
        other = plan_identity.fingerprint(payload() | change, record(), RULE)
        assert other["inputs_sha256"] != base["inputs_sha256"], change
    # The writer's own fields are not a reading: they decide the other half.
    same = plan_identity.fingerprint(payload(model="other-model"), record(), RULE)
    assert same["inputs_sha256"] == base["inputs_sha256"] and same["versions_sha256"] != base["versions_sha256"]


def test_the_effort_the_model_was_asked_at_is_part_of_the_writer():
    base = plan_identity.fingerprint(payload(), record(), RULE)
    effort = payload()
    effort["model"] = dict(effort["model"], reasoning_effort="high")
    other = plan_identity.fingerprint(effort, record(), RULE)
    assert other["inputs_sha256"] == base["inputs_sha256"] and other["sha256"] != base["sha256"]


def test_case_and_spacing_do_not_make_a_term_another_term():
    found = plan_identity.difference(plan(setting=("Acoustic  Network",), task=("routing",)),
                                      plan(setting=("acoustic network",), task=("routing",)))
    assert (found["added"], found["removed"], found["moved"]) == ([], [], [])
    assert found["kept"] == 2


def test_a_backup_list_that_changed_order_is_reported():
    before = plan(setting=("a",), task=("b",), setting_backup=("c", "d"))
    after = plan(setting=("a",), task=("b",), setting_backup=("d", "c"))
    found = plan_identity.difference(before, after)
    # No term was added or dropped, but the first backup the block would use is another one.
    assert (found["added"], found["removed"], found["moved"]) == ([], [], [])
    assert found["reordered"] == {"setting_backup": {"before": ["c", "d"], "after": ["d", "c"]}}


def test_a_question_the_person_rewrote_is_another_fingerprint():
    other = plan_identity.fingerprint(payload(question="SYNTHETIC: which routing protocol saves most energy?"),
                                      record(), RULE)
    assert other["inputs_sha256"] != plan_identity.fingerprint(payload(), record(), RULE)["inputs_sha256"]


def test_the_comparison_names_the_added_the_dropped_and_the_terms_that_changed_place():
    before = plan(setting=("underwater sensor network", "acoustic channel"), task=("routing protocol",))
    after = plan(setting=("underwater sensor network",), task=("routing protocol", "energy consumption"),
                 setting_backup=("acoustic channel",))
    found = plan_identity.difference(before, after)
    assert found["added"] == ["energy consumption"]
    assert found["removed"] == []
    # The dropped setting term is the block's backup now: the plan still holds it, in another part of the query.
    assert found["moved"] == [{"term": "acoustic channel", "from": "setting", "to": "setting_backup"}]
    assert found["kept"] == 2 and found["reordered"].keys() == {"setting", "task", "setting_backup"}


def test_a_term_that_changed_block_is_not_counted_as_added_and_dropped():
    found = plan_identity.difference(plan(setting=("routing protocol",), task=("energy",)),
                                     plan(setting=("energy",), task=("routing protocol",)))
    assert found["added"] == [] and found["removed"] == []
    assert [row["term"] for row in found["moved"]] == ["energy", "routing protocol"]
    assert found["kept"] == 0


def test_two_plans_with_nothing_in_common_report_every_term():
    found = plan_identity.difference(plan(setting=("a",), task=("b",)), plan(setting=("c",), task=("d",)))
    assert (found["added"], found["removed"], found["moved"], found["kept"]) == (["c", "d"], ["a", "b"], [], 0)
    assert found["reordered"] == {"setting": {"before": ["a"], "after": ["c"]},
                                  "task": {"before": ["b"], "after": ["d"]}}


def test_a_term_written_twice_is_one_term():
    found = plan_identity.difference(plan(setting=("a", "a"), task=("b",)), plan(setting=("a",), task=("b",)))
    assert (found["added"], found["removed"], found["moved"], found["kept"]) == ([], [], [], 2)
