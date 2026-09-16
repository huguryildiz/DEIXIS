import { Dialog } from '@base-ui/react/dialog'
import { Info, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'

// neutral: an action that can be undone (removing a source from a research, starting a table); red stays for what cannot.
export function ConfirmDialog({ open, dark, title, description, context, confirmLabel, cancelLabel, busy = false, neutral = false, onConfirm, onOpenChange }: {
  open: boolean
  dark: boolean
  title: string
  description: string
  context?: string
  confirmLabel: string
  cancelLabel: string
  busy?: boolean
  neutral?: boolean
  onConfirm: () => void
  onOpenChange: (open: boolean) => void
}) {
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) onOpenChange(next) }}>
    <Dialog.Portal>
      <Dialog.Backdrop className="confirm-dialog-backdrop" />
      <Dialog.Popup className={`confirm-dialog ${dark ? 'dark' : ''}${neutral ? ' is-neutral' : ''}`}>
        <div className="confirm-dialog-heading">
          <span className="confirm-dialog-mark">{neutral ? <Info size={17} aria-hidden /> : <TriangleAlert size={17} aria-hidden />}</span>
          <div>
            <Dialog.Title className="confirm-dialog-title">{title}</Dialog.Title>
            <Dialog.Description className="confirm-dialog-description">{description}</Dialog.Description>
          </div>
        </div>
        {context && <p className="confirm-dialog-context" title={context}>{context}</p>}
        <div className="confirm-dialog-actions">
          <Button className="confirm-dialog-cancel" variant="outline" autoFocus disabled={busy} onClick={() => onOpenChange(false)}>{cancelLabel}</Button>
          <Button className={neutral ? undefined : 'confirm-dialog-danger'} variant={neutral ? 'default' : 'destructive'} disabled={busy} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>
}
