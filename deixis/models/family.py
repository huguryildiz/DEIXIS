"""Which maker's family a model id belongs to, so a review can say whether it came from another one.

The design asks the reviewer to come from a separate model family. A connection does not say which family: one
connection can serve several makers' models (OpenRouter), and one maker's models reach the app through more than
one connection. So the family is read from the model id the call actually resolved to, through the table below.

An id the table does not recognise gives `unknown`, and `unknown` is never counted as a separate family: a review
is only called a separate-family review where both families are known and differ. The comparison never changes
which model runs; it only records what ran.
"""

from __future__ import annotations

FAMILY_RULE = "model_family_v1"

SEPARATE, SAME, UNKNOWN = "yes", "no", "unknown"

# Publisher part of a `publisher/model` id (OpenRouter, Ollama, LM Studio), mapped to the maker.
PUBLISHERS = {
    "openai": "openai", "anthropic": "anthropic", "google": "google", "google-deepmind": "google",
    "qwen": "alibaba", "alibaba": "alibaba", "deepseek": "deepseek", "deepseek-ai": "deepseek",
    "mistralai": "mistral", "mistral": "mistral", "meta": "meta", "meta-llama": "meta",
    "moonshotai": "moonshot", "moonshot": "moonshot", "zai-org": "zhipu", "zhipuai": "zhipu", "thudm": "zhipu",
    "x-ai": "xai", "xai": "xai", "microsoft": "microsoft", "nvidia": "nvidia", "cohere": "cohere",
    "ai21": "ai21", "xiaomi": "xiaomi",
}
# Leading words of a bare model id, longest match first when one is a prefix of another.
PREFIXES = (
    ("claude", "anthropic"),
    ("gpt-oss", "openai"), ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
    ("codex", "openai"), ("text-embedding", "openai"),
    ("gemini", "google"), ("gemma", "google"),
    ("qwen", "alibaba"), ("qwq", "alibaba"),
    ("deepseek", "deepseek"),
    ("mistral", "mistral"), ("magistral", "mistral"), ("ministral", "mistral"), ("codestral", "mistral"),
    ("llama", "meta"), ("muse-spark", "meta"), ("muse-glimmer", "meta"),
    ("kimi", "moonshot"), ("moonshot", "moonshot"),
    ("glm", "zhipu"), ("chatglm", "zhipu"),
    ("grok", "xai"),
    ("phi", "microsoft"),
    ("mimo", "xiaomi"),
    ("command", "cohere"),
    ("jamba", "ai21"),
)


def family(model_id: str | None) -> str | None:
    """The maker of this model id, or None when the table does not recognise it."""
    if not model_id:
        return None
    name = model_id.strip().lower()
    if "/" in name:
        publisher, _, rest = name.partition("/")
        # A publisher the table knows wins; an unknown one still leaves the model part to try.
        if publisher in PUBLISHERS:
            return PUBLISHERS[publisher]
        name = rest
    for prefix, maker in PREFIXES:
        if name.startswith(prefix):
            return maker
    return None


def separate_family(answer_model: str | None, reviewer_model: str | None) -> str:
    """Whether a review by `reviewer_model` reads an answer written by a model of another family.

    `unknown` when either id is unrecognised: an id nobody can place is not evidence of a separate family.
    """
    first, second = family(answer_model), family(reviewer_model)
    if first is None or second is None:
        return UNKNOWN
    return SEPARATE if first != second else SAME
