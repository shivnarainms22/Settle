import { Link } from 'react-router-dom'
import { api, type WorklistRow } from '../api'
import { formatDate, formatMoney } from '../format'
import { useResource } from '../hooks'
import RefChip from '../components/RefChip'
import { Card, Chip, Empty, ErrorBanner, Loading, PageHeader, StatusChip, td, th } from '../components/ui'

const RISK_STYLE: Record<WorklistRow['risk'], string> = {
  high: 'bg-rose-100 text-rose-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-emerald-100 text-emerald-800',
}

export default function Worklist() {
  const res = useResource(() => api.worklist(50), [], 10_000)
  return (
    <div>
      <PageHeader title="Worklist" subtitle="Open invoices ranked by priority: what to work first, why, and what the agent suggests next." />
      {res.error && <ErrorBanner error={res.error} />}
      {res.loading && !res.data ? (
        <Loading />
      ) : (
        <Card className="overflow-hidden [&>div]:p-0">
          {!res.data || res.data.length === 0 ? (
            <Empty>Nothing to work. No open invoices need attention.</Empty>
          ) : (
            <table className="w-full">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>Customer</th>
                  <th className={th}>Invoice</th>
                  <th className={`${th} text-right`}>Balance</th>
                  <th className={`${th} text-right`}>Days overdue</th>
                  <th className={th}>Expected pay</th>
                  <th className={th}>Risk</th>
                  <th className={th}>Why</th>
                  <th className={th}>Next action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {res.data.map((r) => (
                  <tr key={r.invoice_id} className="align-top hover:bg-slate-50">
                    <td className={td}>
                      <Link className="font-medium text-accent hover:underline" to={`/customers/${r.customer_id}`}>{r.customer_name}</Link>
                    </td>
                    <td className={td}>
                      <div className="flex flex-col items-start gap-1">
                        <RefChip refId={`invoice:${r.invoice_id}`} label={r.invoice_id} />
                        <StatusChip status={r.status} />
                      </div>
                    </td>
                    <td className={`${td} money text-right`}>{formatMoney(r.balance_cents)}</td>
                    <td className={`${td} tnum text-right`}>{r.days_overdue > 0 ? r.days_overdue : '-'}</td>
                    <td className={`${td} tnum whitespace-nowrap`}>{r.expected_pay_date ? formatDate(r.expected_pay_date) : <span className="text-slate-400">unknown</span>}</td>
                    <td className={td}><Chip className={`${RISK_STYLE[r.risk] ?? 'bg-slate-100 text-slate-700'} font-semibold uppercase`}>{r.risk}</Chip></td>
                    <td className={td}>
                      <div className="flex flex-wrap gap-1">
                        {(r.reasons ?? []).map((x) => <Chip key={x} className="bg-slate-100 text-slate-700">{x}</Chip>)}
                      </div>
                    </td>
                    <td className={td}>
                      <div className="text-slate-700">{r.next_action}</div>
                      {r.pending_decision_id !== null && (
                        <Link to={`/decisions/${r.pending_decision_id}`} className="text-xs font-medium text-amber-700 hover:underline">
                          Pending decision #{r.pending_decision_id} &rarr;
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
