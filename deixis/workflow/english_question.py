"""The query text the built-in embedding model reads (slice 21, D103, SW8.6).

The built-in model reads English only. Its query is the question when `detect_language` reads the question as English,
else the English sentence the person saved for this scope revision, else nothing: the built-in arm is then off for the
research and says why (`english_question_missing`). Gemini, OpenAI, Ollama and LM Studio take the question as written;
the sentence never goes to them. The language rule is `detect_language` as it is, with its two known failure modes: a
question in another language written without accents is read as English and embedded; an English question full of
accented names can be read as not English, and "The question is already in English" is the way out.
"""

from __future__ import annotations

import hashlib
from typing import Any

from deixis.domain.vocabulary import detect_language

MAX_CHARS = 500
MISSING = "english_question_missing"


def is_english(text: str, language_hint: str | None = None) -> bool:
    return detect_language(text, language_hint) == "en"


def embedding_query(store: Any, scope: dict[str, Any]) -> tuple[str, str] | None:
    """(text, origin) the built-in model embeds as the query of this revision: origin "question" or
    "english_question"; None when the question is not English and no sentence was saved."""
    if is_english(scope["question"], scope.get("language_hint")):
        return scope["question"], "question"
    row = store.english_question(scope["research_id"], scope["revision"])
    return (row["text"], "english_question") if row else None


def query_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()
