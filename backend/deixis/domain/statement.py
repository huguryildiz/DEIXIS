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
