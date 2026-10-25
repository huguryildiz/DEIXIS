"""SYNTHETIC helpers: drive the fast-path search slots and one fast chain request over hand-built inputs.

Shared contracts (record writing, continuation refusal, transport accounting, suppression) that the old search
round and old chain requests used to carry run here through the fast path's own entry points. No live provider.
"""

from deixis.workflow.search import fast_chain, search as fast_search


def plan(queries, *, cap=1000, page_size=100):
    """A frozen fast-path search plan with keyword slots only: no semantic sentence and no Semantic Scholar slot.

    The shape follows `fast_search.build_plan`; the queries go into the keyword slots as given, in order."""
    return {"version": 1, "semantic": {"provider_id": "openalex", "endpoint": "semantic", "query_text": None,
                                      "limit": 50, "query_origin": "SYNTHETIC"},
            "keywords": [{"index": i, "query": q} for i, q in enumerate(queries)], "keyword_cap": cap,
            "page_size": page_size, "order": "page_then_query", "s2_bulk": None, "s2_bulk_index": None,
            "s2_reserved": 0, "dropped": [], "expansion": "fast_path_frozen_plan"}


async def search(flow, run, queries, retry_failed=False, **sizes):
    """Run the keyword slots of `queries` through `fast_search.execute`; returns its (pause reason, detail) or None."""
    scope = flow.store.scope(run["research_id"])
    return await fast_search.execute(flow, run, scope, plan(queries, **sizes), retry_failed)


def chain_spec(direction="forward", *, index=0, cites="W9", batch=None, links=(), limit=None):
    backward = direction == "backward"
    return {"direction": direction, "batch": list(batch or []) if backward else None,
            "cites": None if backward else cites, "links": list(links),
            "limit": limit if limit is not None else (len(batch or []) if backward else 25),
            "index": index, "key": f"chain:fast:{index}"}


def chain_round(flow, run, forms=None):
    flow._chain_forms = lambda *args: forms or {"task": ["synthetic"]}
    round_ = fast_chain.Round(flow, run, flow.store.scope(run["research_id"]), {"terms": [], "outcome_terms": []})
    round_.admit.set()
    return round_


async def chain(flow, run, spec=None, forms=None):
    """Send one fast chain request and write its reply, as the round's writer does; returns the stored step."""
    spec = spec or chain_spec()
    round_ = chain_round(flow, run, forms)
    await round_.fetch(spec)
    round_.write_reply(spec)
    return flow.store.existing_step(run["id"], spec["key"])
