import type { CandidateVersion } from '../api'
import { t } from '../i18n'
import { dateText, kindLabels, label } from './labels'

export function VersionBody({ version, searches }: { version: CandidateVersion; searches: number }) {
  return <section className="candidate-version" aria-label={t('Version {n}', { n: version.version })}>
    <h3>{t('Version {n}', { n: version.version })}</h3>
    <p>{t(version.origin === 'model_decomposition' ? 'model proposal' : 'your edit')} · {dateText(version.created_at)}</p>
    <h4>{t('Claim statement')}</h4><p className="candidate-claim" data-stored-text>{version.claim_statement}</p>
    <h4>{t('Conditions')}</h4>{version.conditions.length ? <ul>{version.conditions.map((text, i) => <li key={i} data-stored-text>{text}</li>)}</ul> : <p>{t('None.')}</p>}
    <h4>{t('Elements')}</h4><ol>{version.elements.map(element => <li key={element.id}><span>{label(kindLabels, element.kind)}: </span><span data-stored-text>{element.text}</span></li>)}</ol>
    <h4>{t('Nearest simple explanation')}</h4>{version.nearest_simple_explanation === null ? <><p>{t('None stated')}</p>{version.origin === 'model_decomposition' && <p>{t('The model could not name one from the records it was given, or you left it empty.')}</p>}</> : <p data-stored-text>{version.nearest_simple_explanation}</p>}
    <h4>{t('Critical assumption')}</h4><p data-stored-text>{version.critical_assumption}</p>
    <h4>{t('Validation plan')}</h4><p data-stored-text>{version.validation_plan}</p>
    <p className="candidate-fine">{t('A validation plan names what check would support, narrow or weaken the claim. It is not an experiment design.')}</p>
    {version.origin === 'model_decomposition' && <p className="candidate-fine">{t('Written by a model from the text above; its structure was checked by code, its scientific content was not.')}</p>}
    {searches > 0 && <p>{t('{n} searches ran on this version', { n: searches })}</p>}
  </section>
}
