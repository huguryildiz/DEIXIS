"""The revision's English sentence for reranking and search.

The built-in model reads English only. Its query is the question when `detect_language` reads the question as English,
else the revision's English sentence, else nothing: the built-in arm is then off for the research and says why
(`english_question_missing`). The sentence is written once per revision, by the person (origin `user`, or `question`
for "The question is already in English") or, when the question is not English and has no key terms, by the model
step that translates it (origin `model`); code also picks the search words from it then, and OpenAlex's semantic
request sends the same text (`search.build_plan`). Every origin is read the same way here, and the person's sentence
outranks the model's because the model is asked only when none is stored. Gemini, OpenAI, Ollama and LM Studio take
the question as written; the sentence never goes to them. The language rule is `detect_language` as it is, with its
two known failure modes: a question in another language written without accents is read as English and embedded; an
English question full of accented names can be read as not English, and "The question is already in English" is the
way out.
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
    "english_question" (the stored sentence, whoever wrote it); None when the question is not English and no sentence
    is stored yet."""
    if is_english(scope["question"], scope.get("language_hint")):
        return scope["question"], "question"
    row = store.english_question(scope["research_id"], scope["revision"])
    return (row["text"], "english_question") if row else None
