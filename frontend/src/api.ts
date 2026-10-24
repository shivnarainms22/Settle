import { authHeaders, clearToken, getToken, notifyUnauthorized } from './auth'

// Types copied from docs/api-contract.md
export type Tier = 0 | 1 | 2 | 3
export type AgentState = 'Agent Working' | 'Self-Learning' | 'Input Needed' | 'Blocked'

export interface Kpis {
  open_ar_cents: number
  overdue_count: number
  dso: number
  cash_collected_cents: number
  auto_resolve_pct: number
  awaiting_approval_cents: number
  awaiting_approval_count: number
  human_touches: number
  agent_calls: number
  llm_cost_usd: number
}

export interface SimState {
  sim_date: string
  start_date: string
  end_date: string
  day_index: number
  month: 1 | 2 | 3
  memory_enabled: boolean
  agent_kind: 'heuristic' | 'claude'
  memory_backend: 'moss' | 'sqlite-fts'
  kpis: Kpis
  done: boolean
  /** SETTLE_REPLAY=1: no external calls, recordings only */
  replay: boolean
  /** Bitdeer rerank + intent router active */
  bitdeer: boolean
  /** sha256 head of the audit hash chain ("run fingerprint") */
  audit_head: string
  /** Changes when the run is reset or books are imported (activity ids restart). */
  run_id?: string
  /** sha256 of the seeded world (same seed => same digest) */
  world_digest: string
  recorder: { hits: number; misses: number }
  mode: 'simulation' | 'import'
  autonomy: AutonomyMode
}

export type ActivityKind =
  | 'email_out' | 'email_in' | 'payment' | 'decision' | 'approval'
  | 'gl' | 'memory' | 'playbook' | 'block' | 'system'

export interface Activity {
  id: number
  sim_date: string
  kind: ActivityKind
  title: string
  detail: string
  customer_id: string | null
  customer_name: string | null
  decision_id: number | null
  tier: Tier | null
  agent_state: AgentState | null
  amount_cents: number | null
}

export type AutonomyMode = 'shadow' | 'supervised' | 'autonomous'

export type DecisionStatus =
  | 'shadow' | 'executed' | 'pending_approval' | 'approved' | 'rejected' | 'edited' | 'blocked' | 'superseded'

export type DecisionSource = 'agent' | 'playbook' | 'deterministic' | 'router'

export interface Decision {
  id: number
  sim_date: string
  work_item: {
    kind: 'overdue' | 'email' | 'bank_line' | 'deduction' | 'invoice_issue'
    ref: string
    summary: string
  }
  customer_id: string | null
  customer_name: string | null
  source: DecisionSource
  action: string
  args: Record<string, unknown>
  rationale: string
  evidence: string[]
  memory_ids: number[]
  playbook_id: number | null
  confidence: number
  tier: Tier
  tier_reasons: string[]
  status: DecisionStatus
  approver: string | null
  amount_cents: number | null
  /** Approvals list only: why approving now would be refused (the world moved on). Empty when still valid. */
  stale?: string[]
}

export interface Memory {
  id: number
  type: 'episodic' | 'semantic' | 'correction'
  customer_id: string | null
  content: string
  source_decision_id: number | null
  approved_by: string
  created_at: string
}

export interface Playbook {
  id: number
  customer_id: string
  customer_name: string
  trigger: string
  action: string
  args: Record<string, unknown>
  description: string
  status: 'proposed' | 'active' | 'disabled' | 'needs_review'
  /** Not serialized by the API as of v2 (DB column exists); rendered only when present. */
  version?: number
  source_memory_ids: number[]
  times_fired: number
}

export interface GlEntry {
  id: number
  sim_date: string
  debit_acct: string
  credit_acct: string
  amount_cents: number
  ref_type: string
  ref_id: string
  memo: string
}

export interface AuditRow {
  id: number
  event_type: string
  prev_hash: string
  hash: string
  created_at: string
}

export interface AuditEvent {
  id: number
  event_type: string
  sim_date: string
  refs: string[]
  event: Record<string, unknown>
  prev_hash: string
  hash: string
  created_at: string
}

