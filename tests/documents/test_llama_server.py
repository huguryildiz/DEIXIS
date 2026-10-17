"""The built-in models' llama.cpp servers (`documents/local_embedding.py`): start, probe, replies, cuts, failures.

The server is `fake_llama_server.py`, written into a SYNTHETIC runtime folder as `llama-server` and run through the
production watcher; the model files are SYNTHETIC bytes with their own digests. Passing shows how DEIXIS starts, talks
to, checks and stops the server, not how any real model embeds or ranks.
"""

import asyncio
import fcntl
import json
import os
import socket
import time

import pytest

from deixis.documents import builtin_catalog, local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError, LocalModels
from builtin_helpers import install_model, ready

EMB, RER = "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"
pytestmark = pytest.mark.skipif(os.name != "posix", reason="the built-in models are POSIX only in this slice")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    paths = local_embedding.builtin_paths(tmp_path / "data")
    ready(paths, monkeypatch, EMB, RER, "bge-m3")
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_LLAMA_RECORD", str(record))
    monkeypatch.setenv("FAKE_LLAMA_STATE", str(tmp_path / "state"))

    def lines():
        return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    return paths, lines


def run(coro):
    return asyncio.run(coro)


async def using(models, coro):
    try:
        return await coro
    finally:
        await models.close()


def gone(pid, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_embeddings_come_back_in_input_order_with_the_query_instruction_and_the_pinned_command_line(setup):
    paths, lines = setup
    models = LocalModels(paths)
    texts = ["alpha beta", "gamma delta", "alpha beta"]
    vectors = run(using(models, models.embed(EMB, texts, "document")))
    assert len(vectors) == 3 and all(len(v) == 1024 for v in vectors)
    assert list(vectors[0]) == list(vectors[2]) and list(vectors[0]) != list(vectors[1])  # mapped by index, not position
    starts = [line for line in lines() if "argv" in line]
    argv = starts[0]["argv"]
    for flag, value in (("--host", "127.0.0.1"), ("-c", "8192"), ("-ub", "8192"), ("-b", "8192"), ("-np", "1"),
                        ("-ngl", "99"), ("--pooling", "last")):
        assert argv[argv.index(flag) + 1] == value
    assert "--embedding" in argv and "--rerank" not in argv and "--port" in argv and len(argv[argv.index("--api-key") + 1]) == 48
    requests = [line for line in lines() if line.get("path") == "/v1/embeddings"]
    probe, call = requests
    assert probe["body"]["input"][0].startswith("Instruct: " + builtin_catalog.EMBEDDING_INSTRUCTION + "\nQuery:")
    assert call["body"]["input"] == texts  # documents carry no instruction


def test_bge_m3_uses_cls_pooling_and_no_instruction(setup):
    paths, lines = setup
    models = LocalModels(paths)
    run(using(models, models.embed("bge-m3", ["alpha"], "query")))
    argv = [line for line in lines() if "argv" in line][0]["argv"]
    assert argv[argv.index("--pooling") + 1] == "cls"
    assert [line for line in lines() if line.get("path") == "/v1/embeddings"][-1]["body"]["input"] == ["alpha"]


def test_rerank_scores_are_raw_any_sign_or_size_and_mapped_by_index(setup):
    paths, lines = setup
    models = LocalModels(paths)
    scores, cut = run(using(models, models.rerank(RER, "packet energy", ["packet energy", "nothing here", "energy"], 30)))
    assert scores == [4.0, -3.0, 0.5] and cut == []  # the fake sorts results by score; they come back in input order
    argv = [line for line in lines() if "argv" in line][0]["argv"]
    assert "--rerank" in argv and "--embedding" not in argv


@pytest.mark.parametrize("mode,kind", [("null_vector", "embed"), ("nan", "embed"), ("wrong_count", "embed"),
                                       ("duplicate_index", "embed"), ("wrong_dim", "embed"), ("not_unit", "embed"),
                                       ("wrong_count", "rerank"), ("duplicate_index", "rerank"), ("nan", "rerank")])
def test_a_wrong_reply_is_refused_and_the_server_is_killed(setup, monkeypatch, mode, kind):
    paths, lines = setup
    monkeypatch.setenv("FAKE_LLAMA", mode)
    models = LocalModels(paths)
    call = (models.embed(EMB, ["alpha beta", "gamma"], "document") if kind == "embed"
            else models.rerank(RER, "alpha", ["alpha", "beta"], 30))
    with pytest.raises(LocalEmbeddingError) as error:
        run(using(models, call))
    assert error.value.code == "builtin_bad_reply"
    pid = [line for line in lines() if "argv" in line][0]["pid"]
    assert gone(pid) and models.servers == {}


def test_a_slow_load_waits_for_health_and_a_crash_is_reported_then_the_next_request_starts_again(setup, monkeypatch):
    paths, lines = setup
    monkeypatch.setenv("FAKE_LLAMA", "slow_load:1.0,crash")
    models = LocalModels(paths)

    async def scenario():
        with pytest.raises(LocalEmbeddingError) as error:
            await models.embed(EMB, ["alpha"], "document")
        assert error.value.code == "builtin_stopped"
        monkeypatch.setenv("FAKE_LLAMA", "")
        return await models.embed(EMB, ["alpha"], "document")
    started = time.monotonic()
    assert len(run(using(models, scenario()))) == 1
    assert time.monotonic() - started >= 1.0
    assert len([line for line in lines() if "argv" in line]) == 2


def test_a_taken_port_is_retried_and_three_taken_ports_fail(setup, monkeypatch):
    paths, lines = setup
    monkeypatch.setenv("FAKE_LLAMA", "bind_fail:2")
    models = LocalModels(paths)
    assert len(run(using(models, models.embed(EMB, ["alpha"], "document")))) == 1
    assert len([line for line in lines() if "argv" in line]) == 3

    monkeypatch.setenv("FAKE_LLAMA", "bind_fail:9")
    monkeypatch.setenv("FAKE_LLAMA_STATE", str(paths.root.parent.parent / "state-2"))
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError, match="no free port after 3 attempts"):
        run(using(models, models.embed(EMB, ["alpha"], "document")))


