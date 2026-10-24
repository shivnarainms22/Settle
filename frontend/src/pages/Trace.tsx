import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useResource } from '../hooks'
import { parseRef, traceHref } from '../trace'
import EventTimeline from '../components/EventTimeline'
import VerifyChain from '../components/VerifyChain'
import { Button, Card, ErrorBanner, Loading, PageHeader } from '../components/ui'

function TraceSearch({ initial }: { initial: string }) {
  const navigate = useNavigate()
  const [text, setText] = useState(initial)
  const valid = parseRef(text) !== null

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid) navigate(traceHref(text.trim()))
      }}
    >
      <input
        aria-label="Trace ref"
        className="w-64 rounded-md border border-slate-300 px-3 py-1.5 font-mono text-sm"
        placeholder="invoice:INV-1088 or run"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
      />
      <Button type="submit" variant="primary" disabled={!valid}>Trace</Button>
    </form>
  )
}

export default function Trace() {
  const { ref = 'run' } = useParams()
  const res = useResource(() => api.getTrace(ref), [ref])

  return (
    <div>
      <PageHeader
        title="Trace"
        subtitle={`Every audit event touching ${ref}, oldest first. Each entry is hash-chained to the one before it.`}
        right={<VerifyChain />}
      />
      <div className="mb-5"><TraceSearch key={ref} initial={ref} /></div>
      {res.error && <ErrorBanner error={res.error} />}
      <Card title={<span className="font-mono">{ref}</span>} right={res.data && <span className="tnum text-xs text-slate-500">{res.data.count} events</span>}>
        {res.loading ? <Loading /> : res.data ? <EventTimeline events={res.data.events} /> : null}
      </Card>
    </div>
  )
}
