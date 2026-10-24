import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { actionLabel, formatDate, formatMoney } from '../format'
import { toTraceRef } from '../trace'
import { useResource } from '../hooks'
import MemoryList from '../components/MemoryList'
import PlaybookCard from '../components/PlaybookCard'
import AgentRunSections from '../components/Provenance'
import EventTimeline from '../components/EventTimeline'
import FlagDecision from '../components/FlagDecision'
import RefChip from '../components/RefChip'
import VerifyChain from '../components/VerifyChain'
import { useSim } from '../components/SimProvider'
import { Card, Chip, ConfidenceBar, Empty, ErrorBanner, Json, Loading, Mono, PageHeader, StatusChip, TierChip, Toast, td, th } from '../components/ui'

export default function DecisionDetailPage() {
  const { id = '' } = useParams()
  const res = useResource(() => api.decision(Number(id)), [id])
  const { refresh } = useSim()
  const [toast, setToast] = useState<string | null>(null)
  const clearToast = useCallback(() => setToast(null), [])

  if (res.error && !res.data) return <ErrorBanner error={res.error} />
  if (!res.data) return <Loading />
  const d = res.data

  return (
    <div>
      <Link to="/" className="text-sm text-accent hover:underline">&larr; Command center</Link>
      <PageHeader
        title={`Decision #${d.id}`}
        subtitle={`${formatDate(d.sim_date)} · ${d.work_item.kind} ${d.work_item.ref}`}
        right={
          <div className="flex items-start gap-3">
            {(d.status === 'executed' || d.status === 'approved' || d.status === 'edited') && (
              <FlagDecision id={d.id} onFlagged={(m) => { setToast(m); res.reload(); refresh() }} />
            )}
            <VerifyChain />
          </div>
        }
      />

      {(d.security_flags ?? []).length > 0 && (
        <div role="alert" className="mb-5 rounded-xl border border-rose-200 bg-rose-50 px-5 py-4">
          <div className="text-sm font-bold uppercase tracking-wide text-rose-700">Prompt injection detected and ignored</div>
          <ul className="mt-1 space-y-0.5 text-sm text-rose-900">
            {d.security_flags!.map((f) => <li key={f}>{f}</li>)}
          </ul>
          <div className="mt-1 text-xs text-rose-700/80">
            Customer text is untrusted data. Even an agent that obeyed it could not move money: policy runs after the agent, in code.
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-5">
        <Card title="Decision" className="col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <TierChip tier={d.tier} />
            <StatusChip status={d.status} />
            <Chip className="bg-slate-100 text-slate-600">source: {d.source}</Chip>
            <span className="font-mono text-sm font-semibold">{actionLabel(d.action)}</span>
            {d.amount_cents !== null && <span className="money ml-auto text-lg font-semibold">{formatMoney(d.amount_cents)}</span>}
          </div>
          <div className="mt-3 text-sm text-slate-600">
            {d.customer_id ? <Link className="font-medium text-accent hover:underline" to={`/customers/${d.customer_id}`}>{d.customer_name}</Link> : 'No customer'}
            <span className="mx-2 text-slate-300">|</span>{d.work_item.summary}
            <RefChip refId={toTraceRef(d.work_item.kind, d.work_item.ref)} label={d.work_item.ref} className="ml-2" />
          </div>
          <p className="mt-3 text-sm leading-relaxed text-slate-800">{d.rationale}</p>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Confidence</div>
              <ConfidenceBar value={d.confidence} />
            </div>
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Approver</div>
              <div className="text-sm">{d.approver ?? <span className="text-slate-400">none (autonomous)</span>}</div>
            </div>
          </div>
          <div className="mt-4">
            <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Policy tier reasons</div>
            {d.tier_reasons.length === 0 ? <div className="text-sm text-slate-400">none</div> : (
              <ul className="space-y-0.5 text-sm text-slate-700">{d.tier_reasons.map((r) => <li key={r}>&bull; {r}</li>)}</ul>
            )}
          </div>
        </Card>

        <Card title="Action args">
          <Json value={d.args} />
        </Card>

        <Card title="Evidence" className="col-span-2">
          {d.evidence_resolved.length === 0 ? <Empty>No evidence cited.</Empty> : (
            <ul className="space-y-3">
              {d.evidence_resolved.map((e) => (
                <li key={e.ref}>
                  <div className="flex items-center gap-2">
                    <RefChip refId={e.ref} />
                    {e.kind === 'delivery'
                      ? <Chip className="bg-teal-100 text-teal-800">proof of delivery</Chip>
                      : <span className="text-xs text-slate-400">{e.kind}</span>}
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{e.text}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Cited memories">
          <MemoryList memories={d.memories} />
        </Card>

        {d.playbook && (
          <Card title="Playbook applied" className="col-span-3">
            <PlaybookCard p={d.playbook} />
          </Card>
        )}

        <Card title="Resulting GL entries" className="col-span-3 overflow-hidden [&>div]:p-0">
          {d.gl_entries.length === 0 ? <Empty>No ledger impact.</Empty> : (
            <table className="w-full">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>ID</th><th className={th}>Date</th><th className={th}>Debit</th><th className={th}>Credit</th>
                  <th className={`${th} text-right`}>Amount</th><th className={th}>Ref</th><th className={th}>Memo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {d.gl_entries.map((g) => (
                  <tr key={g.id}>
                    <td className={td}><Mono>{g.id}</Mono></td>
                    <td className={`${td} tnum`}>{formatDate(g.sim_date)}</td>
                    <td className={td}>{g.debit_acct}</td>
                    <td className={td}>{g.credit_acct}</td>
                    <td className={`${td} money text-right font-medium`}>{formatMoney(g.amount_cents)}</td>
                    <td className={td}><RefChip refId={toTraceRef(g.ref_type, g.ref_id)} label={`${g.ref_type}:${g.ref_id}`} /></td>
                    <td className={`${td} text-slate-600`}>{g.memo}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        {d.agent_run && <AgentRunSections run={d.agent_run} />}

        <Card title="Audit trail (hash chain)" className="col-span-3">
          <EventTimeline events={d.trace} />
        </Card>
      </div>
      <Toast message={toast} onDone={clearToast} />
    </div>
  )
}