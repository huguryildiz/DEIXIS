"""The PDF waiting list, the institution proxy link and the proposed match of a dropped file (slice 18a).

Pure tests: no database, no network, no model. The records are SYNTHETIC and from two fields (greenhouse irrigation,
bakery logistics); passing shows the rules behave as the slice says, not that a person finds the list useful or that
a proxy login works (it was not tried: no institutional account).
"""

import pytest

from deixis.documents import identity
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

def test_the_three_waiting_codes_come_from_the_reason_table():
    assert set(fulltext.WAITING_CODES) == {"no_fulltext", "text_unreadable", "human_pdf_wrong"}
    assert all(REASON_CODES[code].next_step == "waiting_for_pdf" for code in fulltext.WAITING_CODES)


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


def test_a_person_s_pdf_wrong_keeps_the_work_listed_although_the_judged_file_s_text_is_still_there():
    judged = work("a", code=decision("human_pdf_wrong", "human"), has_text=True)
    # The text of another version counts: that work can be read and does not wait.
    readable = work("b", version("b2", has_text=True), code=decision("human_pdf_wrong", "human"))
    assert heads(fulltext.waiting([judged, readable], [PLAN])) == ["a"]


def test_any_other_decision_of_the_person_takes_the_work_off_the_list():
    for code in ("human_include", "human_criterion_not_met", "human_not_sure"):
        # The person's decision stands over a code's `no_fulltext` on another version.
        answered = work("a", version("a2", decision("no_fulltext")), code=decision(code, "human"))
        assert fulltext.waiting([answered], [PLAN]) == []


def test_the_person_s_newest_decision_is_the_one_that_speaks():
    older = version("a2", decision("human_not_sure", "human", created_at="2026-09-24T09:00:00.000Z"))
    newer = work("a", older, code=decision("human_pdf_wrong", "human", created_at="2026-09-24T11:00:00.000Z"))
    assert heads(fulltext.waiting([newer], [PLAN])) == ["a"]
    swapped = work("a", version("a2", decision("human_pdf_wrong", "human", created_at="2026-09-24T09:00:00.000Z")),
                   code=decision("human_not_sure", "human", created_at="2026-09-24T11:00:00.000Z"))
    assert fulltext.waiting([swapped], [PLAN]) == []


def test_two_decisions_of_the_person_in_the_same_millisecond_are_settled_by_the_order_they_were_written():
    same = "2026-09-24T10:00:00.000Z"
    first = work("a", version("a2", dict(decision("human_not_sure", "human", created_at=same), order=7)),
                 code=dict(decision("human_pdf_wrong", "human", created_at=same), order=9))
    assert fulltext.current_fulltext(first)["reason_code"] == "human_pdf_wrong"
    assert heads(fulltext.waiting([first], [PLAN])) == ["a"]
    second = work("a", version("a2", dict(decision("human_not_sure", "human", created_at=same), order=9)),
                  code=dict(decision("human_pdf_wrong", "human", created_at=same), order=7))
    assert fulltext.current_fulltext(second)["reason_code"] == "human_not_sure"
    assert fulltext.waiting([second], [PLAN]) == []


def test_a_stale_decision_lists_nothing_whoever_wrote_it():
    works = [work("a", code=decision("no_fulltext", stale=True)),
             work("b", code=decision("human_pdf_wrong", "human", stale=True))]
    assert fulltext.waiting(works, [PLAN]) == []


def test_a_work_with_text_on_any_version_does_not_wait():
    works = [work("a", code=decision("no_fulltext"), has_text=True),
             work("b", version("b2", has_text=True), code=decision("text_unreadable"))]
    assert fulltext.waiting(works, [PLAN]) == []


def test_a_work_the_plan_did_not_reach_has_no_decision_and_is_not_listed():
    works = [work("a", code=decision("no_fulltext")), work("b")]  # b: `not_reached`, no decision
    assert heads(fulltext.waiting(works, [{"works": ["a"], "not_reached": ["b"]}])) == ["a"]


