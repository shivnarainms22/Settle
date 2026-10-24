import { useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type EvalDeterminism, type EvalMonth, type EvalResult, type EvalRun } from '../api'
import { formatMoney, formatPercent, shortHash } from '../format'
import { useResource } from '../hooks'
import { Button, Card, Empty, ErrorBanner, Loading, Mono, PageHeader, Spinner, td, th } from '../components/ui'

const ON_COLOR = '#4f46e5'
const OFF_COLOR = '#94a3b8'

function MonthChart({ title, data, fmt, domain }: {
  title: string
  data: { month: string; on: number; off: number }[]
  fmt: (n: number) => string
  domain?: [number, number]
}) {
  return (
    <Card title={title}>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="month" tick={{ fontSize: 12 }} />
            <YAxis tickFormatter={fmt} domain={domain} tick={{ fontSize: 12 }} width={52} />
            <Tooltip formatter={(v: number) => fmt(v)} />
            <Legend />
            <Line name="Memory ON" dataKey="on" stroke={ON_COLOR} strokeWidth={3} dot={{ r: 5 }} />
            <Line name="Memory OFF" dataKey="off" stroke={OFF_COLOR} strokeWidth={3} strokeDasharray="6 4" dot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

type MetricRow = {
  label: string
  get: (m: EvalMonth) => number | null
  fmt: (n: number) => string
  /** Red when > 0 (safety counters). */
  unsafe?: boolean
  /** Green "0" when zero, red when > 0. */
  breach?: boolean
  /** Green when exactly zero (no red styling when above). */
  goodAtZero?: boolean
  /** Shown instead of n/a when the value is null. */
  nullLabel?: string
}

const METRICS: MetricRow[] = [
  { label: 'Action accuracy', get: (m) => m.action_accuracy, fmt: (n) => formatPercent(n, 1) },
  { label: 'Auto-resolution', get: (m) => m.auto_resolution_rate, fmt: (n) => formatPercent(n, 1) },
  { label: 'Cash-app accuracy', get: (m) => m.cash_app_accuracy, fmt: (n) => formatPercent(n, 1) },
  { label: 'Escalation precision', get: (m) => m.escalation_precision, fmt: (n) => formatPercent(n, 1) },
  { label: 'Avg daily DSO (days)', get: (m) => m.dso, fmt: (n) => n.toFixed(1) },
  { label: 'Human touches', get: (m) => m.human_touches, fmt: (n) => String(n) },
  { label: 'Agent calls', get: (m) => m.agent_calls, fmt: (n) => String(n) },
  { label: 'Routed past the agent (Bitdeer)', get: (m) => m.router_skips ?? null, fmt: (n) => String(n), nullLabel: '—' },
  { label: 'LLM cost (modeled at list price)', get: (m) => m.modeled_llm_cost_usd ?? m.llm_cost_usd, fmt: (n) => `$${n.toFixed(2)}` },
  { label: 'LLM cost per invoice', get: (m) => m.modeled_cost_per_invoice_usd ?? m.cost_per_invoice_usd, fmt: (n) => `$${n.toFixed(4)}` },
  { label: 'Unsafe actions', get: (m) => m.unsafe_actions, fmt: (n) => String(n), unsafe: true },
  { label: 'Adversarial breaches', get: (m) => m.adversarial_breaches, fmt: (n) => String(n), unsafe: true, breach: true },
  { label: 'Touchless cash application (%)', get: (m) => m.touchless_cash_rate, fmt: (n) => formatPercent(n, 1) },
  { label: 'Unapplied cash ($)', get: (m) => m.unapplied_cash_cents, fmt: (n) => formatMoney(n) },
  { label: 'Dispute cycle time (days)', get: (m) => m.dispute_cycle_days, fmt: (n) => n.toFixed(1), nullLabel: '—' },
  { label: 'Credit leakage ($)', get: (m) => m.credit_leakage_cents, fmt: (n) => formatMoney(n), goodAtZero: true },
  { label: 'Forecast WAPE (lower is better)', get: (m) => m.forecast_wape, fmt: (n) => formatPercent(n, 1) },
  { label: 'Playbooks suspended (drift)', get: (m) => m.playbooks_suspended, fmt: (n) => String(n) },
]

function Cell({ m, v, strong }: { m: MetricRow; v: number | null; strong?: boolean }) {
  if (v === null) return <td className={`${td} text-right text-slate-400`}>{m.nullLabel ?? 'n/a'}</td>
  const hot = m.unsafe && v > 0
  const ok = (m.breach || m.goodAtZero) && v === 0
  const tone = hot ? 'bg-rose-100 font-semibold text-rose-700' : ok ? 'bg-emerald-50 font-semibold text-emerald-700' : strong ? 'font-semibold' : 'text-slate-600'
  return <td className={`${td} tnum text-right ${tone}`}>{m.fmt(v)}</td>
}

function Reproducibility({ d }: { d: EvalDeterminism }) {
  return (
    <Card title="Reproducibility" className="col-span-1">
      <div className={`flex items-center gap-3 text-3xl font-bold ${d.identical ? 'text-emerald-600' : 'text-rose-600'}`}>
        <span>{d.identical ? '✓' : '✗'}</span>
        <span>{d.identical ? 'Identical' : 'Diverged'}</span>
      </div>
      <dl className="mt-4 space-y-2 text-xs">
        <div className="flex gap-6">
          <div><dt className="text-slate-400">head</dt><dd title={d.head}><Mono>{shortHash(d.head, 16)}</Mono></dd></div>
          <div><dt className="text-slate-400">rerun_head</dt><dd title={d.rerun_head}><Mono>{shortHash(d.rerun_head, 16)}</Mono></dd></div>
        </div>
        <div><dt className="text-slate-400">world_digest</dt><dd title={d.world_digest}><Mono>{shortHash(d.world_digest, 16)}</Mono></dd></div>
      </dl>
      <p className="mt-4 text-xs text-slate-500">
        Memory-ON run executed twice from scratch; identical audit chain heads prove the run is deterministic.
      </p>
    </Card>
  )
}

function TraceCompleteness({ run }: { run: EvalRun }) {
  const t = run.trace
  const rows: [string, string][] = [
    ['Audit events', t.audit_events.toLocaleString('en-US')],
    ['Entity refs', t.entity_refs.toLocaleString('en-US')],
    ['Decision provenance coverage', formatPercent(t.decision_provenance_coverage, 0)],
    ['GL audit coverage', formatPercent(t.gl_audit_coverage, 0)],
  ]
  return (
    <Card title={`Trace completeness: memory ${run.memory ? 'ON' : 'OFF'}`}>
      <dl className="space-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between"><dt className="text-slate-500">{k}</dt><dd className="tnum font-medium">{v}</dd></div>
        ))}
        <div className="flex justify-between">
          <dt className="text-slate-500">Chain</dt>
          <dd className={`font-semibold ${t.chain_ok ? 'text-emerald-600' : 'text-rose-600'}`}>{t.chain_ok ? '✓ OK' : '✗ BROKEN'}</dd>
        </div>
      </dl>
    </Card>
  )
}

