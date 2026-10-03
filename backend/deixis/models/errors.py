"""Compatibility exports for callers of the original model-limit helper path."""
from deixis.domain.limits import http_limit, limit_kind

__all__ = ["http_limit", "limit_kind"]
