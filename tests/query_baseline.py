"""SYNTHETIC query freeze on e19a7f7; capture explicitly before production edits.

PYTHONPATH=backend:. .venv/bin/python tests/query_baseline.py --write

The entries of the SearchPlan v2 compiler (`compile_queries`, `_terms`, `_fit`, `_compact_openalex`) were taken out
of the frozen file when that compiler was removed (clean start, slice 3a); every other entry is the e19a7f7 freeze.

Arguments and results are interned by their order-preserving JSON bytes to keep
the broad rule cross-product below 4 MB. No canonical/sorted conversion is used.
"""

import argparse
import json
import socket
from contextlib import ExitStack
from dataclasses import asdict, is_dataclass
from pathlib import Path
from unittest.mock import patch

import httpx

from deixis.providers import facade, query_compiler as compiler, query_rules as rules, registry

BASELINE = Path(__file__).parent / "fixtures/connectors/query_baseline.json"
TERMS = {
    "single": "alpha", "phrase": "body area networks", "hyphen": "on-body",
    "alphanumeric": "5G", "non_ascii": "naïve", "greek": "μ-wave",
    "star": "alpha*", "tilde": "alpha~", "pipe": "alpha|beta", "plus": "alpha+beta",
    "negative": "-alpha", "colon": "title:x", "apostrophe": "O'Brien",
    "boolean_upper": "AND", "boolean_lower": "or", "boolean_phrase": "rock and roll",
    "stopwords": "of the art", "medium": "m" * 90, "over_limit": "z" * 350,
}
HAND_TEXTS = [
    "", '"alpha', "(alpha", "alpha)", "title:x", '"body area networks"',
    "TITLE-ABS-KEY(alpha AND beta)", "TITLE(alpha)", "alpha AND beta", "TITLE-ABS-KEY((alpha)",
    "(alpha OR beta)", "alpha AND beta", "alpha NOT beta", "abs:alpha NOT abs:beta",
    "abs:alpha abs:beta", "alpha", "abs:alpha (abs:beta OR abs:gamma)",
    "alpha AND beta OR gamma", "alpha AND beta AND gamma", "alpha beta gamma",
    '"alpha|beta"', '"alpha+beta"', "alpha*", "alpha~", "-alpha", "(-alpha)",
    'title:x AND "alpha|beta" + -gamma*~', "(alpha AND NOT title:x)",
    "one two three four five six seven", "one two three four five six seven eight",
    "one two three four five six seven eight nine",
    '"alpha" OR beta AND gamma delta epsilon OR zeta AND eta AND theta',
    *[" OR ".join(f"w{i}" for i in range(n + 1)) for n in (4, 5, 6)],
    *[" OR ".join(f"abs:w{i}" for i in range(n + 1)) for n in (4, 5, 6)],
]


