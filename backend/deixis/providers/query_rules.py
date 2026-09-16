"""Per-provider query syntax rules for compiled search queries.

Each rule follows a live probe recorded in the provider adapter's docstring. The query compiler builds every query to
pass them (D44); a query a provider would reject, silently misread or answer with zero records is never sent. The
OpenAlex-style checks for boolean queries (OR ambiguity, part and operator limits) also apply to bioRxiv (searched through
OpenAlex), IEEE Xplore, CORE and the inside of a Scopus field group.
"""

from __future__ import annotations

import re

NAMES = {"openalex": "OpenAlex", "semantic_scholar": "Semantic Scholar", "crossref": "Crossref", "arxiv": "arXiv",
         "pubmed": "PubMed",
         "biorxiv": "bioRxiv", "ieee_xplore": "IEEE Xplore", "scopus": "Scopus", "core": "CORE", "serpapi": "SerpApi"}
MAX_PLAIN_WORDS = 8
MAX_ARXIV_OPERATORS = 5
SCOPUS_GROUP = re.compile(r"^\s*(TITLE-ABS-KEY|TITLE|ABS|KEY)\((.*)\)\s*$", re.DOTALL)
ARXIV_OPERAND = re.compile(r'^(ti|abs|all|au|cat|jr|co):("[^"]+"|[^\s"()]+)$')


def balanced(query: str) -> bool:
    if query.count('"') % 2:
        return False
    depth = 0
    for char in re.sub(r'"[^"]*"', "", query):
        depth += (char == "(") - (char == ")")
        if depth < 0:
            return False
    return depth == 0


def boolean_part(provider_id: str, query: str) -> str | None:
    """The part of a query that OpenAlex-style boolean checks apply to, or None."""
    if provider_id in ("openalex", "biorxiv", "ieee_xplore", "core"):
        return query
    if provider_id == "scopus" and (match := SCOPUS_GROUP.match(query)) and balanced(match.group(2)):
        return match.group(2)
    return None


def syntax_issues(provider_id: str, query: str) -> list[str]:
    name = NAMES[provider_id]
    if provider_id in ("semantic_scholar", "crossref"):
        issues = []
        if re.search(r'["()]', query) or re.search(r"\b(AND|OR|NOT)\b", query):
            issues.append(f"{name} ignores quotes, parentheses and AND/OR/NOT; write plain distinctive words")
        if len(query.split()) > MAX_PLAIN_WORDS:
            issues.append(f"more than {MAX_PLAIN_WORDS} words; {name} ranks records matching any word, so keep only distinctive words")
        return issues
    if not balanced(query):
        silently = {"ieee_xplore": " (it returns zero records instead of an error)",
                    "core": " (it returns other records instead of an error)"}.get(provider_id, "")
        return [f"unbalanced quotes or parentheses{silently}"]
    if provider_id == "core":
        issues = []
        if re.search(r"\b[A-Za-z]+:", re.sub(r'"[^"]*"', "", query)):
            issues.append("CORE does not read a field prefix such as title: as a filter; write the query without field prefixes")
        if '"' in query and not re.search(r"\bAND\b", query):
            issues.append("CORE answers a quoted phrase without AND with an error; join the phrase with AND to a group of alternatives")
        return issues
    if provider_id == "scopus" and not SCOPUS_GROUP.match(query):
        return ["wrap the whole query in one field group such as TITLE-ABS-KEY(...)"]
    if provider_id == "serpapi" and (re.search(r"[()]", query) or re.search(r"\b(AND|NOT)\b", query)):
        return ["Google Scholar reads no parentheses, AND or NOT; use quoted phrases, plain words and OR"]
    if provider_id == "arxiv":
        return _arxiv_issues(query)
    return []


def _arxiv_issues(query: str) -> list[str]:
    tokens = re.findall(r'[A-Za-z]+:"[^"]*"|"[^"]*"|\(|\)|[^\s()]+', query)
    issues: list[str] = []
    operators, previous = 0, "start"
    for token in tokens:
        if token in ("AND", "OR", "ANDNOT"):
            operators, previous = operators + 1, "operator"
        elif token == "NOT":
            issues.append("arXiv excludes terms with ANDNOT, not NOT")
            previous = "operator"
        elif token == "(":
            if previous in ("operand", "close"):
                issues.append("join terms and groups with AND, OR or ANDNOT; arXiv does not read adjacency as AND")
            previous = "open"
        elif token == ")":
            previous = "close"
        else:
            if not ARXIV_OPERAND.match(token):
                issues.append(f"{token!r} needs a field prefix such as abs: or ti:, with a multiword phrase quoted after it")
            if previous in ("operand", "close"):
                issues.append("join terms and groups with AND, OR or ANDNOT; arXiv does not read adjacency as AND")
            previous = "operand"
    if operators > MAX_ARXIV_OPERATORS:
        issues.append(f"more than {MAX_ARXIV_OPERATORS} AND/OR/ANDNOT operators")
    return list(dict.fromkeys(issues))


