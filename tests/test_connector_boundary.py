"""B1 boundary and SYNTHETIC compatibility freeze; no live provider evidence."""

import ast
import asyncio
import importlib
import inspect
import json
import os
import socket
import subprocess
import sys
from collections import Counter
from dataclasses import FrozenInstanceError, asdict, fields, is_dataclass, replace
from pathlib import Path
from typing import get_args

import httpx
import pytest

import connector_baseline as baseline
from deixis.providers import contract as c, facade, common, registry, query_compiler, pacing, arxiv, semantic_scholar

ROOT = Path(__file__).resolve().parents[1]
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


def test_search_request_hash_excludes_options_without_changing_equality():
    request = c.SearchRequest("x", 1, options={"references": True})
    equivalent = c.SearchRequest("x", 1, options={"references": True})
    different = c.SearchRequest("x", 1, options={"references": False})
    assert request == equivalent and request != different
    assert hash(request) == hash(equivalent) == hash(different)
    assert {request: "found"}[equivalent] == "found"


@pytest.mark.parametrize("change", [{"contract_id": "unsupported"}, {"provider_id": "other"}, {"adapter_revision": registry.CONNECTORS["openalex"].adapter_revision + 1}])
def test_constructor_refuses_incompatible_descriptor(change):
    connector = registry.CONNECTORS["openalex"]
    with pytest.raises(c.ContractViolation):
        facade.CompatibilityConnector(connector, replace(facade.descriptor_for(connector, 0), **change))


def test_descriptors_frozen():
    assert baseline.descriptors() == FROZEN["descriptors"]


def test_descriptors_registry_and_module_policy():
    facades = facade.connectors()
    assert list(facades) == list(registry.CONNECTORS)
    enum = json.loads((ROOT / "contracts/research/common.schema.json").read_text())["$defs"]["provider_id"]["enum"]
    assert set(facades) == set(enum)
    defaults = inspect.signature(common.send).parameters
    for order, (pid, f) in enumerate(facades.items()):
        d = f.descriptor
        assert d.order == order and d.display_name == facade.query_rules.NAMES[pid]
        assert d.contract_id in c.SUPPORTED_CONTRACTS and d.query_rules_revision == c.QUERY_RULES_REVISION
        assert d.adapter_revision == registry.CONNECTORS[pid].adapter_revision
        assert d.capabilities == {"search"} and d.capabilities <= c.CAPABILITIES
        assert d.endpoints[0].endpoint_id is None
        assert len({e.endpoint_id for e in d.endpoints}) == len(d.endpoints)
        for endpoint in d.endpoints:
            reading = registry.reading({"provider_id": pid, "endpoint": endpoint.endpoint_id})
            assert (endpoint.paging, endpoint.max_results, endpoint.max_reachable) == (
                reading.paging, reading.max_results, reading.max_reachable)
            assert endpoint.paging in c.PAGING_MODES and endpoint.total in c.TOTAL_SEMANTICS
            assert all(o.value_type in {"bool", "str"} and o.values is None for o in endpoint.options)
            r = endpoint.retry
            expected = {name: defaults[name].default for name in ("rate_limit_statuses", "unstated_wait", "timeout")}
            expected.update(max_retry_wait=common.MAX_RETRY_WAIT_SECONDS,
                            max_rate_limit_retries=common.MAX_RATE_LIMIT_RETRIES, min_interval=0.0, shared_gate=None)
            assert asdict(r) == expected | registry.CONNECTORS[pid].retry
    assert facades["biorxiv"].descriptor.lineage == "openalex"
    assert facades["biorxiv"].descriptor.host == facades["openalex"].descriptor.host
    for names in facade.UNBOUND_HELPERS.values():
        for name in names:
            module, attr = name.split(".")
            assert callable(getattr(importlib.import_module("deixis.providers." + module), attr))


