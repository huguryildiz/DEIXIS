"""One OpenAlex spending cap shared by benchmark runners working at the same time (D163 M1 measurement).

A runner reserves, before each question it starts and under an exclusive file lock, the most that question can cost:
`question_bound_usd`, every OpenAlex request the frozen limits of its depth allow (counts, keyword pages, semantic
requests, the chain's attempt limit, lookups), each with its rate-limit and network retries, at the prices the owner
read from OpenAlex. The reservation stays open until the runner has seen the product run stopped; a run whose state is
unknown keeps it for good. Every reading of OpenAlex's balance (daily plus prepaid) adds the drop since the last
reading to the spend; a rise (the daily allowance reset, or a top-up) hides the spending since that reading, so the
open reservations are counted as spent then. A reservation is refused once spend so far plus every open reservation
plus the new one would pass the cap. The product sends a question's requests itself, so a question is the smallest
unit a runner can reserve for; the bound is what makes that unit safe.
"""
from __future__ import annotations

import fcntl
import json
import uuid
from contextlib import contextmanager
from pathlib import Path


PRICE_CLASSES = ('count', 'list', 'search', 'semantic')


def question_requests(effort):
    """The most OpenAlex requests of each price class one discovery run of `effort` can send before its list freezes,
    read from the limits the run freezes: count probes (the code vocabulary's, and the model query's for each checked
    attempt), keyword pages for every query the depth allows, semantic requests (the question, the block terms, every
    seed PDF), and list requests (the chain's attempt limit, routing, seed matches), each with its rate-limit and
    network retries where they are not already in the limit."""
    from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES, PROVIDER_WAIT, SW_READ_LIMIT, TEST_EFFORT_BUDGETS
    from deixis.providers.openalex import MAX_RESULTS
    from deixis.workflow.run import fast_path
    from deixis.workflow.run.store import MAX_SEEDS
    from deixis.workflow.search import chaining, search_query, vocabulary

    retries = (1 + PROVIDER_WAIT[effort]) * (1 + MAX_TRANSIENT_NETWORK_RETRIES)
    policy = fast_path.freeze_budget({}, effort)
    pages = -(-SW_READ_LIMIT[effort] // MAX_RESULTS)
    # The model query's counts are read once per checked attempt; the product allows ATTEMPTS of them.
    return {'count': (vocabulary.MAX_PROBES + search_query.MAX_COUNT_REQUESTS * search_query.ATTEMPTS + 1) * retries,
            'search': TEST_EFFORT_BUDGETS[effort].max_provider_requests * pages * retries,
            'semantic': (2 + MAX_SEEDS) * retries,
            'list': chaining.attempt_limit(policy, effort) + (1 + MAX_SEEDS) * retries}


def question_bound_usd(effort, prices):
    """The most one question can cost at `prices` (USD per request of each class in PRICE_CLASSES)."""
    if missing := [c for c in PRICE_CLASSES if c not in prices]:
        raise ValueError(f'no price for {missing}')
    return sum(n * prices[c] for c, n in question_requests(effort).items())


class Refused(Exception):
    """The cap would be passed; no new question may start."""


class Ledger:
    def __init__(self, path, cap_usd, reserve_usd, balance):
        """`balance()` returns OpenAlex's daily plus prepaid USD now, or None when OpenAlex did not state it."""
        self.path, self.cap, self.reserve_usd, self.balance = Path(path), cap_usd, reserve_usd, balance
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _state(self):
        with open(self.path.with_suffix('.lock'), 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(self.path.read_text()) if self.path.exists() else None
                if state is None:
                    start = self.balance()
                    if start is None:
                        raise Refused('OpenAlex did not state its balance')
                    state = {'cap_usd': self.cap, 'last_balance_usd': start, 'spent_usd': 0.0, 'open': {}}
                if state['cap_usd'] != self.cap:
                    raise Refused(f"ledger cap is {state['cap_usd']} USD, not {self.cap}")
                yield state
                self.path.write_text(json.dumps(state, indent=1))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _reconcile(self, state):
        now = self.balance()
        if now is None:
            raise Refused('OpenAlex did not state its balance')
        last = state['last_balance_usd']
        # A drop is spending; a rise is a reset or a top-up that hides the spending since the last reading, which the
        # open reservations bound.
        state['spent_usd'] = round(state['spent_usd'] + (last - now if now <= last else sum(state['open'].values())), 6)
        state['last_balance_usd'] = now

    def reserve(self, who):
        """A reservation token for one question, or Refused."""
        with self._state() as state:
            self._reconcile(state)
            held = sum(state['open'].values())
            if state['spent_usd'] + held + self.reserve_usd > self.cap:
                raise Refused(f"cap {self.cap} USD: spent {state['spent_usd']:.4f}, reserved {held:.4f}")
            token = f'{who}:{uuid.uuid4().hex[:8]}'
            state['open'][token] = self.reserve_usd
            return token

    def settle(self, token):
        """Close a reservation once its run is seen stopped, after recording the spend OpenAlex now reports."""
        with self._state() as state:
            self._reconcile(state)
            state['open'].pop(token, None)
            return state['spent_usd']
