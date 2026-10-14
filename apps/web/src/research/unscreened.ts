import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, screenMoreApi, type UnscreenedPage } from '../api'
import { t } from '../i18n'

// The never-screened works of the ranked list (F12) and "Screen N more" (F13), shared by the Sources panel's "Not read"
// tab (P5, P7) and the Search funnel panel (P41; UI parity S27). The list and its count come from one route: `total`
// counts the works the pages list, in the frozen list's order. Rank and similarity are the signals it was ordered by.

export const SCREEN_MORE_SIZE = 40  // screen_more.SIZE: the next 40 screenable works of the ranked list
const PAGE = 50

export type Unscreened = {
  page: UnscreenedPage | null; items: UnscreenedPage['items']
  // 'none': the research has no completed search with a ranked list; 'failed': the list could not be read.
  status: 'loading' | 'ready' | 'none' | 'failed'
  loadingMore: boolean; moreFailed: boolean; more: () => void; reload: () => Promise<void>
}

// The first page is read again on every recorded event (the list shrinks as works are screened); each read gets a
// number, so a page that arrives after a newer read started is dropped, and "Show more" is locked while it runs.
export function useUnscreened(researchId: string, cursor: number): Unscreened {
  const [page, setPage] = useState<UnscreenedPage | null>(null)
  const [items, setItems] = useState<UnscreenedPage['items']>([])
  const [status, setStatus] = useState<Unscreened['status']>('loading')
  const [loadingMore, setLoadingMore] = useState(false)
  const [moreFailed, setMoreFailed] = useState(false)
  const read = useRef(0)
  const reload = useCallback(() => {
    const seq = ++read.current
    return screenMoreApi.unscreened(researchId, 0, PAGE).then(next => {
      if (seq !== read.current) return
      setPage(next); setItems(next.items); setStatus('ready'); setMoreFailed(false)
    }, e => {
      if (seq !== read.current) return
      // A failed refresh keeps no rows from before it: the tab says the list could not be read.
      setPage(null); setItems([])
      setStatus(e instanceof ApiError && e.status === 422 ? 'none' : 'failed')
    })
  }, [researchId])
  useEffect(() => { void reload() }, [reload, cursor])
  const more = () => {
    if (!page || loadingMore) return
    const seq = read.current
    setLoadingMore(true)
    setMoreFailed(false)
    void screenMoreApi.unscreened(researchId, items.length, PAGE).then(next => {
      if (seq === read.current) setItems(previous => [...previous, ...next.items])
    }, () => { if (seq === read.current) setMoreFailed(true) }).finally(() => setLoadingMore(false))
  }
  return { page, items, status, loadingMore, moreFailed, more, reload }
}

// Queues one Screen more run and reports what the server returned: the number of works the run planned, read twice at
// the abstract stage. It never includes a source by itself. Locked while the request runs.
export function useScreenMore(researchId: string, toast: (tone: 'success' | 'error', text: string) => void, after: () => Promise<unknown>) {
  const [screening, setScreening] = useState(false)
  const lock = useRef(false)
  const screenMore = async () => {
    if (lock.current) return
    lock.current = true
    setScreening(true)
    try {
      const run = await screenMoreApi.screenMore(researchId, crypto.randomUUID())
      const planned = (run.budget as unknown as { screen_more?: { planned?: number } }).screen_more?.planned
      toast('success', planned === undefined
        ? t('Screen more queued. Its works are read twice at the abstract stage; it never includes a source by itself.')
        : t(planned === 1 ? 'Screen more queued: {n} work is read twice at the abstract stage. It never includes a source by itself.' : 'Screen more queued: {n} works are read twice at the abstract stage. It never includes a source by itself.', { n: planned }))
      await after()
    } catch (e) {
      toast('error', e instanceof ApiError && e.status === 409 ? t('Another run of this research is active, so Screen more was not queued.')
        : e instanceof ApiError && e.code === 'nothing_left' ? t('No work with an abstract is left on the ranked list, so Screen more was not queued.')
        : e instanceof ApiError && e.code === 'no_completed_discovery' ? t('This research has no completed search with a ranked list, so Screen more was not queued.')
        : e instanceof Error ? e.message : String(e))
    } finally { lock.current = false; setScreening(false) }
  }
  return { screening, screenMore }
}
