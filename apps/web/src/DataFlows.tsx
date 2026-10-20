import { useEffect, useState } from 'react'
import { api, shellApi, type ContactEmailSetting, type Connections, type ModelRole, type RoleModelSetting, type SemanticSearch } from './api'
import { t, uiLocale } from './i18n'
import { connectionName } from './labels'

// Where your data goes (F3): one place that says which kind of data reaches which service, built from the settings as
// they are now. It describes flows and promises nothing the code does not enforce. What the fast path sends where:
// OpenAlex gets the search words (Semantic Scholar too in Detailed mode); Semantic Scholar, Crossref and Scopus get DOIs
// for abstracts and metadata; OpenAlex, Unpaywall (only with an email), CORE (only with a key) and Europe PMC get DOIs
// to find a PDF. SerpApi gets a title only from the "Find PDF" action (acquire_for_source with web_search on), never
// from a research run. Nothing here was measured on the network.

const list = (names: string[]) => new Intl.ListFormat(uiLocale(), { style: 'long', type: 'conjunction' }).format(names)

type DataFlowInput = {
  /** The default model of each role; null while unread. */
  defaults: Record<ModelRole, RoleModelSetting> | null
  connections: Connections | null
  semantic: SemanticSearch | null
  email: ContactEmailSetting | null
  /** Optional services that are on now: Mathpix with its switch on and keys saved, a Zotero web key; null while unread. */
  optional: { mathpix: boolean; zoteroWeb: boolean } | null
}

/** The rows as [heading, text]; a text is null while its setting is still unread; a row with nothing to say is left out. */
function dataFlowRows({ defaults, connections, semantic, email, optional }: DataFlowInput): [string, string | null][] {
  const picked = defaults ? [...new Set(Object.values(defaults).filter(d => d.model).map(d => d.model_connection))] : null
  const models = !picked ? null
    : t('A research sends its question, search words, abstracts, and passages and excerpts from PDFs to the model you choose for it. An account or API provider receives them. A local server receives them on this computer, unless that server forwards them elsewhere; Ollama does this for its cloud models.')
      + ' ' + (picked.length ? t('Default models now: {names}.', { names: list(picked.map(connectionName)) }) : t('No default model is chosen yet.'))

  const mailSet = !!email && (!!email.email || email.environment_set)
  const access = (id: string) => connections?.providers.find(p => p.id === id)?.access_mode === 'api_key'
  const dois = !connections || !email ? null : t('The DOI of each work found is sent to: {names}, to read abstracts, check details and look for a PDF.', {
    names: list(['OpenAlex', 'Semantic Scholar', 'Crossref', 'Europe PMC', ...(mailSet ? ['Unpaywall'] : []), ...(access('core') ? ['CORE'] : []), ...(access('scopus') ? ['Scopus'] : [])]),
  })

  const mail = !email ? null
    : email.email ? t('Your email address ({email}) is sent to OpenAlex and Crossref with each request, and to Unpaywall with each PDF lookup.', { email: email.email })
    : email.environment_set ? t('An email address set when DEIXIS started is sent to OpenAlex and Crossref with each request, and to Unpaywall with each PDF lookup.')
    : t('No email address is set, so none is sent. Without one DEIXIS does not ask Unpaywall for PDFs.')

  const search = !semantic ? null
    : semantic.provider === 'gemini' ? t('Titles, abstracts and passage text are sent to {service}.', { service: 'Google' })
    : semantic.provider === 'openai' ? t('Titles, abstracts and passage text are sent to {service}.', { service: 'OpenAI' })
    : semantic.provider === 'builtin' ? t('Not sent anywhere. The built-in model runs on this computer.')
    : semantic.provider === 'off' ? t('Semantic search is off. Nothing is sent.')
    : t('Stays on this computer. {server} reads it and runs here.', { server: semantic.provider === 'ollama' ? 'Ollama' : 'LM Studio' })

  const extras = !optional || !connections ? null : [
    ...(optional.mathpix ? [t('Mathpix is on: images of equation areas cut from PDFs are sent to Mathpix.')] : []),
    ...(access('serpapi') ? [t('SerpApi: when you ask DEIXIS to find a PDF and none is found, the work’s title is sent to SerpApi.')] : []),
    ...(optional.zoteroWeb ? [t('A Zotero web key is saved: when you use your web library, titles and DOIs of works are sent to zotero.org to find their PDFs.')] : []),
  ]

  const copilot = connections?.models.copilot_cli?.installed
  const usage = t('DEIXIS sends no usage data. Whenever it runs Claude Code, Codex or Gemini CLI it switches their telemetry off, in their sign-in windows too.')
    + (copilot ? ` ${t('GitHub Copilot CLI has no documented telemetry switch for subscription use, so DEIXIS sets none.')}` : '')

  return [
    [t('Model calls'), models],
    [t('Search queries'), t('Words from your question are sent to OpenAlex, and in Detailed mode to Semantic Scholar too.')],
    [t('Lookups by DOI'), dois],
    [t('PDF downloads'), t('To fetch a PDF, DEIXIS requests it from the publisher, repository or preprint server that hosts it, so that server sees the request.')],
    [t('Email address'), mail],
    [t('Semantic search'), search],
    ...(extras === null ? [[t('Optional services'), null] as [string, string | null]] : extras.length ? [[t('Optional services'), extras.join(' ')] as [string, string | null]] : []),
    [t('Storage'), t('Your library, notes and PDF files are kept on this computer.')],
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
  const [optional, setOptional] = useState<DataFlowInput['optional']>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!active) return
    let live = true
    const fail = () => { if (live) setFailed(true) }
    api.connections().then(value => { if (live) setConnections(value) }, fail)
    api.semanticSearch().then(value => { if (live) setSemantic(value) }, fail)
    shellApi.contactEmail().then(value => { if (live) setEmail(value) }, fail)
    Promise.all([api.mathpix(), api.credentials()]).then(([mathpix, credentials]) => {
      if (live) setOptional({ mathpix: mathpix.switch === 'on' && mathpix.pair.configured,
        zoteroWeb: credentials.keys.some(k => k.env === 'ZOTERO_API_KEY' && k.configured) })
    }, fail)
    return () => { live = false }
  }, [active, refresh])
  return <>
    <h2 id="data-flows" data-panel="general">{t('Where your data goes')}</h2>
    <div className="rows set-flows" data-panel="general">
      {dataFlowRows({ defaults, connections, semantic, email, optional }).map(([heading, text]) => <div key={heading}>
        <b>{heading}</b>
        <p>{text ?? (failed ? t('Could not be read.') : <span className="shimmer-text">{t('Checking…')}</span>)}</p>
      </div>)}
    </div>
  </>
}
