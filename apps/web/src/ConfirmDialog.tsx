import { Info, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import type { ReactNode } from 'react'

// neutral: an action that can be undone (removing a source from a research, starting a table); red stays for what cannot.
// Drawn in the shared dialog shell (mockup `.pal.dlg`): icon and title in the head, the text in the body, the actions in the footer.
export function ConfirmDialog({ open, dark, title, description, context, children, confirmLabel, cancelLabel, busy = false, neutral = false, onConfirm, onOpenChange }: {
  open: boolean
  dark: boolean
  title: string
  description: string
  context?: string
  children?: ReactNode
  confirmLabel: string
  cancelLabel: string
  busy?: boolean
  neutral?: boolean
  onConfirm: () => void
  onOpenChange: (open: boolean) => void
}) {
  return <Dialog open={open} onOpenChange={next => { if (!busy) onOpenChange(next) }}>
    <DialogContent className={`confirm-dialog ${dark ? 'dark' : ''}${neutral ? ' is-neutral' : ''}`} backdropClassName="confirm-dialog-backdrop"
      icon={<span className="confirm-dialog-mark">{neutral ? <Info size={16} aria-hidden /> : <TriangleAlert size={16} aria-hidden />}</span>} title={title}>
      <DialogBody>
        <DialogDescription className="confirm-dialog-description">{description}</DialogDescription>
        {context && <p className="confirm-dialog-context" title={context}>{context}</p>}
        {children}
      </DialogBody>
      <DialogFooter className="confirm-dialog-actions">
        <Button className="confirm-dialog-cancel" variant="outline" autoFocus disabled={busy} onClick={() => onOpenChange(false)}>{cancelLabel}</Button>
        <Button className={neutral ? undefined : 'confirm-dialog-danger'} variant={neutral ? 'default' : 'destructive'} disabled={busy} onClick={onConfirm}>{confirmLabel}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
