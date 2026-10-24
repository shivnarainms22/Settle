"""End-to-end verifier: independently re-checks a run from its records alone.

It does not trust the engine's own status flags; it re-derives them:
  chain            the audit log's hash chain is intact
  provenance       every decision has exactly one provenance record whose input hashes to its stored sha256
  policy_replay    re-running the policy engine on every recorded decision reproduces its stored tier
  guardrails       no tier-3 action ever executed; every tier-2 action that executed was approved by a named human
  invoice_replay   every invoice's current state is exactly the end of its audited field-level diff chain
  ledger           double entry balances; AR in the GL ties to the invoice subledger; every post is audited
  messages         every email in or out has its audit event
  memory           every memory was written from a human verdict or an observed outcome, never an agent's guess
  work_items       every work item's status is consistent with its decision
  determinism      (CLI --rerun) a fresh replay of the same seed reproduces the identical audit-chain head

    uv run python -m settle.verify            # oracle run with memory, all checks, then replay re-run
"""

import dataclasses
import hashlib
import sqlite3
import sys

from settle import audit, ledger
from settle.db import connect, loads
from settle.executor import INVOICE_FIELDS
from settle.models import Decision
from settle.policy import PolicyContext, assign_tier

EXECUTED = ("executed", "approved", "edited")
MAX_EXAMPLES = 5


# events that change the books, the customer or memory; a shadow decision must never be the cause of one
SIDE_EFFECTS = ("invoice_updated", "email_sent", "bank_line_matched", "memory_write", "profile_updated", "handoff")


def _result(name: str, checked: int, failures: list[str], what: str) -> dict:
    return {
        "name": name,
        "ok": not failures,
        "checked": checked,
        "failures": len(failures),
        "examples": failures[:MAX_EXAMPLES],
        "what": what,
    }


def check_chain(conn) -> dict:
    v = audit.verify(conn)
    fails = [] if v["ok"] else [f"chain breaks at audit event #{v['broken_at']}"]
    return _result("chain", v["length"], fails, "audit log hash chain is intact")


def check_provenance(conn) -> dict:
    fails = []
    decisions = conn.execute("SELECT id FROM decisions ORDER BY id").fetchall()
    runs: dict[int, list] = {}
    for r in conn.execute("SELECT decision_id, input_json, input_sha256 FROM agent_runs ORDER BY id"):
        runs.setdefault(r["decision_id"], []).append(r)
    for d in decisions:
        rs = runs.get(d["id"], [])
        if len(rs) != 1:
            fails.append(f"decision #{d['id']} has {len(rs)} provenance records")
        elif hashlib.sha256(rs[0]["input_json"].encode("utf-8")).hexdigest() != rs[0]["input_sha256"]:
            fails.append(f"decision #{d['id']} input does not match its sha256")
    return _result("provenance", len(decisions), fails, "each decision's exact input is recorded and hash-verified")


def check_policy_replay(conn) -> dict:
    fails = []
    rows = conn.execute(
        "SELECT d.*, w.kind, w.ref FROM decisions d JOIN work_items w ON w.id=d.work_item_id ORDER BY d.id"
    ).fetchall()
    for r in rows:
        original = loads(r["original_json"]) or {"action": r["action"], "args": loads(r["args_json"], {})}
        d = Decision(
            original["action"],
            original["args"],
            r["rationale"],
            confidence=r["confidence"],
            source=r["source"],
            playbook_id=r["playbook_id"],
        )
        cust = (
            conn.execute("SELECT * FROM customers WHERE id=?", (r["customer_id"],)).fetchone()
            if r["customer_id"]
            else None
        )
        sender = None
        if r["kind"] == "email":
            sender = conn.execute("SELECT sender FROM emails WHERE id=?", (r["ref"],)).fetchone()["sender"]
        ctx = PolicyContext(
            cust["tier"] if cust else None,
            cust["verified_domain"] if cust else None,
            cust["bank_account_on_file"] if cust else None,
            sender.split("@")[-1] if sender else None,
        )
        try:
            expected, _ = assign_tier(d, ctx)
        except (KeyError, TypeError, ValueError):
            expected = 2
        reasons = " ".join(loads(r["tier_reasons_json"], []))
        if "failed validation" in reasons or "policy could not evaluate" in reasons or "supervised mode" in reasons:
            expected = max(expected, 2)
        if expected != r["tier"]:
            fails.append(f"decision #{r['id']} ({original['action']}): stored tier {r['tier']}, policy says {expected}")
    return _result("policy_replay", len(rows), fails, "re-running the policy engine reproduces every stored tier")


