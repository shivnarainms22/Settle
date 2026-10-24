import { Link } from 'react-router-dom'
import { traceHref } from '../trace'

/** A clickable `kind:id` reference that opens its audit trace. */
export default function RefChip({ refId, label, className = '' }: { refId: string; label?: string; className?: string }) {
  return (
    <Link
      to={traceHref(refId)}
      title={`Trace ${refId}`}
      className={`inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 font-mono text-xs font-medium text-indigo-700 transition hover:bg-indigo-100 hover:underline ${className}`}
    >
      {label ?? refId}
    </Link>
  )
}
