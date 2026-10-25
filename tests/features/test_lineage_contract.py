"""Synthetic L3 contract/transport checks, never model behavior or scientific validity."""

import asyncio
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, parse_step_input, valid_response
from test_contracts import CASES, STEP_INPUTS


def fixture():
    return copy.deepcopy(STEP_INPUTS['I_lineage_links'])


def output():
    return copy.deepcopy(next(c['output'] for c in CASES if c['name'] == 'lineage_valid'))


def codes(si):
    return {i.code for i in contracts.check_step_input(si)}


def verdict(si, draft):
    return contracts.validate_model_output(si, draft)


def first(si):
    return si['lineage_target']['candidates'][0]


def evidence(si, n=0):
    p = si['passages'][n]
    return {'passage_id': p['passage_id'], 'quote': p['text']}


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_lineage_schema_is_registered_strict_and_resolves_its_refs():
    assert contracts.SCHEMA_FILES['LineageLinksDraft'] == 'lineage-links-draft.schema.json'
    assert contracts.SCHEMA_VERSIONS['LineageLinksDraft'] == 'deixis.lineage_links_draft.v1'
    assert contracts.TASK_OUTPUTS['lineage_links'] == ('LineageLinksDraft',)
    for name in ('LineageLinksDraft', 'StepInput'):
        validator = contracts.canonical_validator(name)
        Draft202012Validator.check_schema(validator.schema)
        for node in walk(validator.schema):
            if '$ref' in node:
                assert validator._resolver.lookup(node['$ref']).contents
    schema = contracts.load_schema('LineageLinksDraft')
    assert 'continues_predecessor_uncertainty' not in json.dumps(schema)
    wire = contracts.step_output_schema('lineage_links')
    assert 'common.schema.json' not in json.dumps(wire)
    assert contracts.strict_compatibility_issues(wire) == []
    Draft202012Validator(wire).validate(output())


def test_fixture_step_input_is_clean():
    assert contracts.check_step_input(fixture()) == []


def test_unlocatable_quote_is_reported_and_a_located_quote_passes():
    si, draft = fixture(), output()
    draft['decisions'][0]['evidence'][0]['quote'] = 'SYNTHETIC invented words absent from every passage.'
    report = verdict(si, draft)
    assert 'anchor_not_in_passage' in report.codes()
    assert any('the quoted text was not found in the cited passage' in i.message for i in report.issues)
    draft['decisions'][0]['evidence'][0] = evidence(si)
    assert verdict(si, draft).ok


def test_citation_edge_alone_never_creates_a_link():
    si, draft = fixture(), output()
    first(si)['edge_state'] = 'present'
    no_relation = copy.deepcopy(draft)
    no_relation['decisions'][0].update(decision='no_relation',relation=None,what_changed=None,support_type=None,evidence=[])
    assert verdict(si, no_relation).ok
    assert no_relation['decisions'][0]['relation'] is None and no_relation['decisions'][0]['evidence'] == []
    empty = copy.deepcopy(draft)
    empty['decisions'][0]['evidence'] = []
    assert 'link_without_evidence' in verdict(si, empty).codes()
    unshown = copy.deepcopy(draft)
    unshown['decisions'][0]['evidence'][0]['passage_id'] = 'psg_SYNTHUNKNOWN01'
    assert 'unknown_passage_id' in verdict(si, unshown).codes()
    irrelevant = copy.deepcopy(draft)
    irrelevant['decisions'][0].update(support_type='analyst_inference',evidence=[evidence(si,2)])
    # T11 is structural only: a real quote about green apparatus proves no development relation.
    assert verdict(si, irrelevant).ok
    for fixed in [draft, no_relation, empty, unshown, irrelevant]:
        before = [(i.code,i.path,i.message) for i in verdict(si, fixed).issues]
        for state in ['present','absent_in_read_list','unresolved','not_read']:
            for warning in [False,True]:
                first(si).update(edge_state=state,year_order_warning=warning)
                assert [(i.code,i.path,i.message) for i in verdict(si,fixed).issues] == before


