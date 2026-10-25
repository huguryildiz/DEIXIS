"""D59, D38: one author–year–title key per work, given once across the library.

Records are SYNTHETIC. Passing shows how keys are formed, kept and exposed; it says nothing about provider metadata quality.
"""

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
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


def test_colliding_keys_get_letters_and_the_first_keeps_its_key(store):
    first, _ = store.upsert_provider_source("openalex", record("W1", ["Tadashi Nakano"], 2013, doi="10.1/a"), None)
    second, _ = store.upsert_provider_source("openalex", record("W2", ["T. Nakano"], 2013, doi="10.1/b"), None)
    third, _ = store.upsert_provider_source("openalex", record("W3", ["nakano, t."], 2013, doi="10.1/c"), None)

    assert [key_of(store, s) for s in (first, second, third)] == ["nakano2013synthetic", "nakano2013syntheticb", "nakano2013syntheticc"]
