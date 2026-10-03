"""Compatibility boundary for application search dispatch.

Change CONTRACT_ID for protocol methods, required fields or vocabulary, and
QUERY_RULES_REVISION for rendering/rule output. Adapter request, mapping, cursor,
retry/wait and capability semantics normally require an adapter_revision bump.
Facade enforcement before send of descriptor-declared option names, value types
and values or request field types is exempt, as is B3a's expressly adopted retry
allowance rule: None means omission; otherwise an exact nonnegative int. This
exemption requires unchanged registry callables and identical requests/outcomes
for every still-accepted request. Changing what an accepted request sends or
returns still requires the adapter_revision bump. An omitted endpoint retains
the historical default; incompatible descriptors raise ContractViolation.

B3b exempts refusing, before rendering or checking, an undeclared endpoint or
unregistered provider from a QUERY_RULES_REVISION bump only if every registered
provider/default or declared endpoint renders, counts and validates identically,
and module-level rule functions retain every historical output. Other rendered
query or issue-list changes still require the bump (D193).

Dispatched pages record contract and adapter revisions. Resume accepts legacy
NULL provenance, but refuses malformed or incompatible recorded revisions (D194).
Admission and sanitization are application post-processing, separate from search
adapter equivalence. Lookup and chaining helpers remain unbound capabilities.
"""

from dataclasses import dataclass, replace
from copy import deepcopy
from inspect import signature

from deixis.providers import registry, query_rules, query_compiler, contract

UNBOUND_HELPERS = registry.UNBOUND_HELPERS


def descriptor_for(connector: registry.Connector, order: int) -> contract.ConnectorDescriptor:
    pid = connector.provider_id
    defaults = signature(registry.common.send).parameters
    policy = {name: defaults[name].default for name in ("rate_limit_statuses", "unstated_wait", "timeout")}
    policy.update(max_retry_wait=registry.common.MAX_RETRY_WAIT_SECONDS,
                  max_rate_limit_retries=registry.common.MAX_RATE_LIMIT_RETRIES,
                  min_interval=0.0, shared_gate=None)
    retry = contract.RetryPolicy(**(policy | connector.retry))

    def options(names):
        return tuple(contract.OptionDescriptor(name, "str" if name == "sort" else "bool", None) for name in names)

    endpoints = (contract.EndpointDescriptor(None, connector.paging, connector.max_results,
                 connector.max_reachable, connector.page_gap, connector.total, options(connector.sw_options), retry),)
    endpoints += tuple(contract.EndpointDescriptor(eid, e.paging, e.max_results, e.max_reachable,
                       connector.page_gap if e.page_gap is None else e.page_gap, e.total, options(e.options), retry)
                       for eid, e in connector.endpoints.items())
    return contract.ConnectorDescriptor(
        pid, connector.display_name if connector.display_name is not None else pid,
        order, contract.CONTRACT_ID, connector.adapter_revision,
        connector.key_env, connector.key_required, connector.searchable, connector.sw_searchable,
        connector.supplementary, connector.host, connector.lineage, connector.requests_per_search,
        frozenset({"search"}), contract.QUERY_RULES_REVISION, endpoints,
    )


def context_for(connector: registry.Connector, http, contact_email: str | None) -> contract.ConnectorContext:
    return contract.ConnectorContext(http, connector.api_key(), contact_email)


def connectors() -> dict[str, "CompatibilityConnector"]:
    return {pid: CompatibilityConnector(c, descriptor_for(c, order))
            for order, (pid, c) in enumerate(registry.CONNECTORS.items())}


def search_request(query_text: str, limit: int, **kwargs) -> contract.SearchRequest:
    """Map registry-call keywords without validating or changing their values."""
    fields = {name: kwargs.pop(name, None) for name in ("cursor", "max_rate_limit_retries", "endpoint")}
    return contract.SearchRequest(query_text, limit, **fields, options=kwargs)


def sanitize(value, secrets):
    """Copy JSON-like data, replacing only the operation's supplied secrets."""
    secrets = sorted({s for s in secrets if s}, key=lambda s: (-len(s), s))

    def clean(item):
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "<redacted>")
            return item
        if isinstance(item, dict):
            keys = [clean(key) for key in item]
            if len(set(keys)) != len(keys):
                return {"<omitted>": "secret_key_collision"}
            return {key: clean(v) for key, v in zip(keys, item.values())}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return deepcopy(item)

    return clean(value)


def usable_identity(value):
    return (isinstance(value, str) and bool(value.strip()) and value.strip() != "None"
            and not value.strip().startswith(("{", "[")))


@dataclass(frozen=True)
class Dispatched:
    outcome: registry.common.SearchOutcome
    dropped_records: int
    connector: dict

    @property
    def returned_count(self):
        return len(self.outcome.records) + self.dropped_records


