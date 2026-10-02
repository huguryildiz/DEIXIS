"""X3 synthetic text evidence, with independent output checks and read goldens.

No test invokes TeX, a model, a provider, a socket or a database.
"""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
import re

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.workflow.report import export_text, latex, latex_math, latex_text
from report_latex_cases import BASES, CASES, COVERAGE, ERRORS, EXCEPTIONS, PAYLOAD, SKIPPED_KEY, build, claim, section, table

FIXTURES = Path(__file__).parent / 'fixtures' / 'report_latex'
GOLDEN_IDS = [key for key in CASES if key.rsplit('-', 1)[0] not in ERRORS]
REQUIRED = {
    'draft_rules_known', 'draft_rules_more_than_three', 'draft_rule_unknown', 'draft_warning_filtered',
    'draft_error_absent_or_invalid', 'draft_sections_unvalidated', 'missing_rows_key', 'missing_rows_title_fallback',
    'insufficient_reasons', 'empty_section', 'ii_viii_text_with_claims', 'ii_viii_text_no_claims', 'vi_preface',
    'review_none', 'review_not_reviewed_unknown_reason', 'review_reverted', 'review_unread_sections',
    'identity_draft_and_valid', 'edit_none', 'edit_current', 'edit_historical', 'edit_in_draft', 'edit_empty_lists',
    'edit_zero_links_with_other_links', 'edit_zero_links_none_left', 'evidence_changed', 'anchors_all_located',
    'anchors_unlocated', 'corpus_none', 'corpus_dict',
    'review_not_reviewed_input_too_large', 'review_not_reviewed_budget_exhausted', 'review_not_reviewed_nothing_to_review',
    'review_not_reviewed_model_mismatch', 'review_not_reviewed_model_call_failed', 'review_not_reviewed_invalid_model_output',
    'review_reviewed_0_findings', 'review_reviewed_1_finding', 'review_reviewed_2_findings',
}


def render(case_id):
    view, title, corpus, bib_sources = CASES[case_id]()
    return latex.to_latex(view, title=title, corpus=corpus, bib_sources=bib_sources)


@pytest.mark.parametrize('case_id', GOLDEN_IDS)
def test_golden(case_id):
    bundle = render(case_id)
    # read_bytes avoids universal-newline conversion; empty .bib is pinned too.
    assert bundle.tex == (FIXTURES / (case_id + '.tex')).read_bytes().decode('utf-8')
    assert bundle.bib == (FIXTURES / (case_id + '.bib')).read_bytes().decode('utf-8')


def _all_claims(view):
    return [c for s in view['sections'] for c in s['claims']]


def _all_links(view):
    return [link for c in _all_claims(view) for link in c['evidence']]


