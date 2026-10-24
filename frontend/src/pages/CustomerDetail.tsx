import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { formatDate, formatMoney } from '../format'
import { useResource } from '../hooks'
import MemoryList from '../components/MemoryList'
import RefChip from '../components/RefChip'
import PlaybookCard from '../components/PlaybookCard'
import { Card, Chip, Empty, ErrorBanner, Loading, Mono, PageHeader, StatusChip, td, th } from '../components/ui'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
    </div>
  )
}

export default function CustomerDetailPage() {
  const { id = '' } = useParams()
  const res = useResource(() => api.customer(id), [id], 5000)

  if (res.error && !res.data) return <ErrorBanner error={res.error} />
  if (!res.data) return <Loading />
  const c = res.data
  const p = c.profile

  return (
    <div>
      <Link to="/customers" className="text-sm text-accent hover:underline">&larr; Customers</Link>
      <PageHeader title={c.name} subtitle={`${c.id} · ${c.tier === 'key_account' ? 'Key account' : 'Standard'} · owner ${c.owner_in_sales}`} />
      {res.error && <ErrorBanner error={res.error} />}

      <div className="grid grid-cols-3 gap-5">
        <Card title="Learned profile (semantic memory)" className="col-span-1">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
            <Fact label="Aliases">{p.aliases.length ? p.aliases.join(', ') : '-'}</Fact>
            <Fact label="Avg days late"><span className="tnum">{p.avg_days_late === null ? '-' : p.avg_days_late.toFixed(1)}</span></Fact>
            <Fact label="Payments observed"><span className="tnum">{p.payments_observed}</span></Fact>
            <Fact label="Disputes"><span className="tnum">{p.dispute_count}</span></Fact>
            <Fact label="Needs PO">{p.needs_po === null ? <span className="text-slate-400">unknown</span> : p.needs_po ? <Chip className="bg-amber-100 text-amber-800">yes</Chip> : 'no'}</Fact>
            <Fact label="Reliable late payer">{p.reliable_late_payer ? <Chip className="bg-sky-100 text-sky-800">yes</Chip> : 'no'}</Fact>
            <Fact label="Bank on file"><Mono>{p.bank_account_on_file || '-'}</Mono></Fact>
            <Fact label="Verified domain"><Mono>{p.verified_domain || '-'}</Mono></Fact>
          </dl>
          {p.notes.length > 0 && (
            <ul className="mt-4 space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-600">
              {p.notes.map((n) => <li key={n}>&bull; {n}</li>)}
            </ul>
          )}
        </Card>

        <Card title="Invoices" className="col-span-2 overflow-hidden [&>div]:p-0">
          {c.invoices.length === 0 ? <Empty>No invoices.</Empty> : (
            <table className="w-full">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>Invoice</th><th className={th}>PO</th><th className={th}>Due</th>
                  <th className={`${th} text-right`}>Amount</th><th className={`${th} text-right`}>Balance</th>
                  <th className={`${th} text-right`}>Days over</th><th className={th}>Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {c.invoices.map((i) => (
                  <tr key={i.id}>
                    <td className={td}><RefChip refId={`invoice:${i.id}`} label={i.id} /></td>
                    <td className={td}><Mono>{i.po_number ?? '-'}</Mono></td>
                    <td className={`${td} tnum`}>{formatDate(i.due_on)}</td>
                    <td className={`${td} money text-right`}>{formatMoney(i.amount_cents)}</td>
                    <td className={`${td} money text-right font-medium`}>{formatMoney(i.balance_cents)}</td>
                    <td className={`${td} tnum text-right`}>{i.days_overdue > 0 ? i.days_overdue : '-'}</td>
                    <td className={td}><StatusChip status={i.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Email thread" className="col-span-2">
          {c.emails.length === 0 ? <Empty>No emails.</Empty> : (
            <div className="max-h-[480px] space-y-3 overflow-y-auto">
              {c.emails.map((e) => (
                <div key={e.id} className={`flex ${e.direction === 'out' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${e.direction === 'out' ? 'rounded-br-sm bg-accent text-white' : 'rounded-bl-sm bg-slate-100 text-slate-800'}`}>
                    <div className={`mb-0.5 flex gap-2 text-[11px] ${e.direction === 'out' ? 'text-indigo-200' : 'text-slate-500'}`}>
                      <span>{e.direction === 'out' ? 'Settle' : e.sender}</span>
                      <span>{formatDate(e.sim_date)}</span>
                      <RefChip refId={`email:${e.id}`} label={e.id} className="!bg-white/20 !text-inherit" />
                    </div>
                    <div className="font-semibold">{e.subject}</div>
                    <div className="mt-1 whitespace-pre-wrap">{e.body}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Memories" className="col-span-1">
          <MemoryList memories={c.memories} />
        </Card>

        <Card title="Playbooks" className="col-span-3">
          {c.playbooks.length === 0 ? <Empty>No playbooks for this customer yet.</Empty> : (
            <div className="grid grid-cols-2 gap-4">
              {c.playbooks.map((pb) => <PlaybookCard key={pb.id} p={pb} />)}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
