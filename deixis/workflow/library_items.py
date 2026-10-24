"""Library items (UI parity S19a, F14): source versions the person keeps in the Library apart from any research.

One row per source version, so versions are never merged. A saved item outlives every research that held it: the
research purge and source purge in `store.py` keep a saved record, its passages and its file.
"""

from __future__ import annotations

from deixis.storage.db import now, transaction
from deixis.workflow.store import NotFound, Store

# Importers whose record carries the person's own bibliographic fields, stored through the provider-record path: a
# Zotero item, and a .bib / .ris entry no provider confirmed (`imports/bibtex_ris.py`, S19b).
USER_SUPPLIED_PROVIDERS = ("zotero", "reference_file")


def save(store: Store, svids: list[str], origin: str) -> list[str]:
    """Save these source versions; returns the ones that were not saved before (a saved item keeps its first row).

    Metadata counts as a provider's only for a provider record saved as it is that no user-supplied import touched. An
    uploaded file's title comes from its file name and an imported entry from the person's own file, so those stay
    `user_supplied` until a provider confirms them. A Zotero import is stored as a provider record (`origin` 'provider')
    and may fill blank fields of another provider's record, so any record a Zotero mapping names stays
    `user_supplied` too.
    """
    chosen = list(dict.fromkeys(svids))
    added: list[str] = []
    with transaction(store.conn):
        for svid in chosen:
            row = store.conn.execute("SELECT origin FROM source_versions WHERE id = ?", (svid,)).fetchone()
            if row is None:
                raise NotFound(svid)
            provider = origin == "saved" and row["origin"] == "provider" and not has_user_supplied_mapping(store, svid)
            metadata_origin = "provider" if provider else "user_supplied"
            inserted = store.conn.execute(
                "INSERT OR IGNORE INTO library_items (source_version_id, origin, metadata_origin, added_at)"
                " VALUES (?, ?, ?, ?)", (svid, origin, metadata_origin, now()))
            if inserted.rowcount:
                added.append(svid)
    return added


def has_user_supplied_mapping(store: Store, svid: str) -> bool:
    """Whether a user-supplied importer wrote this record, so some of its fields may be the person's own."""
    return store.conn.execute(
        f"SELECT 1 FROM identifier_mappings WHERE source_version_id = ? AND provider IN"
        f" ({', '.join('?' * len(USER_SUPPLIED_PROVIDERS))}) LIMIT 1", (svid, *USER_SUPPLIED_PROVIDERS)).fetchone() is not None


def confirm(store: Store, svid: str, provider: str) -> bool:
    """This saved item's record is a provider's record of its DOI (a DOI lookup returned it, or the record stored under
    that DOI is the provider's own): who confirmed it and when are set together (the
    table's CHECK). Only a user-supplied item not confirmed before changes, and only a provider's record that no
    user-supplied importer wrote (an upload's or an imported entry's fields stay the person's own). Returns whether the
    item changed."""
    row = store.conn.execute("SELECT origin FROM source_versions WHERE id = ?", (svid,)).fetchone()
    if row is None or row["origin"] != "provider" or has_user_supplied_mapping(store, svid):
        return False
    changed = store.conn.execute(
        "UPDATE library_items SET metadata_confirmed_by = ?, metadata_confirmed_at = ? WHERE source_version_id = ?"
        " AND metadata_origin = 'user_supplied' AND metadata_confirmed_by IS NULL", (provider, now(), svid))
    return bool(changed.rowcount)