def json_value(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def serialized(value):
    return json.dumps(json_value(value), indent=2, ensure_ascii=False)


def deny_network(*args, **kwargs):
    raise AssertionError("network/DNS forbidden in query freeze")


def invoke(function, provider, endpoint, arguments):
    args, kwargs = arguments["args"], arguments["kwargs"]
    try:
        if function in ("render_query", "facade_query_issues", "display_name"):
            connector = facade.connectors()[provider]
            if function == "display_name":
                result = connector.descriptor.display_name
            else:
                method = connector.render_query if function == "render_query" else connector.query_issues
                result = method(*args, endpoint=endpoint, **kwargs)
        elif function in ("NAMES", "PLAIN_PROVIDERS"):
            result = rules.NAMES if function == "NAMES" else compiler.PLAIN_PROVIDERS
        else:
            module = rules if function in ("syntax_issues", "boolean_part", "query_issues") else compiler
            method = getattr(module, function)
            if function == "boolean_part":
                result = method(provider, *args, **kwargs)
            elif function in ("syntax_issues", "query_issues", "_render", "_rendered", "_fit_blocks"):
                result = method(provider, *args, endpoint=endpoint, **kwargs)
            else:
                result = method(*args, **kwargs)
        return json_value(result)
    except Exception as exc:
        return {"raised": {"type": type(exc).__name__, "message": str(exc)}}


def coverage(frozen, *, historical=False):
    required = {"_render", "_rendered", "_fit_blocks", "render_query", "syntax_issues",
                "boolean_part", "query_issues", "facade_query_issues", "compile_block_queries"}
    recorded = {(entry["function"], entry["provider"], entry["endpoint"]) for entry in frozen["entries"]}
    for pid, connector in registry.CONNECTORS.items():
        for endpoint in (None, *connector.endpoints):
            if historical and (pid, endpoint) == ("openalex", "semantic"):
                continue  # Added after the immutable e19a7f7 snapshot; tested separately.
            for function in sorted(required):
                assert (function, pid, endpoint) in recorded, f"{pid}/{endpoint}: missing {function}"


def samples(entry):
    """Alternating argument/result references, without redundant JSON brackets."""
    return zip(entry["samples"][::2], entry["samples"][1::2])


def pair_corpus():
    pairs = [([f"c{i}" for i in range(n)], [f"f{i}" for i in range(m)])
             for n, m in [(n, n - 1) for n in range(1, 9)] + [(9 - n, n) for n in range(1, 9)]]
    pairs += [([term], ["beta"]) for term in TERMS.values()]
    pairs += [(["Alpha", "alpha", "Alpha"], ["beta", "beta", "Beta"]),
              (["one two three four five six seven eight nine"], ["ten eleven"])]
    return pairs


def block_corpus(pairs):
    groups = [[core, family] if family else [core] for core, family in pairs]
    groups += [[[f"c{i}" for i in range(n)]] for n in range(1, 9)]
    groups += [[["alpha"], []], [[], ["beta"]], [["alpha"], ["beta"], ["gamma", "delta"]],
               [["alpha", "beta", "gamma", "delta"], ["e", "f", "g"]],
               [["x" * 140, "y" * 140], ["z" * 20, "w" * 20]]]
    return groups


def vocabulary(groups):
    return {"terms": [{"block": block, "root": term, "phrase": term, "in_query": "phrase", "dropped": None}
                      for block, group in zip(("setting", "task", "outcome"), groups) for term in group]}


def capture():
    inputs, outputs, input_ids, output_ids = [], [], {}, {}
    entries, undeclared, grouped = [], [], {}
    text_corpus = dict.fromkeys(HAND_TEXTS)

    def intern(value, pool, ids):
        key = serialized(value)
        if key not in ids:
            ids[key] = len(pool)
            pool.append(json_value(value))
        return ids[key]

    def record(function, provider, endpoint, args=(), kwargs=None, section="entries"):
        arguments = {"args": list(args), "kwargs": kwargs or {}}
        result = invoke(function, provider, endpoint, arguments)
        if section == "undeclared" and isinstance(result, dict) and "raised" in result:
            expected_type = "KeyError" if provider == "unregistered" else "ContractViolation"
            if result["raised"]["type"] == expected_type:
                section = "entries"
        key = (section, function, provider, endpoint)
        if key not in grouped:
            entry = {"function": function, "provider": provider, "endpoint": endpoint, "samples": []}
            grouped[key] = entry
            (entries if section == "entries" else undeclared).append(entry)
        grouped[key]["samples"].extend([intern(arguments, inputs, input_ids), intern(result, outputs, output_ids)])
        if function == "_render" and isinstance(result, str):
            text_corpus[result] = None
        if function == "_fit_blocks" and isinstance(result, list):
            text_corpus[result[0]] = None
        return result

    pairs = pair_corpus()
    groups = block_corpus(pairs)
    lengths = []
    for pid, connector in registry.CONNECTORS.items():
        record("display_name", pid, None)
        for endpoint in (None, *connector.endpoints):
            for core, family in pairs:
                record("_render", pid, endpoint, (core, family))
                record("_rendered", pid, endpoint, ([core, family],))
            for blocks in groups:
                record("_fit_blocks", pid, endpoint, (blocks,))
                record("render_query", pid, endpoint, (blocks,))
            for length in (299, 300, 301):
                # A single word has constant syntax overhead and never encounters a word cap.
                overhead = len(compiler._render(pid, ["x"], [], endpoint)) - 1
                blocks = [["x" * (length - overhead)]]
                result = record("_render", pid, endpoint, (blocks[0], []))
                assert len(result) == length, (pid, endpoint, length)
                lengths.append([pid, endpoint, length])
                record("_rendered", pid, endpoint, (blocks,))
                record("_fit_blocks", pid, endpoint, (blocks,))
                record("render_query", pid, endpoint, (blocks,))
        for endpoint in dict.fromkeys(("bulk", "nope")):
            if endpoint in connector.endpoints:
                continue
            for function, args in [("_render", (["alpha", "beta"], ["gamma", "delta"])),
                                   ("_rendered", ([["alpha", "beta"], ["gamma", "delta"]],)),
                                   ("_fit_blocks", ([["alpha", "beta"], ["gamma", "delta"]],)),
                                   ("render_query", ([["alpha", "beta"], ["gamma", "delta"]],)),
                                   ("facade_query_issues", ("alpha AND beta",))]:
                record(function, pid, endpoint, args, section="undeclared")

    for function, args in [("_render", (["alpha"], ["beta"])), ("_rendered", ([["alpha"], ["beta"]],))]:
        record(function, "unregistered", None, args, section="undeclared")
    record("_fit_blocks", "unregistered", None, ([["alpha"], ["beta"]],))
    for pid, connector in registry.CONNECTORS.items():
        for endpoint in dict.fromkeys((None, *connector.endpoints, "bulk", "nope")):
            for text in text_corpus:
                for function in ("syntax_issues", "boolean_part", "query_issues"):
                    record(function, pid, endpoint, (text,))
                if endpoint is None or endpoint in connector.endpoints:
                    record("facade_query_issues", pid, endpoint, (text,))
    for text in text_corpus:
        for function in ("syntax_issues", "boolean_part", "query_issues"):
            record(function, "unregistered", None, (text,))

    providers = list(registry.CONNECTORS)
    provider_lists = [providers, providers[::-1], providers + providers[:2], providers[:3],
                      ["crossref", "serpapi"], ["semantic_scholar", "arxiv", "serpapi"]]
    vocabs = [vocabulary([["alpha", "beta"], ["gamma", "delta"], ["outcome"]]),
              vocabulary([]), vocabulary([[], ["task"]]), vocabulary([["alpha", "alpha"], ["beta"]]),
              {"terms": [{"block": "setting", "root": "root", "phrase": "root phrase", "in_query": "root", "dropped": None},
                         {"block": "task", "root": "task", "phrase": "task phrase", "in_query": "phrase", "dropped": None},
                         {"block": "setting", "root": "ignored", "phrase": "ignored", "in_query": "phrase", "dropped": "user"}]}]
    for vocab in vocabs:
        for selected in provider_lists:
            for limit in (0, 1, 3, 100):
                for routed in (False, True):
                    record("compile_block_queries", None, None, (vocab, selected, limit), {"routed": routed})
        for pid, connector in registry.CONNECTORS.items():
            for endpoint in (None, *connector.endpoints):
                record("compile_block_queries", pid, endpoint, (vocab, [pid], 100), {"routed": endpoint is not None})
    synonyms = [*TERMS.values(), "Alpha", "alpha", "Alpha", '"quoted"', "(parenthesized)", "[bracketed]", "", "   "]
    for synonym in synonyms:
        record("quoted", None, None, (synonym,))
    record("NAMES", None, None)
    record("PLAIN_PROVIDERS", None, None)
    result = {"base_commit": "e19a7f7", "synthetic": True, "enumeration": "deterministic; no randomness",
              "term_classes": TERMS, "length_boundaries": lengths, "rule_texts": list(text_corpus),
              "inputs": inputs, "outputs": outputs, "entries": entries, "undeclared": undeclared}
    coverage(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    with ExitStack() as stack:
        for target, attribute in ((socket.socket, "connect"), (socket, "getaddrinfo"),
                                  (httpx.HTTPTransport, "handle_request"),
                                  (httpx.AsyncHTTPTransport, "handle_async_request")):
            stack.enter_context(patch.object(target, attribute, deny_network))
        frozen = capture()
    data = serialized(frozen) + "\n"
    assert len(data.encode()) < 4_000_000, len(data.encode())
    BASELINE.write_text(data)
    print(f"wrote {sum(len(e['samples']) // 2 for section in ('entries', 'undeclared') for e in frozen[section])} samples; {len(data.encode())} bytes")