def _predicate(branch, view, corpus):
    error = (view.get('run') or {}).get('error')
    rules = [x.get('rule') for x in error if isinstance(x, dict) and isinstance(x.get('rule'), str)] if isinstance(error, list) else []
    review = view.get('review') or {}
    check = view.get('edit_check') or {}
    claims = _all_claims(view)
    links = _all_links(view)
    texts = [s for s in view['sections'] if s['section_id'] in ('II', 'VIII') and (s.get('draft') or {}).get('text')]
    predicates = {
        'draft_rules_known': lambda: view['status'] == 'draft' and {'banned_word', 'empty_section', 'corpus_count_mismatch'} <= set(rules),
        'draft_rules_more_than_three': lambda: view['status'] == 'draft' and len(set(rules)) > 3,
        'draft_rule_unknown': lambda: view['status'] == 'draft' and 'SYNTHETIC_unknown_rule' in rules,
        'draft_warning_filtered': lambda: any(isinstance(x, dict) and x.get('rule', '').endswith('_warning') and x.get('detail', '').startswith('WARNING:') for x in error),
        'draft_error_absent_or_invalid': lambda: view['status'] == 'draft' and (not error or not isinstance(error, list)),
        'draft_sections_unvalidated': lambda: view['status'] == 'draft' and {'draft', 'failed'} <= {s['status'] for s in view['sections']},
        'missing_rows_key': lambda: any(r['source_key'] for r in view['missing_rows']['failed_rows']),
        'missing_rows_title_fallback': lambda: any(r['source_key'] is None and r['title'] for r in view['missing_rows']['failed_rows']),
        'insufficient_reasons': lambda: any(len((s.get('draft') or {}).get('insufficient_evidence', [])) > 1 for s in view['sections']),
        'empty_section': lambda: any(not s['claims'] and not s.get('draft') for s in view['sections']),
        'ii_viii_text_with_claims': lambda: {s['section_id'] for s in texts if s['claims']} == {'II', 'VIII'},
        'ii_viii_text_no_claims': lambda: {s['section_id'] for s in texts if not s['claims']} == {'II', 'VIII'},
        'vi_preface': lambda: any(s['section_id'] == 'VI' for s in view['sections']),
        'review_none': lambda: view['review'] is None,
        'review_not_reviewed_unknown_reason': lambda: review.get('status') == 'not_reviewed' and review.get('reason') not in export_text.REVIEW_REASONS,
        'review_reverted': lambda: review.get('status') == 'reviewed' and len(review['reverted']) == 2,
        'review_unread_sections': lambda: review.get('status') == 'reviewed' and len(review['sections_not_reviewed']) == 2,
        'identity_draft_and_valid': lambda: (view['status'] == 'draft' and view['report_version'] is None) or (view['status'] == 'valid' and view['report_version'] == 12),
        'edit_none': lambda: not view['has_human_edits'],
        'edit_current': lambda: view['has_human_edits'] and check.get('current') is True,
        'edit_historical': lambda: view['has_human_edits'] and check.get('current') is False,
        'edit_in_draft': lambda: view['has_human_edits'] and view['status'] == 'draft' and view['edited_after_version'] is None,
        'edit_empty_lists': lambda: bool(check) and not any(check[k] for k in ('items', 'skipped_rules', 'not_checked')),
        'edit_zero_links_with_other_links': lambda: bool(links) and any(not c['evidence'] and c['evidence_basis'] == 'none' and c['support_type_note'] for c in claims),
        'edit_zero_links_none_left': lambda: not links and any(c['evidence_basis'] == 'none' and c['support_type_note'] for c in claims),
        'evidence_changed': lambda: view['evidence_changes']['any'] is True,
        'anchors_all_located': lambda: bool(links) and all(link['anchor_match'] is not None for link in links),
        'anchors_unlocated': lambda: any(link['anchor_match'] is None for link in links),
        'corpus_none': lambda: corpus is None,
        'corpus_dict': lambda: isinstance(corpus, dict) and set(corpus) == {'found', 'unique', 'screened', 'included', 'full_text'},
    }
    if branch.startswith('review_not_reviewed_') and branch != 'review_not_reviewed_unknown_reason':
        return review.get('status') == 'not_reviewed' and review.get('reason') == branch.removeprefix('review_not_reviewed_')
    if branch.startswith('review_reviewed_'):
        count = int(branch.removeprefix('review_reviewed_')[0])
        return review.get('status') == 'reviewed' and len(review['findings']) == count
    return predicates[branch]()


def test_coverage_registry_is_exact_and_each_case_witnesses_its_branch():
    assert set(COVERAGE) == REQUIRED
    assert {k for k in REQUIRED if k.startswith('review_not_reviewed_') and k != 'review_not_reviewed_unknown_reason'} == {
        'review_not_reviewed_' + r for r in export_text.REVIEW_REASONS}
    for branch, bases in COVERAGE.items():
        assert isinstance(bases, list) and bases
        for base in bases:
            for lang in ('en', 'tr'):
                assert f'{base}-{lang}' in CASES
                view, _, corpus, _ = CASES[f'{base}-{lang}']()
                assert _predicate(branch, view, corpus), (branch, base, lang)
    assert any(CASES[key]()[0]['language'] == 'tr-TR' for key in GOLDEN_IDS)
    assert {CASES[base + '-en']()[0]['status'] for base in COVERAGE['identity_draft_and_valid']} == {'valid', 'draft'}


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


