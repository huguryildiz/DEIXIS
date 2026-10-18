"""Electrical-engineering survey benchmark (benchmark plan 3a, .local/plans/benchmark-plan.md): pure helpers.

Each question comes from one survey article in an EE survey venue (2019–2024, at least 80 references). The gold set is
the survey's OpenAlex `referenced_works`, kept only when OpenAlex has the work and dates it on or before the survey; the
survey itself is never gold. A reference list is incomplete and a little broad, so absolute recall means little here:
only the paired difference between arms is read.

Before cutting at k, both arms' lists lose the survey itself and every record dated after it (by day; a record known
only by its year gets its date from OpenAlex, and one that cannot be dated is dropped). DEIXIS has no date limit, so a
run can chain from the survey or from a later paper and pull the survey's own reference list into its pool: a record
that reached the list only through such a seed is dropped as well (`clean`). The list closes up after each drop. What
this cannot undo is the chaining budget such a seed used up; the report counts the exposed questions.

Selection is deterministic: a survey's topic is the first title rule that matches (fixed order), else its venue's
default topic; within a topic surveys are ordered by venue tier, then cited_by_count, then a seeded hash of the id.
"""
from __future__ import annotations

import hashlib
import random
import re

try:
    from .bioasq import DEPTHS, macro, norm_title, paired_bootstrap  # noqa: F401 (paired_bootstrap: eesurvey_run)
    from .common import doi as norm_doi
    from .litsearch import matched, openalex_short
except ImportError:
    from bioasq import DEPTHS, macro, norm_title, paired_bootstrap  # noqa: F401
    from common import doi as norm_doi
    from litsearch import matched, openalex_short

SEED = 20261018
YEARS = (2019, 2024)
MIN_REFS = 80
PER_TOPIC = 6  # the plan asks 5–7 per topic; a topic with fewer candidates keeps what it has
TUNE_SHARE = 1 / 3

# OpenAlex source ids, looked up 18 Oct 2026. Tier 1 is read first; IEEE Access only fills a topic short of PER_TOPIC.
VENUES = {
    'S23688054': ('IEEE Communications Surveys & Tutorials', 1, None),
    'S68686220': ('Proceedings of the IEEE', 1, None),
    'S120977877': ('IEEE Signal Processing Magazine', 1, 'signal_processing'),
    'S201045332': ('IEEE Antennas and Propagation Magazine', 1, 'antennas_rf'),
    'S147622553': ('IEEE Microwave Magazine', 1, 'antennas_rf'),
    'S4210184428': ('IEEE Journal of Microwaves', 1, 'antennas_rf'),
    'S4210203048': ('IEEE Open Journal of Antennas and Propagation', 1, 'antennas_rf'),
    'S4210208367': ('IEEE Control Systems Magazine', 1, 'control'),
    'S54761077': ('Annual Reviews in Control', 1, 'control'),
    'S4210191328': ('Annual Review of Control, Robotics, and Autonomous Systems', 1, None),  # robotics too: rules only
    'S205083296': ('IEEE Power and Energy Magazine', 1, 'power_energy'),
    'S59604973': ('IEEE Transactions on Smart Grid', 1, 'power_energy'),
    'S29875816': ('IEEE Transactions on Power Electronics', 1, 'power_energy'),
    'S2764607435': ('CSEE Journal of Power and Energy Systems', 1, 'power_energy'),
    'S2737292043': ('Protection and Control of Modern Power Systems', 1, 'power_energy'),
    'S4210202420': ('IEEE Open Journal of the Communications Society', 1, None),
    'S2480266640': ('IEEE Internet of Things Journal', 1, None),
    'S132957497': ('IEEE Journal of Oceanic Engineering', 1, 'underwater_sensor'),
    'S2485537415': ('IEEE Access', 2, None),
}
# Venues that publish only surveys, tutorials and invited reviews: every paper there counts as a survey.
REVIEW_VENUES = {'S23688054', 'S68686220', 'S120977877', 'S54761077', 'S4210191328'}
SURVEY_TITLE = re.compile(r'\b(survey|review|tutorial|overview|state[- ]of[- ]the[- ]art)\b', re.I)

