"""Offline identities and secret-free evidence serialization for measurement tools."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def doi(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '',
                  (value or '').strip(), flags=re.I).casefold()


def identity(record):
    """A title is never a work identity. Aliases must already have been verified."""
    if record.get('verified_work_id'):
        return 'work:' + record['verified_work_id']
    if value := doi(record.get('doi')):
        return 'doi:' + value
    for provider in ('openalex', 'semantic_scholar'):
        if value := record.get(provider + '_id'):
            return provider + ':' + value
    return None


def reference_identity(paper):
    """Which identity this benchmark reference carries of its own, read without looking at any pool.

    Whether a reference can be measured at all is a property of the reference, never of the search: a reference
    the measurement cannot identify is one nobody can say was found or lost, while a reference that carries a
    DOI and was not found is a verified loss. Deriving measurability from a pool match would take every verified
    loss out of the denominator and read the ratio as better than it is.

    'doi' is the reference's own DOI; 'verified_work' a stored work identity it was written with;
    'verified_alternate' an alternate DOI a person has verified (`alternate_identity_status`). None means the
    reference carries nothing but a title, which is not a work identity.
    """
    if doi(paper.get('doi')):
        return 'doi'
    if paper.get('verified_work_ids'):
        return 'verified_work'
    if paper.get('alternate_identity_status') == 'verified' and any(doi(d) for d in paper.get('alternate_dois') or []):
        return 'verified_alternate'
    return None


def measurable(paper):
    """Whether this reference can be counted as found or lost at all (`reference_identity`)."""
    return reference_identity(paper) is not None


def unverified_alternates(paper):
    """Alternate DOIs the reference names that nobody has verified, so no report may match on them.

    They are named rather than used: a person can verify one and the next reading of the same snapshot then
    counts the version it points at.
    """
    if paper.get('alternate_identity_status') == 'verified':
        return []
    return [d for d in paper.get('alternate_dois') or [] if doi(d)]


def requested_records(records, paper):
    """The versions that carry the reference's **own** identity, not a sibling version of the same work.

    "The work is in the pool" and "the version the reference asks for was read" are two different measurements:
    a reference written with an arXiv DOI is answered by the journal record only if the two are linked, and even
    then what was read may be the other version. `matching_records` answers the first question, this one the
    second.
    """
    allowed = {doi(paper['doi'])} if doi(paper.get('doi')) else set()
    if paper.get('alternate_identity_status') == 'verified':
        allowed.update(doi(d) for d in paper.get('alternate_dois') or [] if doi(d))
    if allowed:
        # A reference that names a DOI asks for that record. Its work identity, where it carries one too, covers
        # every sibling version of the work, which is the other question (`matching_records`).
        return [r for r in records if doi(r.get('doi')) in allowed]
    works = {w for w in paper.get('verified_work_ids') or [] if w}
    return [r for r in records if (r.get('verified_work_id') or r.get('work_id')) in works]


def matching_records(records, paper):
    """Resolve DOI/verified aliases, then include versions of the same stored work.

    An identity that does not survive normalisation is no identity: a reference whose DOI is blank once
    `doi` has stripped it would otherwise match every version that stores no DOI, and a reference the
    measurement cannot identify would be reported as found.
    """
    allowed = {doi(paper['doi'])} if doi(paper.get('doi')) else set()
    if paper.get('alternate_identity_status') == 'verified':
        allowed.update(doi(d) for d in paper.get('alternate_dois') or [] if doi(d))
    works = {w for w in paper.get('verified_work_ids') or [] if w}
    def work(row):
        return row.get('verified_work_id') or row.get('work_id')
    def row_doi(row):
        value = doi(row.get('doi'))
        return value if value else None
    works.update(work(r) for r in records if row_doi(r) in allowed and work(r))
    return [r for r in records if row_doi(r) in allowed or work(r) in works]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


SECRET = re.compile(r'authorization|api.?key|token|secret|password|credential|^key$', re.I)


def sanitize(value):
    """Raw provider data may echo credentials; hashes refer to the retained, sanitized body."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not SECRET.search(k)}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?i)Bearer\s+[^\s"<>]+', 'Bearer [redacted]', value)
        value = re.sub(r'(?i)(api[-_]?key|access[-_]?token|secret|password)=([^&\s"<>]+)',
                       r'\1=[redacted]', value)
        def clean_url(match):
            parsed = urlsplit(match[0])
            host = parsed.netloc.rsplit('@', 1)[-1]
            query = [(k, v) for k, v in parse_qsl(parsed.query) if not SECRET.search(k)]
            return urlunsplit((parsed.scheme, host, parsed.path, urlencode(query), ''))
        return re.sub(r'https?://[^\s"<>]+', clean_url, value)
    return value


def load_benchmark(path):
    from pathlib import Path
    value = json.loads(Path(path).read_text())
    if value.get('question_sha256') != sha(value['question']):
        raise ValueError('benchmark question hash mismatch')
    return value
