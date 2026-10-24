import { useState } from 'react'
import { api, type VerifyCheck, type VerifyResult } from '../api'
import ExportButton from '../components/ExportButton'
import { checkLabel } from '../stack'
import { Button, Card, Chip, Empty, ErrorBanner, Mono, PageHeader, Spinner } from '../components/ui'

function PassBadge({ ok }: { ok: boolean }) {
  return (
    <Chip className={`${ok ? 'bg-emerald-600' : 'bg-rose-600'} w-14 justify-center text-[10px] font-bold uppercase tracking-wide text-white`}>
      {ok ? 'Pass' : 'Fail'}
    </Chip>
  )
}

function CheckRow({ c }: { c: VerifyCheck }) {
  return (
    <li className="flex gap-4 px-5 py-3.5">
      <div className="pt-0.5"><PassBadge ok={c.ok} /></div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-4">
          <div className="text-sm font-semibold text-slate-900">{checkLabel(c.name)}</div>
          <div className="tnum shrink-0 text-xs text-slate-500">{c.checked.toLocaleString('en-US')} checked</div>
        </div>
        <div className="mt-0.5 text-sm text-slate-500">{c.what}</div>
        {c.failures > 0 && (
          <div className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2">
            <div className="text-xs font-semibold text-rose-700">{c.failures} failure{c.failures === 1 ? '' : 's'}</div>
            <ul className="mt-1 space-y-0.5">
              {c.examples.map((x) => <li key={x}><Mono className="break-all text-rose-800">{x}</Mono></li>)}
            </ul>
          </div>
        )}
      </div>
    </li>
  )
}

function Report({ r }: { r: VerifyResult }) {
  return (
    <>
      <Card className="mb-5">
        <div className="flex items-center gap-6">
          <div className={`text-5xl font-bold tracking-tight ${r.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
            {r.ok ? 'PASS ✓' : 'FAIL ✗'}
          </div>
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wide text-slate-400">Audit head</div>
            <Mono className="break-all text-slate-800">{r.head}</Mono>
            <div className="mt-1 text-xs text-slate-500">
              {r.checks.filter((c) => c.ok).length} of {r.checks.length} checks passed
            </div>
          </div>
        </div>
      </Card>
      <Card className="overflow-hidden [&>div]:p-0">
        {r.checks.length === 0 ? <Empty>No checks returned.</Empty> : (
          <ul className="divide-y divide-slate-100">{r.checks.map((c) => <CheckRow key={c.name} c={c} />)}</ul>
        )}
      </Card>
    </>
  )
}

export default function Verify() {
  const [result, setResult] = useState<VerifyResult | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [running, setRunning] = useState(false)

  async function run() {
    setRunning(true)
    setError(null)
    try { setResult(await api.verify()) }
    catch (e) { setError(e instanceof Error ? e : new Error(String(e))) }
    finally { setRunning(false) }
  }

  return (
    <div>
      <PageHeader
        title="Verify"
        subtitle="Independent end-to-end checks of the live run: nothing here is trusted, everything is recomputed."
        right={
          <div className="flex items-center gap-3">
            <ExportButton label="Download audit (JSONL)" path="/api/export/audit" fallbackName="settle-audit.jsonl" />
            {running && <Spinner label="Verifying..." />}
            <Button variant="primary" disabled={running} onClick={run}>{running ? 'Verifying...' : 'Verify this run'}</Button>
          </div>
        }
      />
      {error && <ErrorBanner error={error} />}
      {result ? <Report r={result} /> : !error && (
        <Card><Empty>Click "Verify this run" to recompute every check against the current audit trail.</Empty></Card>
      )}
    </div>
  )
}
