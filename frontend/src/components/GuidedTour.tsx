import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { TOUR_STEPS, nextStepIndex, stepTarget } from '../tour'
import { canOperate } from '../permissions'
import { useAuth } from './AuthProvider'
import { formatDate } from '../format'
import { useSim } from './SimProvider'
import { Button, Card } from './ui'

/** Guided tour: each step advances the sim to just after its event, then opens the decision (or page) that shows it. */
export default function GuidedTour() {
  const { user } = useAuth()
  const { sim, busy, run } = useSim()
  const navigate = useNavigate()
  const [open, setOpen] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const next = nextStepIndex(sim?.sim_date)

  async function go(i: number) {
    const s = TOUR_STEPS[i]
    setError(null)
    try {
      // Viewers can only navigate. The sim cannot go backwards, so reached steps just open.
      if (canOperate(user) && sim && sim.sim_date < s.to) await run(() => api.advanceTo(s.to))
      navigate(s.pick ? stepTarget(s, await api.decisions(1000)) : s.path)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Card
      className="mt-6"
      title={`Guided tour · ${Math.min(next, TOUR_STEPS.length)}/${TOUR_STEPS.length} reached`}
      right={<Button variant="ghost" className="!py-1 text-xs" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Show'}</Button>}
    >
      {!open ? (
        <div className="text-sm text-slate-500">A guided tour in {TOUR_STEPS.length} steps.</div>
      ) : (
        <ol className="space-y-2">
          {TOUR_STEPS.map((s, i) => {
            const reached = sim ? sim.sim_date >= s.to : false
            const current = i === next
            return (
              <li
                key={s.to}
                className={`flex items-start gap-3 rounded-lg px-3 py-2 ${current ? 'bg-indigo-50 ring-1 ring-indigo-200' : ''}`}
              >
                <span
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    reached ? 'bg-emerald-100 text-emerald-700' : 'bg-indigo-100 text-indigo-700'
                  }`}
                >
                  {reached ? '✓' : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-slate-900">
                    {s.title} <span className="tnum font-normal text-slate-400">({formatDate(s.to)})</span>
                  </div>
                  <div className="text-xs leading-relaxed text-slate-500">{s.detail}</div>
                </div>
                <Button
                  variant={current ? 'primary' : 'ghost'}
                  className="shrink-0 !py-1 text-xs"
                  disabled={busy || !sim}
                  onClick={() => void go(i)}
                >
                  {!canOperate(user) || reached ? 'Open' : 'Advance and open'}
                </Button>
              </li>
            )
          })}
        </ol>
      )}
      {error && <div className="mt-3 text-sm text-rose-600">{error}</div>}
    </Card>
  )
}
