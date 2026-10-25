import { CircleX } from 'lucide-react'
import { t } from '../lib/i18n'
import type { useFollowUpCommand } from './commands'

// What the server said about a follow-up command: its refusal, that it is still on its way, or that no HTTP answer came
// back (Retry sends the same command with the same key).
export function CommandFeedback({ command }: { command: ReturnType<typeof useFollowUpCommand> }) {
  return <>
    {command.error && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{command.error}</span></div>}
    {command.busy && <p role="status" className="foot-note"><span className="shimmer-text">{t('Sending follow-up command…')}</span></p>}
    {command.pending && !command.busy && <div className="notice bad" role="alert"><CircleX aria-hidden /><div className="nb"><span>{t('The request did not receive an HTTP answer. Retry sends the same command.')}</span><div className="acts"><button type="button" className="ghost" onClick={() => { void command.retry() }}>{t('Retry')}</button></div></div></div>}
  </>
}
