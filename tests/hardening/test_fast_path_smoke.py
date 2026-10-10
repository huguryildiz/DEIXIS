"""Fast path end to end (D250–D254): one Quick question through search, chain, read and the automatic answer.

SYNTHETIC records, a scripted model, mocked OpenAlex and scripted PDFs. This shows that the slices run together in one
research; it does not measure latency, recall or answer quality.
"""

import httpx

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow import fast_path
from fakes import FakeAdapter
from test_abstract_flow import ON_TOPIC, responder
from test_fetch_overlap_flow import discover, wait
from test_fulltext_flow import Fetcher, Transport, named_pdf, ok, work
from test_small_batch_flow import client_of


def url(n):
    return f"https://example.org/w{n}.pdf"


def test_quick_question_runs_every_fast_path_stage_and_answers_unattended(tmp_path, monkeypatch):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    works = [work(n, pdf_url=url(n), title=ON_TOPIC) for n in range(1, 31)]
    fetcher = Fetcher({url(n): ok(named_pdf(f"10.1/oa.{n}")) for n in range(1, 31)})
    app = create_app(Settings(data_dir=tmp_path, port=8765, search_query="code", protocol_approval="ask",
                              fulltext_fetch="auto", fulltext_adjudication="auto"),
                     adapters={"fake": FakeAdapter(responder())},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(Transport(works))), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed", discovery
        store = app.state.store
        budget = store.run(discovery_id)["budget"]
        answers = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'answer'", (rid,)).fetchall()
        assert len(answers) == 1
        _, answer = wait(client, rid, answers[0][0])
        assert answer["status"] == "completed", answer
        view = client.get(f"/api/researches/{rid}").json()
        stages = {row["stage"]: row["status"] for row in store.conn.execute("SELECT stage, status FROM fast_path_stages")}
        outcome = store.conn.execute("SELECT answer_outcome FROM fast_path_ledgers").fetchone()[0]
        kinds = {row[0]: row[1] for row in store.conn.execute(
            "SELECT kind, count(*) FROM run_steps WHERE status = 'succeeded' GROUP BY kind")}

    assert fast_path.enabled(budget)
    assert set(budget["fast_path"]["enforced_stages"]) == {"search", "ranking", "read", "answer"}
    assert stages == dict.fromkeys(("plan", "search", "ranking", "read", "answer"), "done")
    assert outcome == "structurally_valid"
    assert kinds["provider_search:openalex"] >= 1 and kinds["provider_chain:openalex"] >= 1
    assert kinds["code:fast_chain"] >= 1
    assert len(fetcher.calls) == kinds["fetch_pdf"] == 10  # Quick reads the first K = 10 eligible works
    assert kinds["model:fulltext_adjudication"] == 20  # two reads per work
    assert kinds["code:fast_path_cutoff"] == 1 and kinds["model:grounded_answer"] == 1
    assert "model:term_advice" not in kinds  # approval is unattended
    claims = view["answers"][0]["claims"]
    assert claims and {claim["evidence_basis"] for claim in claims} == {"full_text"}


def test_hung_read_call_is_cut_and_the_answer_still_publishes(tmp_path, monkeypatch):
    """D258: one fulltext read hangs past the read deadline; the read closes, the run is not paused, the answer runs."""
    import asyncio
    from deixis.domain import canonical
    from fakes import parse_step_input

    class Hanging(FakeAdapter):
        hung = 0

        async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
            if parse_step_input(message)["task_type"] == "fulltext_adjudication" and not self.hung:
                self.hung += 1
                await asyncio.sleep(60)
            return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)

    bases, *rest = fast_path.MODES["quick"]
    monkeypatch.setitem(fast_path.MODES, "quick", ((1, 1, 1, 3, 30), *rest))
    freeze = fast_path.freeze_budget
    def short_drain(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        policy.pop("policy_hash")
        policy["read_drain_ms"] = 300
        return policy | {"policy_hash": canonical.sha256_hex(policy)}
    monkeypatch.setattr(fast_path, "freeze_budget", short_drain)
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    works = [work(n, pdf_url=url(n), title=ON_TOPIC) for n in range(1, 31)]
    fetcher = Fetcher({url(n): ok(named_pdf(f"10.1/oa.{n}")) for n in range(1, 31)})
    adapter = Hanging(responder())
    app = create_app(Settings(data_dir=tmp_path, port=8765, search_query="code", protocol_approval="ask",
                              fulltext_fetch="auto", fulltext_adjudication="auto"),
                     adapters={"fake": adapter},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(Transport(works))), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed", discovery
        store = app.state.store
        answers = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'answer'", (rid,)).fetchall()
        _, answer = wait(client, rid, answers[0][0])
        assert answer["status"] == "completed", answer
        cut = store.conn.execute("SELECT count(*) FROM run_steps WHERE run_id = ? AND error_code = 'model_read_cutoff'",
                                 (discovery_id,)).fetchone()[0]
        outcome = store.conn.execute("SELECT answer_outcome FROM fast_path_ledgers").fetchone()[0]
    assert adapter.hung == 1 and cut == 1 and outcome == "structurally_valid"