def test_a_port_another_process_holds_is_left_and_the_next_one_taken(setup, monkeypatch):
    paths, lines = setup
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    ports = iter([busy.getsockname()[1], local_embedding.free_port()])
    monkeypatch.setattr(local_embedding, "free_port", lambda: next(ports))
    try:
        models = LocalModels(paths)
        assert len(run(using(models, models.embed(EMB, ["alpha"], "document")))) == 1
    finally:
        busy.close()
    assert len([line for line in lines() if "argv" in line]) == 2


def test_a_server_that_does_not_know_the_key_fails_the_probe(setup, monkeypatch):
    paths, _ = setup
    monkeypatch.setenv("FAKE_LLAMA", "reject_key")
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError, match="HTTP 401"):
        run(using(models, models.embed(EMB, ["alpha"], "document")))


def test_a_request_that_outlives_its_time_is_killed_and_a_cancelled_one_too(setup, monkeypatch):
    paths, lines = setup
    monkeypatch.setenv("FAKE_LLAMA", "hang")
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError) as error:
        run(using(models, models.rerank(RER, "alpha", ["alpha"], 1)))
    assert error.value.code == "builtin_timeout"
    assert gone([line for line in lines() if "argv" in line][0]["pid"])
    models = LocalModels(paths)

    async def cancelled():
        task = asyncio.create_task(models.rerank(RER, "alpha", ["alpha"], 60))
        await asyncio.sleep(1.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    run(using(models, cancelled()))
    assert gone([line for line in lines() if "argv" in line][-1]["pid"]) and models.servers == {}


def test_a_text_over_the_token_limit_is_cut_counted_and_reported_and_a_very_long_one_refused(setup):
    paths, lines = setup
    models = LocalModels(paths)
    report = {}
    long = "word " * 2000  # 10,000 bytes: one token per byte in the fake, over the 8,176-token input limit
    run(using(models, models.embed(EMB, ["short", long], "document", report)))
    assert report == {"truncated_texts": 1}
    sent = [line for line in lines() if line.get("path") == "/v1/embeddings"][-1]["body"]["input"]
    assert sent[0] == "short" and len(sent[1].encode()) == local_embedding.INPUT_TOKENS
    assert [line["path"] for line in lines() if line.get("path") in ("/tokenize", "/detokenize")] == ["/tokenize", "/detokenize"]
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError) as error:
        run(using(models, models.embed(EMB, ["x" * (local_embedding.MAX_INPUT_CHARS + 1)], "document")))
    assert error.value.code == "builtin_input_too_long"


