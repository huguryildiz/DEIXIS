"""Image input on the API connections that read equation crops (D113): one PNG goes with the message, nothing else is
added, and a step without an image is sent exactly as before.

Mocked httpx transports only: these show the request shape, not that the live APIs accept it.
"""

import asyncio
import base64
import json

import httpx
import pytest

from deixis.documents import equation_model
from deixis.models import anthropic_api, gemini, openai_api

PNG = b"\x89PNG\r\n\x1a\nSYNTHETIC"
ENCODED = base64.standard_b64encode(PNG).decode()


def sent(module, cls, env, monkeypatch, image):
    monkeypatch.setenv(env, "test-key")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"type": "invalid_request_error"}})

    adapter = cls(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    kwargs = {"image_png": PNG} if image else {}
    asyncio.run(adapter.run_step(equation_model.INSTRUCTION, "", equation_model.MESSAGE, equation_model.SCHEMA, "m-1", None, **kwargs))
    assert adapter.accepts_images is True and adapter.key_env == env
    return seen[0]


@pytest.mark.parametrize("image", [True, False])
def test_anthropic_puts_the_png_before_the_message(monkeypatch, image):
    body = sent(anthropic_api, anthropic_api.AnthropicAdapter, "ANTHROPIC_API_KEY", monkeypatch, image)
    content = body["messages"][0]["content"]
    if image:
        assert content == [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ENCODED}},
                           {"type": "text", "text": equation_model.MESSAGE}]
    else:
        assert content == equation_model.MESSAGE
    assert len(body["messages"]) == 1 and body["system"].startswith(equation_model.INSTRUCTION)


@pytest.mark.parametrize("image", [True, False])
def test_openai_sends_the_png_as_an_input_image(monkeypatch, image):
    body = sent(openai_api, openai_api.OpenAIAdapter, "OPENAI_API_KEY", monkeypatch, image)
    if image:
        assert body["input"] == [{"role": "user", "content": [
            {"type": "input_image", "image_url": "data:image/png;base64," + ENCODED},
            {"type": "input_text", "text": equation_model.MESSAGE}]}]
    else:
        assert body["input"] == equation_model.MESSAGE
    assert body["store"] is False


@pytest.mark.parametrize("image", [True, False])
def test_gemini_sends_the_png_as_inline_data(monkeypatch, image):
    body = sent(gemini, gemini.GeminiAdapter, "GEMINI_API_KEY", monkeypatch, image)
    parts = body["contents"][0]["parts"]
    expected = [{"text": equation_model.MESSAGE}]
    if image:
        expected = [{"inlineData": {"mimeType": "image/png", "data": ENCODED}}] + expected
    assert parts == expected and len(body["contents"]) == 1
