"""D59, D38: one author–year–title key per work, given once across the library.

Records are SYNTHETIC. Passing shows how keys are formed, kept and exposed; it says nothing about provider metadata quality.
"""

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.source_keys import key_stem
from deixis.workflow.store import Store


def record(rid, authors, year, doi=None, title="SYNTHETIC molecular channel", version_label="publishedVersion", merge_by_doi=True):
    return ProviderRecord(
        provider_record_id=rid, title=title, authors=authors, year=year, venue=None, publication_type=None, doi=doi,
        landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label=version_label, abstract=None,
        abstract_origin=None, identifiers={}, raw={}, merge_by_doi=merge_by_doi,
    )


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def key_of(store, svid):
    return store.source_key(store.source(svid)["work_id"])


@pytest.mark.parametrize(("authors", "title", "year", "expected"), [
    (["Zeng, X."], "Multiparity and outcomes", 2022, ("zeng2022multiparity", "author")),
    (["Tadashi Nakano"], "The molecular channel", 2013, ("nakano2013molecular", "author")),
    (["Farsad, N."], "", 2016, ("farsad2016", "author")),
    (["H. Birkan Yılmaz"], "Çok-yollu kanallar", 2016, ("yilmaz2016cokyollu", "author")),
    (["García-Márquez, Gabriel"], "A study", 2019, ("garciamarquez2019study", "author")),
    (["van der Waals, J."], "On the continuity", 1873, ("waals1873continuity", "author")),
    (["John Smith Jr."], "SYNTHETIC title", None, ("smithndsynthetic", "author")),
    (["CHAE, C.-B."], "Molecular MIMO", 2016, ("chae2016molecular", "author")),
    ([], "The Molecular Channel", 2019, ("molecular2019", "title")),
    ([], "Multiparty computation", None, ("multipartynd", "title")),
    ([], "", None, ("sourcend", "title")),
])
def test_key_stem(authors, title, year, expected):
    assert key_stem(authors, title, year) == expected


def test_colliding_keys_get_letters_and_the_first_keeps_its_key(store):
    first, _ = store.upsert_provider_source("openalex", record("W1", ["Tadashi Nakano"], 2013, doi="10.1/a"), None)
    second, _ = store.upsert_provider_source("openalex", record("W2", ["T. Nakano"], 2013, doi="10.1/b"), None)
    third, _ = store.upsert_provider_source("openalex", record("W3", ["nakano, t."], 2013, doi="10.1/c"), None)

    assert [key_of(store, s) for s in (first, second, third)] == ["nakano2013synthetic", "nakano2013syntheticb", "nakano2013syntheticc"]


def test_versions_of_one_work_share_its_key(store):
    arxiv = "10.48550/arxiv.1234.5678"
    v1, _ = store.upsert_provider_source("arxiv", record("A1", ["Ada Lovelace"], 2020, doi=arxiv, version_label="submittedVersion", merge_by_doi=False), None)
    v2, _ = store.upsert_provider_source("openalex", record("W9", ["Ada Lovelace"], 2021, doi=arxiv, version_label="submittedVersion", merge_by_doi=False), None)

    assert store.source(v1)["work_id"] == store.source(v2)["work_id"]
    assert key_of(store, v1) == key_of(store, v2) == "lovelace2020synthetic"


def test_an_upload_title_key_gives_way_to_authors_but_an_author_key_is_kept(store):
    svid = store.create_upload_source("Diffusion channels")
    assert key_of(store, svid) == "diffusionnd"

    store.enrich_source("crossref", svid, record("10.1/x", ["Alan Turing"], 1952))
    assert key_of(store, svid) == "turing1952diffusion"

    store.enrich_source("crossref", svid, record("10.1/y", ["Someone Else"], 1999))
    assert key_of(store, svid) == "turing1952diffusion"


def test_cleared_keys_are_given_again_oldest_work_first(store):
    from deixis.workflow.source_keys import assign_missing

    first, _ = store.upsert_provider_source("openalex", record("W1", ["Tadashi Nakano"], 2013, doi="10.1/a"), None)
    second, _ = store.upsert_provider_source("openalex", record("W2", ["T. Nakano"], 2013, doi="10.1/b"), None)
    store.conn.execute("UPDATE works SET source_key = NULL, source_key_basis = NULL")

    assert assign_missing(store) == 2
    assert [key_of(store, s) for s in (first, second)] == ["nakano2013synthetic", "nakano2013syntheticb"]
    assert assign_missing(store) == 0
