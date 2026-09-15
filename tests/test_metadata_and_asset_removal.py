from types import SimpleNamespace

from deixis.providers import crossref
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store


def sparse_record() -> ProviderRecord:
    return ProviderRecord(
        provider_record_id="seed", title="Exact title", authors=[], year=None, venue=None,
        publication_type=None, doi="10.1/test", landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label="publishedVersion", abstract=None, abstract_origin=None, identifiers={}, raw={},
    )


def test_crossref_details_enrich_a_sparse_exact_doi_record(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid, _ = store.upsert_provider_source("known_list", sparse_record(), None)
    record = crossref.record_from_item({
        "DOI": "10.1/test", "title": ["Exact title"],
        "author": [{"given": "Ada", "family": "Lovelace"}, {"given": "Alan", "family": "Turing"}],
        "issued": {"date-parts": [[2024]]}, "container-title": ["Journal of Exact Records"],
        "type": "journal-article", "URL": "https://doi.org/10.1/test", "volume": "12", "issue": "3", "page": "41-59",
    })

    store.enrich_source("crossref", svid, record)

    source = store.source(svid)
    assert source["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert (source["year"], source["venue"], source["volume"], source["issue"], source["pages"]) == (
        2024, "Journal of Exact Records", "12", "3", "41-59",
    )
    assert store.find_source_by_identifier("crossref", "10.1/test") == svid


def test_removed_asset_is_excluded_from_future_retrieval_and_stales_answers(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("Question?", "academic", "quick", ["crossref"], "fake", "m", "en")
    svid, _ = store.upsert_provider_source("known_list", sparse_record(), None)
    store.add_to_corpus(rid, svid, "search", selection_state="included", selection_origin="user")
    extraction = SimpleNamespace(
        status="succeeded", error=None, page_count=1,
        pages=[SimpleNamespace(text="Wrong document text", physical_page=1, printed_label=None)],
    )
    asset_id = store.add_asset_with_pages(
        svid, "abc", 100, "abc.pdf", "user_upload", None, "wrong.pdf", extraction, "test",
        lambda text: [(0, len(text), text)],
    )
    before = store.selection_revision(rid)

    store.remove_asset(rid, svid, asset_id)

    assert not store.has_asset(svid)
    assert store.passages_for(svid) == []
    assert store.asset(asset_id)["removed_at"] is not None
    assert store.selection_revision(rid) == before + 1

