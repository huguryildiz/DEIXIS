import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { CitationChaining, RunApproval } from './api'
import { approvedByText } from './labels'
import { t } from './i18n'

// The protocol a discovery run froze before it searched (D80). Nobody reviews it any more: the run goes on without
// asking, so the record folds to one line. Opened, it shows the queries that were sent and the citation chain the run
// will follow.
export function ProtocolApproval({ approval }: { approval: RunApproval }) {
  const [open, setOpen] = useState(false)
  const approved = approval.approved
  return <section className="approval-card is-approved">
    <button type="button" className="approval-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? <ChevronDown size={15} aria-hidden /> : <ChevronRight size={15} aria-hidden />}
      <span>{approvedByText(approval.approved_by)}</span>
      {approval.approved_by === 'unattended' && <small>{t('not reviewed, fast path')}</small>}
    </button>
    {open && <div className="approval-diff">
      {approval.approved_by === 'unattended'
        && <p className="approval-hint">{t('Nobody reviewed the search vocabulary; the fast path went on without asking.')}</p>}
      {approved.queries.length > 0 && <div className="approval-diff-group">
        <strong>{t('Queries sent')}</strong>
        <ul>{approved.queries.map(query => <li key={`${query.provider_id}:${query.query_text}`}>
          {query.origin && <small>{t(query.origin === 'model' ? 'model' : 'from the question’s words')}</small>} <code>{query.query_text}</code></li>)}</ul>
      </div>}
      {approval.chaining && <ChainingSection chaining={approval.chaining} />}
    </div>}
  </section>
}

// The fast chain this run will follow (`fast_chain_v1`), as its budget froze it: OpenAlex only. It starts during the
// search, from the first works of OpenAlex's semantic search (the ranking fills in when that search gives fewer), and
// only replies that arrive before the arrival cutoff (the ranking deadline minus `arrival_margin_ms`) add works. The seeds themselves are listed in the run view.
function ChainingSection({ chaining }: { chaining: CitationChaining }) {
  return <div className="approval-chaining">
    <div className="approval-block-head">
      <strong>{t('Citation chaining')}</strong>
      <small>{t('OpenAlex only. While the search runs, OpenAlex is asked for the works that the first {seeds} works of its semantic search cite, and for the works that cite them; when that search gives fewer works, the ranking fills the list. Works you verified are not used as seeds. A new work is kept when a setting or task term stands in its title or abstract and its reply arrives a few seconds before the ranking stage ends; the seeds are listed in the run once the search is done.', { seeds: chaining.seeds })}</small>
    </div>
    <p className="approval-hint">{t('Up to {backward} reference requests and {forward} citing requests · up to {cap} citing works per request · at most {attempts} attempts with retries', { backward: chaining.backward_requests, forward: chaining.forward_requests, cap: chaining.citing_cap, attempts: chaining.attempt_limit })}</p>
  </div>
}