def test_registry_retry_overrides_match_source_policy():
    assert registry.CONNECTORS["arxiv"].retry == {
        "rate_limit_statuses": arxiv.RATE_LIMIT_STATUSES,
        "unstated_wait": arxiv.UNSTATED_RATE_LIMIT_WAIT,
        "max_retry_wait": arxiv.MAX_RATE_LIMIT_WAIT,
        "min_interval": arxiv.MIN_INTERVAL_SECONDS,
    }
    assert registry.CONNECTORS["semantic_scholar"].retry == {
        "unstated_wait": semantic_scholar.UNSTATED_RATE_LIMIT_WAIT,
        "min_interval": pacing.SEMANTIC_SCHOLAR_PACER.interval_seconds,
        "shared_gate": "SEMANTIC_SCHOLAR_PACER",
    }
    tree = ast.parse(inspect.getsource(registry.serpapi))
    timeouts = [kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "send"
                for kw in node.keywords if kw.arg == "timeout" and isinstance(kw.value, ast.Constant)]
    assert len(timeouts) == 1
    assert registry.CONNECTORS["serpapi"].retry == {"timeout": timeouts[0]}


def provider_id_literals(source):
    return [(node.lineno, node.value) for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in registry.CONNECTORS]


def test_facade_has_no_provider_id_literals():
    assert provider_id_literals(inspect.getsource(facade)) == []
    for pid in registry.CONNECTORS:
        assert provider_id_literals(f'provider_id = {pid!r}') == [(1, pid)]


def test_synthetic_connector_retry_needs_no_facade_branch(monkeypatch):
    synthetic = replace(registry.CONNECTORS["openalex"], provider_id="synthetic", retry={"timeout": 47.0})
    monkeypatch.setitem(registry.CONNECTORS, "synthetic", synthetic)
    monkeypatch.setitem(facade.query_rules.NAMES, "synthetic", "SYNTHETIC")
    retry = facade.connectors()["synthetic"].descriptor.endpoints[0].retry
    assert retry.timeout == 47.0
    assert retry.unstated_wait == inspect.signature(common.send).parameters["unstated_wait"].default


@pytest.mark.parametrize("agent", [None, "DEIXIS synthetic agent", "python-httpx/custom"])
def test_recorded_headers_normalize_only_default_httpx_agent(agent):
    headers = {"x-synthetic": "preserve 1.2.3"}
    if agent is not None:
        headers["user-agent"] = agent
    with httpx.Client(transport=httpx.MockTransport(baseline.deny_network)) as client:
        request = client.build_request("GET", "https://synthetic.invalid", headers=headers)
        recorded = dict(baseline.recorded_request(request)["headers"])
        assert recorded["user-agent"] == ("python-httpx/<version>" if agent is None else agent)
        for name, value in request.headers.items():
            if name != "user-agent":
                assert recorded[name] == value


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
            outcome = await f.lookup(contract.LookupRequest(doi="10.9999/synthetic"), context)
            assert outcome.status == "unsupported" and outcome.outcome is None
        assert dict(os.environ) == before
