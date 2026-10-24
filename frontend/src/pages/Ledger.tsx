import { api } from '../api'
import { formatMoney } from '../format'
import { useResource } from '../hooks'
import { Card, Empty, ErrorBanner, Loading, PageHeader, td, th } from '../components/ui'

export default function Ledger() {
  const res = useResource(api.ledger, [], 5000)
  const accounts = res.data?.accounts ?? []
  const totalDebit = accounts.reduce((s, a) => s + a.debit_cents, 0)
  const totalCredit = accounts.reduce((s, a) => s + a.credit_cents, 0)

  return (
    <div>
      <PageHeader title="Ledger" subtitle="Trial balance. Only the executor posts here." />
      {res.error && <ErrorBanner error={res.error} />}
      {res.loading && !res.data ? <Loading /> : (
        <Card className="overflow-hidden [&>div]:p-0">
          {accounts.length === 0 ? <Empty>No postings yet.</Empty> : (
            <table className="w-full">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>Account</th>
                  <th className={`${th} text-right`}>Debit</th>
                  <th className={`${th} text-right`}>Credit</th>
                  <th className={`${th} text-right`}>Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {accounts.map((a) => (
                  <tr key={a.account}>
                    <td className={`${td} font-medium`}>{a.account}</td>
                    <td className={`${td} money text-right`}>{formatMoney(a.debit_cents)}</td>
                    <td className={`${td} money text-right`}>{formatMoney(a.credit_cents)}</td>
                    <td className={`${td} money text-right font-semibold ${a.balance_cents < 0 ? 'text-rose-600' : ''}`}>{formatMoney(a.balance_cents)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t-2 border-slate-300 bg-slate-50">
                <tr>
                  <td className={`${td} font-semibold`}>Total</td>
                  <td className={`${td} money text-right font-semibold`}>{formatMoney(totalDebit)}</td>
                  <td className={`${td} money text-right font-semibold`}>{formatMoney(totalCredit)}</td>
                  <td className={`${td} text-right text-xs ${totalDebit === totalCredit ? 'text-emerald-600' : 'font-bold text-rose-600'}`}>
                    {totalDebit === totalCredit ? 'balanced' : 'OUT OF BALANCE'}
                  </td>
                </tr>
              </tfoot>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
