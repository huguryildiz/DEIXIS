"""Test on a keyless source's Settings sheet (P5): one request without a key, reported as answered or not.

Only a connector running without a key right now is tested here (its access mode is `keyless`): a source key is not
tested in advance (D53), and a source that requires one has nothing to send without it. The request uses a new
connection, so it does not ride a pooled one from before a network change. Nothing is stored.
"""

from typing import Any, Callable

from fastapi import HTTPException, Request

from deixis.providers import keyless_check, registry


def register_provider_test_routes(app, contact_email: Callable[[], str | None]) -> None:
    @app.post("/api/providers/{provider_id}/test")
    async def test_keyless_provider(provider_id: str, request: Request) -> dict[str, Any]:
        connector = registry.CONNECTORS.get(provider_id)
        if connector is None:
            raise HTTPException(404, f"{provider_id} is not a source DEIXIS connects to")
        if connector.access_mode() != "keyless" or provider_id not in keyless_check.REQUESTS:
            raise HTTPException(422, f"{provider_id} uses a key; this test is for sources used without one")
        async with request.app.state.fresh_http() as client:
            return await keyless_check.check(client, provider_id, contact_email())