asyncio.run(run())
'''
    # -S excludes sitecustomize; explicitly provide only package and dependency paths.
    paths = [str(ROOT / "backend"), *(p for p in sys.path if "site-packages" in p)]
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
                result = await f.lookup(c.LookupRequest(provider_record_id="synthetic"), ctx)
                assert result.status == "unsupported" and result.answer is None and result.outcome is None
    asyncio.run(run())
    assert dict(os.environ) == before_env and memory_keychain.items == before_keyring


@pytest.mark.parametrize("pid", list(registry.CONNECTORS))
@pytest.mark.parametrize("key", [None, "", baseline.SYNTHETIC_KEY])
def test_access_matches_registry(pid, key, monkeypatch):
    connector = registry.CONNECTORS[pid]
    if connector.key_env and key is not None:
        monkeypatch.setenv(connector.key_env, key)
    with _null_http() as http:
        context = facade.context_for(connector, http, None)
        assert facade.CompatibilityConnector(connector).access(context).access_mode == connector.access_mode()


def _null_http():
    # Access does not use the injected client; close it through its asynchronous owner.
    from contextlib import contextmanager

    @contextmanager
    def context():
        client = httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network))
        try:
            yield client
        finally:
            asyncio.run(client.aclose())
    return context()


INVALID_SEARCHES = [
    ("openalex", {"limit": value}) for value in (0, -1, True, "5")
] + [("openalex", {"query_text": None}), ("openalex", {"endpoint": "bulk"}),
     ("semantic_scholar", {"endpoint": "nope"}), ("semantic_scholar", {"options": {"sort": "x"}}),
     ("biorxiv", {"options": {"references": True}}), ("openalex", {"cursor": 2})]


@pytest.mark.parametrize("pid,kwargs", INVALID_SEARCHES)
def test_search_validation_before_send(pid, kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            request = c.SearchRequest(**({"query_text": "synthetic", "limit": 1} | kwargs))
            with pytest.raises(c.ContractViolation):
                await facade.connectors()[pid].search(request, c.ConnectorContext(http, baseline.SYNTHETIC_KEY, None))
    asyncio.run(run())


@pytest.mark.parametrize("kwargs", [{}, {"doi": "a", "provider_record_id": "b"}, {"doi": ""}, {"provider_record_id": 2}])
def test_lookup_validation_before_send(kwargs):
    with pytest.raises(c.ContractViolation):
        c.LookupRequest(**kwargs)


@pytest.mark.parametrize("pid", list(registry.CONNECTORS))
@pytest.mark.parametrize("lookup_request", [c.LookupRequest(doi="10.9999/synthetic"), c.LookupRequest(provider_record_id="synthetic")])
def test_lookup_unsupported_without_search_outcome(pid, lookup_request):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            result = await facade.connectors()[pid].lookup(lookup_request, c.ConnectorContext(http, None, None))
            assert result.status == "unsupported" and result.outcome is None and result.answer is None
            assert not isinstance(result, common.SearchOutcome)
    asyncio.run(run())


def test_baseline_coverage():
    baseline.coverage(FROZEN["cases"])
    assert FROZEN["contract_id"] == c.CONTRACT_ID and FROZEN["query_rules_revision"] == c.QUERY_RULES_REVISION
    assert FROZEN["base_commit"] == "5990b02"
    assert baseline.SYNTHETIC_KEY not in baseline.BASELINE.read_text()
    assert {case["id"] for case in FROZEN["cases"]}.__len__() == len(FROZEN["cases"])
    for case in FROZEN["cases"]:
        assert case["adapter_revision"] == registry.CONNECTORS[case["provider_id"]].adapter_revision
        for result in case["expected"]["results"]:
            if "outcome" in result:
                outcome = result["outcome"]
                assert outcome["status"] in c.SEARCH_STATUSES
                assert outcome["delivery_class"] is None or outcome["delivery_class"] in c.DELIVERY_CLASSES
                assert outcome["error_kind"] is None or outcome["error_kind"] in c.ERROR_KINDS


def test_new_registry_pair_requires_fixtures(monkeypatch):
    synthetic = replace(registry.CONNECTORS["openalex"], provider_id="synthetic")
    monkeypatch.setattr(registry, "CONNECTORS", dict(registry.CONNECTORS, synthetic=synthetic))
    with pytest.raises(AssertionError, match="synthetic"):
        baseline.coverage(FROZEN["cases"])
    monkeypatch.setitem(facade.query_rules.NAMES, "synthetic", "SYNTHETIC")
    assert "synthetic" in facade.connectors()


@pytest.mark.parametrize("case", [case for case in FROZEN["cases"]
                                 if case["shape"] in {"non_json_200", "efetch_malformed"}], ids=lambda case: case["id"])
def test_unreadable_body_shapes_are_required(case):
    assert case["script"][-1]["status"] == 200
    if case["shape"] == "non_json_200":
        assert len(case["script"]) == 1 and case["script"][0]["text"] == "<SYNTHETIC not json"
    else:
        assert case["provider_id"] == "pubmed" and len(case["script"]) == 2
        assert case["script"][0]["body_file"] == "pubmed-1.json"
        assert case["script"][1]["url"] == registry.pubmed.FETCH_URL
    with pytest.raises(AssertionError, match=case["shape"]):
        baseline.coverage([other for other in FROZEN["cases"] if other["id"] != case["id"]])


@pytest.mark.parametrize("case", FROZEN["cases"], ids=lambda case: case["id"])
def test_baseline_equivalence(case):
    assert baseline.replay(case) == case["expected"]
    assert baseline.replay(case, True) == case.get("facade_expected", case["expected"])
    if "facade_expected" in case:
        assert case["shape"] == "unknown_endpoint"
        assert case["expected"]["requests"] == case["facade_expected"]["requests"] == []
        assert case["facade_expected"]["results"][0]["raised"]["type"] == "ContractViolation"


@pytest.mark.parametrize("entry", FROZEN["rendering"], ids=lambda e: f"{e['provider_id']}/{e['endpoint_id']}/{len(e['groups'][0])}")
def test_rendering_baseline(entry):
    f = facade.connectors()[entry["provider_id"]]
    rendering = f.render_query(entry["groups"], entry["endpoint_id"])
    if entry["fitted"] is None:
        assert rendering is None
    else:
        assert [rendering.native_query, list(rendering.dropped)] == entry["fitted"]
        assert rendering.rule_revision == c.QUERY_RULES_REVISION
        assert Counter(rendering.retained + rendering.dropped) == Counter(t for g in entry["groups"] for t in g)


@pytest.mark.parametrize("entry", FROZEN["query_issues"], ids=lambda e: f"{e['provider_id']}/{e['endpoint_id']}")
def test_query_issues_baseline(entry):
    assert facade.connectors()[entry["provider_id"]].query_issues(entry["text"], entry["endpoint_id"]) == entry["issues"]


@pytest.mark.parametrize("groups", [[["alpha", "alpha"], ["beta"]], baseline.BLOCKS[1]])
def test_duplicate_term_retained_occurrences(groups):
    f = facade.connectors()["openalex"]
    result = f.render_query(groups)
    expected = ("alpha", "alpha", "beta") if len(groups[0]) == 2 else ("alpha", "beta", "gamma", "delta", "epsilon", "eta")
    assert result.retained == expected
    assert Counter(result.retained + result.dropped) == Counter(t for g in groups for t in g)


@pytest.mark.parametrize("optimize", [False, True])
def test_rendering_mismatch_raises_even_with_optimized_python(optimize, tmp_path):
    code = '''
