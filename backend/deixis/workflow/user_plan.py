"""A search plan the person edited (UI parity S23a, F18).

The person sees the plan a run searched (the model-written query, the code's query beside it, the criterion and the
providers), changes the words of each block, the criterion or the optional providers, and saves it. Saving is a new
scope revision that carries the plan (`scope_revisions.user_plan_json`); nothing earlier is edited. A discovery run
of that revision does what it always does up to the planning calls (question words, seed checks, OpenAlex term
counts), then builds what `vocabulary_labels`, `search_query` and `criterion_proposal` would have given from the plan
by code (origin `user`), records the approval as `user_edited` and freezes the protocol with the plan in it, before
its first request that fetches search results. The plan's words alone make the keyword queries and the ranking and
screening blocks: the code's query from the question is not searched beside them, so a removed word stays removed.

Rules this module holds:
- The plan is checked with the SearchQuery term rules (`contracts.check_user_search_plan`); a plan that breaks one
  is refused with the reasons and never stored.
- OpenAlex is required. Semantic Scholar, Crossref and Scopus may be left out: such a provider gets no search request
  and no abstract lookup request in any run of the revision, and the record says `excluded_by_user`. Full-text
  acquisition is not covered by this choice: Crossref is still asked for a work's PDF links (`NOT_COVERED`).
- The plan's criterion carries the population and comparator mapping of the criterion it started from, so an
  unchanged criterion keeps the comparator guard; a mapping whose part the person changed is dropped, never invented.
- The plan's criterion is the criterion of its own revision only (`store.frozen_criterion` with the revision): a
  plan with no criterion is never given an older one, and a later revision never takes the plan's back.
- A revision made by another route (a new question, other seeds) carries no plan over.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.domain import canonical, contracts
from deixis.providers import query_compiler
from deixis.providers.registry import CONNECTORS
from deixis.workflow import criterion as criterion_rules
from deixis.workflow.vocabulary import GATE_BLOCKS

ORIGIN = "user"
APPROVAL_MODE = "user_edited"
EXCLUDED = "excluded_by_user"
REQUIRED = contracts.USER_PLAN_REQUIRED_PROVIDER
OPTIONAL = ("semantic_scholar", "crossref", "scopus")
# Requests a left-out provider still gets, outside the search and the abstract lookups: full-text acquisition asks
# Crossref for a work's PDF links (`documents/acquisition.py`, a required route).
NOT_COVERED = {"crossref": ["pdf_link_lookup"]}
SCHEMA_VERSION = contracts.SCHEMA_VERSIONS["UserSearchPlan"]


class PlanRefused(ValueError):
    """The plan breaks a rule; `issues` says which, in the contract's words."""

    def __init__(self, code: str, issues: list[dict[str, str]]):
        super().__init__(code)
        self.code, self.issues = code, issues


def of(scope: dict[str, Any]) -> dict[str, Any] | None:
    """The plan this scope revision was saved with, or None for a revision no person planned."""
    return scope.get("user_plan")


def excluded(scope: dict[str, Any]) -> list[str]:
    """The optional providers the person left out of this revision's plan; none without a plan."""
    plan = of(scope)
    return [provider for provider in OPTIONAL if provider not in plan["providers"]] if plan else []


def plan_sha256(plan: dict[str, Any]) -> str:
    return canonical.sha256_hex(plan)


def check(plan: Any) -> dict[str, Any]:
    """The plan when every rule holds; otherwise PlanRefused with every issue found."""
    report = contracts.check_user_search_plan(plan)
    if not report.ok:
        raise PlanRefused("invalid_search_plan", [{"code": i.code, "path": i.path, "message": i.message}
                                                  for i in report.issues])
    return plan


# ---- the plan as the shapes the model steps would have left ---------------------------------------------------

def answer(plan: dict[str, Any]) -> dict[str, Any]:
    """The plan's terms in the SearchQuery answer shape `search_query.check` counts. The person gives no kind and no
    reason for a term, and none is invented: `kind` is null and `why` empty."""
    return {**{block: [{"term": row["term"], "kind": None, "why": ""} for row in plan[block]] for block in GATE_BLOCKS},
            **{f"{block}_backup": [{"term": row["term"]} for row in plan[f"{block}_backup"]] for block in GATE_BLOCKS}}


def record(plan: dict[str, Any]) -> dict[str, Any]:
    """What the vocabulary keeps of where its query came from, in place of a model call's record: no StepInput, no
    model and no package, because no model was asked."""
    return {"status": "ready", "origin": ORIGIN, "attempts": [], "step_input_id": None, "resolved_model": None,
            "skill_package_hash": None, "answer": answer(plan), "plan_sha256": plan_sha256(plan)}


