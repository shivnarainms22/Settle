import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Activity, type SimState } from '../api'
import { streamUrl } from '../auth'
import { useInterval } from '../hooks'

const MAX_FEED = 300

interface SimCtx {
  sim: SimState | null
  activities: Activity[] // newest first
  error: Error | null
  transport: 'sse' | 'polling' | 'connecting'
  busy: boolean
  /** Run a sim-mutating call, adopt returned state, and refresh the feed. */
  run: (fn: () => Promise<SimState>, opts?: { resetFeed?: boolean }) => Promise<void>
  refresh: () => void
}

const Ctx = createContext<SimCtx | null>(null)

export function useSim(): SimCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useSim outside SimProvider')
  return c
}

export function SimProvider({ children }: { children: ReactNode }) {
  const [sim, setSim] = useState<SimState | null>(null)
  const [activities, setActivities] = useState<Activity[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [transport, setTransport] = useState<SimCtx['transport']>('connecting')
  const [busy, setBusy] = useState(false)
  const lastId = useRef(0)

  const addActivities = useCallback((incoming: Activity[]) => {
    if (incoming.length === 0) return
    setActivities((prev) => {
      const seen = new Set(prev.map((a) => a.id))
      const fresh = incoming.filter((a) => !seen.has(a.id))
      if (fresh.length === 0) return prev
      const merged = [...fresh, ...prev].sort((a, b) => b.id - a.id).slice(0, MAX_FEED)
      return merged
    })
    lastId.current = Math.max(lastId.current, ...incoming.map((a) => a.id))
  }, [])

  const fetchState = useCallback(() => {
    api.state().then(
      (s) => { setSim(s); setError(null) },
      (e) => setError(e),
    )
  }, [])

  const pollActivity = useCallback(() => {
    api.activity(lastId.current).then(
      (rows) => { addActivities(rows); setError(null) },
      (e) => setError(e),
    )
  }, [addActivities])

  // A reset moves ids backwards: drop the local feed and start over.
  const resetFeed = useCallback(() => {
    lastId.current = 0
    setActivities([])
  }, [])

  const refresh = useCallback(() => {
    fetchState()
    pollActivity()
  }, [fetchState, pollActivity])

  const run = useCallback(
    async (fn: () => Promise<SimState>, opts?: { resetFeed?: boolean }) => {
      setBusy(true)
      try {
        const s = await fn()
        if (opts?.resetFeed) resetFeed()
        setSim(s)
        setError(null)
        pollActivity()
      } catch (e) {
        setError(e instanceof Error ? e : new Error(String(e)))
      } finally {
        setBusy(false)
      }
    },
    [pollActivity, resetFeed],
  )

  useEffect(() => {
    fetchState()
    pollActivity()
  }, [fetchState, pollActivity])

  // SSE with polling fallback
  useEffect(() => {
    if (typeof EventSource === 'undefined') { setTransport('polling'); return }
    const es = new EventSource(streamUrl())
    es.onopen = () => setTransport('sse')
    es.addEventListener('activity', (ev) => {
      try { addActivities([JSON.parse((ev as MessageEvent).data) as Activity]) }
      catch (e) { setError(new Error(`Bad activity event: ${e instanceof Error ? e.message : e}`)) }
    })
    es.addEventListener('state', (ev) => {
      try { setSim(JSON.parse((ev as MessageEvent).data) as SimState); setError(null) }
      catch (e) { setError(new Error(`Bad state event: ${e instanceof Error ? e.message : e}`)) }
    })
    es.onerror = () => {
      // Stop retrying SSE; the 2s poll takes over.
      es.close()
      setTransport('polling')
    }
    return () => es.close()
  }, [addActivities])

  useInterval(() => { pollActivity(); fetchState() }, transport === 'polling' ? 2000 : null)
  // While backend unreachable (even under SSE), keep retrying so the banner clears itself.
  useInterval(fetchState, error && transport !== 'polling' ? 3000 : null)

  return (
    <Ctx.Provider value={{ sim, activities, error, transport, busy, run, refresh }}>
      {children}
    </Ctx.Provider>
  )
}
