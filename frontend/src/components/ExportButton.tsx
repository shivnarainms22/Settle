import { useState } from 'react'
import { downloadFile } from '../download'
import { Button, ErrorBanner } from './ui'

/** Authenticated file download button; the filename comes from Content-Disposition. */
export default function ExportButton({ label, path, fallbackName }: { label: string; path: string; fallbackName: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function go() {
    setBusy(true)
    setError(null)
    try { await downloadFile(path, fallbackName) }
    catch (e) { setError(e instanceof Error ? e : new Error(String(e))) }
    finally { setBusy(false) }
  }

  return (
    <div>
      {error && <ErrorBanner error={error} />}
      <Button disabled={busy} onClick={go}>{busy ? 'Preparing...' : label}</Button>
    </div>
  )
}
