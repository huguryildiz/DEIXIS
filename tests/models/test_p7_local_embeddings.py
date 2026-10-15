"""Ollama and LM Studio paths through mocked OpenAI-compatible transports."""
import asyncio
import json

import httpx
import pytest

from deixis.documents import embeddings as e


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
@pytest.mark.parametrize("failure", ["refused", "429", "413"])
def test_mid_batch_failure(provider, failure, monkeypatch):
    monkeypatch.setattr(e, "BATCH", 1)
    calls, sent = [], []
    def handler(request):
        calls.append(request)
        assert str(request.url) == e.LOCAL_URLS[provider] + "/embeddings"
        assert "authorization" not in request.headers
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3, 4]}]})
        if failure == "refused":
            raise httpx.ConnectError("SYNTHETIC refused", request=request)
        return httpx.Response(int(failure), json={"error": {"message": "SYNTHETIC request too large" if failure == "413" else "SYNTHETIC limited"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(e.EmbeddingError, match="ConnectError" if failure == "refused" else f"HTTP {failure}"):
        asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["first", "second"], "RETRIEVAL_DOCUMENT", on_sent=lambda: sent.append(1)))
    assert len(calls) == 2 and len(sent) == (1 if failure == "refused" else 2)


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_429_retries_and_counts_requests(provider):
    calls, sent = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "SYNTHETIC"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    budget = e.RateBudget()
    with pytest.raises(e.EmbeddingError, match="rate limited 4 times"):
        asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["text"], "RETRIEVAL_QUERY", budget, on_sent=lambda: sent.append(1)))
    assert len(calls) == len(sent) == 4 and budget.rate_limited_waits == 3


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_success_returns_normalized_vectors_in_input_order(provider):
    def handler(request):
        assert json.loads(request.content) == {"model": "synthetic", "input": ["a", "b"]}
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 2]}, {"index": 0, "embedding": [3, 4]}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vectors = asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["a", "b"], "RETRIEVAL_DOCUMENT"))
    assert list(vectors[0]) == pytest.approx([.6, .8]) and list(vectors[1]) == [0, 1]


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_extra_unindexed_embedding_is_a_typed_bad_reply(provider):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "data": [{"index": 0, "embedding": [1, 0]}, {"embedding": [0, 1]}],
    })))
    with pytest.raises(e.EmbeddingError, match="bad_reply"):
        asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["a"], "RETRIEVAL_QUERY"))


def test_a_local_embedding_request_never_goes_through_a_proxy_from_the_environment(monkeypatch):
    """D34 follow-up: passage text sent to Ollama or LM Studio must not leave the computer through HTTP_PROXY/ALL_PROXY.
    Two real servers on loopback, the embedding server and a proxy; the environment points every proxy at the latter."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    hits = {"server": [], "proxy": []}

    def serve(name, reply):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                hits[name].append(self.path)
                body = json.dumps(reply).encode()
                self.send_response(200 if name == "server" else 502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    server = serve("server", {"data": [{"index": 0, "embedding": [3, 4]}]})
    proxy = serve("proxy", {"error": "SYNTHETIC proxy"})
    try:
        proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
            monkeypatch.setenv(name, proxy_url)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setitem(e.LOCAL_URLS, "ollama", f"http://127.0.0.1:{server.server_address[1]}/v1")

        async def go():
            async with httpx.AsyncClient() as shared:  # the app's shared client honours the proxy variables
                control = await shared.post(e.LOCAL_URLS["ollama"] + "/embeddings", json={})
                assert control.status_code == 502 and hits["proxy"]  # without the fix the request would go this way
                hits["proxy"].clear()
                deps = SimpleNamespace(http=shared)
                assert e.client_for("openai", deps) is shared  # remote APIs keep the person's proxy
                client = e.client_for("ollama", deps)
                assert client is not shared and client is e.client_for("lm_studio", deps)
                assert client.trust_env is False and client.follow_redirects is False
                try:
                    return await e.Embedder("ollama", "synthetic").embed(client, ["passage"], "RETRIEVAL_DOCUMENT")
                finally:
                    await client.aclose()

        (vector,) = asyncio.run(go())
        assert list(vector) == pytest.approx([.6, .8])
        assert hits == {"server": ["/v1/embeddings"], "proxy": []}
    finally:
        server.shutdown()
        proxy.shutdown()