@pytest.mark.parametrize('case_id', GOLDEN_IDS)
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


@pytest.mark.parametrize('base,message', ERRORS.items())
@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_expected_error_cases_only(base, message, lang):
    view, title, corpus, sources = CASES[f'{base}-{lang}']()
    with pytest.raises(RevisionConflict) as caught:
        latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert str(caught.value) == message
    assert not (FIXTURES / f'{base}-{lang}.tex').exists()
    assert not (FIXTURES / f'{base}-{lang}.bib').exists()


@pytest.mark.parametrize('number', [True, False, 0, -1, 1.0, None, '1', PAYLOAD])
@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_reference_number_types(number, lang):
    view, title, corpus, sources = build('plain', lang)
    view['references'][0]['number'] = number
    with pytest.raises(RevisionConflict, match='Reference numbers must be positive integers'):
        latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)


@pytest.mark.parametrize('field', ['edited_after_version', 'errors', 'warnings'])
@pytest.mark.parametrize('value', [True, False, 1.0, '1', PAYLOAD])
@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_piecewise_number_guards(field, value, lang):
    view, title, corpus, sources = build('edit_current', lang)
    if field == 'edited_after_version':
        view[field] = value
    else:
        view['edit_check'][field] = value
    with pytest.raises(RevisionConflict, match='must be an integer or null|counts must be integers'):
        latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)


@pytest.mark.parametrize('version', ['1\n', PAYLOAD, None, True, -1])
def test_stem_guard(version):
    view, title, corpus, sources = build('plain', 'en')
    view['report_version'] = version
    with pytest.raises(RevisionConflict, match='filename stem is invalid'):
        latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)


def test_line_body_and_fixed_none_share_coercion():
    writer = latex._Writer(False, {}, {})
    assert writer.fixed(None) == writer.line(None) == writer.body(None, None) == ''
    assert writer.line('  $$x$$  ') == '$x$'
    assert writer.body('  $$x$$  ', None) == '\\begin{equation*}\nx\n\\end{equation*}'


def test_bundle_is_frozen_and_note_count_is_full():
    bundle = render('plain-en')
    assert bundle.note_count == len(bundle.notes)
    with pytest.raises(FrozenInstanceError):
        bundle.tex = 'changed'


def test_import_boundary():
    allowed = {'__future__', 'dataclasses', 're', 'unicodedata', 'typing', 'collections.abc', 'deixis.domain.rules',
               'deixis.workflow.bibliography', 'deixis.workflow.report', 'deixis.workflow.report.export_text',
               'deixis.workflow.report.latex_math', 'deixis.workflow.report.latex_text', 'deixis.workflow.report.latex_preamble',
               'deixis.workflow.report.store'}
    for node in ast.walk(ast.parse(Path(latex.__file__).read_text())):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed
            if node.module == 'deixis.workflow.report':
                assert {a.name for a in node.names} <= {'export_text', 'latex_math', 'latex_text', 'latex_preamble'}
            if node.module == 'deixis.workflow.report.store':
                assert [a.name for a in node.names] == ['DISPLAY_ORDER']


@pytest.mark.parametrize('count', [0, 1, 20, 21])
def test_comment_count_and_limit(count):
    notes = tuple(f'Note {i}' for i in range(count))
    text = latex._comment_block('report-synthetic-v1', notes)
    assert f"% Export notes: {count if count else 'none'}" in text
    assert len([line for line in text.splitlines() if re.match(r'% \d+\.', line)]) == min(count, 20)
    assert ('% and 1 more' in text) == (count == 21)
    assert all(line.startswith('%') for line in text.splitlines())


@pytest.mark.parametrize('whole_length', [199, 200, 201])
def test_comment_whole_line_length_and_uncut_notes(whole_length):
    full = 'x' * (whole_length - len('% 1. '))
    notes = latex._normalise_notes([full])
    line = latex._comment_block('report-synthetic-v1', notes).splitlines()[-1]
    assert len(line) == min(whole_length, 200)
    assert notes == (full,)


