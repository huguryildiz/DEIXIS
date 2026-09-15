"""Per-provider query syntax rules for search plans.

Each rule follows a live probe recorded in the provider adapter's docstring. A query a provider would reject, silently
misread or answer with zero records goes back to the model for repair instead of being run. The OpenAlex-style checks
for boolean queries (OR ambiguity, part and operator limits) live in `contracts` and also apply to bioRxiv (searched
through OpenAlex), IEEE Xplore, CORE and the inside of a Scopus field group.
"""

from __future__ import annotations

import re

NAMES = {"openalex": "OpenAlex", "semantic_scholar": "Semantic Scholar", "crossref": "Crossref", "arxiv": "arXiv",
         "pubmed": "PubMed",
         "biorxiv": "bioRxiv", "ieee_xplore": "IEEE Xplore", "scopus": "Scopus", "core": "CORE", "serpapi": "SerpApi"}
EXAMPLES = {
    "openalex": '"molecular communication" AND ("resource allocation" OR scheduling)',
    "biorxiv": '"quorum sensing" AND (optimization OR "optimal control")',
    "ieee_xplore": '"molecular communication" AND ("resource allocation" OR scheduling)',
    "core": '"molecular communication" AND ("resource allocation" OR scheduling)',
    "scopus": 'TITLE-ABS-KEY("molecular communication" AND ("resource allocation" OR scheduling))',
    "arxiv": 'abs:"molecular communication" AND (abs:scheduling OR abs:allocation)',
    "semantic_scholar": "molecular communication resource allocation",
    "crossref": "molecular communication scheduling",
    "pubmed": '"molecular communication" AND (optimization OR scheduling)',
    "serpapi": '"molecular communication" scheduling OR "resource allocation"',
}
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
