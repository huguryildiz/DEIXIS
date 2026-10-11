"""Library items (UI parity S19a, F14): source versions the person keeps in the Library apart from any research.

One row per source version, so versions are never merged. A saved item outlives every research that held it: the
research purge and source purge in `store.py` keep a saved record, its passages and its file.
"""

from __future__ import annotations

from deixis.storage.db import now, transaction
from deixis.workflow.store import NotFound, Store

# Importers whose record carries the person's own bibliographic fields, stored through the provider-record path.
USER_SUPPLIED_PROVIDERS = ("zotero",)


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
            imported = store.conn.execute(
                f"SELECT 1 FROM identifier_mappings WHERE source_version_id = ? AND provider IN"
                f" ({', '.join('?' * len(USER_SUPPLIED_PROVIDERS))}) LIMIT 1", (svid, *USER_SUPPLIED_PROVIDERS)).fetchone()
            provider = origin == "saved" and row["origin"] == "provider" and imported is None
            metadata_origin = "provider" if provider else "user_supplied"
            inserted = store.conn.execute(
                "INSERT OR IGNORE INTO library_items (source_version_id, origin, metadata_origin, added_at)"
                " VALUES (?, ?, ?, ?)", (svid, origin, metadata_origin, now()))
            if inserted.rowcount:
                added.append(svid)
    return added