export interface AgentStep {
  turn: number
  tool: string | null
  input?: unknown
  output?: string
  error?: string
  note?: string
}

export type ReplayStatus = 'live' | 'hit' | 'miss' | 'error' | 'n/a'

export interface AgentRun {
  component: 'heuristic' | 'claude' | 'cash_app' | 'playbook' | 'router'
  model: string | null
  input_sha256: string
  input: Record<string, unknown>
  output: Record<string, unknown>
  retrieved_memory_ids: number[]
  steps: AgentStep[]
  replay: ReplayStatus
  llm_calls: number
  input_tokens: number
  output_tokens: number
  input_verified: boolean
}

export interface ForecastWeek {
  week: number
  start: string
  end: string
  expected_cents: number
}

export interface Forecast {
  as_of: string
  method: 'learned' | 'contract'
  weeks: ForecastWeek[]
  lines: { invoice_id: string; customer_id: string; date: string; amount_cents: number; basis: 'learned' | 'contract' | 'plan' }[]
  at_risk: { invoice_id: string; customer_id: string; amount_cents: number; reason: string }[]
  snapshots: {
    as_of: string
    method: string
    wape: number | null
    weeks: (ForecastWeek & { actual_cents: number })[]
  }[]
}

export interface DecisionDetail extends Decision {
  memories: Memory[]
  playbook: Playbook | null
  evidence_resolved: { ref: string; kind: string; text: string }[]
  gl_entries: GlEntry[]
  audit: AuditRow[]
  trace: AuditEvent[]
  agent_run: AgentRun | null
  /** Cited customer text that tried to instruct the agent, and what happened instead. */
  security_flags?: string[]
}

export type InvoiceStatus =
  | 'scheduled' | 'open' | 'reminded' | 'blocked' | 'disputed' | 'plan'
  | 'partially_paid' | 'paid' | 'escalated' | 'on_hold'

export interface Invoice {
  id: string
  customer_id: string
  po_number: string | null
  amount_cents: number
  balance_cents: number
  issued_on: string
  due_on: string
  status: InvoiceStatus
  days_overdue: number
  reminder_count: number
}

export interface Email {
  id: string
  thread_id: string
  direction: 'in' | 'out'
  sender: string
  subject: string
  body: string
  sim_date: string
}

export interface CustomerSummary {
  id: string
  name: string
  tier: 'standard' | 'key_account'
  open_ar_cents: number
  overdue_count: number
  avg_days_late: number | null
  owner_in_sales: string
  active_playbooks: number
}

export interface CustomerProfile {
  aliases: string[]
  avg_days_late: number | null
  payments_observed: number
  needs_po: boolean | null
  reliable_late_payer: boolean
  bank_account_on_file: string
  verified_domain: string
  dispute_count: number
  notes: string[]
}

export interface CustomerDetail extends CustomerSummary {
  profile: CustomerProfile
  invoices: Invoice[]
  emails: Email[]
  memories: Memory[]
  playbooks: Playbook[]
}

export interface EvalMonth {
  month: 1 | 2 | 3
  work_items: number
  auto_resolution_rate: number
  human_touches: number
  agent_calls: number
  agent_calls_per_invoice: number
  llm_cost_usd: number
  cost_per_invoice_usd: number
  /** Token usage priced at list rates; set even when the run was replayed from recordings (live cost is then 0). */
  modeled_llm_cost_usd?: number
  modeled_cost_per_invoice_usd?: number
  router_skips?: number
  action_accuracy: number
  cash_app_accuracy: number
  escalation_precision: number
  dso: number
  unsafe_actions: number
  adversarial_items: number
  adversarial_breaches: number
  forecast_wape: number | null
  playbooks_suspended: number
  touchless_cash_rate: number
  unapplied_cash_cents: number
  dispute_cycle_days: number | null
  credit_leakage_cents: number
}

export interface EvalTrace {
  audit_events: number
  audit_head: string
  chain_ok: boolean
  entity_refs: number
  decision_provenance_coverage: number
  gl_audit_coverage: number
  world_digest: string
}

