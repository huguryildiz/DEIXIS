"""One OpenAlex spending cap shared by benchmark runners working at the same time.

A runner reserves, before each question it starts and under an exclusive file lock, the most that question can cost:
`question_bound_usd`, the OpenAlex requests the frozen limits of its depth allow through first-answer work and
queued full-text fetches, including rate-limit, network, and redirect attempts where allowed. Its full-text term
assumes one source version per work; the product has no version-count cap, so it is not an absolute spending ceiling
for a research with multiple versions of one work. The reservation stays
open until the runner has seen the product run stopped; a run whose state is
unknown keeps it for good. Every reading of OpenAlex's balance (daily plus prepaid) adds the drop since the last
reading to the spend; a rise (the daily allowance reset, or a top-up) hides the spending since that reading, so the
open reservations are counted as spent then. A reservation is refused once spend so far plus every open reservation
plus the new one would pass the cap. The product sends a question's requests itself, so a question is the smallest
unit a runner can reserve for. A separate later run needs its own reservation.

`openalex_prices.json`, beside this file, distinguishes measured reply-header prices from the published content
download price. One credit is 0.0001 USD.
"""
from __future__ import annotations

import fcntl
import json
import uuid
from contextlib import contextmanager
from pathlib import Path


PRICE_CLASSES = ('count', 'list', 'search', 'semantic', 'group_by_search',
                 'doi_lookup', 'content_lookup', 'content')


def question_requests(effort):
    """OpenAlex requests a discovery can send through its first answer and queued full-text work.

    K works hold slots at once. Failed fetches release slots, so up to N window works can be tried; an unknown
    attempt can restart through the background queue up to the work-attempt limit. Each work may have multiple
    source versions, whose count is not capped by depth; this models one version per work.
    """
    from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES
    from deixis.providers.openalex import MAX_RESULTS
    from deixis.documents.fetch import MAX_REDIRECTS
    from deixis.workflow.run import fast_path
    from deixis.workflow.read.fulltext import FULLTEXT_WORK_ATTEMPTS
    from deixis.workflow.run.store import MAX_SEEDS
    from deixis.workflow.search import chaining, search_query, vocabulary

    policy = fast_path.freeze_budget({}, effort)
    shared = lambda key: fast_path.search_read(policy, effort, key)
    retries = (1 + shared('provider_wait')) * (1 + MAX_TRANSIENT_NETWORK_RETRIES)
    pages = -(-shared('read_limit_per_query') // min(shared('keyword_page_size'), MAX_RESULTS))
    # Slot refill can traverse N works; foreground and background share each work's capped attempts.
    works = fast_path.MODES[effort].read_top * FULLTEXT_WORK_ATTEMPTS
    # The model query's counts are read once per checked attempt; the product allows ATTEMPTS of them.
    return {'count': (vocabulary.MAX_PROBES + search_query.MAX_COUNT_REQUESTS * search_query.ATTEMPTS + 1) * retries,
            'search': (shared('max_provider_requests') * pages + shared('phrase_searches')) * retries,
            'semantic': (2 + MAX_SEEDS + shared('phrase_searches')) * retries,
            'group_by_search': retries,
            'list': chaining.attempt_limit(policy, effort) + MAX_SEEDS * retries,
            'doi_lookup': works, 'content_lookup': works,
            'content': works * (MAX_REDIRECTS + 1)}


def question_bound_usd(effort, prices):
    """One-version-per-work allowance at `prices` (USD per class in PRICE_CLASSES)."""
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
