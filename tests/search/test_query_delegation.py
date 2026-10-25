"""SYNTHETIC B3b byte equality, declaration admission and bounded refusals."""

import json
import socket
from pathlib import Path

import httpx
import pytest

import query_baseline as baseline
from deixis.providers import facade, query_compiler as compiler, query_rules as rules, registry

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


@pytest.mark.parametrize("entry", [e for e in FROZEN["entries"] if entry_id(e) in {"render_query/openalex/None", "render_query/semantic_scholar/bulk"}],
                         ids=entry_id)
def test_freeze_replay(entry):
    for input_id, output_id in baseline.samples(entry):
        arguments = FROZEN["inputs"][input_id]
        actual = baseline.invoke(entry["function"], entry["provider"], entry["endpoint"], arguments)
        assert baseline.serialized(actual) == baseline.serialized(FROZEN["outputs"][output_id]), (
            entry_id(entry), input_id, arguments)


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


REFUSALS = [(entry, input_id) for entry in FROZEN["undeclared"] for input_id, _ in baseline.samples(entry)]


@pytest.mark.parametrize("entry,input_id", [r for r in REFUSALS if entry_id(r[0]) == "render_query/openalex/bulk"],
                         ids=[entry_id(e) for e, _ in REFUSALS if entry_id(e) == "render_query/openalex/bulk"])
def test_named_refusals(entry, input_id):
    actual = baseline.invoke(entry["function"], entry["provider"], entry["endpoint"], FROZEN["inputs"][input_id])
    expected_type = "KeyError" if entry["provider"] == "unregistered" else "ContractViolation"
    assert isinstance(actual, dict) and actual.get("raised", {}).get("type") == expected_type
    name = entry["provider"] if expected_type == "KeyError" else entry["endpoint"]
    assert name in actual["raised"]["message"]