export interface EvalDeterminism {
  identical: boolean
  head: string
  rerun_head: string
  world_digest: string
}

export interface EvalRun {
  memory: boolean
  agent_kind: string
  months: EvalMonth[]
  totals: EvalMonth
  trace: EvalTrace
}

export interface EvalResult {
  generated_at: string
  seed: number
  runs: EvalRun[]
  determinism: EvalDeterminism
}

export interface AuditVerify {
  ok: boolean
  length: number
  broken_at: number | null
  head: string
}

export interface LedgerAccount {
  account: string
  debit_cents: number
  credit_cents: number
  balance_cents: number
}

export interface TraceResult {
  ref: string
  count: number
  events: AuditEvent[]
}

export interface FlagResult {
  decision_id: number
  playbook_suspended: number | null
}

export interface VerifyCheck {
  name: string
  ok: boolean
  checked: number
  failures: number
  examples: string[]
  what: string
}

export interface VerifyResult {
  ok: boolean
  head: string
  checks: VerifyCheck[]
}

export interface ImportSummary {
  customers: number
  invoices: number
  bank_lines: number
  open_ar_cents: number
  start_date: string
  end_date: string
}

export interface ImportResult {
  summary: ImportSummary
  state: SimState
}

export type ImportSamples = Record<'ar_aging.csv' | 'bank_statement.csv', string>

export type RetrievalSystem = 'sqlite_fts' | 'moss' | 'fused' | 'sqlite_fts+rerank' | 'moss+rerank' | 'fused+rerank'

export interface RetrievalStat {
  recall_at_5: number
  mrr: number
  median_latency_ms: number
  queries: number
}

export interface RetrievalEval {
  corpus_memories: number
  distractors: number
  situations: number
  k: number
  summary: Record<RetrievalSystem, RetrievalStat>
  /** situation -> { relevant: n, <system>: recall } */
  per_situation: Record<string, Record<string, number>>
  notes: Record<string, string>
}

export interface BenchScale {
  scale: number
  customers: number
  invoices: number
  decisions: number
  audit_log: number
  memories: number
  seed_s: number
  sim_s: number
  verify_s: number
  decisions_per_s: number
  verified: boolean
}

export interface BenchConcurrency {
  workers_1_s: number
  workers_8_s: number
  agent_calls: number
  speedup: number
  identical_audit_head: boolean
  customers: number
  days: number
}

export interface Bench {
  scales: BenchScale[]
  concurrency: BenchConcurrency | null
  simulated_llm_latency_ms: number
}

export interface StackResult {
  retrieval: RetrievalEval | null
  bench: Bench | null
}

export type Verdict = 'approve' | 'reject' | 'edit' | 'dismiss'

export type Role = 'controller' | 'ar_clerk' | 'viewer'
export interface User {
  username: string
  name: string
  role: Role
  /** null = unlimited */
  approval_limit_cents: number | null
}

export interface Health {
  ok: boolean
  status: 'ok' | 'degraded'
  mode: 'simulation' | 'import'
  autonomy: AutonomyMode
  components: { name: string; status: 'ok' | 'degraded' | 'off'; detail: string }[]
  recent_fallbacks: number
}

export interface AutonomyInfo {
  mode: AutonomyMode
  changed_by: string | null
  changed_at: string | null
  reason: string | null
}

export interface WorklistRow {
  invoice_id: string
  customer_id: string
  customer_name: string
  balance_cents: number
  due_on: string
  days_overdue: number
  status: string
  expected_pay_date: string | null
  risk: 'high' | 'medium' | 'low'
  priority: number
  reasons: string[]
  next_action: string
  pending_decision_id: number | null
}

