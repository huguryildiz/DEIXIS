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


def matching_records(records, paper):
    """Resolve DOI/verified aliases, then include versions of the same stored work."""
    allowed = {doi(paper['doi'])} if paper.get('doi') else set()
    if paper.get('alternate_identity_status') == 'verified':
        allowed.update(doi(d) for d in paper.get('alternate_dois', []) if doi(d))
    works = set(paper.get('verified_work_ids', []))
    def work(row):
        return row.get('verified_work_id') or row.get('work_id')
    works.update(work(r) for r in records if doi(r.get('doi')) in allowed and work(r))
    return [r for r in records if doi(r.get('doi')) in allowed or work(r) in works]


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