def test_normalisation_before_dedup_and_comment_injection():
    notes = latex._normalise_notes(['a\n b α', 'a b β', PAYLOAD + '\nNOT_A_COMMENT'])
    assert notes[:1] == ('a b ?',) and len(notes) == 2
    assert all('\n' not in note and all(' ' <= ch <= '~' for ch in note) for note in notes)
    assert all(line.startswith('%') for line in latex._comment_block('report-synthetic-v1', notes).splitlines())


@pytest.mark.parametrize('lang', ['en', 'tr'])
@pytest.mark.parametrize('n,groups', [(0, 1), (1, 1), (7, 1), (8, 2), (13, 2), (20, 3)])
@pytest.mark.parametrize('rows', [0, 2])
def test_table_groups_headers_rows_widths(lang, n, groups, rows):
    view, title, corpus, sources = build(f'table_{n}', lang)
    view['table_i'] = table(n, rows)
    for row in view['table_i']['rows']:
        row['ref_number'] = 1 if row['source_version_id'] == 's1' else None
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    text = bundle.tex
    assert text.count(r'\begin{longtable}') == groups
    assert text.count(r'\addtocounter{table}{-1}') == groups - 1
    assert text.count(r'\onecolumn') == text.count(r'\twocolumn') == 1
    tables = re.findall(r'\\begin\{longtable\}(.*?)\\end\{longtable\}', text, re.S)
    for g, part in enumerate(tables):
        size = min(7, n - g * 7)
        assert part.count(r'>{\raggedright\arraybackslash}p{1.0in}') == 1
        if size:
            width = f'\\dimexpr(\\textwidth-1.0in-2\\tabcolsep)/{size}-2\\tabcolsep\\relax'
            assert part.count(width) == size
        tail = part.split(r'\endlastfoot', 1)[1]
        data = [line for line in tail.splitlines() if line.strip()]
        assert len(data) == rows
        assert all(line.endswith(r' \\') for line in data)
        assert part.count('Kaynak' if lang == 'tr' else 'Source') == 2
        assert part.count(r'\caption') == 2
        assert 'TABLO I.' not in part and 'TABLE I.' not in part
        for r in range(rows):
            assert ('[1] Synth26' if r == 0 else 'SYNTHETIC row 2') in tail
        for c in range(g * 7, g * 7 + size):
            assert part.count(f'SYNTHETIC C{c + 1} ') == 2
            for r in range(rows):
                assert text.count(f'SYNTHETIC R{r + 1}C{c + 1} ') == 1
    if groups > 1:
        assert f'Table I was split into {groups} column groups of at most 7 data columns.' in bundle.notes
    assert latex.MAX_DATA_COLUMNS == 7 and latex.SOURCE_COLUMN_WIDTH == '1.0in'


@pytest.mark.parametrize('lang', ['en', 'tr'])
@pytest.mark.parametrize('kind,low,high', [('cell', 400, 401), ('heading', 400, 401), ('source', 200, 201)])
def test_long_threshold_exact_boundaries(lang, kind, low, high):
    low_bundle, high_bundle = [render(f'table_{kind}_{length}-{lang}') for length in (low, high)]
    assert not any('table value' in note for note in low_bundle.notes)
    assert high_bundle.notes == ('1 table value was moved to the Long table values list in Report notes.',)
    pointer = '1 numaralı nota bakın' if lang == 'tr' else 'see note 1'
    assert pointer in high_bundle.tex and r'\item[1.] ' in high_bundle.tex
    assert latex.HEADING_THRESHOLD == latex.CELL_THRESHOLD == 400 and latex.SOURCE_THRESHOLD == 200


