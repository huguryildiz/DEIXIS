"""SYNTHETIC B3b byte equality, declaration admission and bounded refusals."""

import ast
import inspect
import json
import os
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import httpx
import pytest

import query_baseline as baseline
from test_connector_boundary import provider_id_literals
from deixis.providers import contract, facade, query_compiler as compiler, query_rules as rules, registry

ROOT = Path(__file__).resolve().parents[2]
FROZEN = json.loads(baseline.BASELINE.read_text())


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", baseline.deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", baseline.deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", baseline.deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", baseline.deny_network)


def entry_id(entry):
    return f"{entry['function']}/{entry['provider']}/{entry['endpoint']}"


@pytest.mark.parametrize("entry", FROZEN["entries"], ids=entry_id)
def test_freeze_replay(entry):
    for input_id, output_id in baseline.samples(entry):
        arguments = FROZEN["inputs"][input_id]
        actual = baseline.invoke(entry["function"], entry["provider"], entry["endpoint"], arguments)
        assert baseline.serialized(actual) == baseline.serialized(FROZEN["outputs"][output_id]), (
            entry_id(entry), input_id, arguments)


def test_freeze_registry_coverage():
    baseline.coverage(FROZEN, historical=True)


def test_registration_without_freeze_fails_by_name(monkeypatch):
    monkeypatch.setitem(registry.CONNECTORS, "synthetic_missing_freeze",
                        replace(registry.CONNECTORS["openalex"], provider_id="synthetic_missing_freeze"))
    with pytest.raises(AssertionError, match="synthetic_missing_freeze"):
        baseline.coverage(FROZEN, historical=True)


def test_freeze_contains_required_classes():
    assert FROZEN["base_commit"] == "e19a7f7"
    assert baseline.BASELINE.stat().st_size < 4_000_000
    assert FROZEN["term_classes"] == baseline.TERMS
    assert len(FROZEN["length_boundaries"]) == 3 * (sum(1 + len(c.endpoints) for c in registry.CONNECTORS.values()) - 1)
    for entry in FROZEN["entries"]:
        if entry["function"] == "_render" and entry["provider"] in registry.CONNECTORS:
            lengths = {len(FROZEN["outputs"][o]) for _, o in baseline.samples(entry)
                       if isinstance(FROZEN["outputs"][o], str)}
            assert {299, 300, 301} <= lengths, entry_id(entry)
    for entry in FROZEN["undeclared"]:
        for _, output_id in baseline.samples(entry):
            expected = FROZEN["outputs"][output_id]
            assert not isinstance(expected, dict) or "raised" not in expected, entry_id(entry)


@pytest.mark.parametrize("provider", list(registry.CONNECTORS))
def test_declarations_complete(provider):
    connector = registry.CONNECTORS[provider]
    assert connector.display_name
    assert connector.query_syntax is not None
    for endpoint, descriptor in connector.endpoints.items():
        assert descriptor.query_syntax is not None, (provider, endpoint)
    endpoint = connector.sw_query.get("endpoint")
    assert endpoint is None or endpoint in connector.endpoints, (provider, endpoint)
    declaration = registry.resolve_query_syntax(provider)
    with pytest.raises(FrozenInstanceError):
        declaration.kind = "mutated"


def test_semantic_endpoint_uses_plain_queries_without_changing_keyword_syntax():
    assert registry.resolve_query_syntax("openalex", "semantic").kind == "plain"
    assert registry.resolve_query_syntax("openalex").kind == "boolean"
    groups = [["alpha", "beta"], ["gamma", "delta"]]
    rendered = facade.connectors()["openalex"].render_query(groups, "semantic")
    assert rendered.native_query == "alpha gamma"
    assert list(rendered.dropped) == ["beta", "delta"]
    assert compiler.fit_block_counts("openalex", groups, "semantic") == ("alpha gamma", [1, 1])
    assert rules.query_issues("openalex", "alpha gamma", "semantic") == []
    assert rules.query_issues("openalex", '"alpha" AND gamma', "semantic")


@pytest.mark.parametrize("kind", ["Plain", "bulk "])
def test_unknown_kind_refused_at_construction(kind):
    with pytest.raises(ValueError, match="unknown query syntax kind"):
        rules.QuerySyntax(kind)


def test_unknown_extra_rules_refused_at_construction():
    with pytest.raises(ValueError, match="unknown query extra_rules"):
        rules.QuerySyntax(extra_rules="field_phrases")