# Title rules, checked in this order; the first match decides. Venue defaults come only after every rule missed.
TOPICS = (
    ('underwater_sensor', r'underwater|undersea|\bsubsea|acoustic communication|ocean|marine|maritime|sensor network'
                          r'|\bWSNs?\b|wireless sensor'),
    ('antennas_rf', r'antenna|metasurface|metamaterial|reflectarray|phased[- ]array|radio[- ]frequency|microwave'
                    r'|rectenna|power amplifier|electromagnetic|millimeter[- ]wave circuit|frequency selective'),
    ('power_energy', r'power system|power grid|smart grid|microgrid|power electronic|converter|inverter|energy storage'
                     r'|batter(y|ies)|renewable|wind (power|energy|turbine)|photovoltaic|\bsolar\b|electric vehicle'
                     r'|demand response|energy management|\bHVDC\b|power distribution|distribution (system|grid)'
                     r'|transmission (line|system)|electricity'),
    ('control', r'(?<!access )(?<!power )(?<!congestion )(?<!admission )\bcontrol(ler|lers|led)?\b(?! plane| placement)'
                r'|\bMPC\b|stabili[sz]|observer|state estimation|multi-agent system'),
    ('ml', r'machine learning|deep learning|reinforcement learning|neural network|federated learning'
           r'|artificial intelligence|\bAI\b|learning-based|large language model|\bLLMs?\b|generative'),
    ('signal_processing', r'signal processing|estimation|compressive|compressed sensing|sparse|\bradar\b|beamforming'
                          r'|locali[sz]ation|positioning|filtering|sampling|tensor|array processing'
                          r'|synthetic aperture|integrated sensing|\bISAC\b|spectrum sensing|compressive sensing'),
    ('wireless', r'wireless|\b[56]G\b|beyond 5G|\bMIMO\b|\bNOMA\b|cellular|mobile|satellite|\bUAVs?\b|drone|vehicular'
                 r'|spectrum|millimeter[- ]wave|mmWave|terahertz|\bTHz\b|communication|network|Internet of Things'
                 r'|\bIoT\b|edge computing|backscatter|intelligent (reflecting )?surface|optical wireless|visible light'),
)
TOPIC_ORDER = tuple(name for name, _ in TOPICS)
# Outside the seven topics even when a topic word appears (security, cryptography, quantum, computer vision).
OFF_TOPIC = re.compile(r'blockchain|authenticat|secur|privacy|attack|intrusion|malware|cryptograph|adversarial|quantum'
                       r'|object detection', re.I)
TOPIC_LABELS = {'wireless': 'Kablosuz ve telekom', 'signal_processing': 'Sinyal işleme',
                'ml': 'Makine öğrenmesi (EE ve haberleşme)', 'antennas_rf': 'Anten ve RF',
                'power_energy': 'Güç ve enerji sistemleri', 'control': 'Kontrol',
                'underwater_sensor': 'Sualtı ve sensör ağları'}


def source_of(work):
    location = work.get('primary_location') or {}
    return openalex_short((location.get('source') or {}).get('id'))


def is_survey(work):
    """A survey by venue, by OpenAlex type, or by its title; returns the reason or None."""
    if source_of(work) in REVIEW_VENUES:
        return 'survey venue'
    if work.get('type') == 'review':
        return 'type review'
    if SURVEY_TITLE.search(work.get('display_name') or ''):
        return 'survey word in title'
    return None


COMM_VENUES = {'S23688054', 'S4210202420', 'S2480266640'}
# What makes an ML survey an EE one outside a communications venue: another topic's term, but not a bare "network".
EE_CONTEXT = [p for name, p in TOPICS if name not in ('ml', 'wireless')] + [
    r'wireless|communication|\b[56]G\b|cellular|mobile|edge computing|Internet of Things|\bIoT\b|radio|spectrum|MIMO'
    r'|satellite|\bUAVs?\b|vehicular|electric']