@pytest.mark.parametrize('lang', ['en', 'tr'])
@pytest.mark.parametrize('base', ['table_long', 'table_all_long', 'table_option', 'table_parenthetical'])
def test_long_values_are_lossless_and_numbered_by_position(base, lang):
    view, _, _, _ = build(base, lang)
    t = view['table_i']
    expected = []
    tr = lang == 'tr'
    for c, column in enumerate(t['columns'], 1):
        if len(column['name']) > 400:
            expected.append((f'Sütun {c} başlığı: ' if tr else f'Column {c} heading: ') + column['name'])
    for r, row in enumerate(t['rows'], 1):
        label = f"[{row['ref_number']}]" + (f" {row['source_key']}" if row['source_key'] is not None else '') if row['ref_number'] else f"{'satır' if tr else 'row'} {r}"
        raw = export_text.source_cell(row, tr, str)
        if len(raw) > 200:
            expected.append((f'Satır {r} kaynağı ({label}): ' if tr else f'Row {r} source ({label}): ') + raw)
        for c, column in enumerate(t['columns'], 1):
            cell = next((cell for cell in t['cells'] if cell['source_version_id'] == row['source_version_id'] and cell['column_id'] == column['column_id']), None)
            raw = export_text.cell_text(cell, column, tr, str)
            if len(raw) > 400:
                expected.append((f'Satır {r}, sütun {c} ({label}): ' if tr else f'Row {r}, column {c} ({label}): ') + raw)
    bundle = render(f'{base}-{lang}')
    items = re.findall(r'^\\item\[(\d+)\.\] (.*)$', bundle.tex, re.M)
    assert [int(i) for i, _ in items] == list(range(1, len(expected) + 1))
    assert [text for _, text in items] == [latex_math.convert_text(raw, cell=True)[0].strip() for raw in expected]
    assert len(items) == len(expected)
    assert any(f'{len(expected)} table values were moved' in note or len(expected) == 1 and note.startswith('1 table value was moved') for note in bundle.notes)
    if base in ('table_long', 'table_all_long'):
        # Two equal source titles are different positions; each repeats in two groups.
        assert sum(' source (' in text or ' kaynağı (' in text for _, text in items) == 2
        for i, text in items:
            if ' source (' in text or ' kaynağı (' in text:
                pointer = f'{i} numaralı nota bakın' if tr else f'see note {i}'
                assert len(re.findall(r'(?<!\d)' + re.escape(pointer), bundle.tex)) == 2


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_long_value_label_cannot_open_math_in_the_full_value(lang):
    view, title, corpus, sources = build('table_1', lang)
    view['table_i']['rows'][0]['source_key'] = 'Unclosed $'
    raw = 'finish$ ' + 'word ' * 90
    view['table_i']['cells'][0]['value']['text'] = raw
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    position = 'Satır 1, sütun 1' if lang == 'tr' else 'Row 1, column 1'
    expected = r'\item[1.] ' + position + r' ([1] Unclosed \$): finish\$ ' + ('word ' * 90).strip()
    assert expected in bundle.tex.splitlines()


def test_table_caption_prefixes_and_fail_if_contract_changes(monkeypatch):
    t = table()
    assert export_text.table_caption(t, False).startswith('TABLE I. ')
    assert export_text.table_caption(t, True).startswith('TABLO I. ')
    monkeypatch.setattr(export_text, 'table_caption', lambda *args: 'SYNTHETIC missing prefix')
    with pytest.raises(AssertionError, match='prefix is missing'):
        render('table_1-en')


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_first_cell_and_item_start_guards(lang):
    bundle = render(f'table_guards-{lang}')
    assert '{}[SYNTHETIC bracket] & ' in bundle.tex
    assert '{}*SYNTHETIC star & ' in bundle.tex
    assert latex._itemize(['[label]', '*star']) == '\\begin{itemize}\n\\item {}[label]\n\\item {}*star\n\\end{itemize}'
    assert '{}[1] Synth26 & ' in render(f'table_1-{lang}').tex


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_table_placement(lang):
    after = render(f'table_after_paragraph-{lang}').tex
    assert after.index('SYNTHETIC same paragraph.') < after.index(r'\onecolumn') < after.index('SYNTHETIC after.')
    start = render(f'table_start-{lang}').tex
    assert start.index(r'\onecolumn') < start.index('SYNTHETIC table follows.')
    assert r'\longtable' not in render(f'table_no_iv-{lang}').tex
    assert r'\begin{longtable}' not in render(f'table_absent-{lang}').tex


