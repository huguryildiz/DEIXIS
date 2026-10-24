"""Per-provider query syntax rules for compiled search queries.

Each rule follows a live probe recorded in the provider adapter's docstring. The query compiler builds every query to
pass them (D44); a query a provider would reject, silently misread or answer with zero records is never sent. The
OpenAlex-style checks for boolean queries (OR ambiguity, part and operator limits) also apply to bioRxiv (searched through
OpenAlex), IEEE Xplore, CORE and the inside of a Scopus field group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

NAMES = {"openalex": "OpenAlex", "semantic_scholar": "Semantic Scholar", "crossref": "Crossref", "arxiv": "arXiv",
         "pubmed": "PubMed",
         "biorxiv": "bioRxiv", "ieee_xplore": "IEEE Xplore", "scopus": "Scopus", "core": "CORE", "serpapi": "SerpApi"}
MAX_PLAIN_WORDS = 8
BOOLEAN_OPERATORS = ("AND", "OR", "NOT", "ANDNOT")
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
    from deixis.providers.registry import resolve_query_syntax

    try:
        declaration = resolve_query_syntax(provider_id, strict=False)
    except KeyError:
        return None
    return _boolean_part(declaration, query)


def syntax_issues(provider_id: str, query: str, endpoint: str | None = None) -> list[str]:
    from deixis.providers.registry import resolve_query_syntax

    return _syntax_issues(resolve_query_syntax(provider_id, endpoint, strict=False), query)


def _boolean_part(declaration: QuerySyntax, query: str) -> str | None:
    if declaration.boolean_checks:
        return query
    if declaration.kind == "field_group" and (match := SCOPUS_GROUP.match(query)) and balanced(match.group(2)):
        return match.group(2)
    return None


def _syntax_issues(declaration: QuerySyntax, query: str) -> list[str]:
    if declaration.kind == "bulk":
        return _bulk_issues(query)
    if declaration.kind == "plain":
        name = declaration.display_name
        issues = []
        if re.search(r'["()]', query) or re.search(r"\b(AND|OR|NOT)\b", query):
            issues.append(f"{name} ignores quotes, parentheses and AND/OR/NOT; write plain distinctive words")
        if len(query.split()) > MAX_PLAIN_WORDS:
            issues.append(f"more than {MAX_PLAIN_WORDS} words; {name} ranks records matching any word, so keep only distinctive words")
        return issues
    if not balanced(query):
        return [f"unbalanced quotes or parentheses{declaration.unbalanced_suffix}"]
    if declaration.extra_rules == "field_phrase":
        issues = []
        if re.search(r"\b[A-Za-z]+:", re.sub(r'"[^"]*"', "", query)):
            issues.append("CORE does not read a field prefix such as title: as a filter; write the query without field prefixes")
        if '"' in query and not re.search(r"\bAND\b", query):
            issues.append("CORE answers a quoted phrase without AND with an error; join the phrase with AND to a group of alternatives")
        return issues
    if declaration.kind == "field_group" and not SCOPUS_GROUP.match(query):
        return ["wrap the whole query in one field group such as TITLE-ABS-KEY(...)"]
    if declaration.kind == "scholar" and (re.search(r"[()]", query) or re.search(r"\b(AND|NOT)\b", query)):
        return ["Google Scholar reads no parentheses, AND or NOT; use quoted phrases, plain words and OR"]
    if declaration.kind == "fielded":
        return _arxiv_issues(query)
    return []


def _bulk_issues(query: str) -> list[str]:
    """Semantic Scholar's bulk query syntax as the compiler writes it (D93): quoted phrases and plain words, `|` inside
    a parenthesized group, `+` between groups. Its other operators (`-` negates, `*` is a prefix, `~` a distance) are
    never meant, so a term that would be read as one is refused rather than sent."""
    if not balanced(query):
        return ["unbalanced quotes or parentheses"]
    issues = []
    if any(re.search(r"[|+]", phrase) for phrase in re.findall(r'"([^"]*)"', query)):
        issues.append("a quoted phrase holds | or +, which bulk search reads as an operator")
    bare = re.sub(r'"[^"]*"', " ", query)
    if re.search(r"[*~]", bare) or re.search(r"(^|[\s(])-", bare):
        issues.append("a term would be read as a bulk operator (- negates, * is a prefix, ~ a distance); quote it")
    return issues


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


def query_issues(provider_id: str, query: str, endpoint: str | None = None) -> list[str]:
    """Every rule one provider query must pass: its syntax, then the OpenAlex-style boolean checks where they apply.

    `endpoint` is the one an sw query names (D93); a query that names none is checked as it always was.
    """
    from deixis.providers.registry import resolve_query_syntax

    return resolve_query_syntax(provider_id, endpoint, strict=False).query_issues(query)


@dataclass(frozen=True)
class QuerySyntax:
    """Pure candidate rendering, prefix counts and rules; allocation belongs to the compiler.

    The resolver binds the plain-word display name from its connector. Other
    messages belong to kinds or explicit parameters, independent of that name.
    """

    kind: str = "boolean"
    operand_prefix: str = ""
    operand_suffix: str = ""
    wrapper: str = ""
    boolean_checks: bool = False
    unbalanced_suffix: str = ""
    extra_rules: str = ""
    display_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("boolean", "plain", "bulk", "scholar", "field_group", "fielded"):
            raise ValueError(f"unknown query syntax kind {self.kind!r}")
        if self.extra_rules not in ("", "field_phrase"):
            raise ValueError(f"unknown query extra_rules {self.extra_rules!r}")
        supported = {
            "boolean_checks": ("boolean",),
            "operand_prefix": ("boolean", "field_group", "fielded"),
            "operand_suffix": ("boolean", "field_group", "fielded"),
            "wrapper": ("field_group",),
            "extra_rules": ("boolean", "scholar", "field_group", "fielded"),
            "unbalanced_suffix": ("boolean", "scholar", "field_group", "fielded"),
        }
        for parameter, kinds in supported.items():
            if getattr(self, parameter) and self.kind not in kinds:
                raise ValueError(f"query syntax kind {self.kind!r} does not read {parameter}")

    def render(self, core: list[str], family: list[str], quoted: Callable[[str], str]) -> str:
        if self.kind == "bulk":
            return " + ".join(quoted(group[0]) if len(group) == 1 else "(" + " | ".join(quoted(t) for t in group) + ")"
                              for group in (core, family) if group)
        if self.kind == "plain":
            def words(text: str, seen: set[str]) -> list[str]:
                kept: dict[str, str] = {}
                for word in text.split():
                    if word not in BOOLEAN_OPERATORS and word.lower() not in seen:
                        kept.setdefault(word.lower(), word)
                return list(kept.values())

            core_words = words(core[0], set())
            family_words = words(family[0], {w.lower() for w in core_words}) if family else []
            cap = MAX_PLAIN_WORDS
            family_words = family_words[: max(1, cap - len(core_words))] if family_words else []
            return " ".join(core_words[: cap - len(family_words)] + family_words)
        if self.kind == "scholar":
            return " ".join([quoted(core[0]), *([" OR ".join(quoted(t) for t in family)] if family else [])])

        def group(terms: list[str]) -> str:
            operands = [f"{self.operand_prefix}{quoted(t)}{self.operand_suffix}" for t in terms]
            return operands[0] if len(operands) == 1 else "(" + " OR ".join(operands) + ")"

        text = " AND ".join(group(terms) for terms in (core, family) if terms)
        return f"{self.wrapper}({text})" if self.wrapper else text

    def written_counts(self, kept: list[list[str]]) -> list[int]:
        if self.kind == "plain":
            return [min(len(group), 1) for group in kept]
        if self.kind == "scholar":
            return [min(len(group), 1) if position == 0 else len(group) for position, group in enumerate(kept)]
        # Preserve the historical counts for a third block even though render
        # receives only two blocks. B3b characterizes, rather than corrects, it.
        return [len(group) for group in kept]

    def query_issues(self, query: str) -> list[str]:
        issues = _syntax_issues(self, query)
        boolean = _boolean_part(self, query)
        if boolean is None or issues:
            return issues
        if openalex_or_is_ambiguous(boolean):
            issues.append("OR alternatives beside other terms without parentheses")
        return issues + openalex_query_shape_issues(boolean)