def check_guardrails(conn) -> dict:
    fails = []
    rows = conn.execute("SELECT * FROM decisions ORDER BY id").fetchall()
    approvals = {
        r["decision_id"]
        for r in conn.execute(
            "SELECT CAST(json_extract(event_json, '$.decision_id') AS INTEGER) decision_id FROM audit_log"
            " WHERE event_type='approval'"
        )
    }
    executed = {
        r["decision_id"]
        for r in conn.execute(
            "SELECT CAST(json_extract(event_json, '$.decision_id') AS INTEGER) decision_id FROM audit_log"
            " WHERE event_type='decision_executed'"
        )
    }
    for r in rows:
        if r["tier"] == 3 and (r["status"] in EXECUTED or r["id"] in executed):
            fails.append(f"tier-3 decision #{r['id']} executed")
        if r["tier"] == 3 and conn.execute("SELECT 1 FROM gl_entries WHERE decision_id=?", (r["id"],)).fetchone():
            fails.append(f"tier-3 decision #{r['id']} has ledger entries")
        if r["tier"] == 2 and r["status"] in ("approved", "edited"):
            if not r["approver"] or r["id"] not in approvals:
                fails.append(f"tier-2 decision #{r['id']} executed without a recorded human approval")
        if r["tier"] < 2 and r["status"] == "pending_approval":
            fails.append(f"tier-{r['tier']} decision #{r['id']} is stuck pending")
        if r["status"] in EXECUTED and r["id"] not in executed:
            fails.append(f"decision #{r['id']} is {r['status']} but has no execution event")
        if r["status"] == "shadow" and (
            r["id"] in executed or conn.execute("SELECT 1 FROM gl_entries WHERE decision_id=?", (r["id"],)).fetchone()
        ):
            fails.append(f"shadow decision #{r['id']} was executed")
        if r["status"] == "shadow":
            side = conn.execute(
                "SELECT a.event_type FROM audit_log a JOIN audit_refs f ON f.audit_id=a.id WHERE f.ref=?"
                f" AND a.event_type IN ({','.join('?' * len(SIDE_EFFECTS))}) ORDER BY a.id LIMIT 1",
                (f"decision:{r['id']}", *SIDE_EFFECTS),
            ).fetchone()
            if side:
                fails.append(f"shadow decision #{r['id']} caused {side['event_type']}")
    return _result("guardrails", len(rows), fails, "no blocked action executed; every approval-tier action had one")


def check_invoice_replay(conn) -> dict:
    fails = []
    current = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM invoices")}
    last: dict[tuple[str, str], object] = {}
    events = conn.execute("SELECT event_json FROM audit_log WHERE event_type='invoice_updated' ORDER BY id")
    for e in events:
        ev = loads(e["event_json"])
        inv = ev["invoice_id"]
        for field, ch in ev["changes"].items():
            key = (inv, field)
            if key in last and last[key] != ch["old"]:
                fails.append(f"{inv}.{field}: diff chain broken ({last[key]!r} then old={ch['old']!r})")
            last[key] = ch["new"]
    for (inv, field), value in last.items():
        if field in INVOICE_FIELDS and current[inv][field] != value:
            fails.append(f"{inv}.{field}: current {current[inv][field]!r} != audited {value!r}")
    touched = {inv for inv, _ in last}
    return _result("invoice_replay", len(touched), fails, "every invoice's state is the end of its audited diff chain")


def check_ledger(conn) -> dict:
    fails = []
    tb = {a["account"]: a for a in ledger.trial_balance(conn)}
    if sum(a["debit_cents"] for a in tb.values()) != sum(a["credit_cents"] for a in tb.values()):
        fails.append("debits != credits")
    sub = conn.execute("SELECT COALESCE(SUM(balance_cents),0) FROM invoices WHERE status!='scheduled'").fetchone()[0]
    if tb[ledger.AR]["balance_cents"] != sub:
        fails.append(f"AR GL {tb[ledger.AR]['balance_cents']} != invoice subledger {sub}")
    audited = {
        int(r[0])
        for r in conn.execute("SELECT json_extract(event_json, '$.gl_id') FROM audit_log WHERE event_type='gl_post'")
    }
    posts = conn.execute("SELECT id FROM gl_entries WHERE memo NOT LIKE 'Opening %' ORDER BY id").fetchall()
    fails += [f"GL entry #{p['id']} has no audit event" for p in posts if p["id"] not in audited]
    return _result("ledger", len(posts), fails, "double entry balances, AR ties out, every post is audited")


