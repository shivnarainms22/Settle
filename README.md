# Settle

**An autonomous accounts-receivable agent that learns how your customers pay, can't be talked into moving money, and
proves every action it took.**

Settle chases overdue invoices, works out *why* they're late, applies incoming cash, and books it to the ledger. It works
across billing, CRM, email and the bank feed. It remembers how each customer behaves, so it needs a human less every
month. It measures how much less, and it can replay any run to the same cryptographic fingerprint.

![Command center](assets/screenshots/command-center.png)

## Highlights

- **It learns, and it shows the effect.** It has episodic, semantic and procedural memory, written only from human
  verdicts and observed outcomes. In a memory-on vs memory-off ablation with Claude Opus 5.5, human touches fall from
  15 to 5 and forecast error falls from 62% to 32%.
- **Guardrails are code, not prompts.** A policy engine runs *after* the agent decides. Fraud, prompt injection and
  bank-detail changes are blocked even when the agent is fooled; a test swaps in a fully compromised agent to prove
  it.
- **Every action can be verified.**
  - Each state change is a hash-chained audit event.
  - Each decision stores the exact input the model saw, with its hash.
  - A 10-check verifier re-derives the whole run: policy replay, invoice replay and ledger tie-out.
- **Deterministic replay.** Every Claude, Moss and Bitdeer call is recorded. The same seed plus the same recordings
  gives the same audit-chain head, offline.
- **Built to pilot.**
  - Roles with approval limits and separation of duties.
  - Shadow and supervised modes, with a kill switch.
  - A collector worklist, health checks and auditor exports.
  - Import of your own AR aging and bank CSVs.
  - A single-port server or a Docker image.

## How it works

```mermaid
flowchart LR
    subgraph Inputs
        E[Customer email]
        B[Bank feed]
        O[Overdue invoices]
    end
    E & B & O --> W[Work items]
    W --> P{Approved playbook?}
    P -- yes --> V
    P -- no --> C{Deterministic cash match?}
    C -- yes --> V
    C -- no --> R{Bitdeer intent router}
    R -- routine ack --> V
    R -- needs judgement --> A[Claude agent<br/>read tools + memory search]
    A <--> M[(Memory<br/>Moss + FTS5 fused,<br/>Bitdeer rerank)]
    A --> V[Validate<br/>evidence, staleness, amounts]
    V --> T{Policy tiers, in code}
    T -- tier 0/1 --> X[Execute<br/>ledger, invoices, email]
    T -- tier 2 --> H[Human approval]
    T -- tier 3 --> K[Blocked]
    H --> X
    X & H & K --> L[(Hash-chained audit log)]
    X -- outcomes --> M
    H -- verdicts --> M
```

The steps:
1. **Cheapest path first.** Approved playbooks and exact cash matches are tried before anything else. Bitdeer's
   router then sends routine acknowledgements past the expensive agent.
2. **Claude decides.** It calls read tools and searches memory, then submits one structured decision citing its
   evidence.
3. **Validate.** The decision is checked for hallucinated records, stale state and amounts that don't add up.
4. **Policy assigns a tier:**
   - 0: autonomous
   - 1: autonomous, human notified
   - 2: needs approval
   - 3: blocked
5. **Learn from outcomes.** Human verdicts and observed payments become memory. Repeated confirmed outcomes become
   playbooks, which a human approves before they run.

## Results

Seed 7, a simulated B2B company with 12 customers over 3 months, scored against hidden ground truth.

| Claude Opus 5.5 | Memory ON | Memory OFF |
|---|---|---|
| Human touches | **5** | 15 |
| Auto-resolution | **97.8%** | 93.7% |
| Touchless cash application | **99.0%** | 95.1% |
| Escalation precision | **80%** | 33% |
| Cash forecast error (WAPE) | **32.4%** | 62% |
| LLM cost for the run | **$4.22** | $5.31 |
| Action accuracy vs ground truth | 99.1% | 99.2% |
| Unsafe actions · adversarial breaches · credit leakage | 0 · 0 · $0 | 0 · 0 · $0 |

Re-running memory ON from scratch gives an identical audit head.

The first live run had *lower* accuracy with memory on. Memory read "pays 2 days after every reminder" as "reliable
late payer, stop reminding". Profiles now separate reminder-driven payment from intrinsic lateness, and that review is
documented and covered by tests.

| Retrieval benchmark (recall@5 · MRR) | Alone | + Bitdeer rerank |
|---|---|---|
| SQLite FTS5 | 0.688 · 0.661 | 0.796 · 0.861 |
| Moss | 0.657 · 0.629 | — |
| Moss ∪ FTS5, fused | 0.736 · 0.703 | **0.875 · 0.958** |

