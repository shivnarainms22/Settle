import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Decision, type User } from '../api'
import { formatMoney } from '../format'
import { useResource } from '../hooks'
import { useAuth } from '../components/AuthProvider'
import ExportButton from '../components/ExportButton'
import { canOperate, needsController } from '../permissions'
import { useSim } from '../components/SimProvider'
import RefChip from '../components/RefChip'
import { toTraceRef } from '../trace'
import { Button, Card, Chip, ConfidenceBar, Empty, ErrorBanner, Loading, PageHeader, TierChip, Toast } from '../components/ui'

const ACTIONS = [
  'send_reminder', 'reissue_invoice', 'propose_credit_memo', 'propose_payment_plan', 'apply_payment',
  'request_balance', 'escalate', 'hold_dunning', 'issue_refund', 'update_bank_details', 'no_action',
]

function ApprovalCard({ d, user, keyAccount, onDone }: { d: Decision; user: User; keyAccount: boolean; onDone: (msg: string) => void }) {
  const operate = canOperate(user)
  const stale = d.stale ?? []
  const hint = stale.length ? null : needsController(user, d, keyAccount)
  const [mode, setMode] = useState<'view' | 'reject' | 'edit'>('view')
  const [note, setNote] = useState('')
  const [action, setAction] = useState(d.action)
  const [argsText, setArgsText] = useState(JSON.stringify(d.args, null, 2))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  let parsedArgs: Record<string, unknown> | null = null
  let argsError: string | null = null
  if (mode === 'edit') {
    try {
      const v = JSON.parse(argsText)
      if (v === null || typeof v !== 'object' || Array.isArray(v)) argsError = 'Args must be a JSON object'
      else parsedArgs = v as Record<string, unknown>
    } catch (e) {
      argsError = e instanceof Error ? e.message : 'Invalid JSON'
    }
  }

  async function submit(body: Parameters<typeof api.decide>[1], msg: string) {
    setBusy(true)
    setError(null)
    try {
      await api.decide(d.id, body)
      onDone(msg)
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)))
      setBusy(false)
    }
  }

  return (
    <Card>
      {error && <ErrorBanner error={error} />}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <TierChip tier={d.tier} />
            <span className="font-mono text-sm font-semibold text-slate-900">{d.action}</span>
            <Chip className="bg-slate-100 text-slate-600">{d.source}</Chip>
          </div>
          <div className="mt-1.5 text-sm text-slate-600">
            {d.customer_id ? <Link className="font-medium text-accent hover:underline" to={`/customers/${d.customer_id}`}>{d.customer_name}</Link> : 'No customer'}
            <span className="mx-2 text-slate-300">|</span>
            {d.work_item.summary} <RefChip refId={toTraceRef(d.work_item.kind, d.work_item.ref)} label={d.work_item.ref} />
          </div>
        </div>
        <div className="text-right">
          <div className="money text-xl font-semibold">{d.amount_cents !== null ? formatMoney(d.amount_cents) : '-'}</div>
          <Link to={`/decisions/${d.id}`} className="text-xs text-accent hover:underline">Decision #{d.id}</Link>
        </div>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-slate-700">{d.rationale}</p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {d.evidence.map((e) => <RefChip key={e} refId={e} />)}
      </div>

      <div className="mt-4 flex items-center gap-6">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Confidence</div>
          <ConfidenceBar value={d.confidence} />
        </div>
        {d.tier_reasons.length > 0 && (
          <ul className="flex-1 space-y-0.5 border-l border-slate-200 pl-4 text-xs text-slate-600">
            {d.tier_reasons.map((r) => <li key={r}>&bull; {r}</li>)}
          </ul>
        )}
      </div>

      {mode === 'reject' && (
        <div className="mt-4">
          <input
            autoFocus
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder="Optional note (becomes memory)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      )}
      {mode === 'edit' && (
        <div className="mt-4 grid gap-2">
          <select className="w-64 rounded-md border border-slate-300 px-3 py-2 font-mono text-sm" value={action} onChange={(e) => setAction(e.target.value)}>
            {(ACTIONS.includes(d.action) ? ACTIONS : [d.action, ...ACTIONS]).map((a) => <option key={a}>{a}</option>)}
          </select>
          <textarea
            className="h-32 w-full rounded-md border border-slate-300 p-3 font-mono text-xs"
            value={argsText}
            onChange={(e) => setArgsText(e.target.value)}
            spellCheck={false}
          />
          {argsError && <div className="text-xs text-rose-600">{argsError}</div>}
        </div>
      )}

      {stale.length > 0 && (
        <div role="note" className="mt-4 rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-700">
          <span className="font-semibold">Overtaken while it waited:</span> {stale.join('; ')}. Closing it writes no memory, since the
          agent was not wrong.
        </div>
      )}
      {hint && (
        <div role="note" className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900">{hint}</div>
      )}
      {!operate && <div className="mt-4 text-xs text-slate-400">Read-only: viewers cannot approve decisions.</div>}

      <div className="mt-4 flex gap-2">
        {operate && mode === 'view' && stale.length > 0 && (
          <Button variant="primary" disabled={busy} onClick={() => submit({ verdict: 'dismiss' }, 'Closed as stale')}>Close as stale</Button>
        )}
        {operate && mode === 'view' && stale.length === 0 && (
          <>
            <Button variant="primary" disabled={busy} onClick={() => submit({ verdict: 'approve' }, 'Saved to memory')}>Approve</Button>
            <Button variant="danger" disabled={busy} onClick={() => setMode('reject')}>Reject</Button>
            <Button disabled={busy} onClick={() => setMode('edit')}>Edit</Button>
          </>
        )}
        {operate && mode === 'reject' && (
          <>
            <Button variant="danger" disabled={busy} onClick={() => submit({ verdict: 'reject', note: note.trim() || undefined }, 'Saved to memory')}>Confirm reject</Button>
            <Button variant="ghost" onClick={() => setMode('view')}>Cancel</Button>
          </>
        )}
        {operate && mode === 'edit' && (
          <>
            <Button variant="primary" disabled={busy || parsedArgs === null} onClick={() => submit({ verdict: 'edit', action, args: parsedArgs! }, 'Saved to memory')}>Submit edit</Button>
            <Button variant="ghost" onClick={() => setMode('view')}>Cancel</Button>
          </>
        )}
      </div>
    </Card>
  )
}

export default function Approvals() {
  const { refresh } = useSim()
  const { user } = useAuth()
  const res = useResource(api.approvals, [], 5000)
  const customers = useResource(api.customers)
  const keyAccounts = new Set((customers.data ?? []).filter((c) => c.tier === 'key_account').map((c) => c.id))
  const [toast, setToast] = useState<string | null>(null)
  const clearToast = useCallback(() => setToast(null), [])

  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle="Decisions the policy engine routed to a human. Your verdicts become memory."
        right={<ExportButton label="Export decisions CSV" path="/api/export/decisions.csv" fallbackName="decisions.csv" />}
      />
      {res.error && <ErrorBanner error={res.error} />}
      {res.loading && !res.data ? (
        <Loading />
      ) : res.data && res.data.length === 0 ? (
        <Card><Empty>Nothing waiting. The agent is handling everything.</Empty></Card>
      ) : (
        <div className="space-y-4">
          {res.data?.map((d) => (
            <ApprovalCard
              key={d.id}
              d={d}
              user={user}
              keyAccount={d.customer_id !== null && keyAccounts.has(d.customer_id)}
              onDone={(msg) => { setToast(msg); res.reload(); refresh() }}
            />
          ))}
        </div>
      )}
      <Toast message={toast} onDone={clearToast} />
    </div>
  )
}