def criterion(plan: dict[str, Any], sought_terms: list[str]) -> dict[str, Any] | None:
    """The plan's criterion in the shape `criterion.consensus` returns, or None when the person set none. Its phrases
    become cue phrases of the part they were written under; no run voted on them, so `runs` is empty."""
    given = plan["criterion"]
    if given is None:
        return None
    cues: dict[str, str] = {}
    for part in given["parts"]:
        for phrase in part["phrases"]:
            if (normalized := criterion_rules.norm(phrase)) and normalized not in cues:
                cues[normalized] = part["name"]
    words = sorted({w for word in given["exclusion_title_words"] if (w := criterion_rules.norm(word))})
    proposal = {"criterion": given["text"], "parts": given["parts"]}
    return {
        "criterion": given["text"],
        "parts": [{"name": part["name"], "definition": part["definition"], "role": part["role"]}
                  for part in given["parts"]],
        "cue_phrases": [{"phrase": phrase, "part": cues[phrase], "runs": []} for phrase in sorted(cues)],
        "exclusion_title_words": words,
        "dropped_exclusion_title_words": [],
        "base_run": None,
        "runs_ok": [],
        "sought_term_in_criterion": criterion_rules._names_sought(proposal, sought_terms),
        **applicable_elements(given),
    }


def applicable_elements(given: dict[str, Any]) -> dict[str, Any]:
    """The question elements of a plan's criterion that still apply, in the shape `criterion.consensus` writes them.

    An element is carried from the frozen criterion the plan started from, never written by the person (`save`
    refuses one no frozen protocol of the question holds). It still applies only while its part keeps its name, its
    definition and its core role: a part the person changed no longer says what the element pointed at, so the
    element is dropped, and with it a required role no remaining element holds. What `adjudication.mark_comparator`
    reads therefore names the comparator part only while that part is the one the question's comparator was found in.
    """
    parts = {criterion_rules.norm(part["name"]): part for part in given["parts"]}
    kept = [element for element in given["question_elements"]
            if (part := parts.get(criterion_rules.norm(element["part"]))) is not None
            and part["role"] == "core" and part["definition"] == element["part_definition"]]
    roles = {element["role"] for element in kept}
    return {"question_elements": sorted(({"role": e["role"], "words": e["words"], "part": e["part"]} for e in kept),
                                        key=lambda e: e["role"]),
            "required_roles": [role for role in given["required_roles"] if role in roles]}