def topic_of(work):
    """(topic, rule) for a work: the first title rule that matches, else the venue default, else (None, None).
    Machine learning counts only for EE and communications: in a communications venue, or when the title also names
    another topic's term; a general ML survey elsewhere is left out."""
    title = work.get('display_name') or ''
    for name, pattern in TOPICS:
        if found := re.search(pattern, title, re.I):
            if name == 'ml' and source_of(work) not in COMM_VENUES and not any(
                    re.search(p, title, re.I) for p in EE_CONTEXT):
                return None, None
            return name, f'title matches "{found.group(0)}"'
    default = VENUES.get(source_of(work), (None, None, None))[2]
    return (default, 'venue default') if default else (None, None)


def tie(seed, work_id):
    return hashlib.sha256(f'{seed}:{work_id}'.encode()).hexdigest()


def candidates(works):
    """Every survey that passes the rules, with why it passed; duplicates by normalized title keep the first id."""
    out, titles = [], set()
    for w in sorted(works, key=lambda w: openalex_short(w['id'])):
        source = source_of(w)
        year = w.get('publication_year')
        if source not in VENUES or not (YEARS[0] <= (year or 0) <= YEARS[1]):
            continue
        if (w.get('referenced_works_count') or 0) < MIN_REFS:
            continue
        why = is_survey(w)
        topic, rule = topic_of(w)
        key = norm_title(w.get('display_name'))
        if not why or not topic or key in titles or OFF_TOPIC.search(w.get('display_name') or ''):
            continue
        titles.add(key)
        name, tier, _ = VENUES[source]
        out.append({'work': w, 'topic': topic, 'why': {
            'venue': name, 'tier': tier, 'year': year, 'references': w.get('referenced_works_count'),
            'cited_by_count': w.get('cited_by_count'), 'survey_rule': why, 'topic_rule': rule}})
    return out


def select(works, per_topic=PER_TOPIC, seed=SEED, exclude=()):
    """Per topic, surveys ranked by tier, then cited_by_count (high first), then a seeded hash. The first pass takes
    the best survey for each distinct rule match (so three 6G visions do not fill one topic), the second fills the
    remaining places in rank order. Works in `exclude` (the owner's removals) are skipped, so the next one moves up."""
    skip = {openalex_short(w) for w in exclude}
    picked = {}
    for c in candidates(works):
        if openalex_short(c['work']['id']) not in skip:
            picked.setdefault(c['topic'], []).append(c)
    for topic, items in picked.items():
        items.sort(key=lambda c: (c['why']['tier'], -(c['why']['cited_by_count'] or 0),
                                  tie(seed, openalex_short(c['work']['id']))))
        first, seen = [], set()
        for c in items:
            if c['why']['topic_rule'].casefold() not in seen:
                seen.add(c['why']['topic_rule'].casefold())
                first.append(c)
        taken = {id(c) for c in first}
        chosen = {id(c) for c in (first + [c for c in items if id(c) not in taken])[:per_topic]}
        picked[topic] = [c for c in items if id(c) in chosen]  # kept in rank order
    return {t: picked.get(t, []) for t in TOPIC_ORDER}


def abstract(inverted):
    """Plain text from OpenAlex's abstract_inverted_index."""
    if not inverted:
        return None
    words = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    return ' '.join(word for _, word in words)