def lineage_flow(tmp_path, responder=valid_response):
    """Temporary DB and a hand-built target; no service, candidate selection or lineage persistence."""
    conn = db.connect(tmp_path/'library.sqlite')
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research('SYNTHETIC development relation?', 'attached','quick',[], 'fake','research-model','en')
    si = fixture()
    sids = [store.create_upload_source(s['title']) for s in si['sources']]
    target = si['lineage_target']
    target['to']['source_id'] = sids[0]
    for candidate,sid in zip(target['candidates'],sids[1:]):
        candidate['from']['source_id'] = sid
    pids = []
    with transaction(conn):
        for p in si['passages']:
            pids.append(store._insert_passage(sids[0],None,'abstract',None,None,'synthetic_fixture',None,None,p['text']))
    for i,candidate in enumerate(target['candidates']): candidate['mention_passage_ids'] = [pids[i]]
    adapter = FakeAdapter(responder=responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path/'data',port=8871),store,{'fake':adapter},skill.load_skill_package(),None))
    # L3 adds no run kind. Reuse a generic answer run only as a fake-step storage harness.
    run = store.create_run(rid,'answer',{'max_model_calls':4,'max_provider_requests':0},None)
    store.update_run(run['id'],status='running')
    scope = store.scope(rid)
    scope['literature_model'] = 'unused-literature-model'
    return flow,store,adapter,store.run(run['id']),scope,sids,[store.passage(pid) for pid in pids],target


def run_lineage(state):
    flow,store,adapter,run,scope,sids,passages,target = state
    return asyncio.run(flow._model_step(run,scope,'synthetic:lineage','lineage_links',source_ids=sids,
                                       passage_rows=passages,lineage_target=target))


def test_fake_adapter_answers_lineage_step_through_model_step(tmp_path):
    state = lineage_flow(tmp_path)
    flow,store,adapter,run,scope,sids,passages,target = state
    result = run_lineage(state)
    step = store.step(run['id'],'synthetic:lineage','model:lineage_links')
    assert step['status'] == 'succeeded' and step['output'] == result
    payload = store.step_input_payload(result['step_input_id'])
    assert payload['lineage_target'] == target
    assert payload['skill_files'] == ['SKILL.md','references/synthesis.md']
    assert payload['output_schema_versions'] == ['deixis.lineage_links_draft.v1']
    assert payload['skill_package_hash'] == flow.deps.package.package_hash
    assert payload['allowlist']['source_ids'] == sids
    assert payload['allowlist']['passage_ids'] == [p['id'] for p in passages]
    row = store.conn.execute('SELECT user_message FROM step_inputs WHERE id = ?', (result['step_input_id'],)).fetchone()
    shown = parse_step_input(row[0])
    assert shown == adapter.calls[0] == contracts.with_citation_handles(payload)
    raw = json.loads(store.model_session(result['step_input_id'])['raw_output'])
    assert raw['decisions'][0]['from_source_id'] == 'srv_S0000002'
    assert raw['decisions'][0]['evidence'][0]['passage_id'] == 'psg_P0000001'
    assert result['result'] == contracts.resolve_citation_handles(payload,json.dumps(raw))
    assert result['result']['decisions'][0]['from_source_id'] == sids[1]
    assert result['result']['decisions'][0]['evidence'][0]['passage_id'] == passages[0]['id']
    assert len(adapter.calls) == 1
    for real,handle in contracts.citation_handles(payload).items():
        assert real not in row[0] and handle in row[0]
    assert store.conn.execute('SELECT COUNT(*) FROM report_claims').fetchone()[0] == 0


def forbidden_salvage(*args,**kwargs):
    pytest.fail('Lineage must never use D56 answer salvage')


def test_lineage_step_repairs_once_then_stops_without_salvage(tmp_path,monkeypatch):
    monkeypatch.setattr(contracts,'salvage_answer_draft',forbidden_salvage)
    def bad(si):
        draft = json.loads(valid_response(si))
        draft['decisions'][0]['evidence'][0]['quote'] = 'SYNTHETIC nonexistent quote on both attempts.'
        return json.dumps(draft)
    state = lineage_flow(tmp_path,bad)
    result = run_lineage(state)
    flow,store,adapter,run,*_ = state
    assert result['invalid'] and 'anchor_not_in_passage' in {i['code'] for i in result['issues']}
    assert len(adapter.calls) == 2
    step = store.step(run['id'],'synthetic:lineage','model:lineage_links')
    assert step['status'] == 'failed' and step['error_code'] == 'invalid_model_output'
    rows = list(store.conn.execute('SELECT payload_json,user_message FROM step_inputs ORDER BY rowid'))
    assert len(rows) == 2
    assert 'anchor_not_in_passage' in rows[1]['user_message']
    assert 'psg_P0000001' in rows[1]['user_message']
    assert store.conn.execute('SELECT COUNT(*) FROM model_sessions').fetchone()[0] == 2


