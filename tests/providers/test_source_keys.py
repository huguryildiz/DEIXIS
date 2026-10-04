"""D59: one short author–year key per work, given once across the library.

Records are SYNTHETIC. Passing shows how keys are formed, kept and exposed; it says nothing about provider metadata quality.
"""

import shutil

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.source_keys import key_stem
from deixis.workflow.store import Store

REAL_MIGRATIONS = db.MIGRATIONS_DIR


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
    (["Tadashi Nakano"], "", 2013, ("Nakano13", "author")),
    (["Farsad, N."], "", 2016, ("Farsad16", "author")),
    (["H. Birkan Yılmaz"], "", 2016, ("Yilmaz16", "author")),
    (["García-Márquez, Gabriel"], "", 2019, ("GarciaMarq19", "author")),
    (["van der Waals, J."], "", 1873, ("Waals73", "author")),
    (["John Smith Jr."], "", None, ("Smithnd", "author")),
    (["CHAE, C.-B."], "", 2016, ("Chae16", "author")),
    ([], "The Molecular Channel", 2019, ("Molecular19", "title")),
    ([], "", None, ("Sourcend", "title")),
])
def test_key_stem(authors, title, year, expected):
    assert key_stem(authors, title, year) == expected


def test_colliding_keys_get_letters_and_the_first_keeps_its_key(store):
    first, _ = store.upsert_provider_source("openalex", record("W1", ["Tadashi Nakano"], 2013, doi="10.1/a"), None)
    second, _ = store.upsert_provider_source("openalex", record("W2", ["T. Nakano"], 2013, doi="10.1/b"), None)
    third, _ = store.upsert_provider_source("openalex", record("W3", ["nakano, t."], 2013, doi="10.1/c"), None)

    assert [key_of(store, s) for s in (first, second, third)] == ["Nakano13", "Nakano13b", "Nakano13c"]


def test_versions_of_one_work_share_its_key(store):
    arxiv = "10.48550/arxiv.1234.5678"
    v1, _ = store.upsert_provider_source("arxiv", record("A1", ["Ada Lovelace"], 2020, doi=arxiv, version_label="submittedVersion", merge_by_doi=False), None)
    v2, _ = store.upsert_provider_source("openalex", record("W9", ["Ada Lovelace"], 2021, doi=arxiv, version_label="submittedVersion", merge_by_doi=False), None)

    assert store.source(v1)["work_id"] == store.source(v2)["work_id"]
    assert key_of(store, v1) == key_of(store, v2) == "Lovelace20"


def test_an_upload_title_key_gives_way_to_authors_but_an_author_key_is_kept(store):
    svid = store.create_upload_source("Diffusion channels")
    assert key_of(store, svid) == "Diffusionnd"

    store.enrich_source("crossref", svid, record("10.1/x", ["Alan Turing"], 1952))
    assert key_of(store, svid) == "Turing52"

    store.enrich_source("crossref", svid, record("10.1/y", ["Someone Else"], 1999))
    assert key_of(store, svid) == "Turing52"


def test_works_stored_before_the_migration_are_keyed_oldest_first(tmp_path, monkeypatch):
    old = tmp_path / "migrations"
    old.mkdir()
    for path in REAL_MIGRATIONS.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 32:
            shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    with db.transaction(conn):
        for n, created in (("1", "2026-01-02"), ("2", "2026-01-01")):
            conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (f"wrk_{n}", created))
            conn.execute("INSERT INTO source_versions (id, work_id, title, authors_json, year, origin, created_at)"
                         " VALUES (?, ?, 'SYNTHETIC', '[\"Ada Lovelace\"]', 2020, 'provider', ?)", (f"srv_{n}", f"wrk_{n}", created))
    monkeypatch.setattr(db, "MIGRATIONS_DIR", REAL_MIGRATIONS)
    db.migrate(conn)
    store = Store(conn)

    assert store.assign_source_keys() == 2
    assert (store.source_key("wrk_2"), store.source_key("wrk_1")) == ("Lovelace20", "Lovelace20b")
    assert store.assign_source_keys() == 0
