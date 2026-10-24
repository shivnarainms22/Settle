import { useState } from 'react'
import { api } from '../api'
import { canOperate } from '../permissions'
import { useAuth } from './AuthProvider'
import { Button, ErrorBanner } from './ui'

const ACTIONS = [
  'send_reminder', 'reissue_invoice', 'propose_credit_memo', 'propose_payment_plan', 'apply_payment',
  'request_balance', 'escalate', 'hold_dunning', 'issue_refund', 'update_bank_details', 'no_action',
]

/** "Flag as wrong" button + inline form. onFlagged receives the toast message. */
export default function FlagDecision({ id, onFlagged }: { id: number; onFlagged: (message: string) => void }) {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [action, setAction] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const r = await api.flagDecision(id, { note: note.trim(), ...(action ? { correct_action: action } : {}) })
      setOpen(false)
      setNote('')
      setAction('')
      onFlagged(
        r.playbook_suspended !== null
          ? `Playbook #${r.playbook_suspended} suspended for review (conflict detection)`
          : 'Decision flagged and saved to memory',
      )
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setBusy(false)
    }
  }

  if (!canOperate(user)) return null
  if (!open) return <Button variant="danger" onClick={() => setOpen(true)}>Flag as wrong</Button>
  return (
    <div className="w-80 rounded-lg border border-rose-200 bg-white p-3 text-left shadow-sm">
      {error && <ErrorBanner error={error} />}
      <textarea
        autoFocus
        className="h-20 w-full rounded-md border border-slate-300 p-2 text-sm"
        placeholder="What was wrong? (required)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <select
        className="mt-2 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
        value={action}
        onChange={(e) => setAction(e.target.value)}
        aria-label="Correct action"
      >
        <option value="">Correct action (optional)</option>
        {ACTIONS.map((a) => <option key={a}>{a}</option>)}
      </select>
      <div className="mt-3 flex gap-2">
        <Button variant="danger" disabled={busy || note.trim() === ''} onClick={submit}>{busy ? 'Flagging...' : 'Flag decision'}</Button>
        <Button variant="ghost" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  )
}