import socket
def forbidden(*args, **kwargs):
    raise AssertionError("socket or DNS during rendering check")
socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
from deixis.providers import facade, query_compiler
query_compiler._fit_blocks = lambda *args: ("mismatched query", [])
try:
    facade.connectors()["openalex"].render_query([["alpha"], ["beta"]])
except RuntimeError as exc:
    if "query rendering mismatch for openalex/None" not in str(exc):
        raise
else:
    raise AssertionError("rendering mismatch was not refused")
'''
    paths = [str(ROOT / "backend"), *(p for p in sys.path if "site-packages" in p)]
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, *(["-O"] if optimize else []), "-S", "-c", code]
    result = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


# Only source-owned dynamic values have exceptions. Every unresolved new expression fails closed.
SCAN_ALLOWLIST = {
    ("common.py", "error_kind", "limit_kind(error_payload, status=response.status_code, text=f'{detail} {response.text}')"):
        "domain.limits.limit_kind owns G8 classification; dynamic vocabulary is baseline-checked",
    ("pubmed.py", "status", "fetch_outcome.status"): "EFetch copies the classified SearchOutcome status unchanged",
    ("pubmed.py", "delivery_class", "fetch_outcome.delivery_class"): "EFetch copies send's delivery class unchanged",
    ("pubmed.py", "error_kind", "fetch_outcome.error_kind"): "EFetch copies the already-classified SearchOutcome.error_kind unchanged",
    ("zotero.py", "status", "status"): "ZoteroError.status is an integer HTTP status, not an adapter outcome",
}
VOCABULARIES = {"status": c.SEARCH_STATUSES, "delivery_class": c.DELIVERY_CLASSES, "error_kind": c.ERROR_KINDS,
                "lookup_status": c.LOOKUP_STATUSES - {"unsupported"}}


def scan_vocabulary(source, filename="scratch.py"):
    tree = ast.parse(source)
    violations, seen = [], []
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def scope(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                return node
        return tree

    def pairs(target, value):
        if isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)):
                for t, v in zip(target.elts, value.elts):
                    yield from pairs(t, v)
            else:
                # A dynamic tuple cannot silently hide assignments to outcome fields.
                for t in target.elts:
                    yield from pairs(t, value)
        else:
            yield target, value

    def assignments(root):
        # Do not resolve names from an unrelated function with the same local variable name.
        for node in ast.walk(root):
            if scope(node) is not root:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    yield from pairs(target, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                yield from pairs(node.target, node.value)

    def check(value, kind, root, resolving=()):
        if isinstance(value, ast.Constant) and (isinstance(value.value, str) or value.value is None):
            seen.append((kind, value.value))
            if value.value is not None and value.value not in VOCABULARIES[kind]:
                violations.append(f"{filename}:{value.lineno}: invalid {kind} {value.value!r}")
            return
        if isinstance(value, ast.IfExp):
            check(value.body, kind, root, resolving)
            check(value.orelse, kind, root, resolving)
            return
        if (filename, kind, ast.unparse(value)) in SCAN_ALLOWLIST:
            return
        if isinstance(value, ast.Name) and value.id not in resolving:
            bindings = [v for t, v in assignments(root) if isinstance(t, ast.Name) and t.id == value.id]
            if bindings:
                for bound in bindings:
                    check(bound, kind, root, (*resolving, value.id))
                return
        expression = ast.unparse(value)
        if (filename, kind, expression) not in SCAN_ALLOWLIST:
            violations.append(f"{filename}:{value.lineno}: unresolved {kind}: {expression}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            slots = {"SearchOutcome": ("status", "delivery_class"), "LookupAnswer": ("lookup_status",)}.get(name, ())
            for kind, value in zip(slots, node.args):
                check(value, kind, scope(node))
            for kw in node.keywords:
                if kw.arg == "error_kind" or (kw.arg in slots):
                    check(kw.value, kw.arg, scope(node))
                elif name == "LookupAnswer" and kw.arg == "status":
                    check(kw.value, "lookup_status", scope(node))
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for t, value in pairs(target, node.value):
                    if isinstance(t, ast.Attribute) and t.attr in {"status", "delivery_class", "error_kind"}:
                        check(value, t.attr, scope(node))
    return violations, seen


def test_provider_static_vocabulary():
    failures = []
    for path in sorted((ROOT / "backend/deixis/providers").glob("*.py")):
        failures.extend(scan_vocabulary(path.read_text(), path.name)[0])
    assert failures == []


@pytest.mark.parametrize("source,expected", [
    ('SearchOutcome("partial", None, "d", "keyless")', "invalid status"),
    ('SearchOutcome(status="partial", delivery_class=None)', "invalid status"),
    ('outcome.status = "partial"', "invalid status"),
    ('outcome.status, outcome.delivery_class = "completed", "bogus"', "invalid delivery_class"),
    ('status = "completed" if x else "partial"\nSearchOutcome(status, None)', "invalid status"),
    ('delivery = "before_send" if x else "bogus"\nSearchOutcome("failed", delivery)', "invalid delivery_class"),
    ('SearchOutcome("failed", None, error_kind="bogus")', "invalid error_kind"),
    ('LookupAnswer("unsupported")', "invalid lookup_status"),
    ('LookupAnswer(status="unsupported")', "invalid lookup_status"),
    ('outcome.status = dynamic', "unresolved status"),
])
def test_scanner_rejects_each_syntax(source, expected):
    failures, _ = scan_vocabulary(source)
    assert any(expected in failure for failure in failures)


def test_scanner_resolves_valid_forms_and_both_conditional_branches():
    source = '''
def run():
    status = "completed" if flag else "zero_results"
    delivery = "before_send" if flag else "after_send_unknown"
    SearchOutcome(status, delivery, error_kind="quota_exhausted")
    x.status, x.delivery_class = "failed", "rejected_not_executed"
    LookupAnswer(status="found")
'''
    failures, seen = scan_vocabulary(source)
    assert not failures
    assert ("status", "completed") in seen and ("status", "zero_results") in seen
    assert ("delivery_class", "before_send") in seen and ("delivery_class", "after_send_unknown") in seen
    failures, _ = scan_vocabulary('outcome.status, outcome.delivery_class = dynamic')
    assert len(failures) == 2 and all("scratch.py:1: unresolved" in failure for failure in failures)
