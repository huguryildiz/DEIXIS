import { Fragment, type RefObject } from 'react'
import { Keyboard } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter } from '@/components/ui/dialog'
import { KEY_SECTIONS } from './Shortcuts'
import { t } from '../lib/i18n'

// The keys dialog (mockup `keysDlg`, O2): the shortcuts in three sections, and one line at its foot that turns the single
// keys off (WCAG 2.1.4), kept across reloads.
export function KeysDialog({ open, onOpenChange, returnFocus, singleKeys, onSingleKeys }: {
  open: boolean; onOpenChange: (open: boolean) => void; returnFocus: RefObject<HTMLElement | null>
  singleKeys: boolean; onSingleKeys: (on: boolean) => void
}) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="keys-dialog" icon={<Keyboard size={16} aria-hidden="true" />} title={t('Shortcuts')}
      finalFocus={() => (returnFocus.current?.isConnected ? returnFocus.current : null)}>
      <div className="keys">
        {KEY_SECTIONS.map(section => <Fragment key={section.heading}>
          <h3 className="keys-heading"><span>{t(section.heading)}</span></h3>
          {section.rows.map(row => <Fragment key={row.label}>
            <span>{t(row.label)}</span>
            <span className="keys-keys">{row.keys.map((key, index) => <Fragment key={index}>{index > 0 && ' '}<kbd>{key}</kbd></Fragment>)}</span>
          </Fragment>)}
        </Fragment>)}
      </div>
      <DialogFooter className="keys-foot">
        <label><input type="checkbox" checked={singleKeys} onChange={event => onSingleKeys(event.target.checked)} />{t('Single-key shortcuts')}</label>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
