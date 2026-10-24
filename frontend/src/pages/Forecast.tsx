import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type Forecast } from '../api'
import { formatDate, formatMoney, formatMoneyCompact, formatPercent } from '../format'
import { useResource } from '../hooks'
import RefChip from '../components/RefChip'
import { Card, Chip, Empty, ErrorBanner, Loading, PageHeader, td, th } from '../components/ui'

const EXPECTED_COLOR = '#4f46e5'
const ACTUAL_COLOR = '#10b981'

const weekLabel = (w: { week: number }) => `Week ${w.week}`

function WeeklyChart({ forecast }: { forecast: Forecast }) {
  const data = forecast.weeks.map((w) => ({ week: weekLabel(w), range: `${formatDate(w.start)} - ${formatDate(w.end)}`, expected: w.expected_cents }))
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="week" tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={formatMoneyCompact} tick={{ fontSize: 12 }} width={64} />
          <Tooltip formatter={(v: number) => formatMoney(v)} labelFormatter={(_, p) => (p[0]?.payload as { range?: string } | undefined)?.range ?? ''} />
          <Bar name="Expected cash" dataKey="expected" fill={EXPECTED_COLOR} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function AtRiskTable({ items }: { items: Forecast['at_risk'] }) {
  if (items.length === 0) return <Empty>Nothing at risk. Every open invoice is inside its expected window.</Empty>
  return (
    <table className="w-full">
      <thead className="border-b border-slate-200 bg-slate-50">
        <tr>
          <th className={th}>Invoice</th><th className={th}>Customer</th>
          <th className={`${th} text-right`}>Amount</th><th className={th}>Reason</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {items.map((r) => (
          <tr key={r.invoice_id}>
            <td className={td}><RefChip refId={`invoice:${r.invoice_id}`} label={r.invoice_id} /></td>
            <td className={td}><RefChip refId={`customer:${r.customer_id}`} label={r.customer_id} /></td>
            <td className={`${td} money text-right font-medium`}>{formatMoney(r.amount_cents)}</td>
            <td className={`${td} text-slate-600`}>{r.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SnapshotChart({ snap }: { snap: Forecast['snapshots'][number] }) {
  const data = snap.weeks.map((w) => ({ week: `W${w.week}`, expected: w.expected_cents, actual: w.actual_cents }))
  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="week" tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={formatMoneyCompact} tick={{ fontSize: 11 }} width={52} />
          <Tooltip formatter={(v: number) => formatMoney(v)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar name="Expected" dataKey="expected" fill={EXPECTED_COLOR} />
          <Bar name="Actual" dataKey="actual" fill={ACTUAL_COLOR} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function Accuracy({ snapshots }: { snapshots: Forecast['snapshots'] }) {
  if (snapshots.length === 0) {
    return <Empty>No snapshots scored yet. Advance the sim past a month start to score a forecast.</Empty>
  }
  return (
    <div className="grid grid-cols-3 gap-5">
      {snapshots.map((s) => (
        <div key={s.as_of} className="rounded-lg border border-slate-200 p-4">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-sm font-semibold text-slate-800">{formatDate(s.as_of)}</span>
            <span className="tnum text-sm text-slate-600">
              WAPE {s.wape === null ? <span className="text-slate-400">n/a</span> : <strong>{formatPercent(s.wape, 1)}</strong>}
            </span>
          </div>
          <SnapshotChart snap={s} />
        </div>
      ))}
    </div>
  )
}

const METHOD_LABEL: Record<Forecast['method'], string> = {
  learned: 'learned from memory',
  contract: 'contract dates only',
}

export default function ForecastPage() {
  const res = useResource(api.getForecast, [], 5000)
  const f = res.data

  return (
    <div>
      <PageHeader
        title="Cash forecast"
        subtitle={f ? `Next 4 weeks of expected collections as of ${formatDate(f.as_of)}.` : 'Next 4 weeks of expected collections.'}
        right={f && (
          <Chip className={`px-3 py-1 text-xs ${f.method === 'learned' ? 'bg-violet-100 text-violet-800' : 'bg-slate-200 text-slate-700'}`}>
            {METHOD_LABEL[f.method]}
          </Chip>
        )}
      />
      {res.error && <ErrorBanner error={res.error} />}
      {!f ? (
        res.loading ? <Loading /> : null
      ) : (
        <div className="space-y-5">
          <Card title="Expected cash by week">
            {f.weeks.length === 0 ? <Empty>No forecast buckets.</Empty> : <WeeklyChart forecast={f} />}
          </Card>
          <Card title={`At-risk invoices (${f.at_risk.length})`} className="overflow-hidden [&>div]:p-0">
            <AtRiskTable items={f.at_risk} />
          </Card>
          <Card title="Forecast accuracy">
            <Accuracy snapshots={f.snapshots} />
          </Card>
          <p className="text-xs text-slate-500">
            Forecasts use each customer&apos;s learned payment lateness (semantic memory); snapshots are scored against cash actually applied.
          </p>
        </div>
      )}
    </div>
  )
}
