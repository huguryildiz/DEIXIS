"""Short semantic searches beside the plan (`fast_path.PHRASE_SEARCH_RULE`).

One model step writes a few short plain phrases from the question alone, and each phrase is sent to OpenAlex semantic
search as a request of its own. The records join the pool like any search record, each phrase request a query list of
its own. The route never holds the run up:

- The phrase step goes through no limiter the plan uses, and its calls are given on top of the run's preset. On a
  connection that answers one call at a time (a model this computer runs) the step is not asked at all.
- The step is given the question and its English sentence only: no steering, no record.
- A phrase request goes out only after the question's own semantic request was handed to the HTTP client, through the
  same semantic call and its pacer, one phrase at the pacer at a time; the keyword search never waits for one.
- At the protocol freeze an unfinished phrase step is cancelled, not waited for. At the search stage's own deadline
  every phrase request still waiting or in flight is closed and recorded as cancelled, and a reply that comes after
  that deadline is not written.
- A failed or refused phrase step leaves the run going without the route; the reason is stored and frozen.

A phrase request is marked running before it can go out, so one a crash cut is `outcome_unknown` and one a pause cut is
cancelled: a resumed run reads stored phrases, failures and cancellations back and repeats none of them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from deixis.domain.rules import step_model
from deixis.models.openai_compat import LOCAL_CONNECTIONS
from deixis.providers import common, openalex
from deixis.workflow.run import fast_path
from deixis.workflow.search import search as fast_search

STEP_KEY = "search_phrases"  # the phrase step's operation key
TASK = "search_phrases"  # its task type
KIND = "provider_search:openalex"  # the step kind of one phrase request
# Why a phrase step or request ended without its work, as its step records it.
FROZEN = "protocol_frozen"  # the protocol froze before the phrase step answered
CUTOFF = "search_cutoff"  # the search stage ended before the request answered
NOT_SENT = "question_request_not_sent"  # the question's own request never went out, so no phrase follows it
UNKNOWN = "phrase_step_outcome_unknown"  # a crash left the phrase call without an outcome
SERIAL = "serial_model_connection"  # the connection answers one call at a time, so the call would hold up the plan
INTERRUPTED = "phrase_request_interrupted"  # a pause cut the request after it was started
# Connections that answer one call at a time: a phrase call there would queue the plan's own calls behind it.
SERIAL_CONNECTIONS = LOCAL_CONNECTIONS
# How often, in seconds at most, the deadline watch looks at the search stage's deadline again.
WATCH_SECONDS = 0.25


class LateReply(Exception):
    """A phrase reply came after the search stage's deadline: it is not written."""


class _InTime:
    """Awaited by the page sender between the reply and its write: raises `LateReply` once the deadline has passed."""

    def __init__(self, past):
        self.past = past

    def __await__(self):
        if self.past():
            raise LateReply()
        return None
        yield  # a generator, so this is awaitable without a coroutine that could be left unawaited


