"""Persistent admission queue consumed during search, closed at the ranking cutoff."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from deixis.documents import embeddings, local_embedding
from deixis.storage.db import transaction
from deixis.workflow import english_question, fast_path


class Consumer:
    def __init__(self, flow, run, scope):
        self.flow, self.store, self.run, self.scope = flow, flow.store, run, scope
        self.task = None
        self.warmup = None
        self.wake = asyncio.Event()
        self.stopping = False
        self.cutoff = None
        self.error = None
        self.query_vector = None
        self.step, self.embedder, origin = flow._embedding_choice(run["id"], "source_similarity")
        self.closed = bool(((self.step or {}).get("output") or {}).get("cutoff_at"))
        self.query = flow._embedding_query(scope, self.embedder) if self.embedder else None
        self.identity = flow._identity(self.embedder, origin) if self.embedder else {"provider": "off", "stored_model": None}
        if self.embedder and self.embedder.provider == "builtin":
            # Until the offline equality check, default-thread and capped-thread
            # scores are different cache identities, even with the same model files.
            model = self.embedder.model
            if ":threads=" not in model:
                self.embedder = embeddings.Embedder("builtin", model + f":threads={run['budget']['fast_path']['embedding_threads']}", self.embedder.local)
            self.identity = flow._identity(self.embedder, origin) | {"threads": run["budget"]["fast_path"]["embedding_threads"]}
            # Whether the built-in model was installed and its files checked when this step ran: the transcript
            # reads it from the step, never from what Settings say later (D103, decision 5).
            integrity = getattr(self.embedder.local, "integrity", None)
            self.identity["model_installed"] = bool(integrity and integrity.available())
        self.identity |= {"fast_path_queue": 1, "embedding_off_reason":
                          "embedding_off" if self.embedder is None else english_question.MISSING if self.query is None else None}
        if self.step is None:
            key = f"similarity:{self.embedder.stored_model}" if self.embedder else "similarity:off"
            self.step = self.store.step(run["id"], "source_similarity", key, output=self.identity)
        if not self.closed:
            self.store.start_step(self.step["id"])
            flow._merge_step_output(self.step["id"], {}, self.identity)
        self.budget = flow._rate_budget(self.step["id"], self.identity)
        if not self.closed and self.embedder and self.embedder.provider == "builtin" and self.query:
            self.warmup = asyncio.create_task(self._query())

    async def _embed(self, texts, kind):
        token = local_embedding.RUNNER_THREADS.set(self.identity.get("threads"))
        try:
            return await self.embedder.embed(self.flow.deps.http, texts, kind, self.budget,
                                             lambda: self.flow._checkpoint(self.run["id"], self.run["scope_revision"]))
        finally:
            local_embedding.RUNNER_THREADS.reset(token)

    async def _query(self):
        try:
            (self.query_vector,) = await self._embed([self.query[0]], "RETRIEVAL_QUERY")
            self.flow._query_dimensions(self.query_vector, self.store.step_output(self.step["id"]) or {})
        except embeddings.EmbeddingError as exc:
            self.error = exc

    def start(self):
        if not self.closed and self.task is None:
            self.task = asyncio.create_task(self.consume())

    def pending(self):
        return self.store.conn.execute(
            "SELECT * FROM fast_path_embedding_queue WHERE run_id = ? AND status = 'pending'"
            " ORDER BY class, request_index, position LIMIT ?",
            (self.run["id"], self.embedder.batch if self.embedder else 64)).fetchall()

    def should_stop(self):
        chain = self.flow._fast_chains.get(self.run["id"])
        if chain:
            self.cutoff = chain.cutoff()
        return (self.stopping or self.flow._stop_requested(self.run["id"], self.run["scope_revision"])
                or (self.cutoff is not None and self.store.clock.now() >= self.cutoff))

    async def consume(self):
        if self.warmup:
            await self.warmup
        if self.error or not self.embedder or not self.query:
            return
        try:
            while not self.should_stop():
                pending = self.pending()
                if not pending:
                    self.wake.clear()
                    await self.wake.wait()
                    continue
                if self.query_vector is None:
                    await self._query()
                    if self.error or self.should_stop():
                        return
                heads = self.store.work_heads(self.run["research_id"])
                targets = {row["source_version_id"]: heads.get(self.store.source(row["source_version_id"])["work_id"], row["source_version_id"])
                           for row in pending}
                stored = self.store.source_similarities(self.run["research_id"], self.run["scope_revision"], self.embedder.stored_model)
                ids = list(dict.fromkeys(svid for svid in targets.values() if svid not in stored))
                scores = {}
                if ids:
                    texts = ["\n\n".join([self.store.source(svid)["title"], *(p["text"] for p in self.store.passages_for(svid) if p["kind"] == "abstract")]) for svid in ids]
                    vectors = await self._embed(texts, "RETRIEVAL_DOCUMENT")
                    embeddings.same_dimension(vectors, len(self.query_vector))
                    scores = {svid: embeddings.similarity(self.query_vector, vector) for svid, vector in zip(ids, vectors)}
                with transaction(self.store.conn):
                    self.store.save_source_similarities(self.run["research_id"], self.run["scope_revision"], self.embedder.stored_model, scores)
                    for row in pending:
                        chain = self.flow._fast_chains.get(self.run["id"])
                        if chain and chain.past_cutoff():
                            self.store.conn.execute(
                                "UPDATE fast_path_embedding_queue SET status = 'unembedded_at_cutoff', cutoff_at = ?"
                                " WHERE run_id = ? AND source_version_id = ? AND status = 'pending'",
                                (fast_path.timestamp(self.store.clock), self.run["id"], row["source_version_id"]))
                            continue
                        self.store.conn.execute(
                            "UPDATE fast_path_embedding_queue SET status = ?, embedded_at = ?"
                            " WHERE run_id = ? AND source_version_id = ? AND status = 'pending'",
                            ("embedded" if targets[row["source_version_id"]] in scores else "from_store",
                             fast_path.timestamp(self.store.clock), self.run["id"], row["source_version_id"]))
                self.flow._checkpoint(self.run["id"], self.run["scope_revision"])
                await asyncio.sleep(0)
        except embeddings.EmbeddingError as exc:
            self.error = exc

    def notify(self):
        self.wake.set()

    async def stop(self):
        self.stopping = True
        self.notify()
        tasks = [task for task in (self.task, self.warmup) if task is not None]
        if tasks:
            # Let a batch finish; never leave a reply unread on the shared runner.
            await asyncio.gather(*tasks, return_exceptions=True)

    async def drain(self, pool):
        if self.closed:
            return
        deadline = fast_path.stage_deadline(self.store, self.run, "ranking")
        self.cutoff = deadline - timedelta(milliseconds=self.run["budget"]["fast_path"]["arrival_margin_ms"]) if deadline else None
        self.notify()
        chain = self.flow._fast_chains.get(self.run["id"])
        while ((self.pending() and self.task and not self.task.done()) or (chain and not chain.done())) and not self.should_stop():
            if chain:
                self.cutoff = chain.cutoff()
            self.flow._checkpoint(self.run["id"], self.run["scope_revision"])
            await asyncio.sleep(0.01)
        if chain:
            await chain.stop()
            chain.close_open("cutoff")
            heads = set(self.store.work_heads(self.run["research_id"]).values())
            pool = [c for c in self.store.candidates(self.run["research_id"], self.run["scope_revision"])
                    if c["origin"] != "user" and c["source_version_id"] in heads]
        await self.stop()
        if self.task and self.task.done() and not self.task.cancelled():
            error = self.task.exception()
            if error is not None:
                raise error
        self.flow._checkpoint(self.run["id"], self.run["scope_revision"])
        ts = fast_path.timestamp(self.store.clock)
        with transaction(self.store.conn):
            if chain:
                chain.summary()
            # Head changes or earlier-revision corpus records must also have an
            # explicit cutoff outcome; an unqueued source is not a success.
            stored = self.store.source_similarities(self.run["research_id"], self.run["scope_revision"], self.embedder.stored_model) if self.embedder else {}
            heads = self.store.work_heads(self.run["research_id"])
            for row in self.store.conn.execute(
                    "SELECT q.source_version_id, v.work_id FROM fast_path_embedding_queue q"
                    " JOIN source_versions v ON v.id = q.source_version_id"
                    " WHERE q.run_id = ? AND q.status = 'pending'", (self.run["id"],)).fetchall():
                if heads.get(row["work_id"], row["source_version_id"]) in stored:
                    self.store.conn.execute(
                        "UPDATE fast_path_embedding_queue SET status = 'from_store', embedded_at = ?"
                        " WHERE run_id = ? AND source_version_id = ? AND status = 'pending'",
                        (ts, self.run["id"], row["source_version_id"]))
            next_index = self.store.conn.execute("SELECT COALESCE(MAX(request_index), -1) + 1 FROM fast_path_embedding_queue WHERE run_id = ?", (self.run["id"],)).fetchone()[0]
            for pos, candidate in enumerate(pool):
                svid = candidate["source_version_id"]
                status = "from_store" if svid in stored else "unembedded_at_cutoff"
                self.store.conn.execute(
                    "INSERT OR IGNORE INTO fast_path_embedding_queue (run_id, class, request_index, position,"
                    " source_version_id, enqueued_at, status, embedded_at, cutoff_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)",
                    (self.run["id"], next_index, pos, svid, ts, status, ts if svid in stored else None,
                     ts if status == "unembedded_at_cutoff" else None))
            self.store.conn.execute("UPDATE fast_path_embedding_queue SET status = 'unembedded_at_cutoff', cutoff_at = ?"
                                    " WHERE run_id = ? AND status = 'pending'", (ts, self.run["id"]))
            rows = self.store.conn.execute("SELECT class, status, COUNT(*) AS n FROM fast_path_embedding_queue"
                                           " WHERE run_id = ? GROUP BY class, status", (self.run["id"],)).fetchall()
            counts = {status: sum(r["n"] for r in rows if r["status"] == status)
                      for status in ("embedded", "from_store", "unembedded_at_cutoff")}
            total = sum(counts.values())
            output = counts | {"sources": total, "enqueued": total, "missing": counts["unembedded_at_cutoff"],
                               "cutoff_at": ts, "embedded_share": (counts["embedded"] + counts["from_store"]) / total if total else None,
                               "by_class": {str(c): {r["status"]: r["n"] for r in rows if r["class"] == c} for c in (0, 1, 2)},
                               "query_origin": self.query[1] if self.query else english_question.MISSING,
                               "query_sha256": english_question.query_sha256(self.query[0]) if self.query else None}
            if self.embedder:
                output["model"] = self.embedder.stored_model
            status = "partial" if self.error and counts["embedded"] else "failed" if self.error else "succeeded"
            self.flow._finish_embedding_step(self.step["id"], status, output | self.budget.counts(), self.identity,
                error_code="embedding_failed" if self.error else None, error={"error": str(self.error)} if self.error else None)
        self.closed = True