from dataclasses import replace

import pytest

from deixis.workflow.lineage_assembly import Link, assemble


def link(a, b, **kw):
    return Link(a + b, a, b, kw.get("relation", "extends"), kw.get("from_year", 2000 + ord(a)),
                kw.get("to_year", 2000 + ord(b)), ord(a), ord(b))


def test_directed_diamond_is_one_component_with_root_branch_and_merge():
    result = assemble([link("a", "b"), link("a", "c"), link("b", "d"), link("c", "d")])
    assert len(result.components) == 1
    c = result.components[0]
    assert c.members == ("a", "b", "c", "d") and c.roots == c.branches == ("a",) and c.merges == ("d",)
    assert not c.has_cycle and c.adjacency[-1].in_from == ("b", "c")


from dataclasses import replace

import pytest

from deixis.workflow.lineage_candidates import Candidate, LineageWork, find_candidates
from deixis.workflow.lineage_edges import Edge, EdgeFrom, EdgeTo, derive_edges, unassessed_edges
from deixis.workflow.lineage_mentions import PassageText


def work(svid, position, author="Nobody", year=2020, text="Unrelated text", **changes):
    values = dict(source_version_id=svid, work_id="work-" + svid, position=position,
                  title="Short title", authors=(author,), year=year, years=(), references_read=False,
                  referenced_ids=frozenset(), openalex_ids=frozenset(),
                  passages=(PassageText("p-" + svid, "pdf_page", text, 1),))
    return LineageWork(**dict(values, **changes))


def candidate(i, total=1, passages=None):
    return Candidate("to", f"from-{i:03d}", 100, i, total, ("surname_year",),
                     tuple(passages if passages is not None else (f"p-{i}",)), "not_read", False)


def pairs(result):
    return tuple((c.from_source_version_id, c.to_source_version_id) for c in result.candidates)


def synthetic_corpus():
    # D mentions B and an unrelated Smith (2010), colliding with A's first author.
    # F's numbered reference has no surname/year or title fragment in its passages.
    return (
        work("A", 0, "Smith", 2010, openalex_ids=frozenset({"W1"})),
        work("B", 1, "Brown", 2012, "We extend Smith (2010).", references_read=True,
             referenced_ids=frozenset({"W1"}), openalex_ids=frozenset({"W2"})),
        work("C", 2, "Chen", 2013, "We change the method of Smith et al., 2010.", references_read=True),
        work("D", 3, "Davis", 2014, "Brown (2012) is mentioned; unrelated Smith (2010) discusses another topic."),
        work("E", 4, "Evans", 2015),
        work("F", 5, "Fox", 2016, "We cite [1] only.", references_read=True, referenced_ids=frozenset({"W1"})),
    )


def test_human_decided_pair_is_excluded_by_parameter():
    corpus = synthetic_corpus()
    assert pairs(find_candidates(corpus, excluded_pairs=frozenset({("A", "D")}))) == (
        ("A", "B"), ("A", "C"), ("B", "D"))
    assert ("A", "D") in pairs(find_candidates(corpus, excluded_pairs=frozenset({("D", "A")})))


from deixis.workflow.lineage_edges import Edge, EdgeFrom, EdgeTo, derive_edges, edge_state, unassessed_edges


def test_edge_alone_creates_no_candidate():
    from deixis.workflow.lineage_candidates import LineageWork, find_candidates
    from deixis.workflow.lineage_mentions import PassageText

    a = LineageWork("a", "wa", 0, "Short title", ("Smith",), 2015, (), False,
                    frozenset(), frozenset({"W1"}), ())
    f = LineageWork("f", "wf", 1, "Numbered citation", ("Jones",), 2020, (), True,
                    frozenset({"W1"}), frozenset({"W2"}), (PassageText("pf", "pdf_page", "See [1]", 1),))
    assert edge_state(EdgeTo("f", "wf", True, f.referenced_ids), EdgeFrom("a", "wa", a.openalex_ids)) == "present"
    assert find_candidates((a, f)).candidates == ()
