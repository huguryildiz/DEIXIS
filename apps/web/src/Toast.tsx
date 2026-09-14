import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CircleCheck, CircleX, TriangleAlert, X } from 'lucide-react'
import { t } from './i18n'

export type ToastTone = 'success' | 'warning' | 'error'
type Toast = { tone: ToastTone; text: string }

const icons = { success: CircleCheck, warning: TriangleAlert, error: CircleX }
const ToastContext = createContext<(tone: ToastTone, text: string) => void>(() => {})

export const useToast = () => useContext(ToastContext)

// One toast at a time, portaled above sheets. Errors stay until dismissed so they are not missed.
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null)
  const show = useCallback((tone: ToastTone, text: string) => setToast({ tone, text }), [])
  useEffect(() => {
    if (!toast || toast.tone === 'error') return
    const timer = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(timer)
  }, [toast])
  const Icon = toast ? icons[toast.tone] : null
  return <ToastContext.Provider value={show}>
    {children}
    {toast && Icon && createPortal(<div role={toast.tone === 'error' ? 'alert' : 'status'} className={`toast is-${toast.tone}`}>
      <Icon size={16} aria-hidden /><span>{toast.text}</span>
      <button type="button" aria-label={t('Dismiss notification')} onClick={() => setToast(null)}><X size={16} /></button>
    </div>, document.body)}
  </ToastContext.Provider>
}
