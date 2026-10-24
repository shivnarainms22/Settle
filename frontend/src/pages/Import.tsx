import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type AutonomyMode, type ImportSummary } from '../api'
import { csvPreview } from '../csv'
import { formatDate, formatMoney } from '../format'
import { useAuth } from '../components/AuthProvider'
import { canOperate } from '../permissions'
import { useSim } from '../components/SimProvider'
import { Button, Card, Empty, ErrorBanner, PageHeader, Spinner, td, th } from '../components/ui'

const AUTONOMY_HELP: Record<AutonomyMode, string> = {
  shadow: 'Recommended for real books: decisions are recorded as proposals, nothing is executed.',
  supervised: 'Every action waits for human approval before it runs.',
  autonomous: 'The agent executes within policy tiers; only high-risk items wait for a human.',
}

interface Loaded { name: string; text: string }

function readFile(file: File): Promise<Loaded> {
  return file.text().then((text) => ({ name: file.name, text }))
}

function Preview({ text }: { text: string }) {
  const { header, rows } = csvPreview(text, 5)
  if (header.length === 0) return <Empty>File is empty.</Empty>
  return (
    <div className="overflow-x-auto rounded-md border border-slate-200">
      <table className="w-full text-xs">
        <thead className="bg-slate-50"><tr>{header.map((h, i) => <th key={i} className={`${th} whitespace-nowrap`}>{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j} className={`${td} whitespace-nowrap py-1.5 text-xs`}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FileField({ label, required, file, onFile }: {
  label: string; required?: boolean; file: Loaded | null; onFile: (f: File | null) => void
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-slate-700">
        {label} {required ? <span className="text-rose-600">*</span> : <span className="text-xs font-normal text-slate-400">(optional)</span>}
      </label>
      <input
        type="file"
        accept=".csv,text/csv"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-50"
      />
      {file && <div className="mt-1 text-xs text-slate-400">Loaded {file.name} ({file.text.length.toLocaleString('en-US')} chars)</div>}
      {file && <div className="mt-2"><Preview text={file.text} /></div>}
    </div>
  )
}

function Success({ s }: { s: ImportSummary }) {
  const navigate = useNavigate()
  const rows: [string, string][] = [
    ['Customers', String(s.customers)],
    ['Invoices', String(s.invoices)],
    ['Bank lines', String(s.bank_lines)],
    ['Open AR', formatMoney(s.open_ar_cents)],
    ['Date range', `${formatDate(s.start_date)} to ${formatDate(s.end_date)}`],
  ]
  return (
    <Card title="Imported: your books are now the live run" className="border-emerald-300">
      <dl className="grid grid-cols-5 gap-4">
        {rows.map(([k, v]) => (
          <div key={k}><dt className="text-[11px] uppercase tracking-wide text-slate-400">{k}</dt><dd className="tnum mt-0.5 text-lg font-semibold">{v}</dd></div>
        ))}
      </dl>
      <Button variant="primary" className="mt-4" onClick={() => navigate('/')}>Go to command center</Button>
    </Card>
  )
}

export default function Import() {
  const { run } = useSim()
  const { user } = useAuth()
  const [invoices, setInvoices] = useState<Loaded | null>(null)
  const [bank, setBank] = useState<Loaded | null>(null)
  const [memory, setMemory] = useState(true)
  const [autonomy, setAutonomy] = useState<AutonomyMode>('shadow')
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<Error | null>(null)
  const [rejected, setRejected] = useState<{ message: string; errors: string[] } | null>(null)
  const [failure, setFailure] = useState<Error | null>(null)
  const [summary, setSummary] = useState<ImportSummary | null>(null)

  async function pick(file: File | null, set: (l: Loaded | null) => void) {
    setLoadError(null)
    if (!file) return set(null)
    try { set(await readFile(file)) }
    catch (e) { setLoadError(e instanceof Error ? e : new Error(String(e))) }
  }

  async function useSamples() {
    setBusy(true)
    setLoadError(null)
    try {
      const s = await api.importSamples()
      setInvoices({ name: 'ar_aging.csv (sample)', text: s['ar_aging.csv'] })
      setBank({ name: 'bank_statement.csv (sample)', text: s['bank_statement.csv'] })
    } catch (e) { setLoadError(e instanceof Error ? e : new Error(String(e))) }
    finally { setBusy(false) }
  }

  async function submit() {
    if (!invoices) return
    setBusy(true)
    setRejected(null)
    setFailure(null)
    setSummary(null)
    try {
      const res = await api.importBooks({ invoices_csv: invoices.text, bank_csv: bank?.text, memory, autonomy })
      await run(async () => res.state, { resetFeed: true })
      setSummary(res.summary)
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) setRejected({ message: e.message, errors: e.errors })
      else setFailure(e instanceof Error ? e : new Error(String(e)))
    } finally { setBusy(false) }
  }

  return (
    <div>
      <PageHeader
        title="Bring your books"
        subtitle="Your books run through the same agent, policy engine, audit trail and verifier. No simulation, no ground truth."
      />
      {loadError && <ErrorBanner error={loadError} />}
      {failure && <ErrorBanner error={failure} />}
      {rejected && (
        <div role="alert" className="mb-4 rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          <strong className="font-semibold">Import rejected: {rejected.message}.</strong>
          <span className="ml-2">Your current run is untouched; the backend guarantees nothing is replaced on a failed import.</span>
          {rejected.errors.length > 0 && <ul className="mt-2 list-disc space-y-0.5 pl-5">{rejected.errors.map((x, i) => <li key={i}>{x}</li>)}</ul>}
        </div>
      )}
      {summary && <div className="mb-5"><Success s={summary} /></div>}

      <Card
        title="Your files"
        right={<Button disabled={busy} onClick={useSamples}>Use sample QuickBooks export</Button>}
      >
        <div className="grid grid-cols-2 gap-6">
          <FileField label="AR aging export (CSV)" required file={invoices} onFile={(f) => pick(f, setInvoices)} />
          <FileField label="Bank statement (CSV)" file={bank} onFile={(f) => pick(f, setBank)} />
        </div>
        <div className="mt-5 border-t border-slate-100 pt-4">
          <label className="flex items-center gap-3 text-sm font-medium text-slate-700">
            Autonomy
            <select
              aria-label="Autonomy"
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm font-normal"
              value={autonomy}
              onChange={(e) => setAutonomy(e.target.value as AutonomyMode)}
            >
              <option value="shadow">Shadow</option>
              <option value="supervised">Supervised</option>
              <option value="autonomous">Autonomous</option>
            </select>
          </label>
          <p className="mt-1 text-xs text-slate-500">{AUTONOMY_HELP[autonomy]}</p>
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={memory} onChange={(e) => setMemory(e.target.checked)} className="h-4 w-4 accent-indigo-600" />
            Memory {memory ? 'ON' : 'OFF'}
            <span className="text-xs text-slate-400">(agent learns from approvals and outcomes)</span>
          </label>
          <div className="flex items-center gap-3">
            {busy && <Spinner label="Working..." />}
            <Button variant="primary" disabled={busy || !invoices || !canOperate(user)} title={canOperate(user) ? undefined : 'Viewers cannot import'} onClick={submit}>Import and run</Button>
          </div>
        </div>
      </Card>
      <p className="mt-3 text-xs text-slate-500">
        Importing replaces the current run. Files are read in your browser and sent only to the local backend.
      </p>
    </div>
  )
}