async def dispatch_search(provider_id, http, query_text, limit, api_key, contact_email, **registry_kwargs) -> Dispatched:
    connector = CompatibilityConnector(registry.CONNECTORS[provider_id])
    request = search_request(query_text, limit, **registry_kwargs)
    outcome = await connector.search(request, contract.ConnectorContext(http, api_key, contact_email))
    records = [replace(record, raw=sanitize(record.raw, (api_key,))) for record in outcome.records
               if usable_identity(record.provider_record_id)]
    dropped = len(outcome.records) - len(records)
    outcome = replace(outcome, records=records, raw_payload=sanitize(outcome.raw_payload, (api_key,)))
    descriptor = connector.descriptor
    provenance = {"contract_id": descriptor.contract_id, "adapter_revision": descriptor.adapter_revision,
                  "query_rules_revision": descriptor.query_rules_revision,
                  "payload": "sanitized_json" if outcome.raw_payload is not None else None,
                  "dropped_records": dropped}
    return Dispatched(outcome, dropped, provenance)


class CompatibilityConnector:
    def __init__(self, connector: registry.Connector, descriptor: contract.ConnectorDescriptor | None = None):
        if descriptor is None:
            order = list(registry.CONNECTORS).index(connector.provider_id)
            descriptor = descriptor_for(connector, order)
        if (descriptor.provider_id != connector.provider_id or descriptor.contract_id not in contract.SUPPORTED_CONTRACTS
                or descriptor.adapter_revision != connector.adapter_revision):
            raise contract.ContractViolation("incompatible connector descriptor")
        self.connector = connector
        self.descriptor = descriptor

    def access(self, context: contract.ConnectorContext) -> contract.AccessState:
        mode = "api_key" if context.api_key else "not_configured" if self.descriptor.key_required else "keyless"
        return contract.AccessState(self.descriptor.provider_id, mode, self.descriptor.key_required)

    def _endpoint(self, endpoint):
        for declared in self.descriptor.endpoints:
            if declared.endpoint_id == endpoint:
                return declared
        raise contract.ContractViolation(f"unknown endpoint: {endpoint!r}")

    async def search(self, request: contract.SearchRequest, context: contract.ConnectorContext):
        if type(request.limit) is not int or request.limit <= 0:
            raise contract.ContractViolation("limit must be a positive integer")
        if not isinstance(request.query_text, str):
            raise contract.ContractViolation("query_text must be a string")
        if request.cursor is not None and not isinstance(request.cursor, str):
            raise contract.ContractViolation("cursor must be a string or None")
        endpoint = self._endpoint(request.endpoint)
        allowed = {option.name: option for option in endpoint.options}
        if any(name not in allowed for name in request.options):
            raise contract.ContractViolation("undeclared endpoint option")
        for name, value in request.options.items():
            option = allowed[name]
            valid_type = ((option.value_type == "bool" and type(value) is bool)
                          or (option.value_type == "str" and type(value) is str))
            if not valid_type:
                raise contract.ContractViolation(f"{name} must be an exact {option.value_type}")
            if option.values is not None and value not in option.values:
                raise contract.ContractViolation(f"{name} must be one of its declared values")
        if request.max_rate_limit_retries is not None and (
                type(request.max_rate_limit_retries) is not int or request.max_rate_limit_retries < 0):
            raise contract.ContractViolation("max_rate_limit_retries must be a nonnegative integer or None")
        kwargs = {}
        for name in ("cursor", "max_rate_limit_retries", "endpoint"):
            value = getattr(request, name)
            if value is not None:
                kwargs[name] = value
        kwargs.update(request.options)
        return await self.connector.search(context.http, request.query_text, request.limit, context.api_key,
                                           context.contact_email, **kwargs)

    async def lookup(self, request: contract.LookupRequest, context: contract.ConnectorContext):
        request.validate()
        operation = "doi_lookup" if request.doi is not None else "id_lookup"
        return contract.LookupOutcome("unsupported", operation=operation)

    def query_issues(self, text: str, endpoint: str | None = None) -> list[str]:
        self._endpoint(endpoint)
        return registry.resolve_query_syntax(self.descriptor.provider_id, endpoint).query_issues(text)

    def render_query(self, groups, endpoint: str | None = None) -> contract.QueryRendering | None:
        self._endpoint(endpoint)
        pid = self.descriptor.provider_id
        groups = [list(g) for g in groups]
        fitted = query_compiler.fit_block_counts(pid, groups, endpoint)
        if fitted is None:
            return None
        text, used = fitted
        retained = tuple(term for g, n in zip(groups, used) for term in g[:n])
        dropped = tuple(term for g, n in zip(groups, used) for term in g[n:])
        return contract.QueryRendering(text, retained, dropped, contract.QUERY_RULES_REVISION)