def test_versions_at_opposite_fresh_decisions_are_the_queue_s_not_the_list_s():
    disagree = work("a", version("a2", decision("all_parts_verified", "model_agreement")),
                    code=decision("criterion_absent", "model_agreement"))
    assert fulltext.current_fulltext(disagree) is None
    assert fulltext.waiting([disagree], [PLAN]) == []


def test_the_order_is_the_newest_plan_s_then_an_older_plan_s_then_the_head():
    works = [work(head, code=decision("no_fulltext")) for head in ("z", "d", "b", "a", "y")]
    newest, older = {"works": ["d", "b"]}, {"works": ["a", "d", "z"]}
    rows = fulltext.waiting(works, [newest, older])
    assert heads(rows) == ["d", "b", "a", "z", "y"] and [row["place"] for row in rows] == [1, 2, 3, 4, 5]


def test_a_work_whose_head_changed_since_the_plan_keeps_its_place_through_its_other_version():
    moved = work("p1", version("pre", decision("no_fulltext")))  # the plan named the preprint, the work's head now p1
    first = work("q1", code=decision("no_fulltext"))
    assert heads(fulltext.waiting([first, moved], [{"works": ["pre", "q1"]}])) == ["p1", "q1"]


def test_no_plan_no_list():
    assert fulltext.waiting([work("a", code=decision("no_fulltext"))], []) == []


# ---- 2. the proxy ---------------------------------------------------------------------------------------------------

TEMPLATE = "https://login.proxy.synthetic.edu/login?qurl={url}"
PREFIX = "https://login.proxy.synthetic.edu/login?url="


@pytest.mark.parametrize("address", [TEMPLATE, PREFIX, "  https://proxy.synthetic.edu/{url}  "])
def test_a_https_template_or_prefix_is_kept(address):
    assert proxy.validate(address) == address.strip()


@pytest.mark.parametrize("address", [None, "", "   "])
def test_an_empty_address_clears_the_proxy(address):
    assert proxy.validate(address) is None


@pytest.mark.parametrize("address", [
    "http://login.proxy.synthetic.edu/login?url=",                 # not https
    "https://reader:secret@login.proxy.synthetic.edu/login?url=",  # a password
    "https://reader@login.proxy.synthetic.edu/login?url=",         # a user name
    "ftp://login.proxy.synthetic.edu/",
    "javascript:alert(1)//{url}",
    "https://{url}/login",                                         # the placeholder in the host
    "https://login.proxy.synthetic.edu/a?u={url}&v={url}",         # twice
    "https://login.proxy.synthetic.edu/login?url= x",              # a space
    "https:///login?url=",                                         # no host
    "https://login.proxy.synthetic.edu/login#{url}",               # the target in the fragment is never sent
    "https://login.proxy.synthetic.edu/login?url=#start",          # a prefix ending in a fragment
    "https://[bad/login?url=",                                     # not parsable
])
def test_a_proxy_address_that_is_not_plain_https_is_refused(address):
    with pytest.raises(proxy.ProxyRefused):
        proxy.validate(address)


def test_a_template_takes_the_whole_target_percent_encoded():
    target = "https://publisher.synthetic.org/doc?a=1&b=2#fragment"
    assert proxy.link(target, TEMPLATE) == ("https://login.proxy.synthetic.edu/login?qurl="
                                            "https%3A%2F%2Fpublisher.synthetic.org%2Fdoc%3Fa%3D1%26b%3D2%23fragment")


def test_a_prefix_takes_a_plain_target_as_it_is():
    target = "https://publisher.synthetic.org/doc/12345?view=full"
    assert proxy.link(target, PREFIX) == PREFIX + target


@pytest.mark.parametrize("target", ["https://publisher.synthetic.org/doc?a=1&b=2",
                                    "https://publisher.synthetic.org/doc#fragment"])
