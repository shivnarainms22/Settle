import { useEffect, useRef, useState } from 'react'
import type { SimState } from '../api'
import { shortHash } from '../format'
import { Chip, Mono } from './ui'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="break-all font-mono text-[11px] text-slate-100">{value}</div>
    </div>
  )
}

/** Header chip showing the run fingerprint (audit chain head), with replay / Bitdeer badges. */
export default function Fingerprint({ sim }: { sim: SimState }) {
  const [copied, setCopied] = useState(false)
  const [pinned, setPinned] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  // click-to-open only: a hover popover here would cover the sim controls right below it
  useEffect(() => {
    if (!pinned) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setPinned(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setPinned(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [pinned])

  async function copy() {
    try {
      await navigator.clipboard.writeText(sim.audit_head)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setPinned(true) // clipboard blocked: show the full hash so it can be selected by hand
    }
  }

  return (
    <div className="flex items-center gap-2">
      {sim.replay && <Chip className="bg-amber-500 px-2.5 text-[10px] font-bold uppercase tracking-wide text-white">Replay</Chip>}
      {sim.bitdeer && <Chip className="bg-violet-600 px-2.5 text-[10px] font-bold uppercase tracking-wide text-white">Bitdeer</Chip>}
      <div className="relative" ref={box}>
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white py-1 pl-3 pr-1.5 shadow-sm">
          <button className="flex items-center gap-2" onClick={() => setPinned(!pinned)} aria-expanded={pinned} title="Show the full fingerprint">
            <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Run fingerprint</span>
            <Mono className="font-semibold text-slate-800">{shortHash(sim.audit_head, 12).replace('…', '')}</Mono>
          </button>
          <button
            onClick={copy}
            aria-label="Copy run fingerprint"
            className="rounded-md border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <div className={`absolute right-0 top-full z-40 w-[28rem] pt-2 ${pinned ? 'block' : 'hidden'}`}>
          <div className="space-y-2 rounded-lg bg-ink-900 p-3 shadow-xl">
            <Row label="audit_head" value={sim.audit_head} />
            <Row label="world_digest" value={sim.world_digest} />
            <div className="text-[11px] text-slate-400">Same seed gives the same chain head. Recorder: {sim.recorder.hits} hits, {sim.recorder.misses} misses.</div>
          </div>
        </div>
      </div>
    </div>
  )
}