@pytest.mark.parametrize("parameter,value,kinds", [
    ("boolean_checks", True, ("plain", "bulk", "scholar", "field_group", "fielded")),
    ("operand_prefix", "abs:", ("plain", "bulk", "scholar")),
    ("operand_suffix", "[Title/Abstract]", ("plain", "bulk", "scholar")),
    ("wrapper", "TITLE-ABS-KEY", ("boolean", "plain", "bulk", "scholar", "fielded")),
    ("extra_rules", "field_phrase", ("plain", "bulk")),
    ("unbalanced_suffix", " suffix", ("plain", "bulk")),
], ids=lambda value: value if isinstance(value, str) else None)
def test_unread_parameter_refused_at_construction(parameter, value, kinds):
    for kind in kinds:
        with pytest.raises(ValueError, match=parameter):
            rules.QuerySyntax(kind, **{parameter: value})


def test_names_compatibility_and_plain_export():
    expected = [("openalex", "OpenAlex"), ("semantic_scholar", "Semantic Scholar"), ("crossref", "Crossref"),
                ("arxiv", "arXiv"), ("pubmed", "PubMed"), ("biorxiv", "bioRxiv"), ("ieee_xplore", "IEEE Xplore"),
                ("scopus", "Scopus"), ("core", "CORE"), ("serpapi", "SerpApi")]
    assert type(rules.NAMES) is dict
    assert list(rules.NAMES.items()) == expected
    assert all(registry.CONNECTORS[pid].display_name == name for pid, name in expected)
    assert compiler.PLAIN_PROVIDERS == ("semantic_scholar", "crossref")
    assert compiler.PLAIN_PROVIDERS == tuple(pid for pid, c in registry.CONNECTORS.items() if c.query_syntax.kind == "plain")


def test_names_is_not_a_policy_source(monkeypatch):
    before = [baseline.invoke(e["function"], e["provider"], e["endpoint"], FROZEN["inputs"][e["samples"][0]])
              for e in FROZEN["entries"] if e["function"] not in ("NAMES", "PLAIN_PROVIDERS")]
    monkeypatch.setattr(rules, "NAMES", {})
    after = [baseline.invoke(e["function"], e["provider"], e["endpoint"], FROZEN["inputs"][e["samples"][0]])
             for e in FROZEN["entries"] if e["function"] not in ("NAMES", "PLAIN_PROVIDERS")]
    assert before == after


def test_no_provider_branches_in_rules():
    source = inspect.getsource(rules)
    names = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "NAMES" for t in n.targets))
    assert [(line, value) for line, value in provider_id_literals(source)
            if not names.lineno <= line <= names.end_lineno] == []


def test_no_provider_branches_in_compiler():
    source = inspect.getsource(compiler)
    functions = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]
    pairs = set()
    for line, value in provider_id_literals(source):
        owner = next((f.name for f in functions if f.lineno <= line <= f.end_lineno), None)
        pairs.add((owner, value))
    # The SearchPlan v2 compiler's own provider branches went with it (clean start, slice 3a).
    assert pairs == set()


def test_no_provider_branches_in_facade():
    assert provider_id_literals(inspect.getsource(facade)) == []


def test_synthetic_registry_translation(monkeypatch):
    # New symbols are reached here so the old tree fails by test name, not collection.
    connector = replace(registry.CONNECTORS["openalex"], provider_id="synthetic_translation",
                        display_name="Synthetic Plain", query_syntax=rules.QuerySyntax("plain"),
                        sw_query={"endpoint": "extra"},
                        endpoints={"extra": registry.Endpoint("cursor", 10, query_syntax=rules.QuerySyntax("bulk"))})
    monkeypatch.setitem(registry.CONNECTORS, connector.provider_id, connector)
    assert connector.provider_id not in rules.NAMES
    vocabulary = baseline.vocabulary([["alpha", "beta"], ["gamma", "delta"]])
    for routed, endpoint, text, dropped in [(False, None, "alpha gamma", ["beta", "delta"]),
                                           (True, "extra", "(alpha | beta) + (gamma | delta)", [])]:
        (compiled,) = compiler.compile_block_queries(vocabulary, [connector.provider_id], 10, routed=routed)
        assert compiled["query_text"] == text
        assert compiled.get("endpoint") == endpoint
        assert compiled["dropped_terms"] == dropped
        assert rules.query_issues(connector.provider_id, text, endpoint) == []
        rendered = facade.connectors()[connector.provider_id].render_query([["alpha", "beta"], ["gamma", "delta"]], endpoint)
        assert rendered.native_query == text and list(rendered.dropped) == dropped
        assert facade.connectors()[connector.provider_id].query_issues(text, endpoint) == []
    expected = ["Synthetic Plain ignores quotes, parentheses and AND/OR/NOT; write plain distinctive words",
                "more than 8 words; Synthetic Plain ranks records matching any word, so keep only distinctive words"]
    assert rules.query_issues(connector.provider_id, '"one" AND two three four five six seven eight nine') == expected
    assert facade.connectors()[connector.provider_id].descriptor.display_name == "Synthetic Plain"
    monkeypatch.setitem(registry.CONNECTORS, connector.provider_id, replace(connector, display_name=None))
    assert facade.connectors()[connector.provider_id].descriptor.display_name == connector.provider_id


