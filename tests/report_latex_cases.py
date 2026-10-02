"""Hand-built SYNTHETIC X3 read models; no library, provider or model needed."""

from copy import deepcopy
from functools import partial

ORDER = ['abstract', 'index_terms', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX']
PAYLOAD = ('\\input{evil} \\def\\x{y} \\begin {document} \\begin{\n document} '
           '\\write18{x} \\csname x\\endcsname \\catcode \\immediate \\openout ^^M % # { } '
           '}\n@article{evil,')
SKIPPED_KEY = 'SKIPPED_SENTINEL'


def claim(text='SYNTHETIC claim.', versions=('s1',), paragraph=1, **extra):
    return dict(text=text, paragraph=paragraph, equation_ref=None, table_ref=None,
                claim_key='CLAIM_SENTINEL', support_type='SUPPORT_SENTINEL', id='claim_ROW_SENTINEL',
                evidence=[dict(source_version_id=v, ref_number=None, passage_id='psg_SENTINEL',
                               cell_id='cel_SENTINEL', link_id='link_ROW_SENTINEL', anchor_match={'start': 0, 'end': 1})
                          for v in versions], evidence_basis='direct', support_type_note=None) | extra


def section(sid, claims=None, status='valid', draft=None):
    return dict(section_id=sid, claims=claims if claims is not None else [], status=status, draft=draft)


def bibrow(version='s1'):
    return dict(source_version_id=version, title='SYNTHETIC source ' + version, authors=['Ada Yıldız'], year=2026,
                venue='SYNTHETIC Journal', publication_type='article', doi='10.0000/synthetic',
                landing_url='https://example.invalid/synthetic', version_label='publishedVersion', arxiv_id=None,
                volume='2', issue='3', pages='4--5')


def review(n=0, reverted=0, unread=False):
    return dict(status='reviewed', reason=None, sections_reviewed=[{'section_id': 'I'}],
                sections_not_reviewed=[{'section_id': 'VIII'}, {'section_id': 'SYNTHETIC_unknown'}] if unread else [],
                findings=[dict(section_id='I' if i == 0 else None, code='count_error' if i == 0 else 'unknown',
                               text=f'SYNTHETIC finding {i + 1}: a ≥ b & c.') for i in range(n)],
                reverted=[{'sentence_id': f'sentence{i}'} for i in range(reverted)])


def edit(current=True, empty=False):
    return dict(current=current, created_at='2026-10-02 12:00', errors=1, warnings=2,
                items=[] if empty else [dict(section_id='I', rule='count_rule', severity='error', detail='SYNTHETIC 2 & 3')],
                skipped_rules=[] if empty else [dict(section_id='I', claim_key=SKIPPED_KEY, rule='phrase_rule', reason='human edit')],
                not_checked=[] if empty else ['semantic_support', 'numbers_written_as_words', 'passages', 'SYNTHETIC extra limit'])


def table(n=1, rows=2):
    columns = [dict(column_id=f'c{i}', name=f'SYNTHETIC C{i + 1}', options=[{'id': 'opt', 'label': 'SYNTHETIC option'}]) for i in range(n)]
    rowlist = [dict(source_version_id='s1' if i == 0 else f'row{i + 1}', source_key='Synth26' if i == 0 else None,
                    title=f'SYNTHETIC row {i + 1}', ref_number=None, failed=False) for i in range(rows)]
    cells = [dict(source_version_id=row['source_version_id'], column_id=column['column_id'], state='value',
                  id='cel_SENTINEL', value={'text': f'SYNTHETIC R{r + 1}C{c + 1}'})
             for r, row in enumerate(rowlist) for c, column in enumerate(columns)]
    return dict(columns=columns, rows=rowlist, cells=cells)


def _number(view):
    """Synthetic report_view's first-appearance rule, independent of assembler."""
    versions = []
    sections = sorted(view['sections'], key=lambda s: ORDER.index(s['section_id']) if s['section_id'] in ORDER else len(ORDER))
    for sec in sections:
        for paragraph in dict.fromkeys(c['paragraph'] for c in sec['claims']):
            for c in (c for c in sec['claims'] if c['paragraph'] == paragraph):
                for link in c['evidence']:
                    version = link['source_version_id']
                    if version not in versions:
                        versions.append(version)
                    link['ref_number'] = versions.index(version) + 1
    view['references'] = [dict(number=i, source_key='Synth26' if v == 's1' else f'Synth{i}26', **bibrow(v)) for i, v in enumerate(versions, 1)]
    if view['table_i']:
        for row in view['table_i']['rows']:
            row['ref_number'] = versions.index(row['source_version_id']) + 1 if row['source_version_id'] in versions else None
    return [bibrow(v) for v in versions]


def build(base, language):
    view = dict(language='tr-TR' if base == 'kitchen_sink' and language == 'tr' else language,
                status='valid', report_version=12, sections=[section('I', [claim()])], references=[],
                run={'status': 'completed', 'error': None}, missing_rows=None, table_i=None,
                has_human_edits=False, edited_after_version=None, edit_check=None, evidence_changes={'any': False}, review=None)
    title, corpus = 'SYNTHETIC report & α', None
    if base.startswith('draft_'):
        view.update(status='draft', report_version=None)
        errors = {'draft_known': ['banned_word', 'empty_section', 'corpus_count_mismatch'],
                  'draft_more': ['citation_anchor_unmatched', 'anchor_not_in_cell_evidence', 'anchor_not_in_passage', 'other_rule'],
                  'draft_unknown': ['SYNTHETIC_unknown_rule'],
                  'draft_warning': ['banned_word', 'SYNTHETIC_warning']}
        if base in errors:
            view['run']['error'] = [dict(rule=r, detail='WARNING: synthetic' if r.endswith('_warning') else 'SYNTHETIC error') for r in errors[base]]
            view['run']['error'] += [view['run']['error'][0], 'SYNTHETIC non-dict']
        elif base == 'draft_invalid':
            view['run']['error'] = {'rule': 'not a list'}
        elif base == 'draft_empty_error':
            view['run']['error'] = []
        elif base == 'draft_unvalidated':
            view['sections'] += [section('abstract', [claim('SYNTHETIC abstract.', ())], 'draft'),
                                 section('index_terms', [claim('SYNTHETIC terms', ())], 'failed'), section('III', [], 'failed')]
    if base in ('missing_key', 'missing_title', 'missing_no_failed_rows'):
        view['missing_rows'] = dict(counts={'included': 4, 'failed': 1, 'cells_missing': 2},
                                    failed_rows=[] if base == 'missing_no_failed_rows' else [dict(source_key='Missing26' if base == 'missing_key' else None,
                                    title='SYNTHETIC missing title', reason='no_stored_text' if base == 'missing_key' else 'anchor_not_in_passage')])
    if base in ('insufficient', 'empty'):
        view['sections'] += [section('III', draft={'insufficient_evidence': [{'reason': 'SYNTHETIC no comparison.'}, {'reason': '- SYNTHETIC no data.'}]} if base == 'insufficient' else None)]
    if base in ('text_claims', 'text_only'):
        view['sections'] += [section(sid, [claim('SYNTHETIC methodology claim.', ())] if base == 'text_claims' else [],
                                    draft={'text': 'SYNTHETIC frozen counts $n=4$.'}) for sid in ('II', 'VIII')]
    if base == 'vi':
        view['sections'].append(section('VI', [claim('SYNTHETIC candidate.', ())]))
    if base.startswith('review_reason_'):
        view['review'] = dict(status='not_reviewed', reason=base.removeprefix('review_reason_'))
    if base == 'review_reason_missing':
        view['review'] = dict(status='not_reviewed')
    if base in ('review_0', 'review_1', 'review_2', 'review_reverted', 'review_unread'):
        view['review'] = review(int(base[-1]) if base[-1].isdigit() else 1,
                                reverted=2 if base == 'review_reverted' else 0, unread=base == 'review_unread')
    if base.startswith('edit_'):
        view.update(has_human_edits=True, edited_after_version=1)
        if base == 'edit_none':
            view.update(has_human_edits=False, edited_after_version=None)
        if base in ('edit_current', 'edit_historical', 'edit_empty'):
            view['edit_check'] = edit(current=base != 'edit_historical', empty=base == 'edit_empty')
        if base == 'edit_draft':
            view.update(status='draft', report_version=None, edited_after_version=None, edit_check=edit())
        if base in ('edit_zero_other', 'edit_zero_none'):
            c = claim('SYNTHETIC de-cited claim.', (), evidence_basis='none', support_type_note='SUPPORT_NOTE_SENTINEL')
            view['sections'][0]['claims'] = ([view['sections'][0]['claims'][0]] if base == 'edit_zero_other' else []) + [c]
    if base == 'evidence_changed':
        view['evidence_changes']['any'] = True
    if base == 'unlocated':
        view['sections'][0]['claims'][0]['evidence'][0]['anchor_match'] = None
    if base == 'corpus':
        corpus = dict(found=8, unique=7, screened=6, included=4, full_text=3)
    if base == 'no_references':
        view['sections'] = [section('abstract'), section('index_terms'), section('I')]
    if base == 'paragraph_order':
        view['sections'] = [section('IX', [claim('SYNTHETIC last.', ('s3',))]), section('I', [claim('SYNTHETIC first.', ('s1',), 4),
                            claim('SYNTHETIC third.', ('s3',), 2), claim('SYNTHETIC second.', ('s2', 's1', 's2'), 4)])]
    if base == 'keyword_cite':
        view['sections'].insert(0, section('index_terms', [claim('SYNTHETIC keyword $x$', ('s1', 's1'))]))
    if base.startswith('eq_') or base in ('math_classes', 'display_boundary', 'display_spaced', 'display_newline'):
        math_cases = {
            'eq_repeated': [claim('SYNTHETIC $$x$$', equation_ref='R'), claim('SYNTHETIC later.', equation_ref='R')],
            'eq_several': [claim('SYNTHETIC $a$ $$x$$ $$y$$', equation_ref='R'), claim('SYNTHETIC later.', equation_ref='R')],
            'eq_e_first': [claim(r'$$\begin{align}x&=y\end{align}$$', equation_ref='R'), claim('$$x$$', equation_ref='R')],
            'eq_tag_first': [claim(r'$$x\tag{z}$$', equation_ref='R'), claim('$$x$$', equation_ref='R')],
            'eq_own_display': [claim('$$x$$', equation_ref='R'), claim('$$y$$', equation_ref='R')],
            'eq_identical_display': [claim('$$x$$', equation_ref='R'), claim('$$x$$', equation_ref='R')],
            'eq_no_target': [claim('$x$ only.', equation_ref='R'), claim('Later.', equation_ref='R')],
            'eq_two': [claim('$$x$$', equation_ref='R1'), claim('$$y$$', equation_ref='R2'), claim('Later.', equation_ref='R1')],
            'eq_no_ref': [claim('$$x$$')],
            'eq_repeated_e': [claim(r'$$\begin{align}x&=y\end{align}$$', equation_ref='R'), claim(r'$$\begin{align}x&=y\end{align}$$', equation_ref='R')],
            'math_classes': [claim(r'SYNTHETIC $a≥b$ $$\begin{align}x&=y\end{align}$$ $$x\tag{z}$$ $$x&=y$$ $$x\\y$$ $$x$$ $\input{evil}$ $\R$ 文 $文$')],
            'display_boundary': [claim('$$x$$$$y$$'), claim('$$z$$'), claim('$$w$$ tail')],
            'display_spaced': [claim(r'$$\begin {align}x&=y\end {align}$$'), claim('$$z$$ tail')],
            'display_newline': [claim('$$\\begin\n{align}x&=y\\end\n{align}$$'), claim('$$z$$ tail')],
        }
        if base in ('eq_999', 'eq_1000'):
            view['sections'][0]['claims'] = [claim(f'$$x_{{{i}}}$$', equation_ref=f'R{i}', paragraph=i) for i in range(1, int(base[3:]) + 1)]
        elif base == 'eq_abstract':
            view['sections'].insert(0, section('abstract', [claim('SYNTHETIC $$x$$', equation_ref='R')]))
            view['sections'][1]['claims'][0]['equation_ref'] = 'R'
        else:
            view['sections'][0]['claims'] = math_cases[base]
    if base.startswith('table_'):
        n = int(base[6:]) if base[6:].isdigit() else (8 if base in ('table_long', 'table_all_long') else 1)
        t = table(n, rows=0 if base == 'table_zero_rows' else 2)
        view['table_i'] = t
        view['sections'].append(section('IV', [claim('SYNTHETIC table follows.', (), table_ref='TABLE_I')]))
        if base == 'table_start':
            view['sections'][-1]['claims'][0]['table_ref'] = None
        if base == 'table_after_paragraph':
            view['sections'][-1]['claims'] = [claim('SYNTHETIC lead.', (), 3), claim('SYNTHETIC table.', (), 1, table_ref='TABLE_I'), claim('SYNTHETIC same paragraph.', (), 1), claim('SYNTHETIC after.', (), 2)]
        if base == 'table_no_iv':
            view['sections'].pop()
        if base == 'table_absent':
            view['table_i'] = None
        if base == 'table_guards':
            t['rows'][0].update(source_version_id='row1', source_key=None, title='[SYNTHETIC bracket]')
            t['rows'][1]['title'] = '*SYNTHETIC star'
        if base.startswith('table_cell_'):
            t['cells'][0]['value'] = {'text': 'x' * int(base.rsplit('_', 1)[1])}
        if base.startswith('table_source_'):
            t['rows'][0].update(source_key=None, title='s' * (int(base.rsplit('_', 1)[1]) - 4))
        if base.startswith('table_heading_'):
            t['columns'][0]['name'] = 'h' * int(base.rsplit('_', 1)[1])
        if base == 'table_parenthetical':
            t['cells'][0].update(state='not_verified', value={'text': 'v' * 380})
        if base == 'table_option':
            t['columns'][0]['options'][0]['label'] = 'SYNTHETIC option ' * 40
            t['cells'][0]['value'] = {'option_ids': ['opt']}
        if base in ('table_long', 'table_all_long'):
            t['columns'][0]['name'] = 'SYNTHETIC heading ' * 30
            t['rows'][0].update(source_key=None, title='SYNTHETIC long title ' * 20)
            t['rows'][1]['title'] = t['rows'][0]['title']
            for cell in t['cells'] if base == 'table_all_long' else t['cells'][:2]:
                cell['value']['text'] = 'SYNTHETIC long cell ' * 25
        if base == 'table_math':
            expressions = [r'$x≥1$', r'$\begin{array}{c}x\\[1000pt]y\end{array}$', '$1pt$', r'$\Huge x$', '$$x$$']
            view['table_i'] = t = table(5)
            for cell, text in zip(t['cells'], expressions):
                cell['value']['text'] = text
        if base == 'table_states':
            view['table_i'] = t = table(10)
            values = [{'number': 2, 'unit': 'm'}, {'number': 3}, {'answer': 'yes'}, {'answer': 'no'},
                      {'option_ids': ['opt', 'unknown']}, {}, {'text': 'unverified'}, None]
            for cell, val in zip(t['cells'], values):
                cell['value'] = val
            t['cells'][6]['state'] = 'not_verified'
            t['cells'][7]['state'] = 'not_verified'
            t['cells'][8]['state'] = 'not_found'
            t['cells'].pop(9)
    if base == 'kitchen_sink':
        view.update(status='draft', report_version=None, has_human_edits=True, edited_after_version=None,
                    edit_check=edit(), review=review(2, reverted=1, unread=True), evidence_changes={'any': True}, table_i=table(8))
        view['run']['error'] = [dict(rule='banned_word', detail='SYNTHETIC')]
        view['missing_rows'] = dict(counts={'included': 4, 'failed': 1, 'cells_missing': 2}, failed_rows=[dict(source_key=None, title='SYNTHETIC missing', reason='no_stored_text')])
        view['sections'] = [section('abstract', [claim('SYNTHETIC abstract $$x$$', equation_ref='R')]),
                            section('index_terms', [claim('SYNTHETIC keywords $x$', ())]),
                            section('I', [claim('SYNTHETIC later.', equation_ref='R'), claim(r'SYNTHETIC $\R$ 文 $文$.', ('s2',))]),
                            section('II', [claim('SYNTHETIC method claim.', ())], draft={'text': 'SYNTHETIC frozen counts.'}),
                            section('IV', [claim('SYNTHETIC table.', (), table_ref='TABLE_I')]), section('VI'),
                            section('VIII', draft={'text': 'SYNTHETIC limits.'}), section('IX', status='draft')]
        view['table_i']['cells'][0]['value']['text'] = 'SYNTHETIC long cell ' * 30
        corpus = dict(found=8, unique=7, screened=6, included=4, full_text=3)
    if base == 'hostile':
        title = 'SYNTHETIC ' + PAYLOAD
        view.update(status='draft', report_version=None, has_human_edits=True, edited_after_version=1,
                    edit_check=edit(), review=review(2, unread=True), table_i=table(8))
        view['run']['error'] = [dict(rule=PAYLOAD, detail=PAYLOAD)]
        view['sections'] = [section('I', [claim(PAYLOAD + ' $' + PAYLOAD + '$ $$' + PAYLOAD + '$$')]),
                            section('II', draft={'text': PAYLOAD}), section('VIII', draft={'text': PAYLOAD}),
                            section('IV', [claim('SYNTHETIC table', (), table_ref='TABLE_I')]), section(PAYLOAD)]
        view['missing_rows'] = dict(counts={'included': 4, 'failed': 1, 'cells_missing': 2}, failed_rows=[dict(source_key=PAYLOAD, title=PAYLOAD, reason=PAYLOAD), dict(source_key=None, title=PAYLOAD, reason=PAYLOAD)])
        check = view['edit_check']
        check['created_at'] = PAYLOAD
        for item in check['items'] + check['skipped_rules']:
            for key in item:
                item[key] = PAYLOAD
        check['not_checked'] = [PAYLOAD]
        view['review']['reason'] = PAYLOAD
        for finding in view['review']['findings']:
            finding.update(section_id=PAYLOAD, code=PAYLOAD, text=PAYLOAD)
        for item in view['review']['sections_not_reviewed']:
            item['section_id'] = PAYLOAD
        for col in view['table_i']['columns']:
            col.update(name=PAYLOAD, options=[{'id': 'opt', 'label': PAYLOAD}])
        for cell in view['table_i']['cells']:
            cell['value'] = {'option_ids': ['opt']}
        view['table_i']['cells'][0]['value'] = {'text': PAYLOAD}
        view['table_i']['cells'][1]['value'] = {'number': 1, 'unit': PAYLOAD}
        view['table_i']['cells'][3].update(state='not_verified', value={'text': PAYLOAD})
        view['table_i']['cells'][4]['state'] = PAYLOAD
        for row in view['table_i']['rows']:
            row.update(source_key=PAYLOAD + '\n\\input{evil}', title=PAYLOAD)
        view['table_i']['rows'][1]['source_key'] = None
    bib_sources = _number(view)
    if base in ('keys_versions', 'key_none', 'key_hyphen', 'key_space', 'key_newline', 'ref_order', 'uncited', 'uncited_middle', 'key_collision', 'key_collision_reverse'):
        view['sections'][0]['claims'] = [claim('SYNTHETIC first.', ('s1',)), claim('SYNTHETIC second.', ('s2',))]
        bib_sources = _number(view)
        if base == 'keys_versions':
            view['references'][1]['source_key'] = 'sYNTH26'
        if base.startswith('key_') and base not in ('key_collision', 'key_collision_reverse'):
            view['references'][0]['source_key'] = {'key_none': None, 'key_hyphen': 'A-B', 'key_space': 'A B', 'key_newline': 'A\n'}[base]
        if base == 'ref_order':
            view['sections'][0]['claims'].reverse()
        if base in ('uncited', 'uncited_middle'):
            c = view['sections'][0]['claims'][1 if base == 'uncited' else 0]
            c['evidence'] = []
        if base in ('key_collision', 'key_collision_reverse'):
            view['references'][0]['source_key'] = None
            view['references'][1]['source_key'] = 'ref1'
            if base == 'key_collision_reverse':
                view['references'].reverse()
    if base == 'hostile':
        view['references'][0]['source_key'] = PAYLOAD + '\n\\input{evil}'
        for row in bib_sources:
            for key in row:
                if key != 'source_version_id':
                    row[key] = [PAYLOAD] if key == 'authors' else PAYLOAD
    if base == 'missing_reference':
        view['sections'][0]['claims'][0]['evidence'][0]['ref_number'] = 99
    if base == 'link_wrong_version':
        view['sections'][0]['claims'][0]['evidence'][0]['source_version_id'] = 'other'
    if base == 'link_missing_version':
        del view['sections'][0]['claims'][0]['evidence'][0]['source_version_id']
    if base == 'missing_bib':
        bib_sources = []
    if base == 'duplicate_numbers':
        view['references'].append(deepcopy(view['references'][0]) | {'source_version_id': 's2'})
    if base == 'duplicate_versions':
        view['references'].append(deepcopy(view['references'][0]) | {'number': 2})
    if base == 'duplicate_bib':
        bib_sources.append(deepcopy(bib_sources[0]))
    if base == 'missing_bib_field':
        del bib_sources[0]['doi']
    if base == 'bad_edited_version':
        view['edited_after_version'] = PAYLOAD
    if base == 'bad_table_reference':
        view['table_i'] = table()
        view['table_i']['rows'][0]['ref_number'] = 99
    return view, title, corpus, bib_sources


BASES = [
    'plain', 'draft_known', 'draft_more', 'draft_unknown', 'draft_warning', 'draft_absent', 'draft_invalid', 'draft_empty_error',
    'draft_unvalidated', 'missing_key', 'missing_title', 'missing_no_failed_rows', 'insufficient', 'empty', 'text_claims', 'text_only', 'vi',
    'review_reason_input_too_large', 'review_reason_budget_exhausted', 'review_reason_nothing_to_review',
    'review_reason_model_mismatch', 'review_reason_model_call_failed', 'review_reason_invalid_model_output', 'review_reason_unknown', 'review_reason_missing',
    'review_0', 'review_1', 'review_2', 'review_reverted', 'review_unread', 'edit_none', 'edit_current', 'edit_historical', 'edit_draft', 'edit_empty',
    'edit_zero_other', 'edit_zero_none', 'evidence_changed', 'unlocated', 'corpus', 'no_references', 'paragraph_order', 'keyword_cite',
    'math_classes', 'eq_repeated', 'eq_several', 'eq_e_first', 'eq_tag_first', 'eq_own_display', 'eq_identical_display', 'eq_no_target', 'eq_two',
    'eq_no_ref', 'eq_repeated_e', 'eq_abstract', 'eq_999', 'eq_1000', 'display_boundary', 'display_spaced', 'display_newline',
    'keys_versions', 'key_none', 'key_hyphen', 'key_space', 'key_newline', 'ref_order', 'uncited', 'uncited_middle',
    'table_0', 'table_1', 'table_7', 'table_8', 'table_13', 'table_20', 'table_zero_rows', 'table_start', 'table_after_paragraph', 'table_no_iv', 'table_absent',
    'table_guards', 'table_cell_400', 'table_cell_401', 'table_source_200', 'table_source_201', 'table_heading_400', 'table_heading_401',
    'table_parenthetical', 'table_option', 'table_long', 'table_all_long', 'table_math', 'table_states', 'kitchen_sink', 'hostile',
]
ERRORS = {
    'missing_reference': 'A claim citation does not resolve to the same reference number and source version',
    'link_wrong_version': 'A claim citation does not resolve to the same reference number and source version',
    'link_missing_version': 'A claim citation does not resolve to the same reference number and source version',
    'missing_bib': 'A reference has no bibliography source', 'duplicate_numbers': 'Reference numbers must be unique',
    'duplicate_versions': 'Reference source versions must be unique', 'duplicate_bib': 'Bibliography source versions must be unique',
    'missing_bib_field': 'A bibliography source is missing a required field', 'bad_edited_version': 'The edited-after version must be an integer or null',
    'bad_table_reference': "A table row's reference number does not match its source version",
    'key_collision': 'Cite keys collide ignoring case', 'key_collision_reverse': 'Cite keys collide ignoring case',
}
# Noted exceptions retain all invariants except precisely these named ones.
EXCEPTIONS = {'ref_order': {'cite_order'}, 'uncited': {'cite_order', 'all_bib_cited'},
              'uncited_middle': {'cite_order', 'all_bib_cited'}}
CASES = {f'{base}-{lang}': partial(build, base, lang) for base in BASES + list(ERRORS) for lang in ('en', 'tr')}
COVERAGE = {
    'draft_rules_known': ['draft_known'], 'draft_rules_more_than_three': ['draft_more'], 'draft_rule_unknown': ['draft_unknown'],
    'draft_warning_filtered': ['draft_warning'], 'draft_error_absent_or_invalid': ['draft_absent', 'draft_invalid', 'draft_empty_error'],
    'draft_sections_unvalidated': ['draft_unvalidated'], 'missing_rows_key': ['missing_key'], 'missing_rows_title_fallback': ['missing_title'],
    'insufficient_reasons': ['insufficient'], 'empty_section': ['empty'], 'ii_viii_text_with_claims': ['text_claims'], 'ii_viii_text_no_claims': ['text_only'],
    'vi_preface': ['vi'], 'review_none': ['plain'], 'review_not_reviewed_unknown_reason': ['review_reason_unknown', 'review_reason_missing'],
    'review_reverted': ['review_reverted'], 'review_unread_sections': ['review_unread'], 'identity_draft_and_valid': ['draft_known', 'plain'],
    'edit_none': ['plain'], 'edit_current': ['edit_current'], 'edit_historical': ['edit_historical'], 'edit_in_draft': ['edit_draft'],
    'edit_empty_lists': ['edit_empty'], 'edit_zero_links_with_other_links': ['edit_zero_other'], 'edit_zero_links_none_left': ['edit_zero_none'],
    'evidence_changed': ['evidence_changed'], 'anchors_all_located': ['plain'], 'anchors_unlocated': ['unlocated'],
    'corpus_none': ['plain'], 'corpus_dict': ['corpus'],
    'review_not_reviewed_input_too_large': ['review_reason_input_too_large'], 'review_not_reviewed_budget_exhausted': ['review_reason_budget_exhausted'],
    'review_not_reviewed_nothing_to_review': ['review_reason_nothing_to_review'], 'review_not_reviewed_model_mismatch': ['review_reason_model_mismatch'],
    'review_not_reviewed_model_call_failed': ['review_reason_model_call_failed'], 'review_not_reviewed_invalid_model_output': ['review_reason_invalid_model_output'],
    'review_reviewed_0_findings': ['review_0'], 'review_reviewed_1_finding': ['review_1'], 'review_reviewed_2_findings': ['review_2'],
}
