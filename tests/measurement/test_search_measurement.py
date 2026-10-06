"""Synthetic measurement evidence only: no service, keys, model calls or provider network."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from helpers import make_pdf
from scripts.benchmark import check, labels, survey
from scripts.benchmark.common import canonical, identity, load_benchmark, sanitize, sha

BENCHMARKS = Path(__file__).resolve().parents[2] / 'scripts/benchmark'


def record(number, title='SYNTHETIC survey', **extra):
    return {'doi':f'10.1234/{number}', 'title':title, 'abstract':'SYNTHETIC method evidence',
            'openalex_id':f'W{number}', 'semantic_scholar_id':f'S{number}', **extra}


def pool(records):
    return {'format':'frozen-search-pool-v1',
            'question_sha256':load_benchmark(BENCHMARKS/'dbr_vbf.json')['question_sha256'], 'records':records}


def response(records=(), **extra):
    return survey.Response(200, canonical({'records':list(records), **extra}).encode())


@pytest.fixture
def library(tmp_path):
    """Real migrated schema, backed by the existing per-worker SQLite template fixture."""
    path = tmp_path/'library.sqlite'
    conn = db.connect(path)
    db.migrate(conn)
    store = Store(conn)
    bench = load_benchmark(BENCHMARKS/'dbr_vbf.json')
    rid = store.create_research(bench['question'],'academic','standard',['openalex'],
                                'scripted','synthetic-model','en',search_workflow='sw')
    run = store.create_run(rid,'discovery',{},None)
    run_id = run['id']
    start = '2026-10-06T00:00:00+00:00'
    search_time = '2026-10-06T00:00:05+00:00'
    rank_time = '2026-10-06T00:00:08+00:00'
    input_time = '2026-10-06T00:00:10+00:00'
    answer_time = '2026-10-06T00:00:15+00:00'
    def insert(table, **values):
        conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                     tuple(values.values()))
    conn.execute('UPDATE runs SET created_at=?,updated_at=?,usage_json=?,status=? WHERE id=?',
                 (start,answer_time,canonical({'provider_requests':1,'provider_sends':3,'model_calls':2}),
                  'completed',run_id))
    for wid in ('w1','w2','w3'):
        insert('works',id=wid,created_at=start)
    for sid,wid,doi,title in [('v1','w1',bench['papers'][0]['doi'],'SYNTHETIC A'),
                               ('v1pre','w1','10.1234/preprint','SYNTHETIC preprint'),
                               ('v2','w2',bench['papers'][1]['doi'],'SYNTHETIC B'),
                               ('v3','w3',None,bench['papers'][2]['title'])]:
        insert('source_versions',id=sid,work_id=wid,doi=doi,title=title,version_label='publishedVersion',
               origin='provider',created_at=start)
    traces = {'transport':{'sends':3,'dispatches':[{'subrequests':[
        {'url':'https://api.openalex.org/works','sends':3,'attempts':3,'retries':2,'status':'ok','http_status':200}]}]}}
    insert('run_steps',id='search',run_id=run_id,operation_key='code_query:p1',kind='provider:openalex',
           status='succeeded',started_at=start,finished_at=search_time,output_json=canonical(traces))
    payload_dir = tmp_path/'provider-payloads'
    payload_dir.mkdir()
    raw = {'results':[record(i) for i in range(5)]}
    (payload_dir/'raw.json').write_text(canonical(raw))
    insert('search_runs',id='sr1',research_id=rid,run_id=run_id,step_id='search',provider='openalex',
           query_text='SYNTHETIC routing query',request_description='SYNTHETIC API',access_mode='keyless',
           status='completed',result_count=3,provider_total=10000,page_limit=100,retrieved_at=search_time,
           raw_payload_path='raw.json',payload_sha256=sha(canonical(raw)))
    for i,sid in enumerate(('v1','v1pre','v2','v3')):
        insert('candidates',id=f'can{i}',research_id=rid,scope_revision=1,source_version_id=sid,
               search_run_id='sr1',rank=i+1,created_at=search_time)
        insert('candidate_hits',research_id=rid,scope_revision=1,source_version_id=sid,search_run_id='sr1')
    for step_id,key,finished in [('old_rank','ranking',rank_time),('new_rank','ranking_later','2026-10-06T00:01:00+00:00')]:
        insert('run_steps',id=step_id,run_id=run_id,operation_key=key,kind='code:ranking',status='succeeded',
               started_at=search_time,finished_at=finished)
        for i,sid in enumerate(('v1','v1pre','v2') if step_id=='old_rank' else ('v2','v1')):
            insert('record_signal_ranks',ranking_step_id=step_id,research_id=rid,source_version_id=sid,
                   signal='inspection',rank=i+1,available=1)
    text = 'SYNTHETIC DBR uses less energy than VBF.'
    insert('passages',id='p1',source_version_id='v1pre',kind='abstract',abstract_origin='provider',
           text=text,text_sha256=sha(text),retrieved_at=search_time,created_at=search_time)
    insert('run_steps',id='answer_step',run_id=run_id,operation_key='answer',kind='model:grounded_answer',
           status='succeeded',attempt=1,started_at=input_time,finished_at=answer_time)
    payload = {'question':{'text':bench['question']}, 'ranking_step_id':'old_rank',
               'sources':[{'source_id':'v1pre'},{'source_id':'v2'}],
               'passages':[{'passage_id':'p1','source_id':'v1pre','text':text,'reading_depth':'abstract'}]}
    insert('step_inputs',id='input',step_id='answer_step',research_id=rid,run_id=run_id,attempt=1,
           task_type='grounded_answer',scope_revision=1,skill_package_hash='SYNTHETIC',payload_json=canonical(payload),
           base_instructions='',developer_instructions='',user_message='',output_schema_json='{}',created_at=input_time)
    draft = {'claims':[{'claim_label':'C1','text':text,'passage_ids':['p1']}], 'citation_anchors':[]}
    insert('answers',id='a1',research_id=rid,run_id=run_id,step_id='answer_step',step_input_id='input',scope_revision=1,
           selection_revision=1,status='structurally_valid',draft_json=canonical(draft),validation_json='{}',created_at=answer_time)
    insert('claims',id='c1',answer_id='a1',label='C1',ordinal=0,text=text,support_type='source_stated')
    insert('evidence_links',id='link',claim_id='c1',passage_id='p1',source_version_id='v1pre',step_input_id='input',
           anchor_text=text,anchor_match='exact')
    insert('pdf_discovery_runs',id='pdf_lookup',research_id=rid,source_version_id='v2',provider='openalex',
           query_text='SYNTHETIC',status='completed',created_at=search_time,finished_at=rank_time)
    insert('pdf_candidates',id='pdf_candidate',source_version_id='v2',discovery_run_id='pdf_lookup',provider='openalex',
           candidate_url='https://example.org/synthetic.pdf',identity_status='doi_verified',version_status='match',
           access_status='timeout',discovered_at=search_time,attempted_at=rank_time)
    # Existing PDF helper: the download artifact is synthetic and is not treated as inspected text.
    pdf_bytes = make_pdf(['SYNTHETIC unread document'])
    (tmp_path/'synthetic.pdf').write_bytes(pdf_bytes)
    insert('source_assets',id='asset',source_version_id='v1',sha256=sha(pdf_bytes.hex()),byte_size=len(pdf_bytes),
           media_type='application/pdf',storage_path='synthetic.pdf',retrieved_at=search_time,
           origin='user_upload',extraction_status='pending')
    for i,status in enumerate(('failed','completed')):
        insert('model_sessions',id=f'm{i}',research_id=rid,run_id=run_id,step_id='answer_step',step_input_id='input',
               connection='scripted',requested_model='synthetic-model',resolved_model='synthetic-model',
               status=status,started_at=input_time,finished_at=answer_time)
    yield conn,rid,bench,path,insert
    conn.close()


def test_frozen_sets_counts_hashes_keys_and_final_labels():
    for name,count,nkeys in [('dbr_vbf',6,2),('kurt2017',18,3),('uwsn_kconn2022',23,3),('irs2021',32,3)]:
        bench = load_benchmark(BENCHMARKS/(name+'.json'))
        assert len(bench['papers'])==count
        assert sum(p['anchor'] for p in bench['papers'])==nkeys
        assert bench['answer_elements']
    all_papers = [p for file in BENCHMARKS.glob('*.json') for p in load_benchmark(file)['papers']]
    by_doi = {p['doi']:p for p in all_papers if p['doi']}
    assert by_doi['10.1007/978-3-540-79549-0_7']['label']=='ilgili'
    assert by_doi['10.1109/icassp.2019.8683663']['label']=='arka plan'
    assert by_doi['10.1007/11776178_26']['label']=='ilgili'
    assert by_doi['10.1007/s11277-021-08881-7']['label']=='arka plan'
    assert by_doi['10.1016/j.adhoc.2014.07.012']['label']=='ilgili'
    assert by_doi['10.1109/infocom.2008.54']['alternate_identity_status']=='unverified'


def test_read_only_explicit_snapshot_and_no_default(library,monkeypatch):
    _,_,_,path,_ = library
    monkeypatch.delenv('DEIXIS_DATA_DIR',raising=False)
    with pytest.raises(ValueError,match='explicitly'):
        check.connect()
    with pytest.raises(ValueError,match='does not exist'):
        check.connect(path.parent/'missing.sqlite')
    conn = check.connect(path)
    with pytest.raises(sqlite3.OperationalError,match='readonly'):
        conn.execute("UPDATE researches SET title='changed'")
    conn.close()


def test_answer_pinned_ranking_counts_origins_passages_depth_and_calls(library):
    conn,rid,bench,_,_ = library
    result = check.measure(conn,rid,'a1',bench)
    first,second,third = result['papers'][:3]
    assert first['target_key']==bench['papers'][0]['key']
    assert result['direction_claims'][0]['cites']==[first['target_key']]
    assert result['ranking_step_id']=='old_rank'
    assert (first['rank'],second['rank'])==(1,2)  # two versions of one work occupy one position
    assert result['totals']['raw_records']==5
    assert result['totals']['stored_filtered_records']==3
    assert result['totals']['unique_works']==3
    assert result['totals']['source_versions']==4
    assert first['search_origins'][0]['query_text']=='SYNTHETIC routing query'
    assert first['search_origins'][0]['operation_key']=='code_query:p1'
    assert first['passage_given_to_model'] and first['passages_given']==['abstract']
    assert first['cited_versions']==['v1pre']
    assert first['cited_in']==['C1']
    assert second['given_to_model'] and not second['passage_given_to_model']
    assert second['pdf_access']['recorded_attempts']==1
    assert second['pdf_access']['attempts'][0]['access_status']=='timeout'
    assert second['fulltext_decision_state']=='no_decision'
    assert third['identity_status']=='title_match_requires_adjudication' and not third['found']
    assert result['coverage']['keys']['denominator']==2
    assert result['coverage']['keys']['counts']['passage_given_to_model']==1
    assert result['durations']['to_ranking_seconds']==8
    assert result['durations']['to_first_valid_answer_seconds']==15
    assert result['calls']['provider_sends']==3
    assert result['calls']['observed_provider_sends']==3
    assert result['calls']['model_real_sends']==check.UNMEASURABLE
    counts = next(iter(result['calls']['models_by_role'].values()))
    assert counts['recorded_adapter_invocations']==2 and counts['statuses']=={'failed':1,'completed':1}
    assert len(result['frozen_pool']['records'])==4


def test_unavailable_telemetry_never_zero_and_future_ranking_rejected(library):
    conn,rid,bench,_,_ = library
    conn.execute('UPDATE runs SET usage_json=?',(canonical({'provider_requests':2}),))
    result = check.measure(conn,rid,'a1',bench)
    assert result['calls']['provider_sends']==check.UNMEASURABLE
    assert result['durations']['human_wait_seconds']==check.UNMEASURABLE
    with pytest.raises(ValueError,match='pre-answer'):
        check.measure(conn,rid,'a1',bench,'new_rank')
    conn.execute("UPDATE run_steps SET finished_at='2026-10-06T00:00:11+00:00' WHERE id='old_rank'")
    with pytest.raises(ValueError,match='pre-answer'):
        check.measure(conn,rid,'a1',bench)


def test_draft_or_unlocated_anchor_does_not_count_as_cited(library):
    conn,rid,bench,_,_ = library
    conn.execute("UPDATE evidence_links SET anchor_text='SYNTHETIC invented anchor'")
    result = check.measure(conn,rid,'a1',bench)
    assert not result['papers'][0]['cited_in']
    assert result['papers'][0]['draft_cited_in']==['C1']
    assert len(result['invalid_or_draft_links'])==1


def test_identity_alias_version_and_empty_bibliography(tmp_path):
    sent=[]
    base=[record(1,verified_work_id='verified-1')]
    def send(request):
        sent.append(request)
        if request['endpoint']=='search':
            return response()
        return response([record(1,version_label='preprint'),
                         record(9,verified_work_id='verified-1'),record(2),{'title':'unresolved'}])
    result=survey.run(pool(base),'dbr_vbf',send,tmp_path/'trial')
    b=result['arms']['B']
    assert b['new_unique_works']==1
    assert any(r['identity_status']=='version_alias' for r in b['links'])
    assert any(r['identity_status']=='duplicate' for r in b['links'])
    assert any(r['identity_status']=='unresolved_identity' for r in b['links'])
    assert any(r['bibliography_status']=='empty_returned' for r in result['arms']['C']['requests'])
    assert all(r['model_calls']==0 for r in result['arms'].values())
    assert result['arms']['C']['requests'][0]['operation_status']=='cache_replay'
    assert result['arms']['C']['requests'][0]['body_sha256']==b['requests'][0]['body_sha256']
    assert all(r['mode']=='offline_replay' for r in b['requests'])


@pytest.mark.parametrize('status,expected',[(429,'rate_limited'),(401,'unauthorized'),(404,'not_found'),(500,'provider_error')])
def test_http_statuses_and_bounded_retries(tmp_path,status,expected):
    sent=[]
    def send(request):
        sent.append(request)
        return survey.Response(status,b'{}')
    arm=survey.Arm('B',[record(1)],send,tmp_path)
    assert arm.fetch('openalex','references',seed='W1')==[]
    assert len(sent)==(3 if status==429 else 1)
    assert all(r['request_status']==expected for r in arm.log)


def test_retry_success_timeout_invalid_payload_and_no_hidden_send(tmp_path):
    replies=iter([survey.Response(429,b'{}'),response([record(2)])])
    arm=survey.Arm('B',[record(1)],lambda r:next(replies),tmp_path/'retry')
    assert len(arm.fetch('openalex','references',seed='W1'))==1
    assert [r['request_status'] for r in arm.log]==['rate_limited','ok']
    assert arm.log[1]['retry_index']==1
    def timeout(_):
        raise TimeoutError
    arm=survey.Arm('B',[],timeout,tmp_path/'timeout')
    arm.fetch('openalex','references',seed='W1')
    assert arm.log[0]['request_status']=='timeout' and len(arm.log)==1
    arm=survey.Arm('B',[],lambda _:survey.Response(200,b'not JSON'),tmp_path/'bad')
    arm.fetch('openalex','references',seed='W1')
    assert arm.log[0]['request_status']=='invalid_payload'


def test_s2_first_page_only_and_raw_response_secrets(tmp_path):
    requests=[]
    def send(request):
        requests.append(request)
        return survey.Response(200,canonical({'data':[{'citedPaper':{'paperId':'S2','title':'SYNTHETIC'}}],
            'next':100,'total':250,'api_key':'SYNTHETIC_SECRET',
            'url':'https://example.org?api_key=SYNTHETIC_SECRET',
            'headers':{'Authorization':'Bearer SYNTHETIC_SECRET'}}).encode())
    arm=survey.Arm('B',[record(1)],send,tmp_path)
    arm.expand([record(1,openalex_id=None,doi=None)])
    assert len(requests)==1 and requests[0]['offset']==0
    entry=arm.log[0]
    assert entry['first_page_only'] and entry['bibliography_status']=='first_page_only'
    assert entry['returned_count']==1 and entry['next_offset']==100 and entry['total']==250
    body=(tmp_path/entry['body_path']).read_text()
    assert 'SYNTHETIC_SECRET' not in body and sha(body)==entry['body_sha256']
    assert 'SYNTHETIC_SECRET' not in canonical(arm.report())


def test_request_and_work_limits_and_resolution_budget(tmp_path):
    requests=[]
    def send(request):
        requests.append(request)
        return response([record(i+100) for i in range(150)])
    arm=survey.Arm('N',[record(1)],send,tmp_path)
    arm.expand([record(1)])
    assert arm.new==100 and arm.overflow==50
    assert len(arm.records)==101 and len(requests)==1
    assert arm.report()['operation_status']=='budget_exhausted'
    body=(tmp_path/arm.log[0]['body_path']).read_text()
    assert len(json.loads(body)['records'])==150
    arm=survey.Arm('N',[],lambda _:response(),tmp_path/'requests')
    for i in range(25):
        arm.fetch('openalex','references',seed=f'W{i}')
    assert len(arm.log)==20 and arm.stopped
    attempts=[]
    def resolve(request):
        attempts.append(request)
        return survey.Response(200,canonical({'referenced_works':['W2','W3']}).encode()) if request['endpoint']=='references' else response([record(2),record(3)])
    arm=survey.Arm('B',[record(1)],resolve,tmp_path/'resolution',requests=1)
    arm.expand([record(1,semantic_scholar_id=None)])
    assert len(attempts)==1 and arm.new==0 and arm.stopped


def test_c_shared_budget_and_n_equal_send_prefix(tmp_path):
    requests=[]
    def send(request):
        requests.append(request)
        return response()
    result=survey.run(pool([record(i) for i in range(8)]),'dbr_vbf',send,tmp_path/'trial')
    b,c,n=(result['arms'][a] for a in ('B','C','N'))
    assert b['provider_sends']==10
    assert c['provider_sends']<=20 and n['provider_sends']==20
    assert c['requests'][:10]==[r|{'operation_status':'cache_replay','inherited_from':'B'} for r in b['requests']]
    assert len(requests)==b['provider_sends']+(c['provider_sends']-b['provider_sends'])+n['provider_sends']
    assert result['N_at_equal_sends']['B']['observed_sends']==10
    assert result['N_at_equal_sends']['B']['new_identities']==[]


def test_blind_forms_merge_disagreement_and_short_list_denominator():
    arms={'A':[record(i,title=f'SYNTHETIC {i}',score=100-i,arm='secret') for i in range(30)],
          'C':[record(i,title=f'SYNTHETIC {i}',score=100-i) for i in range(2)]}
    result=labels.forms('SYNTHETIC question',arms)
    assert len(result['owner']['items'])==20 and len(result['model_1']['items'])==10
    assert canonical(result['model_1']['items'])==canonical(result['model_2']['items'])
    for form in ('owner','model_1','model_2'):
        text=canonical(result[form])
        assert 'score' not in text and 'positions' not in text and 'secret' not in text
        for item in result[form]['items']:
            item.update(label='relevant',reason='SYNTHETIC methods',reading_depth='abstract')
    right=copy.deepcopy(result['model_2'])
    right['items'][0]['label']='irrelevant'
    merged=labels.merge(result['model_1'],right)
    assert len(merged['agreed'])==9 and len(merged['owner_disagreements'])==1
    scores=labels.score(result['private_key'],result['owner'],merged)
    assert scores['A']['P@20']['value']==1
    assert scores['A']['P@50']['uncertain']==1 and scores['A']['P@50']['value']==29/30
    assert scores['C']['P@20']['denominator']==2
    assert merged['human_verified'] is False


def test_forms_reject_mixed_runs_duplicate_and_unresolved_identity():
    result=labels.forms('SYNTHETIC',{'A':[record(i) for i in range(22)]})
    for role in ('model_1','model_2'):
        for row in result[role]['items']:
            row.update(label='uncertain',reason='SYNTHETIC incomplete',reading_depth='title_only')
    changed=copy.deepcopy(result['model_2'])
    changed['form_id']='other'
    with pytest.raises(ValueError,match='different'):
        labels.merge(result['model_1'],changed)
    with pytest.raises(ValueError,match='resolved'):
        labels.forms('SYNTHETIC',{'A':[{'title':'no identifier'}]})


def test_title_and_unverified_doi_alias_never_score_target(tmp_path):
    bench=load_benchmark(BENCHMARKS/'kurt2017.json')
    target=next(p for p in bench['papers'] if p['alternate_dois'])
    fake={'question_sha256':bench['question_sha256'], 'arms':{a:{'provider_sends':0,'records':[
        {'doi':target['alternate_dois'][0],'title':target['title']}]} for a in ('A','B','C','N')}}
    scored=survey.score_targets(fake,bench)
    assert target['key'] not in scored['coverage']['A']['found']
    assert identity({'title':'same title'}) is None
    assert sanitize({'api_key':'secret','url':'https://user:password@example.org?token=secret&offset=0'}) == {
        'url':'https://example.org?offset=0'}


def test_discovery_ranking_inferred_without_answer_run_ranking(library):
    conn,rid,bench,_,insert = library
    # A second immutable StepInput/answer represents an answer-only run without a ranking reference.
    insert('runs',id='answer_only',research_id=rid,scope_revision=1,kind='answer',status='completed',
           stage='answer',budget_json='{}',usage_json='{}',created_at='2026-10-06T00:00:09+00:00',
           updated_at='2026-10-06T00:00:15+00:00')
    insert('run_steps',id='a2step',run_id='answer_only',operation_key='answer',kind='model:grounded_answer',
           status='succeeded',started_at='2026-10-06T00:00:10+00:00',finished_at='2026-10-06T00:00:15+00:00')
    payload=json.loads(conn.execute("SELECT payload_json FROM step_inputs WHERE id='input'").fetchone()[0])
    payload.pop('ranking_step_id')
    insert('step_inputs',id='input2',step_id='a2step',research_id=rid,run_id='answer_only',attempt=1,
           task_type='grounded_answer',scope_revision=1,skill_package_hash='SYNTHETIC',payload_json=canonical(payload),
           base_instructions='',developer_instructions='',user_message='',output_schema_json='{}',
           created_at='2026-10-06T00:00:10+00:00')
    insert('answers',id='a2',research_id=rid,run_id='answer_only',step_id='a2step',step_input_id='input2',
           scope_revision=1,status='unverified_draft',draft_json='{"claims":[]}',validation_json='{}',
           created_at='2026-10-06T00:00:15+00:00')
    result=check.measure(conn,rid,'a2',bench)
    assert result['ranking_step_id']=='old_rank'
    assert result['ranking_binding']=='inferred_by_time'
    pinned=check.measure(conn,rid,'a2',bench,'old_rank')
    assert pinned['ranking_binding']=='operator_pinned' and pinned['papers'][0]['rank']==1
    with pytest.raises(ValueError,match='pre-answer'):
        check.measure(conn,rid,'a2',bench,'new_rank')
    discovery=conn.execute("SELECT run_id FROM run_steps WHERE id='old_rank'").fetchone()[0]
    insert('run_steps',id='last_rank',run_id=discovery,operation_key='ranking_retry',kind='code:ranking',
           status='succeeded',finished_at='2026-10-06T00:00:09+00:00')
    insert('record_signal_ranks',ranking_step_id='last_rank',research_id=rid,source_version_id='v2',
           signal='inspection',rank=1,available=1)
    assert check.measure(conn,rid,'a2',bench)['ranking_step_id']=='last_rank'
    assert check.measure(conn,rid,'a2',bench,'old_rank')['ranking_step_id']=='old_rank'
    conn.execute("UPDATE run_steps SET status='failed' WHERE kind='code:ranking'")
    result=check.measure(conn,rid,'a2',bench)
    assert result['ranking_step_id'] is None
    assert result['coverage']['all']['counts']['top_20'] is None
    assert result['papers'][0]['rank_state']=='ranking_unmeasurable'


def test_empty_stratum_and_payload_hash_or_path_failure(library):
    conn,rid,bench,path,_ = library
    bench=copy.deepcopy(bench)
    bench['papers'][2]['stratum']='empty_relevant_layer'
    (path.parent/'provider-payloads'/'raw.json').write_text('{"results":[]}')
    result=check.measure(conn,rid,'a1',bench)
    assert result['coverage']['empty_relevant_layer']['denominator']==0
    assert result['coverage']['empty_relevant_layer']['ratios']['found'] is None
    assert result['totals']['raw_records']==check.UNMEASURABLE
    assert result['totals']['raw_count_status_by_search']['sr1']=='payload_hash_mismatch'
    conn.execute("UPDATE search_runs SET raw_payload_path='../outside.json'")
    result=check.measure(conn,rid,'a1',bench)
    assert result['totals']['raw_count_status_by_search']['sr1']=='payload_outside_snapshot'


def test_other_research_pdf_attempt_is_not_attributed(library):
    conn,rid,bench,_,insert=library
    insert('researches',id='other_research',title='SYNTHETIC other',
           created_at='2026-10-06T00:00:00+00:00',updated_at='2026-10-06T00:00:00+00:00')
    conn.execute("UPDATE pdf_discovery_runs SET research_id='other_research'")
    result=check.measure(conn,rid,'a1',bench)
    assert result['papers'][1]['pdf_access']['recorded_attempts']==0
    assert result['papers'][1]['pdf_access']['state']=='no_recorded_attempt'
    assert result['papers'][0]['pdf_access']['assets_available'][0]['extraction_status']=='pending'
    assert result['papers'][0]['passages_given']==['abstract']  # an available PDF did not establish full-text reading


def test_retry_at_budget_boundary_never_sends_twenty_first_request(tmp_path):
    sent=[]
    def send(request):
        sent.append(request)
        return survey.Response(429,b'{}')
    arm=survey.Arm('N',[],send,tmp_path)
    for i in range(10):
        arm.fetch('openalex','references',seed=f'W{i}')
    assert len(sent)==20 and arm.stopped
    assert arm.log[-1]['retry_index']==1
    with pytest.raises(ValueError,match='twenty'):
        survey.Arm('N',[],send,tmp_path,requests=21)


def test_native_openalex_resolution_and_paging_are_charged(tmp_path):
    requests=[]
    def send(request):
        requests.append(request)
        if request['endpoint']=='references':
            return survey.Response(200,canonical({'referenced_works':['W2','W3']}).encode())
        return survey.Response(200,canonical({'results':[record(2),record(3)]}).encode())
    arm=survey.Arm('B',[record(1)],send,tmp_path/'resolve')
    arm.expand([record(1,semantic_scholar_id=None,doi=None)])
    assert [r['endpoint'] for r in requests]==['references','resolve']
    assert arm.new==2 and arm.log[1]['ids']==['W2','W3']
    requests.clear()
    def paged(request):
        requests.append(request)
        return response([record(request['offset']+10)],next_offset=1 if request['offset']==0 else None,total=2)
    arm=survey.Arm('N',[record(1)],paged,tmp_path/'pages')
    arm.expand([record(1,semantic_scholar_id=None,doi=None)])
    assert [r['offset'] for r in requests]==[0,1]
    assert arm.new==2


def test_natural_survey_seed_and_posthoc_target_scoring(tmp_path):
    bench=load_benchmark(BENCHMARKS/'dbr_vbf.json')
    discovered=record(10,title='SYNTHETIC underwater routing review')
    target=record(11,title=bench['papers'][0]['title'],doi=bench['papers'][0]['doi'])
    requests=[]
    def send(request):
        requests.append(request)
        if request['endpoint']=='search':
            return response([discovered])
        if request['seed'] in ('W10','S10'):
            return response([target])
        return response()
    result=survey.run(pool([record(1,title='SYNTHETIC primary paper')]),'dbr_vbf',send,tmp_path/'trial')
    assert result['B_seeds']==[] and result['C_seeds']==[identity(discovered)]
    assert result['arms']['C']['provider_sends']<=20
    scored=survey.score_targets(result,bench)
    assert scored['incremental_targets']['C-A']==['maulana2019']
    assert scored['incremental_targets']['C-B']==['maulana2019']
    assert scored['coverage']['C']['keys']==['maulana2019']
    assert all(bench['papers'][0]['doi'] not in canonical(r) for r in requests)


def test_recovered_retry_does_not_make_completed_arm_fail(tmp_path):
    replies=iter([survey.Response(429,b'{}'),response()])
    arm=survey.Arm('B',[],lambda _:next(replies),tmp_path)
    arm.fetch('openalex','references',seed='W1')
    assert arm.report()['operation_status']=='completed'
    assert arm.log[0]['request_status']=='rate_limited' and arm.log[0]['recovered_by_retry']


def test_model_forms_are_independent_and_owner_evidence_cannot_change():
    result=labels.forms('SYNTHETIC',{'A':[record(i) for i in range(22)]})
    for name in ('owner','model_1','model_2'):
        for row in result[name]['items']:
            row.update(label='relevant',reason='SYNTHETIC',reading_depth='abstract')
    result['model_2']['items'][0]['label']='uncertain'
    assert result['model_1']['items'][0]['label']=='relevant'
    merged=labels.merge(result['model_1'],result['model_2'])
    result['owner']['items'][0]['abstract']='different evidence'
    with pytest.raises(ValueError,match='changed evidence'):
        labels.score(result['private_key'],result['owner'],merged)


def test_budget_without_send_does_not_mutate_previous_seed_page(tmp_path):
    arm=survey.Arm('B',[],lambda _:response(next_offset=10,total=100),tmp_path,requests=1)
    arm.fetch('semantic_scholar','references',seed='S1')
    before=copy.deepcopy(arm.log)
    arm.expand([record(2,doi=None,semantic_scholar_id=None)])
    assert arm.log==before
    assert arm.links[-1]['operation_status']=='not_attempted'


@pytest.mark.parametrize('kind',['ReadTimeout','ConnectTimeout','WriteTimeout','PoolTimeout'])
def test_transport_timeouts_are_recorded(tmp_path,kind):
    import httpx
    def send(_):
        raise getattr(httpx,kind)('SYNTHETIC timeout')
    arm=survey.Arm('N',[],send,tmp_path)
    arm.fetch('openalex','references',seed='W1')
    assert len(arm.log)==1 and arm.log[0]['request_status']=='timeout'


def test_existing_a_surveys_are_not_new_c_seeds_and_allocation_is_recorded(tmp_path):
    base=[record(i) for i in range(10)]
    result=survey.run(pool(base),'dbr_vbf',lambda r:response([base[-1]]) if r['endpoint']=='search'
                      else response(),tmp_path/'trial')
    assert result['C_seeds']==[]
    assert len(result['B_seeds'])==8
    allocation=result['allocation']
    assert allocation['B']==10 and allocation['B_used']==10
    assert allocation['C_remaining_after_B']==10 and allocation['C_including_B']==20


def test_duplicate_and_verified_different_doi_alias(tmp_path):
    base=[record(1,verified_work_id='work-1')]
    arm=survey.Arm('B',base,lambda _:response(),tmp_path)
    arm.add([record(1),record(2,verified_work_id='work-1'),record(3)],'openalex',{})
    assert [link['identity_status'] for link in arm.links]==['duplicate','version_alias','resolved']
    assert arm.new==1


def test_target_identity_rule_shared_with_sqlite_measurement():
    versions=[dict(record(1),id='v1',work_id='w1'),dict(record(2),id='v2',work_id='w1')]
    papers=[{'key':'doi','doi':'10.1234/1','label':'ilgili','anchor':True,'stratum':'test'},
            {'key':'work','verified_work_ids':['w1'],'label':'ilgili','anchor':False,'stratum':'test'},
            {'key':'alias','doi':'10.1234/3','alternate_dois':['10.1234/2'],
             'alternate_identity_status':'verified','label':'ilgili','anchor':False,'stratum':'test'},
            {'key':'unverified','doi':'10.1234/3','alternate_dois':['10.1234/2'],
             'alternate_identity_status':'unverified','label':'ilgili','anchor':False,'stratum':'test'}]
    bench={'question_sha256':'synthetic','papers':papers}
    report={'question_sha256':'synthetic','arms':{a:{'records':versions,'provider_sends':0}
                                               for a in ('A','B','C','N')}}
    found=survey.score_targets(report,bench)['coverage']['A']['found']
    assert found==[p['key'] for p in papers if check.paper_match(versions,p)[0]]
    assert found==['doi','work','alias']


@pytest.mark.parametrize('c_key,expected',[(True,True),(False,False)])
def test_c_minus_n_equal_sends_net_gain_and_key_guard(c_key,expected):
    papers=[{'key':str(i),'doi':f'10.1234/{i}','label':'ilgili','anchor':i==1,'stratum':'test'}
            for i in range(1,5)]
    def arm(numbers,sends):
        return {'records':[record(i) for i,_ in numbers],'provider_sends':sends,
                'links':[{'record':record(i),'identity_status':'resolved','send_index':at} for i,at in numbers]}
    report={'question_sha256':'synthetic','arms':{'A':arm([],0),'B':arm([],0),
        'C':arm([(1 if c_key else 3,1),(2,2)],2),'N':arm([(1,1),(3,3),(4,4)],4)}}
    scored=survey.score_targets(report,{'question_sha256':'synthetic','papers':papers})
    equal=scored['equal_send_comparisons']['C-N']
    assert equal['equal_sends']==2 and equal['coverage']['N']['found']==['1']
    assert equal['net_target_gain']==1 and equal['preference_rule_met']==expected
    assert equal['no_fewer_keys']==c_key
    assert scored['incremental_targets']['C-N']==(['2'] if c_key else ['2','3'])
    report['arms']['N']['provider_sends']=1
    assert survey.score_targets(report,{'question_sha256':'synthetic','papers':papers})[
        'equal_send_comparisons']['C-N']['preference_rule_met'] is None


def test_check_output_requires_force_and_preserves_existing_file(tmp_path,monkeypatch,capsys):
    output=tmp_path/'result.json'
    output.write_text('existing evidence')
    monkeypatch.setattr('sys.argv',['check.py','rid','--answer','a1','--output',str(output)])
    monkeypatch.setattr(check,'connect',lambda:pytest.fail('must reject before reading snapshot'))
    assert check.main()==2
    assert output.read_text()=='existing evidence' and '--force' in capsys.readouterr().err
    class Connection:
        def close(self):
            pass
    monkeypatch.setattr(check,'connect',Connection)
    monkeypatch.setattr(check,'measure',lambda *args:{'totals':{'unique_works':0},'ranking_step_id':None})
    monkeypatch.setattr(check.subprocess,'check_output',lambda *args,**kwargs:'synthetic')
    monkeypatch.setattr('sys.argv',['check.py','rid','--answer','a1','--output',str(output),'--force'])
    assert check.main()==0 and json.loads(output.read_text())['git_head']=='synthetic'