@pytest.mark.parametrize("endpoint", [None, "extra"])
def test_missing_declaration_fails_closed(monkeypatch, endpoint):
    connector = replace(registry.CONNECTORS["openalex"], provider_id="synthetic_missing_declaration",
                        display_name="Synthetic Missing", query_syntax=None if endpoint is None else rules.QuerySyntax(),
                        sw_query={} if endpoint is None else {"endpoint": endpoint},
                        endpoints={} if endpoint is None else {endpoint: registry.Endpoint("cursor", 10)})
    monkeypatch.setitem(registry.CONNECTORS, connector.provider_id, connector)
    with pytest.raises(contract.ContractViolation, match=connector.provider_id):
        compiler.compile_block_queries(baseline.vocabulary([["alpha"], ["beta"]]), [connector.provider_id], 1)
    for strict in (True, False):
        with pytest.raises(contract.ContractViolation, match=connector.provider_id) as exc:
            registry.resolve_query_syntax(connector.provider_id, endpoint, strict=strict)
        assert repr(endpoint) in str(exc.value)
    f = facade.connectors()[connector.provider_id]
    for method, argument in ((f.render_query, [["alpha"], ["beta"]]), (f.query_issues, "alpha")):
        with pytest.raises(contract.ContractViolation, match=connector.provider_id):
            method(argument, endpoint)


REFUSALS = [(entry, input_id) for entry in FROZEN["undeclared"] for input_id, _ in baseline.samples(entry)]


@pytest.mark.parametrize("entry,input_id", REFUSALS, ids=[entry_id(e) for e, _ in REFUSALS])
def test_named_refusals(entry, input_id):
    actual = baseline.invoke(entry["function"], entry["provider"], entry["endpoint"], FROZEN["inputs"][input_id])
    expected_type = "KeyError" if entry["provider"] == "unregistered" else "ContractViolation"
    assert isinstance(actual, dict) and actual.get("raised", {}).get("type") == expected_type
    name = entry["provider"] if expected_type == "KeyError" else entry["endpoint"]
    assert name in actual["raised"]["message"]


@pytest.mark.parametrize("provider,endpoint", [(pid, e) for pid, connector in registry.CONNECTORS.items()
                                             for e in ("bulk", "nope") if e not in connector.endpoints]
                         + [("unregistered", None)])
def test_shared_allocator_refuses(provider, endpoint):
    exception = KeyError if provider == "unregistered" else contract.ContractViolation
    name = provider if endpoint is None else endpoint
    with pytest.raises(exception, match=name):
        compiler.fit_block_counts(provider, [["alpha"], ["beta"]], endpoint)


@pytest.mark.parametrize("first", ["query_rules", "query_compiler", "registry", "facade"])
def test_import_order(first, tmp_path):
    code = f'''
import importlib, socket, httpx
def forbidden(*args, **kwargs):
    raise AssertionError("network/DNS during query import test")
socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
httpx.HTTPTransport.handle_request = forbidden
httpx.AsyncHTTPTransport.handle_async_request = forbidden
importlib.import_module("deixis.providers.{first}")
from deixis.providers import query_rules, query_compiler, registry, facade
assert registry.resolve_query_syntax("openalex") is not None
assert query_rules.query_issues("openalex", "alpha AND beta") == []
vocabulary = {{"terms": [{{"block": b, "root": t, "phrase": t, "in_query": "phrase", "dropped": None}}
                        for b, t in [("setting", "alpha"), ("task", "beta")]]}}
assert query_compiler.compile_block_queries(vocabulary, ["openalex"], 1)[0]["query_text"] == "alpha AND beta"
assert facade.connectors()["openalex"].render_query([["alpha"], ["beta"]]).native_query == "alpha AND beta"
'''
    paths = [str(ROOT / "backend"), *(p for p in sys.path if "site-packages" in p)]
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
