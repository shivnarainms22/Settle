import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Playbook } from '../api'
import { isController } from '../permissions'
import { useAuth } from './AuthProvider'
import RefChip from './RefChip'
import { Button, Chip, ErrorBanner, Mono, StatusChip } from './ui'

export default function PlaybookCard({ p, onChanged }: { p: Playbook; onChanged?: () => void }) {
  const { user } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function act(fn: () => Promise<Playbook>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
      onChanged?.()
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      {error && <ErrorBanner error={error} />}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <StatusChip status={p.status} />
            <span className="font-mono text-sm font-semibold">{p.action}</span>
            <Mono className="text-slate-400">#{p.id}</Mono>
            {p.version !== undefined && <Chip className="bg-slate-100 font-mono text-slate-600">v{p.version}</Chip>}
          </div>
          <Link to={`/customers/${p.customer_id}`} className="mt-1 block text-sm font-medium text-accent hover:underline">{p.customer_name}</Link>
        </div>
        {onChanged && isController(user) && (
          <div className="flex gap-2">
            {p.status === 'needs_review' && <Button variant="primary" disabled={busy} onClick={() => act(() => api.approvePlaybook(p.id))}>Approve new version</Button>}
            {p.status === 'proposed' && <Button variant="primary" disabled={busy} onClick={() => act(() => api.approvePlaybook(p.id))}>Approve</Button>}
            {p.status === 'active' && <Button variant="danger" disabled={busy} onClick={() => act(() => api.disablePlaybook(p.id))}>Disable</Button>}
          </div>
        )}
      </div>
      <p className="mt-2 text-sm text-slate-700">{p.description}</p>
      <div className="mt-2 text-xs text-slate-500">
        <span className="font-medium">Trigger:</span> {p.trigger}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
        <span>Learned from memories:</span>
        {p.source_memory_ids.length === 0 ? <span>none</span> : p.source_memory_ids.map((id) => <Chip key={id} className="bg-violet-50 font-mono text-violet-700">M{id}</Chip>)}
        <RefChip refId={`playbook:${p.id}`} label="Trace" className="ml-auto" />
        <span className="tnum font-medium text-slate-700">Fired {p.times_fired}x</span>
      </div>
    </div>
  )
}
