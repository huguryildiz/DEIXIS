"""A work whose PDF sits on another version than its screened abstract still gives the answer its abstract (D112).

SYNTHETIC data only."""

from types import SimpleNamespace

from deixis.providers.common import ProviderRecord
from deixis.workflow import fast_answer
from test_fast_path_answer import answer_run, cutoff, setup


def sibling_with_pdf(lib, head):
    """A SYNTHETIC second version of `head`'s work that holds a PDF but was never abstract-screened."""
    record = ProviderRecord(provider_record_id="pdf-sibling", title="SYNTHETIC pdf sibling", authors=[], year=None,
                            venue=None, publication_type=None, doi=None, landing_url=None, oa_pdf_url=None,
                            oa_pdf_version=None, version_label=None, abstract=None, abstract_origin="provider",
                            identifiers={}, raw={})
    svid, _ = lib.store.upsert_provider_source("known_list", record, None)
    lib.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?",
                           (lib.store.source(head)["work_id"], svid))
    lib.store.add_to_corpus(lib.rid, svid, "search")
    pages = ["SYNTHETIC page text one.", "SYNTHETIC page text two."]
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=len(pages),
                                 pages=[SimpleNamespace(text=t, physical_page=n, printed_label=None)
                                        for n, t in enumerate(pages, 1)])
    lib.store.add_asset_with_pages(svid, "sha-sibling", 100, "sibling.pdf", "download", None, "sibling.pdf",
                                   extraction, "test", lambda t: [(0, len(t), t)])
    return svid


def test_an_unread_pdf_on_a_sibling_version_does_not_drop_the_screened_abstract(tmp_path):
    lib = setup(tmp_path)
    (head,) = lib.sources
    pdf = sibling_with_pdf(lib, head)
    assert lib.store.answer_version(lib.rid, head) == pdf  # the rule that sends the work to the unscreened version
    frozen = cutoff(lib)
    (row,) = frozen["items"]
    assert row["reason"] is None and row["route"] == "abstract"
    assert row["source_version_id"] == head and row["abstract_ids"]
    plan = fast_answer.input_plan(lib.flow, answer_run(lib), lib.store.scope(lib.rid))
    assert [r["work_id"] for r in plan["items"]] == [row["work_id"]]
    assert plan["passage_ids"]
