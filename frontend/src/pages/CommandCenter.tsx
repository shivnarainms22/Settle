import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Activity, type ActivityKind, type SimState } from '../api'
import { formatDate, formatMoney, formatMoneyCompact, formatPct100 } from '../format'
import { useAuth } from '../components/AuthProvider'
import GuidedTour from '../components/GuidedTour'
import { canOperate, isController } from '../permissions'
import { useSim } from '../components/SimProvider'
import { AgentStateChip, Button, Card, Chip, Empty, Loading, TierChip } from '../components/ui'

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border bg-white p-4 shadow-sm ${accent ? 'border-amber-300 ring-1 ring-amber-200' : 'border-slate-200'}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="money mt-1.5 text-2xl font-semibold text-slate-900">{value}</div>
      {sub && <div className="tnum mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

function Kpis({ sim }: { sim: SimState }) {
  const k = sim.kpis
  return (
    <div className="grid grid-cols-4 gap-4">
      <Kpi label="Open AR" value={formatMoneyCompact(k.open_ar_cents)} sub={`${k.overdue_count} overdue invoices`} />
      <Kpi label="DSO" value={`${k.dso.toFixed(1)} d`} sub="days sales outstanding" />
      <Kpi label="Cash collected" value={formatMoneyCompact(k.cash_collected_cents)} sub={formatMoney(k.cash_collected_cents)} />
      <Kpi label="Auto-resolve" value={formatPct100(k.auto_resolve_pct)} sub="closed with no human" />
      <Kpi
        label="Awaiting approval"
        value={formatMoneyCompact(k.awaiting_approval_cents)}
        sub={`${k.awaiting_approval_count} decision${k.awaiting_approval_count === 1 ? '' : 's'}`}
        accent={k.awaiting_approval_count > 0}
      />
      <Kpi label="Human touches" value={String(k.human_touches)} />
      <Kpi label="Agent calls" value={String(k.agent_calls)} />
      <Kpi label="LLM cost" value={`$${k.llm_cost_usd.toFixed(2)}`} />
    </div>
  )
}

function ResetDialog({ onClose, onConfirm }: { onClose: () => void; onConfirm: (memory: boolean) => void }) {
  const [memory, setMemory] = useState(true)
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50" onClick={onClose}>
      <div role="dialog" aria-label="Reset simulation" className="w-96 rounded-xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold">Reset simulation</h3>
        <p className="mt-1 text-sm text-slate-500">Rewinds the sim to day 0 and clears memory, playbooks and the feed.</p>
        <label className="mt-5 flex cursor-pointer items-center justify-between rounded-lg border border-slate-200 px-4 py-3">
          <span className="text-sm font-medium">Memory enabled</span>
          <input type="checkbox" className="h-5 w-5 accent-indigo-600" checked={memory} onChange={(e) => setMemory(e.target.checked)} />
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => onConfirm(memory)}>Reset ({memory ? 'memory ON' : 'memory OFF'})</Button>
        </div>
      </div>
    </div>
  )
}

const KIND_STYLE: Record<ActivityKind, { bar: string; label: string }> = {
  email_out: { bar: 'border-l-sky-400', label: 'Email out' },
  email_in: { bar: 'border-l-cyan-500', label: 'Email in' },
  payment: { bar: 'border-l-emerald-500', label: 'Payment' },
  decision: { bar: 'border-l-indigo-500', label: 'Decision' },
  approval: { bar: 'border-l-amber-500', label: 'Approval' },
  gl: { bar: 'border-l-slate-500', label: 'Ledger' },
  memory: { bar: 'border-l-violet-500', label: 'Memory' },
  playbook: { bar: 'border-l-fuchsia-500', label: 'Playbook' },
  block: { bar: 'border-l-rose-500', label: 'Blocked' },
  system: { bar: 'border-l-slate-300', label: 'System' },
}