def gold(survey, references):
    """The kept gold works and the counts behind them. `references` are the OpenAlex records fetched for the survey's
    referenced_works; an id OpenAlex no longer returns is counted as missing, a work dated after the survey (or with
    no date) is cut, and the survey itself is never gold."""
    own = openalex_short(survey['id'])
    cut = survey['publication_date']
    listed = list(dict.fromkeys(openalex_short(w) for w in survey.get('referenced_works') or []))
    found = {openalex_short(r['id']): r for r in references}
    kept, after, undated = [], 0, 0
    for wid in listed:
        record = found.get(wid)
        if wid == own or record is None:
            continue
        date = record.get('publication_date')
        if not date:
            undated += 1
        elif date > cut:
            after += 1
        else:
            kept.append(wid)
    return kept, {'listed': len(listed), 'self': own in listed, 'missing': sum(w not in found for w in listed if w != own),
                  'after_survey': after, 'undated': undated, 'kept': len(kept),
                  'with_abstract': sum(bool(found[w].get('abstract_inverted_index')) for w in kept)}


def gold_record(work):
    """What scoring matches a record against: the OpenAlex id, then the DOI, then the normalized title."""
    return {'openalex': [openalex_short(work['id'])], 'dois': [norm_doi(work['doi'])] if work.get('doi') else [],
            'title': work.get('display_name'), 'date': work.get('publication_date'),
            'has_abstract': bool(work.get('abstract_inverted_index'))}


def split(questions, seed=SEED, share=TUNE_SHARE, frozen=None):
    """{id: 'tune' | 'test'}: within each topic, a seeded shuffle of the ids, and the first third (rounded) tune. An id
    in `frozen` (the split already measured) keeps its side; new ids fill the topic's tune places that are left."""
    frozen = frozen or {}
    by_topic = {}
    for q in questions:
        by_topic.setdefault(q['topic'], []).append(q['id'])
    out = {}
    for topic in sorted(by_topic):
        ids = sorted(by_topic[topic])
        kept = {qid: frozen[qid] for qid in ids if qid in frozen}
        new = [qid for qid in ids if qid not in kept]
        random.Random(f'{seed}:{topic}').shuffle(new)
        tune = max(0, round(len(ids) * share) - sum(v == 'tune' for v in kept.values()))
        out.update(kept)
        out.update({qid: 'tune' if i < tune else 'test' for i, qid in enumerate(new)})
    return out


def question_id(survey_id):
    """Fixed by the survey, so an owner's removal never moves another survey's results onto a different question."""
    return f'ee-{openalex_short(survey_id)}'


def fingerprint(questions):
    """What a measured row and its reading depend on: each question's id, wording, survey, cut date, gold set and
    tune/test side."""
    body = sorted((q['id'], q['body'], q['survey']['openalex'], q['cut_date'], sorted(q['gold']), q['split'])
                  for q in questions)
    return hashlib.sha256(repr(body).encode()).hexdigest()[:16]


SURVEY_MENTION = re.compile(r'\b(this|the|that) (survey|review|tutorial|article|paper|overview)\b', re.I)


def question_problems(question, title, run=6):
    """Why a generated question is not usable: it copies the title (whole, or `run` title words in a row) or points
    at the survey itself."""
    found = []
    q_words, t_words = norm_title(question).split(), norm_title(title).split()
    if norm_title(title) and norm_title(title) in norm_title(question):
        found.append('copies the title')
    elif len(t_words) >= run:
        grams = {tuple(t_words[i:i + run]) for i in range(len(t_words) - run + 1)}
        if any(tuple(q_words[i:i + run]) in grams for i in range(len(q_words) - run + 1)):
            found.append(f'shares {run} title words in a row')
    if SURVEY_MENTION.search(question):
        found.append('mentions the survey')
    return found


SEARCH_ROUTES = ('keyword:', 'semantic:')


def dated(record, cut_date, dates):
    """The record's day, or None when it cannot be told whether it comes after the cut: a year before or after the
    cut's year is enough; the cut's own year (or no year) needs the date OpenAlex gives in `dates`."""
    if record.get('date'):
        return record['date']
    year = record.get('year')
    if year is not None and year != int(cut_date[:4]):
        return f'{year}-01-01' if year < int(cut_date[:4]) else f'{year}-12-31'
    return dates.get(openalex_short(record.get('openalex')) or '')


