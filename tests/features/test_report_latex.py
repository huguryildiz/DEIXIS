"""X3 synthetic text evidence, with independent output checks and read goldens.

No test invokes TeX, a model, a provider, a socket or a database.
"""

from copy import deepcopy
from pathlib import Path
import re

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.workflow.features.report import report_latex as latex
from report_latex_cases import CASES, ERRORS, EXCEPTIONS, SKIPPED_KEY

FIXTURES = Path(__file__).parent.parent / 'fixtures' / 'report_latex'


def render(case_id):
    view, title, corpus, bib_sources = CASES[case_id]()
    return latex.to_latex(view, title=title, corpus=corpus, bib_sources=bib_sources)


@pytest.mark.parametrize('case_id', ['plain-en', 'plain-tr'])
def test_golden(case_id):
    bundle = render(case_id)
    # read_bytes avoids universal-newline conversion; empty .bib is pinned too.
    assert bundle.tex == (FIXTURES / (case_id + '.tex')).read_bytes().decode('utf-8')
    assert bundle.bib == (FIXTURES / (case_id + '.bib')).read_bytes().decode('utf-8')


def _commands(text):
    """Independent tiny output tokenizer: consume backslash sequences as tokens."""
    i = 0
    while i < len(text):
        if text[i] != '\\':
            i += 1
            continue
        start = i
        i += 1
        j = i
        while i < len(text) and text[i].isascii() and text[i].isalpha():
            i += 1
        if i == j:
            i += 1
            continue
        name = text[j:i]
        yield name, start, i


def _environments(text):
    stack = []
    for name, start, end in _commands(text):
        if name not in ('begin', 'end'):
            continue
        i = end
        while text[i].isspace():
            i += 1
        assert text[i] == '{', text[start:end + 20]
        j = text.index('}', i)
        environment = text[i + 1:j]
        if name == 'begin':
            stack.append(environment)
        else:
            assert stack and stack.pop() == environment, environment
    assert not stack


def _citations(text):
    keys = []
    for name, _, end in _commands(text):
        if name == 'cite':
            assert text[end] == '{'
            for key in text[end + 1:text.index('}', end)].split(','):
                if key not in keys:
                    keys.append(key)
    return keys


def _bib_keys(text):
    return re.findall(r'^@[A-Za-z]+\{([A-Za-z0-9-]+),$', text, re.M)


def _expected_keys(view):
    holders = {}
    keys = []
    for ref in view['references']:
        source_key = ref.get('source_key')
        if isinstance(source_key, str) and source_key.isascii() and source_key.isalnum():
            lower = source_key.lower()
            holders[lower] = holders.get(lower, 0) + 1
            key = source_key + (f'-{holders[lower]}' if holders[lower] > 1 else '')
        else:
            key = f"ref{ref['number']}"
        keys.append(key)
    return keys


def _no_internal_ids(bundle, view):
    sentinels = {'psg_SENTINEL', 'cel_SENTINEL', 'claim_ROW_SENTINEL', 'link_ROW_SENTINEL',
                 'CLAIM_SENTINEL', 'SUPPORT_SENTINEL', 'SUPPORT_NOTE_SENTINEL', 'claim_key', 'support_type'}
    for sentinel in sentinels:
        for output in (bundle.tex, bundle.bib):
            assert sentinel not in output
            assert sentinel.replace('_', r'\_') not in output
    escaped = SKIPPED_KEY.replace('_', r'\_')
    check = view.get('edit_check')
    expected = bool(view.get('has_human_edits') and check and any(r['claim_key'] == SKIPPED_KEY for r in check['skipped_rules']))
    if expected:
        line = next(line for line in bundle.tex.splitlines() if escaped in line)
        assert line == r'\item I \ensuremath{\cdot} ' + escaped + r': phrase\_rule (human edit)'
        assert bundle.tex.count(escaped) == 1
    else:
        assert escaped not in bundle.tex
    assert escaped not in bundle.bib


def _equation_links(text):
    labels = re.findall(r'\\label\{([^}]+)\}', text)
    refs = re.findall(r'\\eqref\{([^}]+)\}', text)
    assert len(labels) == len(set(labels))
    assert set(refs) <= set(labels)


def _no_empty_itemize(text):
    for body in re.findall(r'\\begin\{itemize\}(.*?)\\end\{itemize\}', text, re.S):
        assert any(line.startswith(r'\item') for line in body.splitlines())


def _header(text):
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line and not line.startswith('%'))
    assert lines[first] == r'\documentclass[journal]{IEEEtran}'
    assert all(line.startswith('%') for line in lines[:first] if line)
    assert all(len(line) <= 200 for line in lines[:first])


@pytest.mark.parametrize('case_id', ['plain-en'])
def test_independent_invariants(case_id):
    view, title, corpus, sources = CASES[case_id]()
    before = deepcopy((view, sources, corpus))
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert (view, sources, corpus) == before
    assert bundle == latex.to_latex(deepcopy(view), title=title, corpus=deepcopy(corpus), bib_sources=deepcopy(sources))
    _no_internal_ids(bundle, view)
    _equation_links(bundle.tex)
    _environments(bundle.tex)
    _no_empty_itemize(bundle.tex)
    _header(bundle.tex)
    assert bundle.tex.count(r'\begin{document}') == bundle.tex.count(r'\end{document}') == 1
    cites = _citations(bundle.tex)
    assert len([line for line in bundle.tex.splitlines() if line.startswith(r'\bibliography{')]) == int(bool(cites))
    assert [line for line in bundle.tex.splitlines() if line.startswith(r'\bibliographystyle{')] == ([r'\bibliographystyle{IEEEtran}'] if cites else [])
    assert bundle.tex.endswith('\\end{document}\n')
    exceptions = EXCEPTIONS.get(case_id.rsplit('-', 1)[0], set())
    cites, bib_keys = _citations(bundle.tex), _bib_keys(bundle.bib)
    if 'cite_order' not in exceptions:
        assert cites == _expected_keys(view)
    assert set(cites) <= set(bib_keys)
    if 'all_bib_cited' not in exceptions:
        assert set(bib_keys) <= set(cites)
    assert bib_keys == _expected_keys(view)


@pytest.mark.parametrize('base,message', [(k, v) for k, v in ERRORS.items() if k == 'missing_reference'])
@pytest.mark.parametrize('lang', ['en'])
def test_expected_error_cases_only(base, message, lang):
    view, title, corpus, sources = CASES[f'{base}-{lang}']()
    with pytest.raises(RevisionConflict) as caught:
        latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert str(caught.value) == message
    assert not (FIXTURES / f'{base}-{lang}.tex').exists()
    assert not (FIXTURES / f'{base}-{lang}.bib').exists()


