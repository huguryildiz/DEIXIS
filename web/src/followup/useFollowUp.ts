import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Watch, type WatchItem } from '../api'

export function useFollowUpCount(id: string, event: number | undefined) {
  const [state, setState] = useState<{ count: number | null; loading: boolean }>({ count: null, loading: true })
  const generation = useRef(0)
  const invalidate = useCallback(() => { ++generation.current }, [])
  const reload = useCallback(async () => {
    const ticket = ++generation.current
    setState(previous => ({ ...previous, loading: true }))
    try {
      const items = await api.watchItems(id)
      if (ticket === generation.current) setState({ count: items.filter(item => item.kind === 'new_record').length, loading: false })
    } catch { if (ticket === generation.current) setState({ count: null, loading: false }) }
  }, [id])
  useEffect(() => {
    let live = true
    void Promise.resolve().then(() => { if (live) void reload() })
    return () => { live = false; invalidate() }
  }, [reload, event, invalidate])
  return { ...state, reload }
}

export function useFollowUp(id: string, event: number, onReload: () => Promise<void>) {
  const [watches, setWatches] = useState<Watch[]>([])
  const [items, setItems] = useState<WatchItem[]>([])
  const [itemsLoaded, setItemsLoaded] = useState(false)
  const [history, setHistory] = useState<WatchItem[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const loaded = useRef(false)
  const generation = useRef(0)
  const invalidate = useCallback(() => { ++generation.current }, [])
  const reload = useCallback(async () => {
    const ticket = ++generation.current
    setLoading(!loaded.current)
    const results = await Promise.allSettled([api.watches(id), api.watchItems(id),
      ...(historyOpen ? [Promise.all([api.watchItems(id, 'dismissed'), api.watchItems(id, 'merged')]).then(lists => lists.flat())] : [])])
    if (ticket !== generation.current) return
    const [watchResult, itemResult, historyResult] = results
    if (watchResult.status === 'fulfilled' && itemResult.status === 'fulfilled') loaded.current = true
    if (watchResult.status === 'fulfilled') setWatches(watchResult.value as Watch[])
    if (itemResult.status === 'fulfilled') { setItems(itemResult.value as WatchItem[]); setItemsLoaded(true) }
    if (historyResult?.status === 'fulfilled') { setHistory(historyResult.value as WatchItem[]); setHistoryLoaded(true) }
    setError(results.filter(result => result.status === 'rejected').map(result => String(result.reason instanceof Error ? result.reason.message : result.reason)).join(' · '))
    setLoading(false)
    await onReload()
  }, [id, onReload, historyOpen])
  useEffect(() => {
    let live = true
    void Promise.resolve().then(() => { if (live) void reload() })
    return () => { live = false; invalidate() }
  }, [reload, event, invalidate])
  return { watches, items, itemsLoaded, history, historyLoaded, loading, error, reload, setHistoryOpen }
}