NO_TARGET = '1 equation reference has no numberable display expression; no cross-reference was written for it.'
OWN_DISPLAY = '1 claim cites an equation reference and holds a display expression of its own; no cross-reference was written for it.'
ORDER_NOTE = 'Reference numbers in the PDF follow the order of first citation and differ from the numbers in DEIXIS.'
NO_CITATIONS = 'The report holds no citations; the bibliography commands were left out.'


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_no_references_or_citations_omits_bibliography_commands(lang):
    bundle = render(f'no_references-{lang}')
    assert not _citations(bundle.tex)
    assert r'\bibliography' not in bundle.tex
    assert bundle.bib == ''
    assert bundle.notes == (NO_CITATIONS,)
    assert bundle.note_count == 1
    assert f'% 1. {NO_CITATIONS}' in bundle.tex.splitlines()
    assert bundle.tex.endswith('\\end{document}\n')


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_references_without_claim_links_keep_bib_and_omit_bibliography_commands(lang):
    view, title, corpus, sources = build('plain', lang)
    cited_bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    for c in _all_claims(view):
        c['evidence'] = []
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert view['references'] and not _all_links(view)
    assert not _citations(bundle.tex)
    assert r'\bibliography' not in bundle.tex
    assert bundle.bib == cited_bundle.bib and bundle.bib
    assert bundle.notes == ('Reference [1] is not cited in the text and BibTeX will not print it.', NO_CITATIONS)
    assert bundle.notes.count(NO_CITATIONS) == 1
    assert bundle.tex.endswith('\\end{document}\n')


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_cited_document_keeps_both_bibliography_commands(lang):
    bundle = render(f'plain-{lang}')
    assert _citations(bundle.tex)
    assert bundle.tex.splitlines().count(r'\bibliographystyle{IEEEtran}') == 1
    assert bundle.tex.splitlines().count('\\bibliography{' + bundle.stem + '}') == 1
    assert NO_CITATIONS not in bundle.notes


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_equation_targets_exact(lang):
    repeated = render(f'eq_repeated-{lang}')
    assert repeated.tex.count(r'\label{eq:EQ1}') == repeated.tex.count(r'\eqref{eq:EQ1}') == 1
    assert repeated.tex.index(r'\eqref{eq:EQ1}') < repeated.tex.index(r'\cite{Synth26}', repeated.tex.index('SYNTHETIC later.'))
    several = render(f'eq_several-{lang}').tex
    assert '\\label{eq:EQ1}\nx' in several and '\\begin{equation*}\ny' in several
    for base in ('eq_e_first', 'eq_tag_first'):
        bundle = render(f'{base}-{lang}')
        assert '\\label{eq:EQ1}\nx' in bundle.tex and OWN_DISPLAY in bundle.notes
    for base in ('eq_own_display', 'eq_identical_display'):
        bundle = render(f'{base}-{lang}')
        assert r'\eqref' not in bundle.tex and bundle.notes == (OWN_DISPLAY,)
    for base in ('eq_no_target', 'eq_repeated_e', 'eq_1000'):
        bundle = render(f'{base}-{lang}')
        assert NO_TARGET in bundle.notes
    assert '\\label{eq:EQ2}\ny' in render(f'eq_two-{lang}').tex
    assert r'\label{eq:EQ1}' in render(f'eq_abstract-{lang}').tex.split(r'\end{abstract}')[0]
    assert r'\label' not in render(f'eq_no_ref-{lang}').tex
    assert len(re.findall(r'\\label\{eq:EQ\d+\}', render(f'eq_999-{lang}').tex)) == 999
    thousand = render(f'eq_1000-{lang}').tex
    assert r'\label{eq:EQ1000}' not in thousand
    assert '\\begin{equation*}\nx_{1000}\n\\end{equation*}' in thousand


