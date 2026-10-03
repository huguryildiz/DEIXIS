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
adapter equivalence. G1-F1 exempts binding unchanged existing helpers from an
adapter revision bump only with capability request/result equivalence and unchanged
search replays. Admission, redaction, accounting and continuation refusals are
separate named application changes.
"""

from dataclasses import dataclass, replace
from copy import deepcopy
from inspect import signature

from deixis.providers import registry, query_rules, query_compiler, contract
from deixis.providers.lookup import LookupAnswer


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
                 connector.max_reachable, connector.page_gap, connector.total,
                 options(tuple(connector.sw_options) + connector.options), retry),)
    endpoints += tuple(contract.EndpointDescriptor(eid, e.paging, e.max_results, e.max_reachable,
                       connector.page_gap if e.page_gap is None else e.page_gap, e.total, options(e.options), retry)
                       for eid, e in connector.endpoints.items())
    return contract.ConnectorDescriptor(
        pid, connector.display_name if connector.display_name is not None else pid,
        order, contract.CONTRACT_ID, connector.adapter_revision,
        connector.key_env, connector.key_required, connector.searchable, connector.sw_searchable,
        connector.supplementary, connector.host, connector.lineage, connector.requests_per_search,
        frozenset({"search"} | set(connector.capabilities)), contract.QUERY_RULES_REVISION, endpoints,
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
    transport: tuple[dict, ...] = ()

    @property
    def returned_count(self):
        return len(self.outcome.records) + self.dropped_records


@dataclass(frozen=True)
class DispatchedLookup:
    operation: str
    answers: dict[str, LookupAnswer]
    outcome: registry.common.SearchOutcome
    returned_count: int
    dropped_records: int
    connector: dict
    transport: tuple[dict, ...] = ()


def _provenance(descriptor, outcome, dropped):
    return {"contract_id": descriptor.contract_id, "adapter_revision": descriptor.adapter_revision,
            "query_rules_revision": descriptor.query_rules_revision,
            "payload": "sanitized_json" if outcome.raw_payload is not None else None,
            "dropped_records": dropped}


def _admit(outcome, api_key):
    records = [replace(record, raw=sanitize(record.raw, (api_key,))) for record in outcome.records
               if usable_identity(record.provider_record_id)]
    dropped = len(outcome.records) - len(records)
    return replace(outcome, records=records, raw_payload=sanitize(outcome.raw_payload, (api_key,))), dropped


def _id_answers(identifiers, outcome):
    returned = {record.provider_record_id for record in outcome.records}
    return {identifier: (LookupAnswer("found") if identifier in returned else
                         LookupAnswer("not_found") if outcome.status in ("completed", "zero_results") else
                         LookupAnswer("failed")) for identifier in identifiers}


async def dispatch_search(provider_id, http, query_text, limit, api_key, contact_email, **registry_kwargs) -> Dispatched:
    connector = CompatibilityConnector(registry.CONNECTORS[provider_id])
    request = search_request(query_text, limit, **registry_kwargs)
    with registry.common.collect_transport() as transport:
        outcome = await connector.search(request, contract.ConnectorContext(http, api_key, contact_email))
    records = [replace(record, raw=sanitize(record.raw, (api_key,))) for record in outcome.records
               if usable_identity(record.provider_record_id)]
    dropped = len(outcome.records) - len(records)
    outcome = replace(outcome, records=records, raw_payload=sanitize(outcome.raw_payload, (api_key,)))
    provenance = _provenance(connector.descriptor, outcome, dropped)
    return Dispatched(outcome, dropped, provenance, tuple(transport))


async def dispatch_lookup(provider_id, operation, http, identifiers, api_key, contact_email,
                          max_rate_limit_retries=None) -> DispatchedLookup:
    connector = CompatibilityConnector(registry.CONNECTORS[provider_id])
    request = contract.LookupBatchRequest(operation, identifiers, max_rate_limit_retries)
    with registry.common.collect_transport() as transport:
        result = await connector.lookup_batch(request, contract.ConnectorContext(http, api_key, contact_email))
    returned = len(result.outcome.records)
    outcome, dropped = _admit(result.outcome, api_key)
    answers = _id_answers(identifiers, outcome) if operation == "id_lookup" else result.answers
    answers = {identifier: replace(answer, abstract=sanitize(answer.abstract, (api_key,)),
                                  paper_id=sanitize(answer.paper_id, (api_key,)),
                                  linked_dois=sanitize(answer.linked_dois, (api_key,)),
                                  has_preprint=sanitize(answer.has_preprint, (api_key,)))
               for identifier, answer in answers.items()}
    outcome = replace(outcome, error=sanitize(outcome.error, (api_key,)))
    return DispatchedLookup(operation, answers, outcome, returned, dropped,
                            _provenance(connector.descriptor, outcome, dropped), tuple(transport))


async def dispatch_citing(provider_id, http, work_id, cursor, limit, api_key, contact_email,
                          max_rate_limit_retries=None, **options) -> Dispatched:
    connector = CompatibilityConnector(registry.CONNECTORS[provider_id])
    request = contract.CitingWorksRequest(work_id, limit, cursor, max_rate_limit_retries, options)
    with registry.common.collect_transport() as transport:
        outcome = await connector.citing_works(request, contract.ConnectorContext(http, api_key, contact_email))
    outcome, dropped = _admit(outcome, api_key)
    # send already redacts error text. Repeating it would change watch rows for
    # keys occurring in the redaction marker (O7).
    return Dispatched(outcome, dropped, _provenance(connector.descriptor, outcome, dropped), tuple(transport))


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
        if operation not in self.connector.capabilities:
            return contract.LookupOutcome("unsupported", operation=operation)
        identifier = request.doi if request.doi is not None else request.provider_record_id
        result = await self.lookup_batch(contract.LookupBatchRequest(operation, (identifier,)), context)
        answer = result.answers[identifier]
        return contract.LookupOutcome(answer.status, operation, answer, result.outcome)

    def _binding(self, operation, allowance, options):
        binding = self.connector.capabilities.get(operation)
        if binding is None:
            raise contract.ContractViolation(f"undeclared capability: {operation}")
        if allowance is not None and not binding.accepts_retry_allowance:
            raise contract.ContractViolation("binding does not accept a retry allowance")
        allowed = {option.name: option for option in binding.options}
        for name, value in options.items():
            if name not in allowed:
                raise contract.ContractViolation("undeclared capability option")
            option = allowed[name]
            if not ((option.value_type == "bool" and type(value) is bool)
                    or (option.value_type == "str" and type(value) is str)):
                raise contract.ContractViolation(f"{name} must be an exact {option.value_type}")
            if option.values is not None and value not in option.values:
                raise contract.ContractViolation(f"{name} must be one of its declared values")
        return binding

    def _missing_key(self, context):
        if self.descriptor.key_required and not context.api_key:
            return registry.common.SearchOutcome("not_configured", "before_send",
                f"{self.descriptor.provider_id} lookup not sent: access=not_configured", "not_configured")
        return None

    async def lookup_batch(self, request: contract.LookupBatchRequest, context: contract.ConnectorContext):
        binding = self._binding(request.operation, request.max_rate_limit_retries, {})
        if len(request.identifiers) > binding.max_batch:
            raise contract.ContractViolation("lookup batch exceeds declared maximum")
        outcome = self._missing_key(context)
        if outcome is not None:
            answers = {identifier: LookupAnswer("failed") for identifier in request.identifiers}
        else:
            result = await binding.call(context.http, request.identifiers, context.api_key, context.contact_email,
                                        request.max_rate_limit_retries)
            if request.operation == "id_lookup":
                outcome = result
                answers = _id_answers(request.identifiers, outcome)
            else:
                answers, outcome = result
        return contract.LookupBatchOutcome(request.operation, answers, outcome)

    async def citing_works(self, request: contract.CitingWorksRequest, context: contract.ConnectorContext):
        binding = self._binding("citing_works", request.max_rate_limit_retries, request.options)
        outcome = self._missing_key(context)
        if outcome is not None:
            return outcome
        return await binding.call(context.http, request.work_id, request.cursor, min(request.limit, binding.max_batch),
                                  context.api_key, context.contact_email, request.max_rate_limit_retries, **request.options)

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
