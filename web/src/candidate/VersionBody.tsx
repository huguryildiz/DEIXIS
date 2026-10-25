import type { CandidateVersion } from '../lib/api'
import { t } from '../lib/i18n'
import { dateText, kindLabels, label } from './labels'

// One card version (mockup `candDetail` "Candidate card"): who wrote it and when, the testable elements E1…, then the
// conditions, assumption, nearest simple explanation and validation plan. An earlier version carries its own heading.
export function VersionBody({ version, searches, origin, earlier = false }: { version: CandidateVersion; searches: number; origin?: string; earlier?: boolean }) {
  const author = t(version.origin === 'model_decomposition' ? 'model proposal' : 'your edit')
  return <section className="candidate-version" aria-label={t('Version {n}', { n: version.version })}>
    {earlier && <h5>{t('Version {n}', { n: version.version })}</h5>}
    <p className="foot-note">{author} · {t('Version {n}', { n: version.version })} · {dateText(version.created_at)}</p>
    <ul className="elist">{version.elements.map((element, i) => <li key={element.id}><b>E{i + 1}</b><span><span data-stored-text>{element.text}</span><small>{label(kindLabels, element.kind)}</small></span></li>)}</ul>
    <dl className="kv2">
      {version.claim_statement !== origin && <><dt>{t('Claim statement')}</dt><dd data-stored-text>{version.claim_statement}</dd></>}
      <dt>{t('Conditions')}</dt><dd>{version.conditions.length ? version.conditions.map((text, i) => <span key={i}>{i > 0 && ' · '}<span data-stored-text>{text}</span></span>) : t('None.')}</dd>
      <dt>{t('Critical assumption')}</dt><dd data-stored-text>{version.critical_assumption}</dd>
      <dt>{t('Nearest simple explanation')}</dt><dd>{version.nearest_simple_explanation === null ? <>{t('None stated')}{version.origin === 'model_decomposition' && <small className="candidate-why">{t('The model could not name one from the records it was given, or you left it empty.')}</small>}</> : <span data-stored-text>{version.nearest_simple_explanation}</span>}</dd>
      <dt>{t('Validation plan')}</dt><dd data-stored-text>{version.validation_plan}</dd>
    </dl>
    <p className="foot-note">{t('A validation plan names what check would support, narrow or weaken the claim. It is not an experiment design.')}{version.origin === 'model_decomposition' && <> {t('Written by a model from the text above; its structure was checked by code, its scientific content was not.')}</>}</p>
    {searches > 0 && <p className="foot-note">{t('{n} searches ran on this version', { n: searches })}</p>}
  </section>
}
