"""The PDF waiting list, the institution proxy link and the proposed match of a dropped file (slice 18a).

Pure tests: no database, no network, no model. The records are SYNTHETIC and from two fields (greenhouse irrigation,
bakery logistics); passing shows the rules behave as the slice says, not that a person finds the list useful or that
a proxy login works (it was not tried: no institutional account).
"""

import pytest

from deixis.domain import proxy
from deixis.domain.reason_codes import REASON_CODES
from deixis.workflow import fulltext


def decision(code, decided_by="code", stale=False, created_at="2026-09-24T10:00:00.000Z"):
    return {"reason_code": code, "decided_by": decided_by, "stale": stale, "created_at": created_at}


def version(svid, code=None, has_text=False):
    return {"id": svid, "has_text": has_text, "fulltext": code}


def work(head, *others, code=None, has_text=False):
    return {"work_id": f"wrk_{head}", "head": head, "versions": [version(head, code, has_text), *others]}


PLAN = {"works": ["a", "b", "c", "d", "e", "f"]}


def heads(rows):
    return [row["head"] for row in rows]


# ---- 1. the list -------------------------------------------------------------------------------------------------


def test_each_waiting_code_lists_the_work_and_no_other_code_does():
    works = [work("a", code=decision("no_fulltext")), work("b", code=decision("text_unreadable")),
             work("c", code=decision("human_pdf_wrong", "human"))]
    others = [work(code, code=decision(code, entry.decided_by if entry.decided_by == "human" else "code"))
              for code, entry in REASON_CODES.items()
              if entry.stage == "fulltext" and entry.next_step != "waiting_for_pdf"]
    rows = fulltext.waiting(works + others, [PLAN])
    assert heads(rows) == ["a", "b", "c"]
    assert [row["reason_code"] for row in rows] == ["no_fulltext", "text_unreadable", "human_pdf_wrong"]
    assert [row["place"] for row in rows] == [1, 2, 3]


# ---- 2. the proxy ---------------------------------------------------------------------------------------------------

PREFIX = "https://login.proxy.synthetic.edu/login?url="


@pytest.mark.parametrize("address", [
    "http://login.proxy.synthetic.edu/login?url=",                 # not https
])
def test_a_proxy_address_that_is_not_plain_https_is_refused(address):
    with pytest.raises(proxy.ProxyRefused):
        proxy.validate(address)


@pytest.mark.parametrize("target", [None, "", "javascript:alert(1)"])
def test_a_stored_link_that_is_not_http_is_never_turned_into_a_link(target):
    assert proxy.link(target, PREFIX) is None and proxy.link(target, None) is None


# ---- 3. the proposed work (the multi-DOI rule) -------------------------------------------------------------------

IRRIGATION = {"id": "sv1", "work_id": "w1", "doi": "10.5555/irrigation.1",
              "title": "SYNTHETIC moisture threshold irrigation of greenhouse benches"}
IRRIGATION_PRE = dict(IRRIGATION, id="sv1p", doi="10.48550/arxiv.2601.00001")
BAKERY = {"id": "sv2", "work_id": "w2", "doi": "10.5555/bakery.2", "title": "SYNTHETIC delivery rounds of a small town bakery"}
SOURCES = [IRRIGATION, IRRIGATION_PRE, BAKERY]