def openalex_or_is_ambiguous(query: str) -> bool:
    """True when OpenAlex would silently mis-read OR in the query.

    Probed live on 2026-09-14: `"molecular communication" optimization OR "operations research"` and
    `"molecular communication" AND optimization OR scheduling` both returned exactly the 3,392 works of the phrase
    alone, while `"molecular communication" AND (optimization OR scheduling)` returned 308. Plain adjacency without OR
    behaves as AND. So OR is accepted only when, at its nesting level, it is the sole operator, and a group containing
    OR is joined to its neighbours with explicit operators.
    """
    tokens = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', query)
    levels: list[dict[str, bool]] = [{"or": False, "other": False, "implicit": False}]
    previous = None  # "operand", "operator" or "open"
    closed_or = False  # the operand just before is a group containing OR
    for token in tokens:
        adjacent = previous == "operand"  # implicit AND with the previous operand
        if token == "(":
            if adjacent:
                if closed_or:
                    return True
                levels[-1]["other"] = True
            levels.append({"or": False, "other": False, "implicit": adjacent})
            previous, closed_or = "open", False
        elif token == ")":
            if len(levels) == 1:
                return True  # unbalanced
            inner = levels.pop()
            if inner["or"] and (inner["other"] or inner["implicit"]):
                return True
            previous, closed_or = "operand", inner["or"]
        elif token in ("AND", "NOT", "OR"):
            levels[-1]["or" if token == "OR" else "other"] = True
            previous, closed_or = "operator", False
        else:
            if adjacent:
                if closed_or:
                    return True
                levels[-1]["other"] = True
            previous, closed_or = "operand", False
    return len(levels) != 1 or (levels[0]["or"] and levels[0]["other"])


OPENALEX_MAX_OPERATORS = 5  # OpenAlex throttles queries with more boolean operators


def openalex_query_shape_issues(query: str) -> list[str]:
    """Structural limits for one OpenAlex title-and-abstract query.

    Every unquoted word and every AND-joined part is required, and results are read in relevance order, so a query that
    requires many parts matches few records (live 2026-09-14: `molecular communication resource allocation scheduling
    routing optimization` returned 4 works and none of 22 user-known papers).
    """
    tokens = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', query)
    issues = []
    if sum(t in ("AND", "OR", "NOT") for t in tokens) > OPENALEX_MAX_OPERATORS:
        issues.append(f"more than {OPENALEX_MAX_OPERATORS} AND/OR/NOT operators")
    depth, top_operands, top_or, run, longest = 0, 0, False, 0, 0
    for token in tokens:
        if token == "(":
            top_operands += depth == 0
            depth, run = depth + 1, 0
        elif token == ")":
            depth, run = max(0, depth - 1), 0
        elif token in ("AND", "OR", "NOT"):
            top_or = top_or or (depth == 0 and token == "OR")
            run = 0
        else:
            top_operands += depth == 0
            run = 0 if token.startswith('"') else run + 1
            longest = max(longest, run)
    if (1 if top_or else top_operands) > 2:
        issues.append("more than two required parts; keep the quoted core phrase and one parenthesized group of alternatives")
    if longest >= 3:
        issues.append("three or more unquoted words in a row are all required; quote the phrase or put alternatives in an OR group")
    return issues


def query_issues(provider_id: str, query: str) -> list[str]:
    """Every rule one provider query must pass: its syntax, then the OpenAlex-style boolean checks where they apply."""
    issues = syntax_issues(provider_id, query)
    boolean = boolean_part(provider_id, query)
    if boolean is None or issues:
        return issues
    if openalex_or_is_ambiguous(boolean):
        issues.append("OR alternatives beside other terms without parentheses")
    return issues + openalex_query_shape_issues(boolean)
