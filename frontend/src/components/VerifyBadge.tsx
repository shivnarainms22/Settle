import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

type State = { kind: 'idle' } | { kind: 'running' } | { kind: 'done'; ok: boolean } | { kind: 'error'; message: string }

/** Compact header control: runs the full verification and links to the detailed report. */
export default function VerifyBadge() {
  const [s, setS] = useState<State>({ kind: 'idle' })

  async function run() {
    setS({ kind: 'running' })
    try { setS({ kind: 'done', ok: (await api.verify()).ok }) }
    catch (e) { setS({ kind: 'error', message: e instanceof Error ? e.message : String(e) }) }
  }

  const tone =
    s.kind === 'done' ? (s.ok ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-rose-300 bg-rose-50 text-rose-700')
    : s.kind === 'error' ? 'border-rose-300 bg-rose-50 text-rose-700'
    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
  const label =
    s.kind === 'running' ? 'Verifying...'
    : s.kind === 'done' ? (s.ok ? 'Verified ✓' : 'Verify failed ✗')
    : s.kind === 'error' ? 'Verify error'
    : 'Verify'

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={run}
        disabled={s.kind === 'running'}
        title={s.kind === 'error' ? s.message : 'Re-run every verification check on this run'}
        className={`rounded-lg border px-3 py-1 text-[11px] font-semibold shadow-sm transition disabled:opacity-60 ${tone}`}
      >
        {label}
      </button>
      <Link to="/verify" className="text-[11px] font-medium text-accent hover:underline">details</Link>
    </div>
  )
}
