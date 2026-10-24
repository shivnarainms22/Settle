import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Bench, BenchScale } from '../api'
import { Card, td, th } from './ui'

const COLS: { label: string; get: (s: BenchScale) => string }[] = [
  { label: 'Customers', get: (s) => s.customers.toLocaleString('en-US') },
  { label: 'Invoices', get: (s) => s.invoices.toLocaleString('en-US') },
  { label: 'Decisions', get: (s) => s.decisions.toLocaleString('en-US') },
  { label: 'Audit events', get: (s) => s.audit_log.toLocaleString('en-US') },
  { label: 'Sim seconds', get: (s) => s.sim_s.toFixed(2) },
  { label: 'Verify seconds', get: (s) => s.verify_s.toFixed(2) },
  { label: 'Decisions/s', get: (s) => s.decisions_per_s.toLocaleString('en-US') },
  { label: 'Verified', get: (s) => (s.verified ? '✓' : '✗') },
]

function ScaleTable({ scales }: { scales: BenchScale[] }) {
  return (
    <div className="col-span-2 overflow-x-auto rounded-md border border-slate-200">
      <table className="w-full">
        <thead className="bg-slate-50"><tr>{COLS.map((c) => <th key={c.label} className={`${th} text-right`}>{c.label}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-100">
          {scales.map((s) => (
            <tr key={s.scale}>
              {COLS.map((c) => (
                <td key={c.label} className={`${td} tnum text-right ${c.label === 'Verified' ? (s.verified ? 'font-bold text-emerald-600' : 'font-bold text-rose-600') : ''}`}>{c.get(s)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SimChart({ scales }: { scales: BenchScale[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Sim seconds vs customers</div>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={scales} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="customers" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} width={36} />
            <Tooltip formatter={(v: number) => `${v}s`} labelFormatter={(l) => `${l} customers`} />
            <Line dataKey="sim_s" name="sim seconds" stroke="#4f46e5" strokeWidth={2.5} dot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function ScaleCard({ bench }: { bench: Bench | null }) {
  return (
    <Card title="Scale: offline benchmark">
      {bench === null ? (
        <div className="py-8 text-center text-sm text-slate-500">
          Scale benchmark has not been run. Run it with
          <code className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">uv run python -m settle.bench</code>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-5">
            <ScaleTable scales={bench.scales} />
            <SimChart scales={bench.scales} />
          </div>
          {bench.concurrency && (
            <p className="mt-4 text-sm text-slate-800">
              <span className="font-semibold">{bench.concurrency.agent_calls} agent calls:</span>{' '}
              {bench.concurrency.workers_1_s}s sequential → {bench.concurrency.workers_8_s}s with 8 workers ({bench.concurrency.speedup}×)
              {bench.concurrency.identical_audit_head ? ', identical audit head ✓' : ', audit head DIVERGED ✗'}
            </p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            Concurrency uses {bench.simulated_llm_latency_ms} ms simulated LLM latency per call; it is not a live-model measurement.
          </p>
        </>
      )}
    </Card>
  )
}
