import { api } from '../api'
import { useResource } from '../hooks'
import RetrievalCard from '../components/RetrievalCard'
import ScaleCard from '../components/ScaleCard'
import { Card, ErrorBanner, Loading, PageHeader, td, th } from '../components/ui'

const COMPONENTS: [string, string, string][] = [
  ['Claude Opus 5.5', 'reasoning on judgment calls', 'Eval tab'],
  ['Moss', 'semantic memory retrieval', 'retrieval card'],
  ['Bitdeer bge-reranker', 'precision reranking', 'retrieval card'],
  ['Bitdeer DeepSeek router', 'skips the expensive agent on acknowledgements', 'Eval agent calls'],
  ['SQLite FTS5', 'keyword retrieval + offline fallback', 'retrieval card'],
  ['Policy engine (code)', 'hard guardrails', 'Verify'],
  ['Hash-chained audit', 'tamper evidence', 'Verify'],
  ['Record/replay', 'determinism', 'Eval reproducibility'],
]

function ComponentTable() {
  return (
    <Card title="Component → role → evidence" className="overflow-hidden [&>div]:p-0">
      <table className="w-full">
        <thead className="border-b border-slate-200 bg-slate-50">
          <tr><th className={th}>Component</th><th className={th}>Role</th><th className={th}>Evidence</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {COMPONENTS.map(([c, role, ev]) => (
            <tr key={c}><td className={`${td} font-medium`}>{c}</td><td className={`${td} text-slate-600`}>{role}</td><td className={`${td} text-accent`}>{ev}</td></tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

export default function Stack() {
  const res = useResource(api.stack, [])
  return (
    <div>
      <PageHeader title="Why each component" subtitle="Every technology in the stack, with the measurement that justifies it." />
      {res.error && <ErrorBanner error={res.error} />}
      {res.loading && !res.data ? <Loading /> : res.data && (
        <div className="space-y-5">
          <RetrievalCard retrieval={res.data.retrieval} />
          <ScaleCard bench={res.data.bench} />
          <ComponentTable />
        </div>
      )}
    </div>
  )
}