def test_labels_reach_render_only_via_label_for(monkeypatch):
    original = latex_math.render
    labels = []
    def spy(m, label=None, unmapped=None):
        if label is not None:
            labels.append((m.source, label))
        return original(m, label=label, unmapped=unmapped)
    monkeypatch.setattr(latex_math, 'render', spy)
    render('eq_several-en')
    assert labels == [('$$x$$', 'eq:EQ1')]
    tree = ast.parse(Path(latex.__file__).read_text())
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'render' for n in ast.walk(tree))


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_display_boundaries_exact(lang):
    body = render(f'display_boundary-{lang}').tex
    assert ('\\begin{equation*}\nx\n\\end{equation*}\n\\begin{equation*}\ny\n\\end{equation*}\n\\cite{Synth26}\n'
            '\\begin{equation*}\nz\n\\end{equation*}\n\\cite{Synth26}\n\\begin{equation*}\nw\n\\end{equation*}\ntail \\cite{Synth26}') in body
    assert '\\end {align}\n\\cite{Synth26}\n\\begin{equation*}' in render(f'display_spaced-{lang}').tex
    assert '\\end\n{align}\n\\cite{Synth26}\n\\begin{equation*}' in render(f'display_newline-{lang}').tex


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_reference_notes_exact(lang):
    assert render(f'keys_versions-{lang}').notes == ('Reference [2] shares a source key with an earlier reference; cite key sYNTH26-2 was used.',)
    for base in ('key_none', 'key_hyphen', 'key_space', 'key_newline'):
        assert render(f'{base}-{lang}').notes == ('Reference [1] has no usable source key; cite key ref1 was used.',)
    assert render(f'ref_order-{lang}').notes == (ORDER_NOTE,)
    assert render(f'uncited-{lang}').notes == ('Reference [2] is not cited in the text and BibTeX will not print it.',)
    assert render(f'uncited_middle-{lang}').notes == (ORDER_NOTE, 'Reference [1] is not cited in the text and BibTeX will not print it.')
    assert r'\nocite' not in render(f'uncited-{lang}').tex
    assert r'\cite{Synth26}' in render(f'keyword_cite-{lang}').tex.split(r'\end{IEEEkeywords}')[0]


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_math_cell_subset_and_unmapped_shared_once(lang):
    bundle = render(f'table_math-{lang}')
    assert '$x\\geq1$' in bundle.tex and '$x$' in bundle.tex
    assert r'\textbackslash{}begin' in bundle.tex and r'\textbackslash{}Huge' in bundle.tex and r'\$1pt\$' in bundle.tex
    assert bundle.notes == ('Math written as plain text: outside table-cell math subset.', 'Display math written inline in a table cell.')
    bundle = render(f'math_classes-{lang}')
    unmapped = [n for n in bundle.notes if n.startswith('Unmapped characters:')]
    assert unmapped == ['Unmapped characters: 2 occurrences; first code points: U+6587.']
    assert r'$\R$' in bundle.tex and r'\textbackslash{}input' in bundle.tex


def _balanced_bib_braces(text):
    depth = 0
    for ch in text:
        depth += int(ch == '{') - int(ch == '}')
        assert depth >= 0
    assert depth == 0


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_hostile_output_cannot_execute_stored_commands(lang):
    view, title, corpus, sources = build('hostile', lang)
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    forbidden = {'input', 'def', 'write', 'csname', 'catcode', 'immediate', 'openout'}
    for text in (bundle.tex, bundle.bib):
        assert not forbidden & {name for name, _, _ in _commands(text)}
    assert bundle.tex.count(r'\begin{document}') == bundle.tex.count(r'\end{document}') == 1
    assert len(_bib_keys(bundle.bib)) == len(view['references'])
    _balanced_bib_braces(bundle.bib)
    _header(bundle.tex)
    assert '@article{evil,' not in bundle.bib.splitlines()
    assert _bib_keys(bundle.bib) == ['ref1']
    assert bundle.notes[0] == 'Reference [1] has no usable source key; cite key ref1 was used.'
    assert 'Bibliography: omitted year of ref1 because it is not a number.' in bundle.notes
    assert all('\n' not in note for note in bundle.notes)


