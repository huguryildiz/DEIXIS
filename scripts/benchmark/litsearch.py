"""LitSearch recall benchmark (Ajith et al., EMNLP 2024, arXiv 2407.18940): the computer-science check next to BioASQ.

Gold sets are the `corpusids` (Semantic Scholar corpus ids) of the 597 ML/NLP queries. Each gold paper is resolved
once to its DOIs, arXiv id, OpenAlex works and title; a system's ranked records are matched to it by OpenAlex id, then
DOI, then normalized title, so a preprint and its published version both count. Gold papers that never resolve stay in
the denominator and are reported, never dropped.
"""
from __future__ import annotations

try:
    from .bioasq import DEPTHS, macro, norm_title, paired_bootstrap, sample
    from .common import doi as norm_doi
except ImportError:
    from bioasq import DEPTHS, macro, norm_title, paired_bootstrap, sample
    from common import doi as norm_doi


YEAR = 2024  # the dataset's release year; later records cannot be gold and are dropped before cutting at k


def load(rows):
    """Questions from the dataset's `query` rows, with stable ids (row order) and deduplicated gold corpus ids."""
    return [{'id': f'ls{i:03d}', 'body': r['query'], 'query_set': r.get('query_set'),
             'specificity': r.get('specificity'), 'quality': r.get('quality'), 'year': YEAR,
             'gold': [str(c) for c in dict.fromkeys(r['corpusids'])]} for i, r in enumerate(rows)]


def gold_dois(external_ids):
    """Every DOI a Semantic Scholar `externalIds` record implies: the publisher DOI and arXiv's own DataCite DOI."""
    ids = external_ids or {}
    out = [norm_doi(ids['DOI'])] if ids.get('DOI') else []
    if ids.get('ArXiv'):
        out.append(f"10.48550/arxiv.{ids['ArXiv']}".casefold())
    return list(dict.fromkeys(d for d in out if d))


def openalex_short(value):
    return str(value).rstrip('/').rsplit('/', 1)[-1].upper() if value else None


def matched(gold_meta, records):
    """Gold corpus ids found in `records`, each with the field that matched."""
    works = {openalex_short(r['openalex']) for r in records if r.get('openalex')}
    dois = {norm_doi(r['doi']) for r in records if r.get('doi')}
    titles = {norm_title(r['title']) for r in records if r.get('title')}
    found = {}
    for cid, meta in gold_meta.items():
        if works & {openalex_short(w) for w in meta.get('openalex') or []}:
            found[cid] = 'openalex'
        elif dois & set(meta.get('dois') or []):
            found[cid] = 'doi'
        elif meta.get('title') and norm_title(meta['title']) in titles:
            found[cid] = 'title'
    return found


def recall(question, records, gold_meta, depths=DEPTHS):
    """{k: recall} for one question; records are in rank order and already time-filtered."""
    meta = {c: gold_meta.get(c, {}) for c in question['gold']}
    return {k: len(matched(meta, records[:k])) / len(meta) for k in depths}


def route_breakdown(questions, rows, gold_meta, top=400):
    """Where DEIXIS's gold papers came from: per gold paper its rank in the pool and the routes that brought it.

    A retrieved gold paper counts once per route (keyword, semantic, chain) and once under `only_<route>` when that
    route alone brought it. A gold paper outside the pool is split by whether OpenAlex has it and has its abstract.
    """
    out = {'gold': 0, 'in_pool': 0, f'in_top_{top}': 0, 'routes': {}, 'only': {},
           'never_retrieved': 0, 'never_in_openalex': 0, 'never_with_abstract': 0, 'never_unresolved': 0}
    for q in questions:
        row = rows.get(q['id'])
        if not row or row.get('error'):
            continue
        records = row['records']
        for cid in q['gold']:
            meta = gold_meta.get(cid, {})
            out['gold'] += 1
            rank = next((i for i, r in enumerate(records) if matched({cid: meta}, [r])), None)
            if rank is None:
                out['never_retrieved'] += 1
                if meta.get('openalex'):
                    out['never_in_openalex'] += 1
                    out['never_with_abstract'] += bool(meta.get('has_abstract'))
                else:
                    out['never_unresolved'] += 1
                continue
            out['in_pool'] += 1
            out[f'in_top_{top}'] += rank < top
            routes = sorted({route.split(':')[0] for route in records[rank].get('routes') or []}) or ['unknown']
            for route in routes:
                out['routes'][route] = out['routes'].get(route, 0) + 1
            if len(routes) == 1:
                out['only'][routes[0]] = out['only'].get(routes[0], 0) + 1
    return out