**Scale:** at 25× (300 customers, 5,640 decisions) the simulation takes 9 s and verification takes 0.33 s. Concurrent
deliberation is 3.5–3.8× faster and gives the same audit head.

## The stack, and what each part does

| Component | Role | How we know it earns its place |
|---|---|---|
| **Claude Opus 5.5** | The agent. It uses read tools and memory search, and must cite evidence in one strict `submit_decision` call. Customer text is treated as untrusted. | Handles disputes, unknown payers and injections with evidence-cited reasoning. |
| **Moss** | Semantic episodic memory, fused with SQLite FTS5. | Fusion beats either index alone. FTS5 stays the source of truth if Moss is down. |
| **Bitdeer AI Model Studio** | `bge-reranker-v2-m3` reranks memory hits. `DeepSeek-V4.1-Flash` routes routine email past the agent. | Rerank lifts MRR from 0.70 to 0.96. The router cut agent calls, and an instruction guard keeps injected text from being cheap-routed. |
| **SQLite** | Ledger, invoices, audit chain, provenance and memory, with WAL and indexes. | Lets the verifier re-derive everything from one file. |
| **FastAPI + SSE** | API, auth, live activity stream, and serving the UI. | — |
| **React + Vite + Tailwind + Recharts** | Command center, approvals, decision provenance, trace, eval and verify. | — |

## Screenshots

| | |
|---|---|
| ![Dispute judged on evidence](assets/screenshots/decision-credit-memo.png) | ![Prompt injection detected and ignored](assets/screenshots/decision-prompt-injection.png) |
| **A dispute judged on evidence:** a pro-rata credit, backed by the carrier record. | **Prompt injection** from a verified customer domain, detected and ignored. |
| ![Memory ablation](assets/screenshots/eval.png) | ![Verifier](assets/screenshots/verify.png) |
| **Memory ablation**, plus a reproducibility proof. | **10 independent checks** over the whole run. |

## Quick start

```bash
./start.sh        # Windows: .\start.ps1   (builds the UI, serves everything on http://localhost:8000)
```

Sign in as **dana** (controller), **sam** (AR clerk, $1,000 approval limit) or **vic** (viewer). The password for all
three is `demo`. Without API keys, Settle runs fully offline with a deterministic stand-in agent.

To use the live stack:
1. Copy the example file: `cp backend/.env.example backend/.env`. It includes the sign-up links.
2. Fill in your keys.
3. Run `cd backend && uv sync --extra moss`.

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` | Claude agent (otherwise the offline agent) |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | Moss memory index (otherwise SQLite FTS5 only) |
| `BITDEER_API_KEY` | Bitdeer rerank and intent router |
| `SETTLE_REPLAY=1` | Serve recorded calls only, with no network |
| `SETTLE_USERS`, `SETTLE_SECRET` | Real users and the token-signing secret |

**Docker.** Keys are passed at run time and are never baked into the image. Demo logins are off unless you opt in:

```bash
docker build -t settle .
docker run --env-file backend/.env -e SETTLE_ALLOW_DEMO_USERS=1 -p 8000:8000 -v settle-data:/data settle
```

**Development:**

```bash
cd backend && uv sync && uv run uvicorn settle.api:app --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173
```

## Verify it yourself

```bash
cd backend
uv run pytest -q                              # 145 tests
uv run python -m settle.verify --offline      # 10-check end-to-end verifier, plus a determinism re-run
uv run python -m settle.eval --heuristic      # memory ablation offline (drop --heuristic to use Claude)
uv run python -m settle.retrieval_eval        # FTS5 vs Moss vs fused, ± Bitdeer rerank
uv run python -m settle.bench                 # scale and concurrency
cd ../frontend && npm test                    # 90 tests
```

`bash done.sh` runs everything: the tests, lint, the verifier and the frontend build.

## Project structure

```
backend/settle/
  engine.py      orchestrator: events → work items → playbook / cash-app / router / agent → validate → policy → execute
  agent.py       Claude agent (tool loop, strict submit_decision, recorded transcript) and the offline agent
  policy.py      autonomy tiers, enforced in code
  executor.py    the only writer of ledger, invoices and outbound email; audited field-level diffs
  memory.py      episodic (Moss + FTS5 + rerank), semantic profiles, procedural playbooks, drift detection
  audit.py       hash chain, entity refs and trace
  recorder.py    record/replay for every external call
  verify.py      end-to-end verifier
  eval.py        memory ablation, determinism proof
  auth.py        users, roles, signed tokens, approval limits
  api.py         FastAPI, SSE, exports, serves the UI
  cash_app.py, bitdeer.py, forecast.py, importer.py, personas.py, seed_data.py
frontend/src/    React app: command center, approvals, worklist, decision provenance, trace, eval, verify, import
assets/          screenshots
```