def test_bundle_keeps_full_notes_when_comments_cut(monkeypatch):
    original = latex_math.convert_text
    full_notes = [f'Note {i}: ' + 'x' * 220 for i in range(21)]
    def convert(*args, **kwargs):
        text, notes = original(*args, **kwargs)
        return text, notes + full_notes
    monkeypatch.setattr(latex_math, 'convert_text', convert)
    bundle = render('plain-en')
    assert bundle.notes == tuple(full_notes)
    assert bundle.note_count == 21 and '% and 1 more\n' in bundle.tex
    assert all(len(line) <= 200 for line in bundle.tex.splitlines() if line.startswith('%'))


@pytest.mark.parametrize('lang', ['en', 'tr'])
@pytest.mark.parametrize('with_citations', [True, False])
def test_all_note_categories_keep_the_contract_order(lang, with_citations):
    view, title, corpus, sources = build('kitchen_sink', lang)
    view['references'][0]['source_key'] = None
    view['sections'][0]['claims'][0]['text'] = 'SYNTHETIC $x$ only.'
    sources[0].update(year=PAYLOAD, doi=PAYLOAD, title='SYNTHETIC 文')
    if not with_citations:
        for c in _all_claims(view):
            c['evidence'] = []
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert bundle.notes == (
        'Reference [1] has no usable source key; cite key ref1 was used.',
        *(() if with_citations else (
            'Reference [1] is not cited in the text and BibTeX will not print it.',
            'Reference [2] is not cited in the text and BibTeX will not print it.',
            NO_CITATIONS,
        )),
        NO_TARGET,
        r'\R is not defined by the export preamble; the document may not compile',
        'Table I was split into 2 column groups of at most 7 data columns.',
        '1 table value was moved to the Long table values list in Report notes.',
        'Bibliography: omitted year of ref1 because it is not a number.',
        'Bibliography: omitted doi of ref1 because it holds a backslash or a control character.',
        'Unmapped characters: 3 occurrences; first code points: U+6587.',
    )


def test_positive_spaced_aligned_stays_math():
    view, title, corpus, sources = build('plain', 'en')
    view['sections'][0]['claims'][0]['text'] = r'$$\begin {aligned}x&=y\end {aligned}$$'
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert '\\begin{equation*}\n\\begin {aligned}x&=y\\end {aligned}\n\\end{equation*}' in bundle.tex
    assert bundle.notes == ()


def test_piecewise_templates_are_tex_neutral():
    forbidden = set('\\{}$&#^_%~"')
    def check(value):
        if value is None:
            return
        if isinstance(value, str):
            assert not forbidden & set(value), value
            assert not any(latex_text.is_unmapped(ch) for ch in value), value
        else:
            for item in value:
                check(item)
    for lang in ('en', 'tr'):
        tr = lang == 'tr'
        esc = lambda v: 'X'
        for base in BASES:
            view, _, _, _ = build(base, lang)
            if view['missing_rows']:
                for row in view['missing_rows']['failed_rows']:
                    check(export_text.missing_row_fields(row, tr, esc))
            note = export_text.edit_note(view, tr, esc)
            if note:
                check((note.paragraph, note.items, note.not_checked_heading, note.skipped_rules, note.not_checked))
            check(export_text.review_note(view, tr, esc))
            if view['review'] and view['review']['status'] == 'reviewed':
                for finding in view['review']['findings']:
                    check(export_text.finding_fields(finding, tr, esc))
            t = view['table_i']
            if t:
                for row in t['rows']:
                    check(export_text.source_cell(row, tr, esc))
                for col in t['columns']:
                    check(export_text.cell_text(None, col, tr, esc))
                    for cell in t['cells']:
                        check(export_text.cell_text(cell, col, tr, esc))