def undated_ids(questions, runs):
    """OpenAlex ids whose date scoring needs: same-year (or yearless) records and every chain seed."""
    need = set()
    for q in questions:
        for rows in runs.values():
            row = rows.get(q['id']) or {}
            for r in row.get('records') or []:
                if not r.get('date') and r.get('year') in (None, int(q['cut_date'][:4])) and r.get('openalex'):
                    need.add(openalex_short(r['openalex']))
                need.update(openalex_short(s) for s in r.get('chain_seeds') or [] if s)
    return need


def clean(records, question, dates):
    """(the records the arm may count, in order, and why the others went): the survey itself, records after the cut
    or with no date to tell, and records that only a chain from such a work brought in. A record that a search also
    found stays, since it did not need the seed."""
    survey, cut = question['survey']['openalex'], question['cut_date']

    def allowed(wid, day):
        return wid != survey and day is not None and day <= cut

    kept, why = [], {'survey': 0, 'after_cut': 0, 'undated': 0, 'chain_leak': 0}
    for r in records:
        wid = openalex_short(r.get('openalex')) if r.get('openalex') else None
        day = dated(r, cut, dates)
        if wid == survey:
            why['survey'] += 1
        elif day is None:
            why['undated'] += 1
        elif day > cut:
            why['after_cut'] += 1
        elif ('chain' in (r.get('routes') or []) and not any(x.startswith(SEARCH_ROUTES) for x in r['routes'])
              and not any(s and allowed(openalex_short(s), dates.get(openalex_short(s)))
                          for s in r.get('chain_seeds') or [])):
            why['chain_leak'] += 1
        else:
            kept.append(r)
    return kept, why


def exposure(records, question, dates):
    """Whether the run chained from the survey, and from how many works dated after it."""
    seeds = {openalex_short(s) for r in records for s in r.get('chain_seeds') or [] if s}
    cut = question['cut_date']
    return {'survey_seed': question['survey']['openalex'] in seeds,
            'later_seeds': sum(1 for s in seeds if (dates.get(s) or '0') > cut)}


def recall(question, records, gold_meta, depths=DEPTHS):
    """{k: recall} for one question; records are in rank order and already time-filtered."""
    meta = {w: gold_meta.get(w, {}) for w in question['gold']}
    return {k: len(matched(meta, records[:k])) / len(meta) for k in depths}


def score_systems(questions, runs, gold_meta, dates, depths=DEPTHS):
    """({system: {question id: {k: recall} or None}}, {system: dropped counts and exposure}) for each system's rows
    (a failed row is None, a missing one absent); `dates` holds the OpenAlex dates undated_ids asked for."""
    systems, dropped = {}, {}
    for name, rows in runs.items():
        per, why = {}, {'survey': 0, 'after_cut': 0, 'undated': 0, 'chain_leak': 0, 'survey_seed': 0,
                        'later_seed_questions': 0}
        for q in questions:
            row = rows.get(q['id'])
            if row is None:
                continue
            if row.get('error'):
                per[q['id']] = None
                continue
            records, counts = clean(row['records'], q, dates)
            for k, v in counts.items():
                why[k] += v
            seen = exposure(row['records'], q, dates)
            why['survey_seed'] += seen['survey_seed']
            why['later_seed_questions'] += bool(seen['later_seeds'])
            per[q['id']] = recall(q, records, gold_meta, depths)
        systems[name], dropped[name] = per, why
    return systems, dropped


def subset(systems, ids):
    return {name: {q: v for q, v in per.items() if q in ids} for name, per in systems.items()}


def summary(per, depths=DEPTHS):
    """Arm means are over the questions the arm answered (`failed` left out); the paired differences count a failure as
    zero (harness.comparisons)."""
    return {'questions': len(per), 'failed': sum(v is None for v in per.values()),
            **{f'@{k}': macro(per, k) for k in depths}}