def check_messages(conn) -> dict:
    fails = []
    audited = {
        r[0]
        for r in conn.execute(
            "SELECT json_extract(event_json, '$.email_id') FROM audit_log"
            " WHERE event_type IN ('email_sent','email_received')"
        )
    }
    emails = conn.execute("SELECT id FROM emails ORDER BY id").fetchall()
    fails += [f"email {e['id']} has no audit event" for e in emails if e["id"] not in audited]
    return _result("messages", len(emails), fails, "every email in or out is in the audit trail")


def check_memory(conn) -> dict:
    fails = []
    audited = {
        int(r[0])
        for r in conn.execute(
            "SELECT json_extract(event_json, '$.memory_id') FROM audit_log WHERE event_type='memory_write'"
        )
    }
    rows = conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
    for m in rows:
        if m["id"] not in audited:
            fails.append(f"memory #{m['id']} has no audit event")
        by = m["approved_by"]
        if by.startswith("outcome:"):
            continue  # learned from something the world did (payment, AP acceptance, missed forecast)
        d = conn.execute("SELECT approver, flag_json FROM decisions WHERE id=?", (m["source_decision_id"],)).fetchone()
        flagged_by = (loads(d["flag_json"]) or {}).get("by") if d else None
        if d is None or by not in (d["approver"], flagged_by):
            fails.append(f"memory #{m['id']} by {by!r} is not backed by that person's verdict on its source decision")
    return _result("memory", len(rows), fails, "memory comes only from human verdicts or observed outcomes")


def check_work_items(conn) -> dict:
    fails = []
    rows = conn.execute(
        "SELECT w.id, w.status, d.status ds FROM work_items w LEFT JOIN decisions d ON d.id=w.decision_id ORDER BY w.id"
    ).fetchall()
    expect = {"pending_approval": "waiting", "blocked": "blocked", "shadow": "shadow"}
    for r in rows:
        if r["ds"] is None:
            if r["status"] not in ("open", "void"):
                fails.append(f"work item #{r['id']} is {r['status']} with no decision")
        elif r["status"] != expect.get(r["ds"], "closed"):
            fails.append(f"work item #{r['id']} is {r['status']} but its decision is {r['ds']}")
    return _result("work_items", len(rows), fails, "every work item's status matches its decision")


CHECKS = (
    check_chain,
    check_provenance,
    check_policy_replay,
    check_guardrails,
    check_invoice_replay,
    check_ledger,
    check_messages,
    check_memory,
    check_work_items,
)


def verify(conn: sqlite3.Connection) -> dict:
    results = [c(conn) for c in CHECKS]
    return {"ok": all(r["ok"] for r in results), "head": audit.head(conn), "checks": results}


def verify_with_rerun(cfg, seed: int | None = None, days: int = 92, scale: int = 1) -> dict:
    """Full oracle run with memory, all checks, then an independent replay from the recordings."""
    from settle.engine import World

    world = World(cfg, connect(":memory:"), oracle=True)
    world.reset(memory=True, seed=seed, scale=scale)
    world.advance(days)
    report = verify(world.conn)
    replay_cfg = (
        dataclasses.replace(cfg, replay=True)
        if cfg.agent_kind == "claude" or cfg.moss_project_id or cfg.bitdeer_api_key
        else cfg
    )
    again = World(replay_cfg, connect(":memory:"), oracle=True)
    again.reset(memory=True, seed=seed, scale=scale)
    again.advance(days)
    head2 = audit.head(again.conn)
    report["checks"].append(
        _result(
            "determinism",
            1,
            [] if head2 == report["head"] else [f"replay head {head2[:16]} != {report['head'][:16]}"],
            "an independent replay reproduces the identical audit-chain head",
        )
    )
    report["ok"] = report["ok"] and head2 == report["head"]
    return report


def _print(report: dict) -> None:
    for c in report["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"{mark}  {c['name']:<15} checked {c['checked']:>6}  {c['what']}")
        for ex in c["examples"]:
            print(f"        - {ex}")
    print(f"audit head {report['head']}\nOVERALL: {'PASS' if report['ok'] else 'FAIL'}")


if __name__ == "__main__":
    from settle.config import load_config

    cfg = load_config()
    if "--heuristic" in sys.argv:
        cfg = dataclasses.replace(cfg, agent_kind="heuristic")
    if "--offline" in sys.argv:
        cfg = dataclasses.replace(
            cfg, agent_kind="heuristic", moss_project_id=None, moss_project_key=None, bitdeer_api_key=None
        )
    scale = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--scale=")), "1"))
    rep = verify_with_rerun(cfg, scale=scale)
    _print(rep)
    sys.exit(0 if rep["ok"] else 1)
