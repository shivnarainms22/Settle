import { useState, type ReactNode } from 'react'
import type { AgentRun, AgentStep, ReplayStatus } from '../api'
import { shortHash } from '../format'
import { parseRetrieval } from '../trace'
import { Card, Chip, Json, Mono } from './ui'

const REPLAY: Record<ReplayStatus, { label: string; style: string }> = {
  live: { label: 'live', style: 'bg-sky-100 text-sky-800' },
  hit: { label: 'replayed from recording', style: 'bg-emerald-100 text-emerald-800' },
  miss: { label: 'recording miss', style: 'bg-amber-100 text-amber-800' },
  error: { label: 'replay error', style: 'bg-rose-100 text-rose-800' },
  'n/a': { label: 'n/a', style: 'bg-slate-100 text-slate-600' },
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-sm text-slate-800">{children}</div>
    </div>
  )
}

function ProvenancePanel({ run }: { run: AgentRun }) {
  const replay = REPLAY[run.replay]
  return (
    <Card title="Provenance">
      <div className="grid grid-cols-4 gap-4">
        <Stat label="Component"><span className="font-mono">{run.component}</span></Stat>
        <Stat label="Model">{run.model ? <span className="font-mono">{run.model}</span> : <span className="text-slate-400">none</span>}</Stat>
        <Stat label="Replay status"><Chip className={replay.style}>{replay.label}</Chip></Stat>
        <Stat label="LLM calls"><span className="tnum">{run.llm_calls}</span></Stat>
        <Stat label="Input sha256">
          <span className="inline-flex items-center gap-2" title={run.input_sha256}>
            <Mono>{shortHash(run.input_sha256, 16)}</Mono>
            {run.input_verified
              ? <Chip className="bg-emerald-100 text-emerald-800">&#10003; verified</Chip>
              : <Chip className="bg-rose-100 text-rose-800">not verified</Chip>}
          </span>
        </Stat>
        <Stat label="Input tokens"><span className="tnum">{run.input_tokens.toLocaleString('en-US')}</span></Stat>
        <Stat label="Output tokens"><span className="tnum">{run.output_tokens.toLocaleString('en-US')}</span></Stat>
      </div>
    </Card>
  )
}

function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <button
        className="flex w-full items-center justify-between text-left text-sm font-semibold tracking-wide text-slate-700"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {title}
        <span className="text-xs text-slate-400">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && <div className="mt-3">{children}</div>}
    </Card>
  )
}

function preview(v: unknown, max = 240): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  if (s === undefined) return ''
  return s.length > max ? `${s.slice(0, max)}…` : s
}

function StepRow({ step, memoryIds }: { step: AgentStep; memoryIds: number[] }) {
  const retrieval = step.tool === 'memory_retrieval' ? parseRetrieval(step.output) : null
  const ids = retrieval && retrieval.memoryIds.length > 0 ? retrieval.memoryIds : memoryIds
  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center gap-2">
        <Mono className="text-slate-400">turn {step.turn}</Mono>
        <span className="font-mono text-sm font-semibold">{step.tool ?? 'reasoning'}</span>
      </div>
      {retrieval ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
          <span>Backend</span>
          <Chip className="bg-slate-100 font-mono text-slate-700">{retrieval.backend}</Chip>
          {retrieval.reranker && (
            <>
              <span>reranker</span>
              <Chip className="bg-violet-100 font-mono text-violet-700">{retrieval.reranker}</Chip>
            </>
          )}
          <span className="ml-2">Retrieved</span>
          {ids.length === 0
            ? <span className="text-slate-400">no memories</span>
            : ids.map((id) => <Chip key={id} className="bg-violet-50 font-mono text-violet-700">M{id}</Chip>)}
        </div>
      ) : (
        <>
          {step.input !== undefined && (
            <div className="mt-1.5 break-all font-mono text-xs text-slate-600"><span className="text-slate-400">in </span>{preview(step.input)}</div>
          )}
          {step.output !== undefined && (
            <div className="mt-1 break-all font-mono text-xs text-slate-600"><span className="text-slate-400">out </span>{preview(step.output)}</div>
          )}
        </>
      )}
      {step.error && <div className="mt-1 text-xs text-rose-600">{step.error}</div>}
      {step.note && <div className="mt-1 text-xs text-slate-500">{step.note}</div>}
    </li>
  )
}

function AgentSteps({ run }: { run: AgentRun }) {
  return (
    <Card title="Agent steps">
      {run.steps.length === 0 ? (
        <div className="text-sm text-slate-400">No tool steps (deterministic path).</div>
      ) : (
        <ol className="space-y-2">
          {run.steps.map((s, i) => <StepRow key={i} step={s} memoryIds={run.retrieved_memory_ids} />)}
        </ol>
      )}
    </Card>
  )
}

/** Provenance, exact input, steps and raw output for a decision's agent run. */
export default function AgentRunSections({ run }: { run: AgentRun }) {
  return (
    <>
      <div className="col-span-3"><ProvenancePanel run={run} /></div>
      <div className="col-span-3"><Collapsible title="Exact input the agent saw"><Json value={run.input} /></Collapsible></div>
      <div className="col-span-3"><AgentSteps run={run} /></div>
      <div className="col-span-3"><Card title="Raw output"><Json value={run.output} /></Card></div>
    </>
  )
}
