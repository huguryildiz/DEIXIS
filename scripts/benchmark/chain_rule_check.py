"""Offline, read-only check of the discovery chain's admission rules on a stored run (the m1 method).

    uv run python scripts/benchmark/chain_rule_check.py <library.sqlite> [<library.sqlite> ...]

For every chain request a discovery run stored (`search_runs` rows `chain:fast:*` with a raw payload), the payload is
parsed with the OpenAlex connector's own parser, identities filtered and the records capped as the fast chain does,
then judged by `chaining.passes` over the run's searched gate forms (`fast_chain_v1`) and by `chaining.passes_v2`
over the forms its protocol froze (a v2 run whose frozen forms are absent or fail their digest is only marked
`forms_unverified`), or, for a v1 run, the forms v2 would have frozen from its vocabulary. A late reply
admits nothing and is left out. The v1 verdict must reproduce `chain_links.passed_filter` of a v1 run, and the v2
verdict that of a v2 run, with 0 mismatches. `extra` counts the chain-only works (`manifest.chain_heads`) that pass v2
and not v1: M1's extra chained records. The payloads sit in `provider-payloads/` beside the library; nothing is
written. Pass copies of libraries, never the owner's own.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from deixis.providers import openalex
from deixis.providers.facade import usable_identity
from deixis.workflow.search import chaining, ranking

# The chain rules a stored library can carry. Only the last one is still carried out; the earlier two are read
# here because old measurement libraries were frozen under them, and both judge a run by the forms it froze.
NORMALISED_RULES = ('fast_chain_v2', 'fast_chain_v3')

LIST_KEY = 'small_batch:v1:list'


def connect(path):
    conn = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def output(conn, run_id, key):
    row = conn.execute('SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?',
                       (run_id, key)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def protocol_body(conn, run):
    step = output(conn, run['id'], 'protocol') or {}
    row = conn.execute('SELECT body_json FROM protocol_records WHERE research_id = ? AND scope_revision = ?'
                       ' AND protocol_revision = ?', (run['research_id'], run['scope_revision'],
                                                      step.get('protocol_revision'))).fetchone()
    return json.loads(row[0]) if row else {}


def chain_records(conn, payloads, run_id):
    """({OpenAlex id: (title, abstract)} of every record a non-late chain reply returned, as the product parsed it,
    the number of non-late replies with records whose payload is missing, so cannot be checked)."""
    records, missing = {}, 0
    for row in conn.execute("SELECT s.raw_payload_path, s.page_limit, s.result_count, st.output_json FROM search_runs s"
                            " JOIN run_steps st ON st.id = s.step_id WHERE s.run_id = ? AND s.query_text LIKE"
                            " 'chain:fast:%'", (run_id,)):
        if (json.loads(row['output_json'] or '{}') or {}).get('late'):
            continue
        path = payloads / row['raw_payload_path'] if row['raw_payload_path'] else None
        if path is None or not path.exists():
            missing += bool(row['result_count'])
            continue
        parsed = [openalex._record(work) for work in json.loads(path.read_text()).get('results') or []]
        kept = [r for r in parsed if usable_identity(r.provider_record_id)][:row['page_limit']]
        for record in kept:
            records.setdefault(record.provider_record_id, (record.title, record.abstract))
    return records, missing


def check(path):
    path = Path(path)
    conn = connect(path)
    out = {}
    for run in conn.execute("SELECT * FROM runs WHERE kind = 'discovery' ORDER BY created_at"):
        listing = output(conn, run['id'], LIST_KEY)
        if listing is None:
            continue
        manifest, budget = listing['manifest'], json.loads(run['budget_json'])
        rule = (budget.get('fast_path') or {}).get('chain_rule')
        blocks = {block: manifest['blocks'].get(block) or [] for block in ('setting', 'task')}
        v1_forms = ranking.block_forms(blocks)
        chaining_body = protocol_body(conn, run).get('citation_chaining') or {}
        frozen = chaining_body.get('admission_forms')
        if rule in NORMALISED_RULES:
            # Such a run is judged only by the forms it froze, and only when they match their digest; nothing is
            # rebuilt.
            if frozen is None or chaining.forms_digest(frozen) != chaining_body.get('admission_forms_sha256'):
                out[run['id']] = {'rule': rule, 'forms_unverified': True}
                continue
        elif frozen is None:  # a v1 run: the forms a later rule would have frozen, as a forecast only
            sq = output(conn, run['id'], 'search_query') or {}
            frozen = chaining.admission_forms(blocks, sq.get('vocabulary') or {'terms': []})
        links, written = {}, {}
        for row in conn.execute('SELECT linked_openalex_id, passed_filter, source_version_id FROM chain_links'
                                ' WHERE run_id = ?', (run['id'],)):
            links[row[0]] = max(links.get(row[0], 0), row[1])
            if row[2]:
                written[row[0]] = row[2]
        records, missing = chain_records(conn, path.parent / 'provider-payloads', run['id'])
        work_of = {svid: version['work_id'] for svid, version in manifest['versions'].items()}
        head_works = {work_of.get(head) for head in manifest.get('chain_heads') or ()}
        mismatches = rejected_v1 = 0
        v2_only, extra = set(), set()
        for oid, (title, abstract) in records.items():
            if oid not in links:
                continue
            v1 = chaining.passes(v1_forms, title, abstract)
            v2 = chaining.passes_v2(frozen, title, abstract)
            mismatches += (v2 if rule in NORMALISED_RULES else v1) != bool(links[oid])
            rejected_v1 += not v1
            if v2 and not v1:
                v2_only.add(oid)
                if links[oid] and work_of.get(written.get(oid)) in head_works:
                    extra.add(work_of[written[oid]])
        out[run['id']] = {'rule': rule, 'forms_unverified': False, 'linked_records': sum(o in links for o in records),
                          'mismatches': mismatches, 'missing_payloads': missing, 'rejected_by_v1': rejected_v1,
                          'v2_only': len(v2_only), 'extra_chained_works': len(extra)}
    return out


def main():
    total = {}
    for path in sys.argv[1:]:
        for run_id, row in check(path).items():
            total[f'{path}:{run_id}'] = row
            print(path, run_id, json.dumps(row))
    print(json.dumps({'runs': len(total), 'forms_unverified': sum(r['forms_unverified'] for r in total.values()),
                      'mismatches': sum(r.get('mismatches', 0) for r in total.values()),
                      'v2_only': sum(r.get('v2_only', 0) for r in total.values())}))


if __name__ == '__main__':
    main()
