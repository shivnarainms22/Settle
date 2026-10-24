import { useCallback, useEffect, useRef, useState } from 'react'

export function useInterval(fn: () => void, ms: number | null) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (ms === null) return
    const t = setInterval(() => ref.current(), ms)
    return () => clearInterval(t)
  }, [ms])
}

export interface Resource<T> {
  data: T | null
  error: Error | null
  loading: boolean
  reload: () => void
}

/** Fetch on mount / dep change; optional polling. Errors are kept and surfaced, never swallowed. */
export function useResource<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  pollMs: number | null = null,
): Resource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher
  const seq = useRef(0)

  const load = useCallback(() => {
    const n = ++seq.current
    fetchRef.current().then(
      (d) => {
        if (n === seq.current) { setData(d); setError(null); setLoading(false) }
      },
      (e) => {
        if (n === seq.current) { setError(e instanceof Error ? e : new Error(String(e))); setLoading(false) }
      },
    )
  }, [])

  useEffect(() => {
    setLoading(true)
    load()
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(load, pollMs)
  return { data, error, loading, reload: load }
}