function FeedItem({ a, onOpen }: { a: Activity; onOpen: (id: number) => void }) {
  const suspended = a.kind === 'playbook' && /suspended/i.test(`${a.title} ${a.detail}`)
  const style = suspended ? { ...KIND_STYLE.playbook, bar: 'border-l-amber-500' } : KIND_STYLE[a.kind]
  const clickable = a.decision_id !== null
  return (
    <li
      onClick={clickable ? () => onOpen(a.decision_id!) : undefined}
      className={`border-l-4 ${style.bar} px-4 py-3 ${clickable ? 'cursor-pointer hover:bg-slate-50' : ''}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {a.agent_state && <AgentStateChip state={a.agent_state} />}
        {a.tier !== null && <TierChip tier={a.tier} />}
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{style.label}</span>
        <span className="ml-auto text-xs text-slate-400">{formatDate(a.sim_date)}</span>
      </div>
      <div className="mt-1 text-sm font-medium text-slate-900">{a.title}</div>
      {a.detail && <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{a.detail}</div>}
      <div className="mt-1 flex gap-3 text-xs text-slate-500">
        {a.customer_name && <span>{a.customer_name}</span>}
        {a.amount_cents !== null && <span className="money font-medium">{formatMoney(a.amount_cents)}</span>}
        {clickable && <span className="text-accent">View decision &rarr;</span>}
      </div>
    </li>
  )
}

function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'green' | 'indigo' | 'rose' }) {
  const t = { slate: 'bg-slate-200 text-slate-700', green: 'bg-emerald-100 text-emerald-800', indigo: 'bg-indigo-100 text-indigo-800', rose: 'bg-rose-100 text-rose-800' }[tone]
  return <Chip className={`${t} px-2.5 py-1`}>{children}</Chip>
}

export default function CommandCenter() {
  const { sim, activities, transport, busy, run } = useSim()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [resetOpen, setResetOpen] = useState(false)

  if (!sim) return <Loading label="Connecting to backend..." />

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Command center</h1>
            <Badge tone="indigo">Month {sim.month} of 3</Badge>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span className="tnum font-medium">{formatDate(sim.sim_date)}</span>
            <span className="text-slate-300">|</span>
            <Badge>agent: {sim.agent_kind}</Badge>
            <Badge>memory: {sim.memory_backend}</Badge>
            <Badge tone={sim.memory_enabled ? 'green' : 'rose'}>Memory {sim.memory_enabled ? 'ON' : 'OFF'}</Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canOperate(user) && (
            <>
              <Button variant="primary" disabled={busy} onClick={() => run(() => api.advanceDays(1))}>Advance 1 day</Button>
              <Button disabled={busy} onClick={() => run(() => api.advanceDays(7))}>Advance 7 days</Button>
              <Button disabled={busy} onClick={() => run(() => api.advanceToMonthEnd())}>To month end</Button>
            </>
          )}
          {isController(user) && <Button variant="danger" disabled={busy} onClick={() => setResetOpen(true)}>Reset</Button>}
        </div>
      </div>

      <Kpis sim={sim} />

      <GuidedTour />

      <Card
        className="mt-6"
        title="Live activity"
        right={
          <span className="flex items-center gap-2 text-xs text-slate-500">
            {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-accent" />}
            <span className={`h-2 w-2 rounded-full ${transport === 'sse' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
            {transport === 'sse' ? 'live (SSE)' : transport === 'polling' ? 'polling every 2s' : 'connecting'}
          </span>
        }
      >
        {activities.length === 0 ? (
          <Empty>No activity yet. Advance the simulation to watch the agent work.</Empty>
        ) : (
          <ul className="-m-5 max-h-[560px] divide-y divide-slate-100 overflow-y-auto">
            {activities.map((a) => (
              <FeedItem key={a.id} a={a} onOpen={(id) => navigate(`/decisions/${id}`)} />
            ))}
          </ul>
        )}
      </Card>

      {resetOpen && (
        <ResetDialog
          onClose={() => setResetOpen(false)}
          onConfirm={(memory) => {
            setResetOpen(false)
            run(() => api.reset(memory), { resetFeed: true })
          }}
        />
      )}
    </div>
  )
}
