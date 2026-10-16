import { useEffect, useState } from 'react'
import { api, shellApi, type ContactEmailSetting, type Connections, type ModelRole, type RoleModelSetting, type SemanticSearch } from './api'
import { t, uiLocale } from './i18n'
import { connectionName } from './labels'

// Where your data goes (F3): one place that says which kind of data reaches which service, built from the settings as
// they are now. Wording follows what the code does: the fast path sends searches to OpenAlex, Semantic Scholar and
// Crossref (and Scopus when its key is set) and nothing to the other sources. Nothing here was measured on the network.
const SEARCH_SOURCES: [string, string][] = [['openalex', 'OpenAlex'], ['semantic_scholar', 'Semantic Scholar'], ['crossref', 'Crossref'], ['scopus', 'Scopus']]
// Connections whose models run on this computer; every other connection reaches a service.
const LOCAL_CONNECTIONS = ['ollama', 'local_server']

const list = (names: string[]) => new Intl.ListFormat(uiLocale(), { style: 'long', type: 'conjunction' }).format(names)

type DataFlowInput = {
  /** The default model of each role; null while unread. */
  defaults: Record<ModelRole, RoleModelSetting> | null
  connections: Connections | null
  semantic: SemanticSearch | null
  email: ContactEmailSetting | null
}

/** The rows as [heading, text]; a text is null while its setting is still unread. */
function dataFlowRows({ defaults, connections, semantic, email }: DataFlowInput): [string, string | null][] {
  const picked = defaults ? [...new Set(Object.values(defaults).filter(d => d.model).map(d => d.model_connection))] : null
  const remote = (picked ?? []).filter(c => !LOCAL_CONNECTIONS.includes(c)).map(connectionName)
  const local = (picked ?? []).filter(c => LOCAL_CONNECTIONS.includes(c)).map(connectionName)
  const models = !picked ? null
    : !picked.length ? t('No default model is chosen yet. A research sends its question, search words, abstracts and passages to the model it is started with.')
    : !remote.length ? t('The models you picked run on this computer ({names}), so your question, search words, abstracts and passages are not sent to a model service.', { names: list(local) })
    : t('Your question, search words, abstracts, and passages and excerpts from PDFs are sent to: {names}.', { names: list(remote) })
      + (local.length ? ` ${t('Running on this computer: {names}.', { names: list(local) })}` : '')

  // The first three need no key; Scopus is named only once its key is set.
  const sources = !connections ? null : t('Search queries are sent to: {names}.', {
    names: list(SEARCH_SOURCES.filter(([id]) => id !== 'scopus' || connections.providers.find(p => p.id === 'scopus')?.access_mode === 'api_key').map(([, name]) => name)),
  })

  const mail = !email ? null
    : email.email ? t('Your email address ({email}) is sent to OpenAlex and Crossref with each request.', { email: email.email })
    : email.environment_set ? t('An email address set when DEIXIS started is sent to OpenAlex and Crossref with each request.')
    : t('No email address is set, so none is sent.')

  const search = !semantic ? null
    : semantic.provider === 'gemini' ? t('Titles, abstracts and passage text are sent to {service}.', { service: 'Google' })
    : semantic.provider === 'openai' ? t('Titles, abstracts and passage text are sent to {service}.', { service: 'OpenAI' })
    : semantic.provider === 'builtin' ? t('Not sent anywhere. The built-in model runs on this computer.')
    : semantic.provider === 'off' ? t('Semantic search is off. Nothing is sent.')
    : t('Stays on this computer. {server} reads it and runs here.', { server: semantic.provider === 'ollama' ? 'Ollama' : 'LM Studio' })

  const copilot = connections?.models.copilot_cli?.installed
  const usage = t('DEIXIS sends no usage data. The telemetry of the connected command-line tools is switched off: Claude Code, Codex and Gemini CLI.')
    + (copilot ? ` ${t('GitHub Copilot CLI is the exception: its documentation names no switch for it, so DEIXIS leaves it as it is.')}` : '')

  return [
    [t('Model calls'), models],
    [t('Search queries'), sources],
    [t('Email address'), mail],
    [t('Semantic search'), search],
    [t('Library and PDFs'), t('Your library, notes and PDFs stay on this computer.')],
    [t('Your keys'), t('Keys are stored on this computer. Each one is sent only to the service it belongs to, to show the request is yours.')],
    [t('Usage data'), usage],
  ]
}

/** Read again each time the General tab is shown, so a change made on another tab is already in the text, and when `refresh`
 *  changes (the email saved on this tab). */
export function DataFlowsSection({ defaults, active, refresh }: { defaults: Record<ModelRole, RoleModelSetting> | null; active: boolean; refresh: number }) {
  const [connections, setConnections] = useState<Connections | null>(null)
  const [semantic, setSemantic] = useState<SemanticSearch | null>(null)
  const [email, setEmail] = useState<ContactEmailSetting | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!active) return
    let live = true
    const fail = () => { if (live) setFailed(true) }
    api.connections().then(value => { if (live) setConnections(value) }, fail)
    api.semanticSearch().then(value => { if (live) setSemantic(value) }, fail)
    shellApi.contactEmail().then(value => { if (live) setEmail(value) }, fail)
    return () => { live = false }
  }, [active, refresh])
  return <>
    <h2 id="data-flows" data-panel="general">{t('Where your data goes')}</h2>
    <div className="rows set-flows" data-panel="general">
      {dataFlowRows({ defaults, connections, semantic, email }).map(([heading, text]) => <div key={heading}>
        <b>{heading}</b>
        <p>{text ?? t(failed ? 'Could not be read.' : 'Checking…')}</p>
      </div>)}
    </div>
  </>
}