def test_a_prefix_takes_a_target_with_an_ampersand_or_a_fragment_encoded(target):
    built = proxy.link(target, PREFIX)
    assert built.startswith(PREFIX) and "&" not in built.removeprefix(PREFIX) and "#" not in built
    from urllib.parse import unquote
    assert unquote(built.removeprefix(PREFIX)) == target


def test_a_doi_with_special_characters_resolves_encoded_in_both_forms():
    doi = "10.1002/(sici)1097-4636(199709)36:3<342::aid-jbm11>3.0.co;2-g"
    url = proxy.doi_url(doi)
    assert url == "https://doi.org/10.1002/%28sici%291097-4636%28199709%2936%3A3%3C342%3A%3Aaid-jbm11%3E3.0.co%3B2-g"
    assert proxy.link(url, None) == url
    assert proxy.link(url, PREFIX) == PREFIX + url  # nothing left to break the proxy's own query
    assert proxy.link(url, TEMPLATE).endswith("https%3A%2F%2Fdoi.org%2F10.1002%2F%2528sici%2529"
                                              "1097-4636%2528199709%252936%253A3%253C342%253A%253Aaid-jbm11%253E3.0.co"
                                              "%253B2-g")
    assert proxy.doi_url("10.5555/a#b&c") == "https://doi.org/10.5555/a%23b%26c"


@pytest.mark.parametrize("target", [None, "", "javascript:alert(1)", "data:text/html,x", "https://", "a b",
                                    "https://[bad", "http://[::1"])
def test_a_stored_link_that_is_not_http_is_never_turned_into_a_link(target):
    assert proxy.link(target, PREFIX) is None and proxy.link(target, None) is None


# ---- 3. the proposed work (the multi-DOI rule) -------------------------------------------------------------------

IRRIGATION = {"id": "sv1", "work_id": "w1", "doi": "10.5555/irrigation.1",
              "title": "SYNTHETIC moisture threshold irrigation of greenhouse benches"}
IRRIGATION_PRE = dict(IRRIGATION, id="sv1p", doi="10.48550/arxiv.2601.00001")
BAKERY = {"id": "sv2", "work_id": "w2", "doi": "10.5555/bakery.2", "title": "SYNTHETIC delivery rounds of a small town bakery"}
SOURCES = [IRRIGATION, IRRIGATION_PRE, BAKERY]


def test_one_work_s_doi_on_the_first_page_proposes_that_version():
    assert identity.propose("SYNTHETIC https://doi.org/10.5555/irrigation.1 page", SOURCES) == ("sv1", "doi")
    assert identity.propose("SYNTHETIC arXiv:2601.00001 page", SOURCES) == ("sv1p", "doi")


def test_the_title_proposes_when_no_doi_is_named():
    text = "Journal of SYNTHETIC studies\nSYNTHETIC moisture threshold irrigation of greenhouse benches\nA. Author"
    assert identity.propose(text, SOURCES) == ("sv1", "title")


def test_two_works_dois_on_the_first_page_let_the_title_decide():
    text = ("SYNTHETIC moisture threshold irrigation of greenhouse benches\nhttps://doi.org/10.5555/irrigation.1\n"
            "see also https://doi.org/10.5555/bakery.2")
    assert identity.propose(text, SOURCES) == ("sv1", "title")
    # The rule `match_pdf_to_source` keeps for `legacy`: the first DOI found in candidate order decides.
    assert identity.match_pdf_to_source(text, [BAKERY, IRRIGATION]) == ("sv2", "doi")


def test_two_works_dois_and_no_single_title_propose_nothing():
    text = "SYNTHETIC cover https://doi.org/10.5555/irrigation.1 and https://doi.org/10.5555/bakery.2"
    assert identity.propose(text, SOURCES) == (None, None)


def test_a_file_that_names_no_candidate_proposes_nothing():
    assert identity.propose("SYNTHETIC unrelated notes on river gauges", SOURCES) == (None, None)