def requests(phrases: list[dict[str, Any]], rule: dict[str, Any], years: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One OpenAlex semantic request per phrase, in the step's order, each carrying the run's date scope."""
    return [fast_search.with_date_scope(
        {"index": index, "provider_id": "openalex", "endpoint": "semantic",
         "query_text": openalex.semantic_text(phrase["text"]), "limit": rule["records"],
         "kind": phrase["kind"]}, years)
            for index, phrase in enumerate(phrases)]


class Route:
    """The short phrase searches of one discovery run, from the run's start to the end of its search stage."""

    def __init__(self, flow: Any, run: dict[str, Any], scope: dict[str, Any], first_request: asyncio.Future,
                 handed: asyncio.Event | None = None):
        self.flow, self.run, self.scope = flow, run, scope
        self.rule = fast_path.phrase_search(run["budget"])
        self.first_request = first_request  # the question's own semantic request
        self.handed = handed or asyncio.Event()  # set once that request is with the HTTP client
        self.watcher: asyncio.Task | None = None  # the watch on the search stage's deadline
        self.model_task: asyncio.Task | None = None  # the phrase step
        self.sender: asyncio.Task | None = None  # the task that opens the phrase requests
        self.tasks: dict[int, asyncio.Task] = {}  # one task per phrase request, by phrase place
        self.reason: str | None = None  # why the route sends nothing, once that is known
        self.closed = False  # the search stage has ended

    def start(self) -> None:
        """Ask for the phrases now, beside the question's own request, and send each once it is allowed to go."""
        self.model_task = asyncio.create_task(self._phrases())
        self.sender = asyncio.create_task(self._send())

    def _frozen(self) -> dict[str, Any] | None:
        """What this run's frozen protocol holds of the route (empty where it froze none), or None while the run has
        frozen no protocol."""
        body = fast_search.frozen_body(self.flow.store, self.run)
        return ((body.get("fast_path_search") or {}).get("phrase_search") or {}) if body is not None else None

    async def _phrases(self) -> list[dict[str, Any]] | None:
        """The phrases, read back where this run already has them, else asked of the model once; None without."""
        from deixis.workflow.run.flow import OptionalStepFailed
        store, run_id = self.flow.store, self.run["id"]
        frozen = self._frozen()
        if frozen is not None:
            # A frozen body is the record of what this run searches: its phrases, or none, never a new ask.
            if frozen.get("status") == "ready":
                return frozen["phrases"]
            self.reason = frozen.get("reason") or "not_frozen"
            return None
        step = store.existing_step(run_id, STEP_KEY)
        if step is not None and step["status"] == "succeeded":
            return step["output"]["result"]["phrases"]
        if step is not None and step["status"] in ("failed", "cancelled", "outcome_unknown"):
            # A stored failure, cancellation or unknown outcome is not asked again: the route is skipped.
            self.reason = UNKNOWN if step["status"] == "outcome_unknown" else step["error_code"] or step["status"]
            return None
        model = step_model(self.scope, TASK)
        if model[0] in SERIAL_CONNECTIONS:
            # One call at a time: the phrase call would make translation, criterion and query wait. Not asked.
            self.reason = SERIAL
            step = store.step(run_id, STEP_KEY, f"model:{TASK}")
            store.finish_step(step["id"], "cancelled", error_code=SERIAL)
            return None
        english = store.english_question(self.run["research_id"], self.run["scope_revision"])
        # The English sentence as it stands when the step starts, stored with its input and kept for any repair.
        target = {"count": self.rule["count"], "english_question": english["text"] if english else None}

        def build(step_id: str) -> dict[str, Any]:
            """The step's input: the question and the phrase target; no record and no steering."""
            return self.flow._step_input(self.run, self.scope, step_id, TASK, [], [], [], [], model) | {
                "phrase_target": target, "user_steering": []}
        try:
            # No limiter: the plan's calls never wait behind this one. A short budget or the spend threshold skips it.
            answer = await self.flow._model_step(self.run, self.scope, STEP_KEY, TASK, model=model, optional=True,
                                                 budget_short="skip", spend_short="skip", step_input_builder=build)
        except OptionalStepFailed as failed:
            self.reason = failed.reason
            self._close_step(failed.reason, "failed")
            return None
        if answer.get("cutoff") or answer.get("invalid"):
            # A refused answer after its repair, a skipped call or a cut one: the run goes on without the route.
            self.reason = "model_read_cutoff" if answer.get("cutoff") else (
                "budget_exhausted" if answer.get("not_reached") else "invalid_model_output")
            return None
        return answer["result"]["phrases"]

    def _close_step(self, reason: str, status: str) -> None:
        """Close the phrase step as `status` with `reason` where it is still open, with any model call still out."""
        store, run_id = self.flow.store, self.run["id"]
        step = store.step(run_id, STEP_KEY, f"model:{TASK}")
        if step["status"] not in ("pending", "running"):
            return
        sessions = store.conn.execute("SELECT id FROM model_sessions WHERE step_id = ? AND status = 'started'",
                                      (step["id"],)).fetchall()
        for session in sessions:
            # A call cut while out may have reached the model: whether it was sent is not known.
            store.finish_model_session(session["id"], status="outcome_unknown", request_sent=None)
        store.finish_step(step["id"], status, error_code=reason,
                          delivery_class="after_send_unknown" if sessions else None)

    def _result(self) -> list[dict[str, Any]] | None:
        """The phrases the step gave, or None while it has not, or where it gave none."""
        task = self.model_task
        if task is None or not task.done() or task.cancelled() or task.exception() is not None:
            return None
        return task.result()

    async def freeze(self) -> dict[str, Any]:
        """What the protocol freezes of the route. An unfinished phrase step is cancelled here and not waited for, so a
        late answer is never sent; the reason is frozen instead of the phrases."""
        task = self.model_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.reason = FROZEN
            self._close_step(FROZEN, "cancelled")
        phrases = self._result()
        record = {"rule": self.rule["rule"], "count": self.rule["count"], "records": self.rule["records"]}
        if phrases is None:
            return record | {"status": "not_written", "reason": self.reason}
        years = self.run["budget"]["fast_path"].get("date_scope")
        return record | {"status": "ready", "phrases": phrases, "requests": requests(phrases, self.rule, years)}

    def _specs(self) -> list[dict[str, Any]]:
        """The phrase requests of this run: the frozen ones once the protocol is frozen, else the step's own."""
        frozen = self._frozen()
        if frozen is not None:
            return list(frozen.get("requests") or [])
        phrases = self._result()
        years = self.run["budget"]["fast_path"].get("date_scope")
        return requests(phrases, self.rule, years) if phrases else []

    def _question_sent(self) -> bool:
        """Whether the question's own semantic request is stored as really sent: it answered, or it ended without an
        answer after a send its record shows. A failure stopped before the send (a quota block, a stop at the pacer,
        no key) is no evidence, and nor is an outcome a crash left unknown with no send recorded."""
        step = self.flow.store.existing_step(self.run["id"], "search:fast:semantic")
        if step is None:
            return False
        if step["status"] == "succeeded":
            return True  # an answer came back, so the request went out
        if step["status"] not in ("failed", "outcome_unknown"):
            return False
        # The transport's own count of sends, or a delivery class only a sent request can have.
        sends = (((step.get("output") or {}).get("transport") or {}).get("sends")) or 0
        return sends > 0 or step.get("delivery_class") not in (None, "before_send")

    def _past_cutoff(self) -> bool:
        """Whether the search stage's own deadline has passed."""
        store = self.flow.store
        deadline = fast_path.stage_deadline(store, self.run, "search")
        return deadline is not None and store.clock.now() >= deadline

    @staticmethod
    async def _first(task: asyncio.Future, event: asyncio.Event) -> None:
        """Wait until `event` is set or `task` has ended, whichever comes first."""
        waiter = asyncio.ensure_future(event.wait())
        try:
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()

    async def _send(self) -> None:
        """Open each phrase request once the question's own request has gone out and the phrases exist."""
        store, run_id = self.flow.store, self.run["id"]
        # The question's own request passes the pacer first; once it is with the client its reply is not waited for.
        await self._first(self.first_request, self.handed)
        if not self.handed.is_set() and not self._question_sent():
            self.reason = self.reason or NOT_SENT
            return
        await asyncio.wait({self.model_task})
        specs = self._specs()
        if not specs:
            return
        send_page = fast_search.page_sender(self.flow, self.run, self.scope, {}, False, {"failure": None,
                                                                                          "s2_task": None})
        for spec in specs:
            if self.closed:
                return
            step = store.existing_step(run_id, fast_search.phrase_key(spec["index"]))
            if step is not None and step["status"] != "pending":
                continue  # answered, failed, cancelled or cut before: never sent again
            handed = asyncio.Event()
            task = asyncio.create_task(self._request(send_page, spec, handed))
            self.tasks[spec["index"]] = task
            # One phrase at the pacer at a time: the next goes to it only once this one is with the client or has
            # ended, so a seed or planned semantic request never queues behind all of them.
            await self._first(task, handed)
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def _request(self, send_page: Any, spec: dict[str, Any], handed: asyncio.Event) -> None:
        """Send one phrase request and record it as any search page is recorded."""
        store, run_id = self.flow.store, self.run["id"]
        key = fast_search.phrase_key(spec["index"])
        # Opened before it is sent: before this run's freeze it carries no protocol hash, after it this run's own.
        step = store.step(run_id, key, KIND, protocol_hash=fast_search.frozen_protocol_hash(store, self.run))
        if step["status"] == "pending":
            # Running before it can go out: a crash from here on leaves it `outcome_unknown`, which no resume resends.
            store.start_step(step["id"])
        token = common.on_handed.set(handed.set)  # this request's own attempts only: the variable is per task
        try:
            # A reply after the deadline is not written (`_InTime` between the reply and its write).
            result, _ = await send_page(spec, key, limit=spec["limit"], klass=fast_search.PHRASE_CLASS,
                                        index=spec["index"], terminal="single_page", after=_InTime(self._past_cutoff))
        except LateReply:
            result = None
        finally:
            common.on_handed.reset(token)
        if result is None and not self.flow._stop_requested(run_id, self.run["scope_revision"]):
            # Not written: the search stage's own time ran out at the pacer or before the reply came.
            fast_search.cancel_step(store, run_id, key, KIND, CUTOFF, ("pending", "running"))
        consumer = self.flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()

    def watch(self) -> None:
        """From the start of the search stage, close the route at that stage's own deadline."""
        self.watcher = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        store = self.flow.store
        while not self.closed:
            deadline = fast_path.stage_deadline(store, self.run, "search")
            if deadline is None:
                return  # no deadline: the route closes when the search stage ends
            left = (deadline - store.clock.now()).total_seconds()
            if left <= 0:
                await self.close()
                return
            # Looked at again, as the deadline is read from the run's own clock and stage record.
            await asyncio.sleep(min(left, WATCH_SECONDS))

    async def _cancel_sending(self) -> None:
        """Stop the sender and every phrase request still waiting at the pacer or in flight."""
        tasks = [task for task in (self.sender, *self.tasks.values()) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _stop_watch(self) -> None:
        """Stop the deadline watch, unless it is the caller."""
        if self.watcher is not None and self.watcher is not asyncio.current_task() and not self.watcher.done():
            self.watcher.cancel()

    async def close(self) -> None:
        """The search stage has ended or reached its deadline: every phrase request without an answer is closed and
        recorded as cancelled, so nothing is sent or written late and a resume sends none of them."""
        self.closed = True
        self._stop_watch()
        await self._cancel_sending()
        store, run_id = self.flow.store, self.run["id"]
        for spec in self._specs():
            # A request never started, one waiting at the pacer and one in flight all end here.
            fast_search.cancel_step(store, run_id, fast_search.phrase_key(spec["index"]), KIND,
                                    self.reason or CUTOFF, ("pending", "running"))

    async def stop(self) -> None:
        """The run stopped or ended: a request never started stays pending, so a resume sends it; one already started
        is closed as interrupted, as it may have gone out. The phrase step is waited for, as the criterion's
        proposals are, so its call is recorded under its own step."""
        self._stop_watch()
        await self._cancel_sending()
        store, run_id = self.flow.store, self.run["id"]
        for spec in self._specs():
            key = fast_search.phrase_key(spec["index"])
            if store.existing_step(run_id, key) is not None:  # only a request this route opened
                fast_search.cancel_step(store, run_id, key, KIND, INTERRUPTED, ("running",))
        if self.model_task is not None:
            await asyncio.gather(self.model_task, return_exceptions=True)
