"""B1 boundary and SYNTHETIC compatibility freeze; no live provider evidence."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict, is_dataclass
from pathlib import Path
from typing import get_args

import httpx
import pytest

import connector_baseline as baseline
from deixis.providers import contract as c, facade, registry, semantic_scholar

ROOT = Path(__file__).resolve().parents[2]
FROZEN = json.loads(baseline.BASELINE.read_text())


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", baseline.deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", baseline.deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", baseline.deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", baseline.deny_network)
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)


def test_cold_import_purity(tmp_path):
    code = '''
import socket, asyncio, os
def forbidden(*args, **kwargs):
    raise AssertionError("socket or DNS during cold import")
socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
from deixis.providers import contract, facade, registry
import httpx
async def run():
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        before = dict(os.environ)
        for f in facade.connectors().values():
            context = facade.context_for(registry.CONNECTORS[f.descriptor.provider_id], http, None)
            f.access(context)
            if "doi_lookup" not in f.descriptor.capabilities:
                outcome = await f.lookup(contract.LookupRequest(doi="10.9999/synthetic"), context)
                assert outcome.status == "unsupported" and outcome.outcome is None
        assert dict(os.environ) == before
asyncio.run(run())
'''
    # -S excludes sitecustomize; explicitly provide only package and dependency paths.
    paths = [str(ROOT), *(p for p in sys.path if "site-packages" in p)]
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-S", "-c", code], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_local_purity_and_secrets(monkeypatch, memory_keychain):
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.setenv(connector.key_env, baseline.SYNTHETIC_KEY)
    before_env, before_keyring = dict(os.environ), dict(memory_keychain.items)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            for f in facade.connectors().values():
                ctx = facade.context_for(registry.CONNECTORS[f.descriptor.provider_id], http, None)
                state = f.access(ctx)
                for value in (repr(f.descriptor), str(asdict(f.descriptor)), repr(state), str(asdict(state)), repr(ctx)):
                    assert baseline.SYNTHETIC_KEY not in value
                if "id_lookup" not in f.descriptor.capabilities:
                    result = await f.lookup(c.LookupRequest(provider_record_id="synthetic"), ctx)
                    assert result.status == "unsupported" and result.answer is None and result.outcome is None
    asyncio.run(run())
    assert dict(os.environ) == before_env and memory_keychain.items == before_keyring


INVALID_SEARCHES = [
    ("openalex", {"limit": value}) for value in (0, -1, True, "5")
] + [("openalex", {"query_text": None}), ("openalex", {"endpoint": "bulk"}),
     ("semantic_scholar", {"endpoint": "nope"}), ("semantic_scholar", {"options": {"sort": "x"}}),
     ("biorxiv", {"options": {"references": True}}), ("openalex", {"cursor": 2})]


@pytest.mark.parametrize("pid,kwargs", [pytest.param(*INVALID_SEARCHES[i], id=f"{INVALID_SEARCHES[i][0]}-kwargs{i}") for i in (0, 6)])
def test_search_validation_before_send(pid, kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            request = c.SearchRequest(**({"query_text": "synthetic", "limit": 1} | kwargs))
            with pytest.raises(c.ContractViolation):
                await facade.connectors()[pid].search(request, c.ConnectorContext(http, baseline.SYNTHETIC_KEY, None))
    asyncio.run(run())


@pytest.mark.provider_pacing
@pytest.mark.parametrize("case", [c for c in FROZEN["cases"] if c["id"] in {"openalex/default/malformed_200",
                                                                              "semantic_scholar/bulk/first_page"}], ids=lambda case: case["id"])
def test_baseline_equivalence(case):
    def without_error_prose(value):
        # D256 removes untrusted HTTP error bodies. Freeze every transport, quota,
        # paging and evidence field; error prose is tested for safety separately.
        if isinstance(value, dict):
            return {key: without_error_prose(item) for key, item in value.items()
                    if not (key == "error" and "http_status" in value)}
        if isinstance(value, list):
            return [without_error_prose(item) for item in value]
        return value
    assert without_error_prose(baseline.replay(case)) == without_error_prose(case["expected"])
    assert without_error_prose(baseline.replay(case, True)) == without_error_prose(case.get("facade_expected", case["expected"]))
    if "facade_expected" in case:
        assert case["shape"] == "unknown_endpoint"
        assert case["expected"]["requests"] == case["facade_expected"]["requests"] == []
        assert case["facade_expected"]["results"][0]["raised"]["type"] == "ContractViolation"


# Only source-owned dynamic values have exceptions. Every unresolved new expression fails closed.


def test_vocabulary_and_frozen_types():
    expected = {
        "SEARCH_STATUSES": {"completed", "zero_results", "not_configured", "auth_required", "entitlement_missing",
                            "rate_limited", "timeout", "parse_error", "failed"},
        "DELIVERY_CLASSES": {"before_send", "rejected_not_executed", "after_send_unknown"},
        "ERROR_KINDS": {"quota_exhausted", "rate_limited"},
        "PAGING_MODES": {"cursor", "offset", "single_page"},
        "TOTAL_SEMANTICS": {"reported", "estimated", "unknown"},
        "LOOKUP_STATUSES": {"found", "not_found", "failed", "unsupported"},
        "CAPABILITIES": {"search", "doi_lookup", "id_lookup", "citing_works"},
    }
    for name, values in expected.items():
        assert type(getattr(c, name)) is frozenset
        assert getattr(c, name) == values
    for alias, name in [(c.SearchStatus, "SEARCH_STATUSES"), (c.DeliveryClass, "DELIVERY_CLASSES"),
                        (c.ErrorKind, "ERROR_KINDS"), (c.PagingMode, "PAGING_MODES"),
                        (c.TotalSemantics, "TOTAL_SEMANTICS"), (c.LookupStatus, "LOOKUP_STATUSES"),
                        (c.Capability, "CAPABILITIES")]:
        assert set(get_args(alias)) == expected[name]
    for name in ("RetryPolicy", "OptionDescriptor", "EndpointDescriptor", "ConnectorDescriptor", "ConnectorContext",
                 "AccessState", "SearchRequest", "QueryRendering", "LookupRequest", "LookupOutcome"):
        cls = getattr(c, name)
        assert is_dataclass(cls) and cls.__dataclass_params__.frozen
    assert issubclass(c.ContractViolation, ValueError)
    assert c.SUPPORTED_CONTRACTS == {c.CONTRACT_ID}
    options = {"references": True}
    request = c.SearchRequest("x", 1, options=options)
    options["references"] = False
    assert request.options["references"] is True
    with pytest.raises(TypeError):
        request.options["references"] = False
    with pytest.raises(FrozenInstanceError):
        request.limit = 2
    for f in facade.connectors().values():
        assert isinstance(f, c.ScholarlyConnector)