def test_the_server_holds_the_model_lock_and_the_watcher_ends_it_when_deixis_is_gone(setup):
    paths, lines = setup
    models = LocalModels(paths)

    async def scenario():
        await models.embed(EMB, ["alpha"], "document")
        probe = os.open(paths.model_lock(EMB), os.O_RDWR)
        with pytest.raises(OSError):
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the server holds it shared while it lives
        server = models.servers[EMB]
        server.process.stdin.close()  # what DEIXIS's end does to the watcher's pipe
        pid = [line for line in lines() if "argv" in line][0]["pid"]
        assert await asyncio.to_thread(gone, pid)
        await server.process.wait()
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free once the server is gone
        os.close(probe)
        models.servers.clear()
    run(using(models, scenario()))


def test_an_idle_server_stops_and_a_new_thread_count_restarts_it(setup):
    paths, lines = setup
    models = LocalModels(paths, idle_seconds=0.3)

    async def scenario():
        await models.embed(EMB, ["alpha"], "document")
        first = [line for line in lines() if "argv" in line][0]
        await asyncio.sleep(1.5)
        assert models.servers == {}
        assert await asyncio.to_thread(gone, first["pid"])
        token = local_embedding.RUNNER_THREADS.set(2)
        try:
            await models.embed(EMB, ["alpha"], "document")
        finally:
            local_embedding.RUNNER_THREADS.reset(token)
        await models.embed(EMB, ["alpha"], "document")  # back to the default: started again
    run(using(models, scenario()))
    starts = [line["argv"] for line in lines() if "argv" in line]
    assert len(starts) == 3 and "--threads" not in starts[0] and starts[1][starts[1].index("--threads") + 1] == "2"


def test_a_changed_model_file_or_server_binary_keeps_the_server_from_starting(setup):
    paths, lines = setup
    models = LocalModels(paths)
    install_model(paths, EMB, body=b"SYNTHETIC changed " * 3, check=False)
    assert not models.available(EMB)
    with pytest.raises(LocalEmbeddingError, match="does not match its last check"):
        run(using(models, models.embed(EMB, ["alpha"], "document")))
    server = paths.runtime.server()
    server.write_bytes(server.read_bytes() + b"\n# changed\n")
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError, match="server binary does not match"):
        run(using(models, models.rerank(RER, "a", ["a"], 30)))
    assert lines() == []


def test_a_model_of_another_kind_or_not_in_the_catalog_is_refused_as_changed(setup):
    paths, _ = setup
    models = LocalModels(paths)
    for call in (models.embed(RER, ["a"], "document"), models.embed("qwen3-embedding-0.6b@97b0c61:512:mps:iabc", ["a"], "query"),
                 models.rerank(EMB, "a", ["a"], 30)):
        with pytest.raises(LocalEmbeddingError) as error:
            run(call)
        assert error.value.code == "builtin_model_changed"


def test_a_model_being_removed_or_installed_turns_requests_away(setup):
    paths, lines = setup
    models = LocalModels(paths)
    models.busy[EMB] = "removing"
    with pytest.raises(LocalEmbeddingError, match="being installed or removed"):
        run(models.embed(EMB, ["a"], "document"))
    assert lines() == []


def test_consecutive_reranks_reuse_one_server_process(setup):
    paths, lines = setup
    models = LocalModels(paths)

    async def scenario():
        for _ in range(3):
            await models.rerank(RER, "alpha", ["alpha", "beta"], 30)
    run(using(models, scenario()))
    assert len([line for line in lines() if "argv" in line]) == 1  # loaded once, not per request
    assert len({line["pid"] for line in lines() if line.get("path") == "/v1/rerank"}) == 1