def _frozen_elements(body: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    """A frozen body's question elements with the definition of the part each names, and its required roles."""
    if body.get("user_plan"):
        given = body["user_plan"]["plan"]["criterion"] or {}
        return list(given.get("question_elements") or []), list(given.get("required_roles") or [])
    origin = body.get("criterion_origin") or {}
    definitions = {criterion_rules.norm(part["name"]): part["definition"] for part in body.get("criterion_parts") or []}
    elements = [{"role": e["role"], "words": e["words"], "part": e["part"],
                 "part_definition": definitions[criterion_rules.norm(e["part"])]}
                for e in origin.get("question_elements") or [] if criterion_rules.norm(e["part"]) in definitions]
    return elements, list(origin.get("required_roles") or [])


def approval(digest: str, plan: dict[str, Any], exclusion_words: list[str]) -> dict[str, Any]:
    """The approval record of a run that searched the person's plan: the person approved it by saving it."""
    return {"mode": APPROVAL_MODE, "approved_by": ORIGIN, "asked": False, "edited": True, "proposal_hash": digest,
            "plan_sha256": plan_sha256(plan), "term_edits": None, "criterion_edited": None,
            "exclusion_word_in_question": exclusion_words}


def protocol_block(scope: dict[str, Any]) -> dict[str, Any] | None:
    """The plan's provenance in the protocol body, beside the query record: the plan as saved, its digest, the scope
    revision that holds it and the providers it leaves out."""
    plan = of(scope)
    if plan is None:
        return None
    return {"origin": ORIGIN, "scope_revision": scope["revision"], "plan": plan, "plan_sha256": plan_sha256(plan),
            "excluded_providers": excluded(scope)}


# ---- the panel's view -------------------------------------------------------------------------------------------

def _base_protocol(store: Any, research_id: str, scope: dict[str, Any]) -> dict[str, Any] | None:
    """The newest frozen protocol of this research for the same question and steering, the current revision's first."""
    rows = store.conn.execute(
        "SELECT scope_revision, protocol_revision, body_json FROM protocol_records WHERE research_id = ?"
        " ORDER BY scope_revision = ? DESC, protocol_revision DESC", (research_id, scope["revision"])).fetchall()
    for row in rows:
        body = json.loads(row["body_json"])
        if body.get("question") == scope["question"] and body.get("steering") == scope.get("steering"):
            return {"scope_revision": row["scope_revision"], "protocol_revision": row["protocol_revision"], "body": body}
    return None


def _queried_form(term: dict[str, Any]) -> str:
    return term["root"] if term.get("in_query") == "root" else term["phrase"]


def from_protocol(body: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    """The plan a frozen protocol searched, in the plan's shape, for the person to start from. A model-written query
    gives its searched terms and its unused backups; a code query its searched forms. Such a plan may break a term
    rule (a code term can be longer than four words); the view reports the issues and saving refuses it until fixed."""
    if body.get("user_plan"):
        return body["user_plan"]["plan"]
    terms = [t for t in body.get("vocabulary") or [] if not t["dropped"]]
    blocks = {block: list(dict.fromkeys(_queried_form(t) for t in terms if t["block"] == block)) for block in GATE_BLOCKS}
    searched = {criterion_rules.norm(form) for forms in blocks.values() for form in forms}
    query = body.get("search_query") or {}
    model_answer = query.get("answer") if query.get("status") == "ready" else None
    backups = {block: [row["term"] for row in (model_answer or {}).get(f"{block}_backup", [])
                       if criterion_rules.norm(row["term"]) not in searched] for block in GATE_BLOCKS}
    criterion = None
    if body.get("inclusion_criterion"):
        cues: dict[str, list[str]] = {}
        for cue in body.get("cue_phrases") or []:
            if cue.get("part"):
                cues.setdefault(cue["part"], []).append(cue["phrase"])
        criterion = {"text": body["inclusion_criterion"],
                     "parts": [{"name": part["name"], "definition": part["definition"],
                                "role": part.get("role", "core"), "phrases": cues.get(part["name"], [])[:15]}
                               for part in body.get("criterion_parts") or []],
                     "exclusion_title_words": list(body.get("exclusion_title_words") or [])}
        # The population and comparator mapping travels with the criterion, so an unchanged criterion keeps
        # the comparator guard (`adjudication.mark_comparator`, D109) when the person saves the plan.
        criterion["question_elements"], criterion["required_roles"] = _frozen_elements(body)
    return {"schema_version": SCHEMA_VERSION,
            **{block: [{"term": form} for form in blocks[block]] for block in GATE_BLOCKS},
            **{f"{block}_backup": [{"term": term} for term in backups[block]] for block in GATE_BLOCKS},
            "criterion": criterion,
            "providers": [REQUIRED] + [p for p in OPTIONAL if p in scope["providers"]]}


def _queries(body: dict[str, Any]) -> list[dict[str, Any]]:
    """The OpenAlex keyword queries a protocol froze, numbered as the panel shows them."""
    rows = [q for q in body.get("compiled_queries") or [] if q["provider_id"] == "openalex"]
    return [{"label": f"Query {n}", "origin": q.get("origin") or "code", "query_text": q["query_text"],
             "compiled_from": "protocol"} for n, q in enumerate(rows, 1)]


def _preview(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The keyword query a saved plan will search, compiled by the existing block compiler from its words before any
    count is read. A preview: the run compiles it again, and a backup only replaces a term once OpenAlex counts that
    term at zero. The code's query from the question is not searched beside a plan, so there is no second query."""
    terms = [{"phrase": criterion_rules.norm(row["term"]), "block": block, "in_query": "phrase", "dropped": None,
              "root": criterion_rules.norm(row["term"])} for block in GATE_BLOCKS for row in plan[block]]
    compiled = query_compiler.compile_block_queries({"terms": terms}, [REQUIRED], 1)
    return [{"label": f"Query {n}", "origin": ORIGIN, "query_text": q["query_text"], "compiled_from": "plan_words"}
            for n, q in enumerate(compiled, 1)]


def _unsearched(plan: dict[str, Any], body: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The words of `plan`, as the plan writes them, that the protocol's frozen search records as not searched."""
    words = (body.get("fast_path_search") or {}).get("words")
    if words is None:
        return None
    left = {(w["block"], criterion_rules.norm(w["term"])): w["left_out"] for w in words if w["searched"] is False}
    return [{"block": block, "term": row["term"], "left_out": left[(block, criterion_rules.norm(row["term"]))]}
            for block in GATE_BLOCKS for row in plan[block] if (block, criterion_rules.norm(row["term"])) in left]


def view(store: Any, research_id: str) -> dict[str, Any]:
    """The plan the panel shows: the current revision's own plan when the person saved one, otherwise the plan the
    newest run of the same question searched (model-made or code-made), or none before any run froze one. Query 1 and
    Query 2 are read-only strings; the person edits words, never query text."""
    research = store.research(research_id)
    scope = store.scope(research_id)
    base = _base_protocol(store, research_id, scope)
    plan, origin, queries, preview = of(scope), None, [], False
    if plan is not None:
        origin = ORIGIN
        searched = base is not None and base["scope_revision"] == scope["revision"]
        preview = not searched
        queries = _preview(plan) if preview else _queries(base["body"])
    elif base is not None:
        body = base["body"]
        plan = from_protocol(body, scope)
        origin = (ORIGIN if (body.get("approval") or {}).get("mode") == APPROVAL_MODE
                  else "model" if (body.get("search_query") or {}).get("status") == "ready" else "code")
        queries = _queries(body)
    issues = contracts.check_user_search_plan(plan).issues if plan is not None else []
    # The plan's words the frozen search did not carry (D26), only for a plan a protocol froze: a preview has none.
    unsearched = (_unsearched(plan, base["body"]) if plan is not None and base is not None and not preview else None)
    return {
        "research_id": research_id, "expected_version": research["version"], "scope_revision": scope["revision"],
        "editable": scope["source_scope"] != "attached",
        "origin": origin,
        "based_on": ({"scope_revision": base["scope_revision"], "protocol_revision": base["protocol_revision"]}
                     if base else None),
        "plan": plan,
        "issues": [{"code": i.code, "path": i.path, "message": i.message} for i in issues],
        "queries": queries,
        # True while the saved plan has not run: the queries are a preview, compiled again when the run starts.
        "queries_preview": preview,
        # Each word of `plan` no query the frozen plan sent carried, with why (`fast_search.plan_words`); null when the
        # protocol recorded no such list (frozen before it, or no protocol yet).
        "unsearched": unsearched,
        "providers": [{"provider_id": provider, "required": provider == REQUIRED,
                       "checked": plan is not None and provider in plan["providers"],
                       "in_scope": provider in scope["providers"],
                       "configured": CONNECTORS[provider].access_mode() != "not_configured",
                       # What this provider is still asked for when it is left out (Crossref: PDF links).
                       "not_covered": NOT_COVERED.get(provider, [])}
                      for provider in (REQUIRED, *OPTIONAL)],
    }


def save(store: Any, research_id: str, expected_version: int, plan: Any) -> int:
    """Check the plan and save it as the research's next scope revision; returns that revision. Refused for a
    research that does not search (attached files only) and for a checked provider outside the research's scope."""
    check(plan)
    scope = store.scope(research_id)
    if scope["source_scope"] == "attached":
        raise PlanRefused("no_academic_search", [{"code": "no_academic_search", "path": "/",
                                                  "message": "Academic search is not part of this research's source scope"}])
    outside = [p for p in plan["providers"] if p not in scope["providers"]]
    if outside:
        raise PlanRefused("invalid_search_plan", [{"code": "provider_not_in_scope", "path": "/providers",
                                                   "message": f"{p} is not among this research's sources"}
                                                  for p in outside])
    invented = _invented_elements(store, research_id, scope, plan["criterion"])
    if invented:
        raise PlanRefused("invalid_search_plan", invented)
    return store.save_user_plan(research_id, expected_version, plan)


def _invented_elements(store: Any, research_id: str, scope: dict[str, Any],
                       given: dict[str, Any] | None) -> list[dict[str, str]]:
    """Question elements and required roles no frozen protocol of this question holds. A mapping is carried from a
    criterion a model proposed and the run froze, with the part text it was found in; the person cannot add one."""
    if given is None:
        return []
    held: set[tuple[str, str, str, str]] = set()
    roles: set[str] = set()
    for row in store.conn.execute("SELECT body_json FROM protocol_records WHERE research_id = ?", (research_id,)):
        body = json.loads(row[0])
        if body.get("question") != scope["question"] or body.get("steering") != scope.get("steering"):
            continue
        elements, required = _frozen_elements(body)
        held |= {(e["role"], e["words"], criterion_rules.norm(e["part"]), e["part_definition"]) for e in elements}
        roles |= set(required)
    issues = [{"code": "question_element_not_frozen", "path": f"/criterion/question_elements/{index}",
               "message": "Only a population or comparator a frozen criterion of this question recorded can be kept"}
              for index, e in enumerate(given["question_elements"])
              if (e["role"], e["words"], criterion_rules.norm(e["part"]), e["part_definition"]) not in held]
    issues += [{"code": "required_role_not_frozen", "path": "/criterion/required_roles",
                "message": f"{role} was not a required role of a frozen criterion of this question"}
               for role in given["required_roles"] if role not in roles]
    return issues
