"""Internal boundary for reviewed scholarly adapters; no runtime plugin loading.

Change CONTRACT_ID when a protocol method, required field or vocabulary changes.
Bump adapter_revision for request, mapping, cursor, retry/wait or capability semantics,
and QUERY_RULES_REVISION for rendering/rule output changes. An omitted endpoint always
means the historical default. Unsupported contracts and unavailable stored adapter
revisions must raise ContractViolation, never restart at page one or change provider.
B1 checks descriptor revisions only; B4 owns recorded-operation revision checks.
Binding unchanged existing helpers is exempt from an adapter revision bump only
with capability request/result equivalence and unchanged search replays (G1-F1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

import httpx

from deixis.providers.common import FIRST_PAGE, SearchOutcome

if TYPE_CHECKING:
    from deixis.providers.lookup import LookupAnswer

CONTRACT_ID = "deixis.scholarly_connector.v1"
QUERY_RULES_REVISION = "deixis.query_rules.r1"
SUPPORTED_CONTRACTS = frozenset({CONTRACT_ID})

SearchStatus = Literal["completed", "zero_results", "not_configured", "auth_required", "entitlement_missing",
                       "rate_limited", "timeout", "parse_error", "failed"]
DeliveryClass = Literal["before_send", "rejected_not_executed", "after_send_unknown"]
ErrorKind = Literal["quota_exhausted", "rate_limited"]
PagingMode = Literal["cursor", "offset", "single_page"]
TotalSemantics = Literal["reported", "estimated", "unknown"]
LookupStatus = Literal["found", "not_found", "failed", "unsupported"]
Capability = Literal["search", "doi_lookup", "id_lookup", "citing_works"]

SEARCH_STATUSES = frozenset({"completed", "zero_results", "not_configured", "auth_required", "entitlement_missing",
                             "rate_limited", "timeout", "parse_error", "failed"})
DELIVERY_CLASSES = frozenset({"before_send", "rejected_not_executed", "after_send_unknown"})
ERROR_KINDS = frozenset({"quota_exhausted", "rate_limited"})
PAGING_MODES = frozenset({"cursor", "offset", "single_page"})
TOTAL_SEMANTICS = frozenset({"reported", "estimated", "unknown"})
LOOKUP_STATUSES = frozenset({"found", "not_found", "failed", "unsupported"})
CAPABILITIES = frozenset({"search", "doi_lookup", "id_lookup", "citing_works"})


class ContractViolation(ValueError):
    """A local contract refusal before any request is sent."""


@dataclass(frozen=True)
class RetryPolicy:
    """Description of module policy; send does not consume this descriptor in B1."""

    rate_limit_statuses: tuple[int, ...]
    unstated_wait: float
    max_retry_wait: float
    max_rate_limit_retries: int
    min_interval: float
    shared_gate: str | None
    timeout: float = 30.0


@dataclass(frozen=True)
class OptionDescriptor:
    name: str
    value_type: Literal["bool", "str"]
    values: tuple[Any, ...] | None


@dataclass(frozen=True)
class EndpointDescriptor:
    endpoint_id: str | None
    paging: PagingMode
    max_results: int
    max_reachable: int | None
    page_gap: float
    total: TotalSemantics
    options: tuple[OptionDescriptor, ...]
    retry: RetryPolicy


@dataclass(frozen=True)
class ConnectorDescriptor:
    provider_id: str
    display_name: str
    order: int
    contract_id: str
    adapter_revision: int
    key_env: str | None
    key_required: bool
    searchable: bool
    sw_searchable: bool
    supplementary: bool
    host: str
    lineage: str | None
    requests_per_search: int
    capabilities: frozenset[str]
    query_rules_revision: str
    endpoints: tuple[EndpointDescriptor, ...]


@dataclass(frozen=True)
class ConnectorContext:
    """Transient call context. Never serialize it: asdict would expose api_key."""

    http: httpx.AsyncClient
    api_key: str | None = field(repr=False)
    contact_email: str | None


@dataclass(frozen=True)
class AccessState:
    """A configured key is not verified access, entitlement or quota."""

    provider_id: str
    access_mode: str
    key_required: bool


@dataclass(frozen=True)
class SearchRequest:
    query_text: str
    limit: int
    endpoint: str | None = None
    cursor: str | None = None
    max_rate_limit_retries: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self):
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True)
class QueryRendering:
    native_query: str
    retained: tuple[str, ...]
    dropped: tuple[str, ...]
    rule_revision: str


@dataclass(frozen=True)
class LookupRequest:
    doi: str | None = None
    provider_record_id: str | None = None

    def validate(self) -> None:
        if (self.doi is None) == (self.provider_record_id is None):
            raise ContractViolation("lookup requires exactly one DOI or provider record identifier")
        value = self.doi if self.doi is not None else self.provider_record_id
        if not isinstance(value, str) or not value:
            raise ContractViolation("lookup identifier must be a nonempty string")

    def __post_init__(self):
        self.validate()


@dataclass(frozen=True)
class LookupOutcome:
    status: LookupStatus
    operation: str
    answer: LookupAnswer | None = None
    outcome: SearchOutcome | None = None


def _retry_allowance(value):
    if value is not None and (type(value) is not int or value < 0):
        raise ContractViolation("max_rate_limit_retries must be a nonnegative integer or None")


@dataclass(frozen=True)
class LookupBatchRequest:
    operation: str
    identifiers: tuple[str, ...]
    max_rate_limit_retries: int | None = None

    def __post_init__(self):
        if self.operation not in ("doi_lookup", "id_lookup"):
            raise ContractViolation("undeclared lookup operation")
        if (type(self.identifiers) is not tuple or not self.identifiers
                or any(not isinstance(value, str) or not value for value in self.identifiers)):
            raise ContractViolation("identifiers must be a nonempty tuple of nonempty strings")
        _retry_allowance(self.max_rate_limit_retries)


@dataclass(frozen=True)
class LookupBatchOutcome:
    operation: str
    answers: Mapping[str, LookupAnswer]
    outcome: SearchOutcome


@dataclass(frozen=True)
class CitingWorksRequest:
    work_id: str
    limit: int
    cursor: str = FIRST_PAGE
    max_rate_limit_retries: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self):
        if not isinstance(self.work_id, str) or not self.work_id:
            raise ContractViolation("work_id must be a nonempty string")
        if type(self.limit) is not int or self.limit <= 0:
            raise ContractViolation("limit must be a positive integer")
        if not isinstance(self.cursor, str) or not self.cursor:
            raise ContractViolation("cursor must be a nonempty string")
        _retry_allowance(self.max_rate_limit_retries)
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@runtime_checkable
class BatchLookupCapable(Protocol):
    async def lookup_batch(self, request: LookupBatchRequest, context: ConnectorContext) -> LookupBatchOutcome: ...


@runtime_checkable
class CitingWorksCapable(Protocol):
    async def citing_works(self, request: CitingWorksRequest, context: ConnectorContext) -> SearchOutcome: ...


@runtime_checkable
class ScholarlyConnector(Protocol):
    descriptor: ConnectorDescriptor

    def access(self, context: ConnectorContext) -> AccessState: ...
    def query_issues(self, text: str, endpoint: str | None = None) -> list[str]: ...
    def render_query(self, groups: Sequence[Sequence[str]], endpoint: str | None = None) -> QueryRendering | None: ...
    async def search(self, request: SearchRequest, context: ConnectorContext) -> SearchOutcome: ...
    async def lookup(self, request: LookupRequest, context: ConnectorContext) -> LookupOutcome: ...
