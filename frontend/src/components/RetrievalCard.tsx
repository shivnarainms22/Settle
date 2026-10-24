import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { RetrievalEval } from '../api'
import { bestKey, bestKeys, componentDeltas, formatDelta, SYSTEMS } from '../stack'
import { Card, td, th } from './ui'

const KEYS = SYSTEMS.map((s) => s.key as string)
const RECALL = '#4f46e5'
const RECALL_BEST = '#059669'
const MRR = '#94a3b8'

function Chart({ r }: { r: RetrievalEval }) {
  const recall = Object.fromEntries(SYSTEMS.map((s) => [s.key, r.summary[s.key]?.recall_at_5 ?? NaN]))
  const best = bestKey(recall, KEYS)
  const data = SYSTEMS.map((s) => ({
    key: s.key, name: s.label, recall: r.summary[s.key]?.recall_at_5, mrr: r.summary[s.key]?.mrr,
  }))
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 12 }} width={40} />
          <Tooltip formatter={(v: number) => v.toFixed(3)} />
          <Legend />
          <Bar name="recall@5 (best in green)" dataKey="recall" fill={RECALL}>
            {data.map((d) => <Cell key={d.key} fill={d.key === best ? RECALL_BEST : RECALL} />)}
          </Bar>
          <Bar name="MRR" dataKey="mrr" fill={MRR} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function PerSituation({ r }: { r: RetrievalEval }) {
  const rows = Object.entries(r.per_situation)
  return (
    <div className="mt-5 overflow-x-auto rounded-md border border-slate-200">
      <table className="w-full">
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Situation (recall@5)</th>
            {SYSTEMS.map((s) => <th key={s.key} className={`${th} text-right normal-case`}>{s.label}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(([name, vals]) => {
            const best = bestKeys(vals, KEYS)
            return (
              <tr key={name}>
                <td className={`${td} font-medium`}>{name.replace(/_/g, ' ')} <span className="text-xs text-slate-400">({vals.relevant} relevant)</span></td>
                {SYSTEMS.map((s) => (
                  <td key={s.key} className={`${td} tnum text-right ${best.has(s.key) ? 'bg-emerald-50 font-bold text-emerald-800' : 'text-slate-600'}`}>
                    {typeof vals[s.key] === 'number' ? vals[s.key].toFixed(2) : 'n/a'}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Adds({ r }: { r: RetrievalEval }) {
  return (
    <div className="mt-5">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">What each component adds</div>
      <ul className="space-y-1 text-sm text-slate-700">
        {componentDeltas(r.summary).map((d) => (
          <li key={d.label}>
            <span className={`tnum inline-block w-40 font-semibold ${d.delta !== null && d.delta > 0 ? 'text-emerald-700' : 'text-slate-600'}`}>{formatDelta(d.delta)}</span>
            {d.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function RetrievalCard({ retrieval }: { retrieval: RetrievalEval | null }) {
  return (
    <Card title="Retrieval: does each component earn its place?">
      {retrieval === null ? (
        <div className="py-8 text-center text-sm text-slate-500">
          Retrieval benchmark has not been run. Run it with
          <code className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">uv run python -m settle.retrieval_eval</code>
        </div>
      ) : (
        <>
          <p className="mb-3 text-sm text-slate-500">
            Cross-customer precedent search over {retrieval.corpus_memories} real memories ({retrieval.distractors} routine
            &apos;paid&apos; distractors), {retrieval.situations} situations × 3 paraphrased queries.
          </p>
          <Chart r={retrieval} />
          <Adds r={retrieval} />
          <PerSituation r={retrieval} />
        </>
      )}
    </Card>
  )
}
