"""A short attached PDF goes to the answer whole, so its passages are neither ranked nor embedded.

The embedding endpoint is mocked; PDF text is SYNTHETIC. What passes here is workflow behavior: which
answer runs send a person's PDF text to the semantic search provider, not retrieval quality.
"""

import httpx

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow.flow import MAX_SMALL_PDF_PAGES
from fakes import FakeAdapter
from test_criterion_passage_flow import TOPIC_PAGE, answer, client_of, fake_fetch, research_with_pdf


def app_with_gemini(tmp_path, monkeypatch):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-test-key")  # semantic search falls to Gemini with no saved choice
    settings = Settings(data_dir=tmp_path / "data", port=8765, search_query="code", fulltext_fetch="off")
    return create_app(settings, adapters={"fake": FakeAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                      fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))


def semantic_steps(view):
    return [s for run in view["runs"] for s in run["steps"] if s["operation_key"] == "semantic_retrieval"]


def test_a_short_attached_pdf_is_given_whole_and_nothing_is_embedded(tmp_path, monkeypatch):
    client = client_of(app_with_gemini(tmp_path, monkeypatch))
    rid = research_with_pdf(client, pages=(TOPIC_PAGE, "SYNTHETIC a second page about the bakery."))
    view, _run, _ = answer(client, rid)
    assert semantic_steps(view) == []


def test_a_long_attached_pdf_is_still_ranked_with_embeddings(tmp_path, monkeypatch):
    client = client_of(app_with_gemini(tmp_path, monkeypatch))
    rid = research_with_pdf(client, pages=[f"{TOPIC_PAGE} Page {n}." for n in range(MAX_SMALL_PDF_PAGES + 1)])
    view, _run, _ = answer(client, rid)
    # The step opens for the PDF's passages; the mocked provider's reply is not what this test reads.
    (step,) = semantic_steps(view)
    assert step["output"]["provider"] == "gemini" and step["output"]["passages"] == MAX_SMALL_PDF_PAGES + 1
