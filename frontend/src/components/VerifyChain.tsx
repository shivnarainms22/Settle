import { useState } from 'react'
import { api, type AuditVerify } from '../api'
import { shortHash } from '../format'
import { Button, Mono, Spinner } from './ui'

export default function VerifyChain() {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<AuditVerify | null>(null)
  const [error, setError] = useState<Error | null>(null)

  async function verify() {
    setBusy(true)
    setError(null)
    try { setResult(await api.verifyAudit()) }
    catch (e) { setError(e instanceof Error ? e : new Error(String(e))) }
    finally { setBusy(false) }
  }

  return (
    <div className="flex items-center gap-3">
      {busy && <Spinner />}
      {error && <span className="text-sm text-rose-600">{error.message}</span>}
      {result && (result.ok ? (
        <span className="rounded-md bg-emerald-100 px-3 py-1.5 text-sm font-bold text-emerald-800">
          OK <span className="tnum font-medium">({result.length} entries)</span>{' '}
          <Mono className="font-medium">head {shortHash(result.head, 12)}</Mono>
        </span>
      ) : (
        <span className="rounded-md bg-rose-600 px-3 py-1.5 text-sm font-bold text-white">
          BROKEN at id <span className="tnum">{result.broken_at}</span>
        </span>
      ))}
      <Button disabled={busy} onClick={verify}>Verify chain</Button>
    </div>
  )
}
