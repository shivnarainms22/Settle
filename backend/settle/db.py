"""SQLite schema and connection helpers. All money columns are integer cents."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, tier TEXT NOT NULL,
    verified_domain TEXT NOT NULL, ap_email TEXT NOT NULL,
    bank_account_on_file TEXT NOT NULL, owner_in_sales TEXT NOT NULL
);

-- Hidden persona specs: drive the simulator and the eval ground truth. Never shown to the agent.
CREATE TABLE IF NOT EXISTS personas (customer_id TEXT PRIMARY KEY, spec_json TEXT NOT NULL);

-- Semantic memory: what Settle has learned about each customer.
CREATE TABLE IF NOT EXISTS profiles (
    customer_id TEXT PRIMARY KEY, aliases_json TEXT NOT NULL DEFAULT '[]',
    late_days_json TEXT NOT NULL DEFAULT '[]', payment_obs_json TEXT NOT NULL DEFAULT '[]', needs_po INTEGER,
    dispute_count INTEGER NOT NULL DEFAULT 0, notes_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS crm_notes (
    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, invoice_id TEXT, kind TEXT NOT NULL, text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, po_number TEXT, amount_cents INTEGER NOT NULL,
    balance_cents INTEGER NOT NULL, issued_on TEXT NOT NULL, due_on TEXT NOT NULL, status TEXT NOT NULL,
    reminder_count INTEGER NOT NULL DEFAULT 0, last_reminder_on TEXT, hold_until TEXT,
    plan_json TEXT, paid_on TEXT, description TEXT NOT NULL DEFAULT ''
);

-- Proof of delivery from the logistics system: the evidence that separates a genuine claim from a stall.
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL, customer_id TEXT NOT NULL, carrier TEXT NOT NULL,
    delivered_on TEXT NOT NULL, signed_by TEXT NOT NULL, condition TEXT NOT NULL, notes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_deliveries_invoice ON deliveries(invoice_id);

CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, customer_id TEXT, invoice_id TEXT,
    direction TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
    sim_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bank_lines (
    id TEXT PRIMARY KEY, amount_cents INTEGER NOT NULL, payer_name TEXT NOT NULL,
    remittance_text TEXT NOT NULL, sim_date TEXT NOT NULL, matched INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sim_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, due_date TEXT NOT NULL, kind TEXT NOT NULL,
    customer_id TEXT, payload_json TEXT NOT NULL, fired INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sim_events_due ON sim_events(fired, due_date);

CREATE TABLE IF NOT EXISTS work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sim_date TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
    customer_id TEXT, summary TEXT NOT NULL, gt_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open', decision_id INTEGER
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, work_item_id INTEGER NOT NULL, sim_date TEXT NOT NULL,
    customer_id TEXT, source TEXT NOT NULL, action TEXT NOT NULL, args_json TEXT NOT NULL,
    rationale TEXT NOT NULL, evidence_json TEXT NOT NULL, memory_ids_json TEXT NOT NULL,
    playbook_id INTEGER, confidence REAL NOT NULL, tier INTEGER NOT NULL, tier_reasons_json TEXT NOT NULL,
    status TEXT NOT NULL, approver TEXT, amount_cents INTEGER, original_json TEXT,
    llm_calls INTEGER NOT NULL DEFAULT 0, trigger TEXT NOT NULL DEFAULT '', correct INTEGER, flag_json TEXT
);

CREATE TABLE IF NOT EXISTS gl_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sim_date TEXT NOT NULL, debit_acct TEXT NOT NULL,
    credit_acct TEXT NOT NULL, amount_cents INTEGER NOT NULL, ref_type TEXT NOT NULL, ref_id TEXT NOT NULL,
    memo TEXT NOT NULL, decision_id INTEGER, invoice_id TEXT
);

CREATE TABLE IF NOT EXISTS forecasts (as_of TEXT PRIMARY KEY, payload_json TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, customer_id TEXT, content TEXT NOT NULL,
    trigger TEXT, action TEXT, source_decision_id INTEGER, approved_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, customer_id UNINDEXED, memory_id UNINDEXED);

CREATE TABLE IF NOT EXISTS playbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL, trigger TEXT NOT NULL,
    action TEXT NOT NULL, args_json TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
    source_memory_ids_json TEXT NOT NULL, times_fired INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, event_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL, sim_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_refs (audit_id INTEGER NOT NULL, ref TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_audit_refs_ref ON audit_refs(ref, audit_id);

-- Provenance of every decision: exactly what the deciding component saw, retrieved, called and returned.
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER NOT NULL, work_item_id INTEGER NOT NULL,
    component TEXT NOT NULL, model TEXT, input_sha256 TEXT NOT NULL, input_json TEXT NOT NULL,
    output_json TEXT NOT NULL, retrieved_memory_ids_json TEXT NOT NULL, steps_json TEXT NOT NULL,
    replay TEXT NOT NULL, llm_calls INTEGER NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sim_date TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '', customer_id TEXT, decision_id INTEGER, tier INTEGER,
    agent_state TEXT, amount_cents INTEGER
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sim_date TEXT NOT NULL, purpose TEXT NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    sim_date TEXT PRIMARY KEY, open_ar_cents INTEGER NOT NULL, dso REAL NOT NULL
);

-- Link tables: decision/event -> invoices, so per-invoice lookups are index seeks instead of JSON LIKE scans.
CREATE TABLE IF NOT EXISTS decision_invoices (decision_id INTEGER NOT NULL, invoice_id TEXT NOT NULL,
    PRIMARY KEY (decision_id, invoice_id));
CREATE INDEX IF NOT EXISTS ix_decision_invoices_inv ON decision_invoices(invoice_id, decision_id);
CREATE TABLE IF NOT EXISTS event_invoices (event_id INTEGER NOT NULL, invoice_id TEXT NOT NULL,
    PRIMARY KEY (event_id, invoice_id));
CREATE INDEX IF NOT EXISTS ix_event_invoices_inv ON event_invoices(invoice_id, event_id);

-- Indexes for every hot query path (dunning scan, work-item queue, approvals, traces, per-customer reads).
CREATE INDEX IF NOT EXISTS ix_invoices_status_due ON invoices(status, due_on);
CREATE INDEX IF NOT EXISTS ix_invoices_customer ON invoices(customer_id, status);
CREATE INDEX IF NOT EXISTS ix_work_items_queue ON work_items(status, sim_date, kind);
CREATE INDEX IF NOT EXISTS ix_work_items_decision ON work_items(decision_id);
CREATE INDEX IF NOT EXISTS ix_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS ix_decisions_customer ON decisions(customer_id);
CREATE INDEX IF NOT EXISTS ix_memories_customer ON memories(customer_id, id);
CREATE INDEX IF NOT EXISTS ix_memories_source ON memories(source_decision_id);
CREATE INDEX IF NOT EXISTS ix_playbooks_lookup ON playbooks(customer_id, trigger, status);
CREATE INDEX IF NOT EXISTS ix_audit_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS ix_gl_invoice ON gl_entries(invoice_id);
CREATE INDEX IF NOT EXISTS ix_gl_decision ON gl_entries(decision_id);
CREATE INDEX IF NOT EXISTS ix_emails_thread ON emails(thread_id);
CREATE INDEX IF NOT EXISTS ix_emails_customer ON emails(customer_id, sim_date);
CREATE INDEX IF NOT EXISTS ix_sim_events_cust ON sim_events(kind, customer_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_decision ON agent_runs(decision_id);
CREATE INDEX IF NOT EXISTS ix_activity_customer ON activity(customer_id);
"""


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def drop_all(conn: sqlite3.Connection) -> None:
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for name in tables:
        if name.startswith("sqlite_") or name.startswith("memories_fts_"):
            continue
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
    )


def loads(text: str | None, default=None):
    if text is None:
        return default
    return json.loads(text)


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