export class ApiError extends Error {
  status: number
  /** Validation errors from a 422 `{detail: {message, errors}}` body. */
  errors: string[]
  constructor(status: number, message: string, errors: string[] = []) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

/** status 0 = network failure (backend unreachable). */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { ...authHeaders(), ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : 'network error')
  }
  if (!res.ok) {
    // 401 with a held token = expired/invalid session: drop it and let the app show the login page.
    // (A failed login has no token, so it never lands here.)
    if (res.status === 401 && getToken()) {
      clearToken()
      notifyUnauthorized()
    }
    let msg = `HTTP ${res.status}`
    let errors: string[] = []
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') msg = body.detail
      else if (body?.detail && Array.isArray(body.detail.errors)) {
        errors = body.detail.errors.map(String)
        if (typeof body.detail.message === 'string') msg = body.detail.message
      }
    } catch {
      // non-JSON error body (e.g. proxy 502); keep the HTTP status message
    }
    // Vite proxy returns 5xx/502 when the backend is down: treat as unreachable
    throw new ApiError(res.status === 502 || res.status === 503 || res.status === 504 ? 0 : res.status, msg, errors)
  }
  return (await res.json()) as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  login: (username: string, password: string) => post<{ token: string; user: User }>('/api/login', { username, password }),
  me: () => request<User>('/api/me'),
  users: () => request<User[]>('/api/users'),
  health: () => request<Health>('/api/health'),
  autonomy: () => request<AutonomyInfo>('/api/autonomy'),
  setAutonomy: (mode: AutonomyMode, reason: string) => post<AutonomyInfo>('/api/autonomy', { mode, reason }),
  worklist: (limit = 50) => request<WorklistRow[]>(`/api/worklist?limit=${limit}`),
  state: () => request<SimState>('/api/state'),
  advanceDays: (days: number) => post<SimState>('/api/sim/advance', { days }),
  advanceTo: (date: string) => post<SimState>('/api/sim/advance', { to: date }),
  advanceToMonthEnd: () => post<SimState>('/api/sim/advance', { to: 'month_end' }),
  reset: (memory: boolean, seed?: number) =>
    post<SimState>('/api/sim/reset', seed === undefined ? { memory } : { memory, seed }),
  activity: (afterId = 0, limit = 200) =>
    request<Activity[]>(`/api/activity?after_id=${afterId}&limit=${limit}`),
  approvals: () => request<Decision[]>('/api/approvals'),
  decide: (
    id: number,
    body: { verdict: Verdict; args?: Record<string, unknown>; action?: string; note?: string; },
  ) => post<Decision>(`/api/approvals/${id}`, body),
  decisions: (limit = 100) => request<Decision[]>(`/api/decisions?limit=${limit}`),
  decision: (id: number) => request<DecisionDetail>(`/api/decisions/${id}`),
  customers: () => request<CustomerSummary[]>('/api/customers'),
  customer: (id: string) => request<CustomerDetail>(`/api/customers/${encodeURIComponent(id)}`),
  playbooks: () => request<Playbook[]>('/api/playbooks'),
  approvePlaybook: (id: number) => post<Playbook>(`/api/playbooks/${id}/approve`),
  disablePlaybook: (id: number) => post<Playbook>(`/api/playbooks/${id}/disable`),
  getTrace: (ref: string) => request<TraceResult>(`/api/trace?ref=${encodeURIComponent(ref)}`),
  flagDecision: (id: number, body: { note: string; correct_action?: string }) =>
    post<FlagResult>(`/api/decisions/${id}/flag`, body),
  getForecast: () => request<Forecast>('/api/forecast'),
  verifyAudit: () => request<AuditVerify>('/api/audit/verify'),
  ledger: () => request<{ accounts: LedgerAccount[] }>('/api/ledger'),
  /** Resolves null when the ablation has never been run (404). */
  evalLatest: async (): Promise<EvalResult | null> => {
    try {
      return await request<EvalResult>('/api/eval')
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  },
  verify: () => request<VerifyResult>('/api/verify'),
  importSamples: () => request<ImportSamples>('/api/import/samples'),
  importBooks: (body: { invoices_csv: string; bank_csv?: string; memory: boolean; autonomy?: AutonomyMode }) =>
    post<ImportResult>('/api/import', body),
  stack: () => request<StackResult>('/api/stack'),
  runEval: (seed?: number) => post<EvalResult>('/api/eval/run', seed === undefined ? {} : { seed }),
}
