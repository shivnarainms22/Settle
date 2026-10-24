import { useState } from 'react'
import { api, type AutonomyMode } from '../api'
import { isController } from '../permissions'
import { useResource } from '../hooks'
import { useAuth } from './AuthProvider'
import { useSim } from './SimProvider'
import { Button, ErrorBanner } from './ui'

const MODES: { mode: AutonomyMode; label: string }[] = [
  { mode: 'shadow', label: 'Shadow' },
  { mode: 'supervised', label: 'Supervised' },
  { mode: 'autonomous', label: 'Autonomous' },
]

const BANNER: Partial<Record<AutonomyMode, { cls: string; title: string; text: string }>> = {
  shadow: { cls: 'border-purple-300 bg-purple-50 text-purple-900', title: 'Shadow mode', text: 'decisions are recorded, nothing executes.' },
  supervised: { cls: 'border-amber-300 bg-amber-50 text-amber-900', title: 'Supervised mode', text: 'every action waits for approval.' },
}

/** Persistent explanation of the current autonomy mode (none needed when fully autonomous). */
export function AutonomyBanner() {
  const { sim } = useSim()
  const b = sim ? BANNER[sim.autonomy] : undefined
  if (!b) return null
  return (
    <div role="status" className={`mb-4 rounded-lg border px-4 py-2.5 text-sm ${b.cls}`}>
      <strong className="font-semibold">{b.title}:</strong> {b.text}
    </div>
  )
}

/** Segmented mode control (controllers only), kill switch, and who/why of the last change. */
export function AutonomyControl() {
  const { user } = useAuth()
  const { sim, refresh } = useSim()
  const mode = sim?.autonomy
  const info = useResource(api.autonomy, [mode])
  const [pending, setPending] = useState<AutonomyMode | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const canChange = isController(user)

  async function apply(next: AutonomyMode, why: string) {
    setBusy(true)
    setError(null)
    try {
      await api.setAutonomy(next, why.trim())
      setPending(null)
      setReason('')
      refresh()
      info.reload()
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setBusy(false)
    }
  }

  if (!mode) return null
  return (
    <div className="flex flex-col items-start gap-1.5">
      <div className="flex items-center gap-2">
        <div role="group" aria-label="Autonomy mode" className="inline-flex shrink-0 whitespace-nowrap overflow-hidden rounded-md border border-slate-300 text-xs font-medium">
          {MODES.map((m) => (
            <button
              key={m.mode}
              disabled={!canChange || busy}
              aria-pressed={mode === m.mode}
              onClick={() => { setError(null); setPending(m.mode === mode ? null : m.mode) }}
              className={`px-3 py-1.5 transition disabled:cursor-default ${
                mode === m.mode ? 'bg-accent text-white' : pending === m.mode ? 'bg-indigo-50 text-indigo-700' : 'bg-white text-slate-600 hover:bg-slate-50 disabled:hover:bg-white'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        {canChange && mode === 'autonomous' && (
          <button
            disabled={busy}
            onClick={() => apply('supervised', 'kill switch')}
            className="whitespace-nowrap rounded-md bg-rose-600 px-3 py-1.5 text-xs font-bold uppercase tracking-wide text-white shadow hover:bg-rose-700 disabled:opacity-50"
          >
            Pause autonomy
          </button>
        )}
      </div>
      {pending && (
        <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (reason.trim()) void apply(pending, reason) }}>
          <input
            autoFocus
            aria-label="Reason for change"
            className="w-64 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs"
            placeholder={`Reason for switching to ${pending} (required)`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button type="submit" variant="primary" className="!py-1 text-xs" disabled={busy || reason.trim() === ''}>Switch</Button>
          <Button type="button" variant="ghost" className="!py-1 text-xs" onClick={() => { setPending(null); setReason('') }}>Cancel</Button>
        </form>
      )}
      {error && <div className="max-w-md"><ErrorBanner error={error} /></div>}
      {info.data?.changed_by && (
        <div className="max-w-md text-right text-[11px] text-slate-500">
          Set by <span className="font-medium">{info.data.changed_by}</span>
          {info.data.reason ? <>: &ldquo;{info.data.reason}&rdquo;</> : null}
        </div>
      )}
    </div>
  )
}
