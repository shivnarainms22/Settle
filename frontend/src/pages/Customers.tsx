import { Link } from 'react-router-dom'
import { api } from '../api'
import { formatMoney } from '../format'
import { useResource } from '../hooks'
import { Card, Chip, Empty, ErrorBanner, Loading, Mono, PageHeader, td, th } from '../components/ui'

export default function Customers() {
  const res = useResource(api.customers, [], 5000)
  return (
    <div>
      <PageHeader title="Customers" subtitle="Open exposure and learned behavior per account." />
      {res.error && <ErrorBanner error={res.error} />}
      {res.loading && !res.data ? (
        <Loading />
      ) : (
        <Card className="overflow-hidden [&>div]:p-0">
          {res.data && res.data.length === 0 ? (
            <Empty>No customers.</Empty>
          ) : (
            <table className="w-full">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>Customer</th>
                  <th className={th}>Segment</th>
                  <th className={`${th} text-right`}>Open AR</th>
                  <th className={`${th} text-right`}>Overdue</th>
                  <th className={`${th} text-right`}>Avg days late</th>
                  <th className={th}>Owner</th>
                  <th className={`${th} text-right`}>Playbooks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {res.data?.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className={td}>
                      <Link to={`/customers/${c.id}`} className="font-medium text-accent hover:underline">{c.name}</Link>
                      <Mono className="ml-2 text-slate-400">{c.id}</Mono>
                    </td>
                    <td className={td}>{c.tier === 'key_account' ? <Chip className="bg-indigo-100 text-indigo-800">key account</Chip> : <span className="text-slate-500">standard</span>}</td>
                    <td className={`${td} money text-right`}>{formatMoney(c.open_ar_cents)}</td>
                    <td className={`${td} tnum text-right`}>{c.overdue_count}</td>
                    <td className={`${td} tnum text-right`}>{c.avg_days_late === null ? '-' : c.avg_days_late.toFixed(1)}</td>
                    <td className={td}>{c.owner_in_sales}</td>
                    <td className={`${td} tnum text-right`}>{c.active_playbooks}</td>
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
