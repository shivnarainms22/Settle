import { useState } from 'react'
import { api, type Health } from '../api'
import { useResource } from '../hooks'
import { Chip } from './ui'

const DOT = { ok: 'bg-emerald-500', degraded: 'bg-amber-500', off: 'bg-slate-300' } as const

/** Polls /api/health. Returns null until the first response (and on failure: the ErrorBanner already reports that). */
export function useHealth(): Health | null {
  return useResource(api.health, [], 10_000).data
}

export function HealthBanner({ health }: { health: Health | null }) {
  if (!health || health.status !== 'degraded') return null
  const bad = (health.components ?? []).filter((c) => c.status === 'degraded')
  return (
    <div role="alert" className="mb-4 rounded-lg border border-yellow-300 bg-yellow-50 px-4 py-2.5 text-sm text-yellow-900">
      <strong className="font-semibold">System degraded.</strong>
      <ul className="mt-1 list-disc pl-5 text-xs">
        {bad.map((c) => <li key={c.name}><span className="font-medium">{c.name}</span>: {c.detail}</li>)}
        {bad.length === 0 && <li>A component reported degraded without detail.</li>}
      </ul>
    </div>
  )
}

/** Small header indicator; click for a popover listing every component. */
export function HealthIndicator({ health }: { health: Health | null }) {
  const [open, setOpen] = useState(false)
  if (!health) return null
  const degraded = health.status === 'degraded'
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
      >
        <span className={`h-2 w-2 rounded-full ${degraded ? DOT.degraded : DOT.ok}`} />
        {degraded ? 'Degraded' : 'Healthy'}
      </button>
      {open && (
        <div role="dialog" aria-label="System health" className="absolute right-0 z-30 mt-2 w-80 rounded-lg border border-slate-200 bg-white p-3 text-xs shadow-xl">
          <ul className="space-y-1.5">
            {(health.components ?? []).map((c) => (
              <li key={c.name} className="flex items-start gap-2">
                <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${DOT[c.status] ?? DOT.off}`} />
                <div><span className="font-medium text-slate-800">{c.name}</span> <Chip className="bg-slate-100 text-slate-600">{c.status}</Chip>
                  <div className="text-slate-500">{c.detail}</div></div>
              </li>
            ))}
          </ul>
          <div className="mt-2 border-t border-slate-100 pt-2 text-slate-500">Agent fallbacks (last 7 sim days): {health.recent_fallbacks}</div>
        </div>
      )}
    </div>
  )
}
