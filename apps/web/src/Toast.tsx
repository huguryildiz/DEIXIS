import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CircleCheck, CircleX, TriangleAlert, X } from 'lucide-react'
import { t } from './i18n'

export type ToastTone = 'success' | 'warning' | 'error'
// An action such as "Undo" calls the same endpoint as the Trash page (D50); closing the toast changes nothing.
export type ToastAction = { label: string; run: () => void }
type Toast = { tone: ToastTone; text: string; action?: ToastAction; id: number }

const icons = { success: CircleCheck, warning: TriangleAlert, error: CircleX }
const ToastContext = createContext<(tone: ToastTone, text: string, action?: ToastAction) => void>(() => {})

export const useToast = () => useContext(ToastContext)

// One toast at a time, portaled above sheets. Errors stay until dismissed so they are not missed; a toast with an action
// stays longer and waits while the pointer or keyboard focus is on it.
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null)
  const [held, setHeld] = useState(false)
  const show = useCallback((tone: ToastTone, text: string, action?: ToastAction) => { setHeld(false); setToast({ tone, text, action, id: Date.now() }) }, [])
  const close = () => { setHeld(false); setToast(null) }
  useEffect(() => {
    if (!toast || toast.tone === 'error' || held) return
    const timer = setTimeout(() => setToast(null), toast.action ? 12000 : 5000)
    return () => clearTimeout(timer)
  }, [toast, held])
  const Icon = toast ? icons[toast.tone] : null
  return <ToastContext.Provider value={show}>
    {children}
    {toast && Icon && createPortal(<div key={toast.id} role={toast.tone === 'error' ? 'alert' : 'status'} className={`toast is-${toast.tone}`}
      onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHeld(false) }}>
      <Icon size={16} aria-hidden /><span>{toast.text}</span>
      {toast.action && <button type="button" className="toast-action" onClick={() => { const { run } = toast.action!; close(); run() }}>{toast.action.label}</button>}
      <button type="button" aria-label={t('Dismiss notification')} onClick={close}><X size={16} /></button>
    </div>, document.body)}
  </ToastContext.Provider>
}