function Results({ result }: { result: EvalResult }) {
  const on = result.runs.find((r) => r.memory)
  const off = result.runs.find((r) => !r.memory)
  if (!on || !off) return <Card><Empty>Result is missing a memory ON or OFF run.</Empty></Card>

  const series = (get: (m: EvalMonth) => number | null) =>
    on.months.map((m, i) => ({
      month: `Month ${m.month}`,
      on: get(m) ?? NaN,
      off: off.months[i] ? get(off.months[i]) ?? NaN : NaN,
    }))

  return (
    <>
      <div className="grid grid-cols-2 gap-5 2xl:grid-cols-4">
        <MonthChart title="Human touches by month" data={series((m) => m.human_touches)} fmt={(n) => String(n)} />
        <MonthChart title="Auto-resolution rate by month" data={series((m) => m.auto_resolution_rate)} fmt={(n) => formatPercent(n)} domain={[0.8, 1]} />
        <MonthChart title="Agent calls per invoice by month" data={series((m) => m.agent_calls_per_invoice)} fmt={(n) => n.toFixed(2)} />
        <MonthChart title="Forecast WAPE by month (lower is better)" data={series((m) => m.forecast_wape)} fmt={(n) => formatPercent(n, 0)} />
      </div>

      <div className="mt-5 grid grid-cols-3 gap-5">
        <Reproducibility d={result.determinism} />
        <TraceCompleteness run={on} />
        <TraceCompleteness run={off} />
      </div>

      <Card title="Totals across the run" className="mt-5 overflow-hidden [&>div]:p-0">
        <table className="w-full">
          <thead className="border-b border-slate-200 bg-slate-50">
            <tr>
              <th className={th}>Metric</th>
              <th className={`${th} text-right text-indigo-600`}>Memory ON</th>
              <th className={`${th} text-right`}>Memory OFF</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {METRICS.map((m) => {
              return (
                <tr key={m.label}>
                  <td className={`${td} font-medium`}>{m.label}</td>
                  <Cell m={m} v={m.get(on.totals)} strong />
                  <Cell m={m} v={m.get(off.totals)} />
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
      <p className="mt-3 text-xs text-slate-500">
        Measured against persona ground truth. Real numbers from this run.
        <span className="ml-2 text-slate-400">Seed {result.seed} &middot; agent {on.agent_kind} &middot; generated {result.generated_at}</span>
      </p>
    </>
  )
}

export default function Eval() {
  const res = useResource(api.evalLatest, [])
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<Error | null>(null)
  const [fresh, setFresh] = useState<EvalResult | null>(null)

  async function run() {
    const shown = res.data?.runs[0]?.agent_kind
    const msg = `Re-run the full ablation (2 runs x 3 simulated months, plus a determinism re-run)?` +
      (shown ? ` This replaces the ${shown} results shown here.` : '') +
      ` With a Claude key configured it makes live, billed API calls.`
    if (!window.confirm(msg)) return
    setRunning(true)
    setRunError(null)
    try { setFresh(await api.runEval()) }
    catch (e) { setRunError(e instanceof Error ? e : new Error(String(e))) }
    finally { setRunning(false) }
  }

  const result = fresh ?? res.data
  return (
    <div>
      <PageHeader
        title="Eval: memory ablation"
        subtitle="Same persona-driven simulation, memory ON vs OFF."
        right={
          <div className="flex items-center gap-3">
            {running && <Spinner label="Running ablation (up to ~60s)..." />}
            <Button variant="primary" disabled={running} onClick={run}>{running ? 'Running...' : 'Run ablation'}</Button>
          </div>
        }
      />
      {res.error && <ErrorBanner error={res.error} />}
      {runError && <ErrorBanner error={runError} />}
      {res.loading && !result ? (
        <Loading />
      ) : result ? (
        <Results result={result} />
      ) : !res.error ? (
        <Card><Empty>The ablation has not been run yet. Click "Run ablation" to generate it.</Empty></Card>
      ) : null}
    </div>
  )
}
