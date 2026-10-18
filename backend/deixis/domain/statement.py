"""The one rule for the sentence a statement research checks (reverse citation search): at most
`MAX_SENTENCE_CHARS` characters once trimmed. Research creation, a question revision of a statement research and a
check request all read it here, so no path stores or checks a longer sentence."""

from __future__ import annotations

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
