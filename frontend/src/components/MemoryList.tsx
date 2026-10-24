import { Link } from 'react-router-dom'
import type { Memory } from '../api'
import { formatDate } from '../format'
import { Chip, Empty, Mono } from './ui'

const TYPE_STYLE: Record<Memory['type'], string> = {
  episodic: 'bg-sky-100 text-sky-800',
  semantic: 'bg-violet-100 text-violet-800',
  correction: 'bg-amber-100 text-amber-800',
}

export default function MemoryList({ memories }: { memories: Memory[] }) {
  if (memories.length === 0) return <Empty>No memories.</Empty>
  return (
    <ul className="divide-y divide-slate-100">
      {memories.map((m) => (
        <li key={m.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-center gap-2">
            <Chip className={TYPE_STYLE[m.type]}>{m.type}</Chip>
            <Mono className="text-slate-400">M{m.id}</Mono>
            <span className="ml-auto text-xs text-slate-400">{m.approved_by} &middot; {formatDate(m.created_at.slice(0, 10))}</span>
          </div>
          <p className="mt-1 text-sm text-slate-700">{m.content}</p>
          {m.source_decision_id !== null && (
            <Link to={`/decisions/${m.source_decision_id}`} className="text-xs text-accent hover:underline">
              from decision #{m.source_decision_id}
            </Link>
          )}
        </li>
      ))}
    </ul>
  )
}
