"""The one rule for the sentence a statement research checks (reverse citation search): at most
`MAX_SENTENCE_CHARS` characters once trimmed. Research creation, a question revision of a statement research and a
check request all read it here, so no path stores or checks a longer sentence."""

from __future__ import annotations

import re

MAX_SENTENCE_CHARS = 600


class StatementTooLong(ValueError):
    """A statement research's sentence over the limit."""


def check_sentence(text: str) -> None:
    if len(text.strip()) > MAX_SENTENCE_CHARS:
        raise StatementTooLong(f"A sentence to check is at most {MAX_SENTENCE_CHARS} characters")


# ------------------------------------------------------------------------------------------- the support class (R4b)
# How a statement check presents one completed work (D108). The stored result stays V3's (`derive_result`, unchanged);
# the class is read from it and the stored parts by this function alone, and the view, counters, exports and screen
# take it from here. Rule 1 (revisions stored before R4b): the class is the result. Rule 2 (new revisions): a work
# counts as support only when at least one of its parts is `stated`; a `found_partial` whose parts are all `partly` or
# `not_stated` is `support_not_shown`, a class of its own and never a support class.
SUPPORT_RULE_VERSION = 2  # what a new revision stores (`statement_checks.support_rule_version`)
SUPPORT_RULE_VERSIONS = (1, 2)
SUPPORT_CLASSES = ("found_whole", "found_partial", "support_not_shown", "not_found_in_given")
SUPPORT = ("found_whole", "found_partial")


def support_class(result: str | None, parts: list[dict] | None, rule_version: int) -> str | None:
    """The class of one item from its stored result and parts under the revision's rule; None without a result (not
    done). A support result with no `stated` part reads as `support_not_shown` under rule 2 (also a `found_whole`
    with no parts, which `derive_result` never gives: the rule fails closed)."""
    if rule_version not in SUPPORT_RULE_VERSIONS:
        raise ValueError(f"unknown support rule version {rule_version!r}")
    if result is None:
        return None
    if rule_version >= 2 and result in SUPPORT and not any(part.get("assessment") == "stated" for part in parts or []):
        return "support_not_shown"
    return result


# --------------------------------------------------------------------------- the claim's field and named authors (R5)
# A sentence pasted from a paper often names neither its field nor anything a search can match on its own ("when two
# requests share one link, ..."). The person may type the field once; when they do not, the query model names it
# (`search_query.field`). Authors the sentence names ("Chandra et al.", "Erçetin and Gedik") become an author filter on
# the providers that take one. Both are read by code from the text typed; nothing here is a relevance verdict.
MAX_FIELD_CHARS = 80  # the length of one search term (`search-query.schema.json`)
MAX_FIELD_WORDS = 4  # the words of one search term (`contracts.SEARCH_QUERY_MAX_WORDS`), typed or the model's
MAX_AUTHOR_GROUPS = 3  # author queries one sentence may add

_NAME = r"[^\W\d_][\w'’-]*"
_ET_AL = re.compile(rf"\b({_NAME})\s+et\s+al\.?")
_PAIR = re.compile(rf"\b({_NAME})\s+(?:and|&)\s+({_NAME})\b(?!\s+et\s+al)")


class FieldRefused(ValueError):
    """A field, typed or the query model's, that cannot be a search term; `code` names the rule it breaks."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def check_field(text: str | None) -> str | None:
    """The field as it will be searched: single spaces, or None when there is none. Query syntax and an over-long
    field are refused rather than cleaned, as a key term is (`vocabulary.USER_TERM_SYNTAX`). The one rule for a typed
    field and the query model's, so the model can write back the field a person typed."""
    from deixis.domain.vocabulary import USER_TERM_SYNTAX

    field = " ".join((text or "").split())
    if not field:
        return None
    if len(field) > MAX_FIELD_CHARS or len(field.split()) > MAX_FIELD_WORDS:
        raise FieldRefused(f"A field is at most {MAX_FIELD_WORDS} words and {MAX_FIELD_CHARS} characters",
                           "query_term_too_long")
    if USER_TERM_SYNTAX.search(field):
        raise FieldRefused("A field holds no quotes, brackets, colons, | ~ ^ \\, leading + or -, or AND/OR/NOT",
                           "query_syntax_in_term")
    return field


def _capitalised(name: str) -> bool:
    return name[0].isupper()


def author_mentions(sentence: str, pairs: bool = True) -> list[tuple[int, int, list[str]]]:
    """Where the sentence names the authors of one work, in order: "X et al." is one work, and with `pairs` so is
    "X and Y" when both words are capitalised and no "et al." follows. Each mention is (start, end, surnames). Two
    capitalised terms ("Age and Fidelity", "Max-Weight and Lyapunov") read as a pair too: that only adds one narrow
    author query, which is why a pair never takes words out of the code query (`without_authors`)."""
    found = [(m.start(), m.end(), [m.group(1)]) for m in _ET_AL.finditer(sentence) if _capitalised(m.group(1))]
    if pairs:
        found += [(m.start(), m.end(), [m.group(1), m.group(2)]) for m in _PAIR.finditer(sentence)
                  if _capitalised(m.group(1)) and _capitalised(m.group(2))
                  and not any(start <= m.start() < end for start, end, _ in found)]
    return sorted(found)


def author_groups(sentence: str) -> list[list[str]]:
    """The surnames of each work the sentence names, at most `MAX_AUTHOR_GROUPS`, one list per work."""
    return [names for _, _, names in author_mentions(sentence)][:MAX_AUTHOR_GROUPS]


def without_authors(sentence: str, pairs: bool = False) -> str:
    """The sentence with its "X et al." mentions cut out (and its "X and Y" pairs with `pairs`), so no surname or
    "et al" becomes a search phrase. A cut leaves a comma, so the words on its two sides never join into one phrase."""
    out, last = [], 0
    for start, end, _ in author_mentions(sentence, pairs):
        out += [sentence[last:start], ","]
        last = end
    return "".join(out + [sentence[last:]])
