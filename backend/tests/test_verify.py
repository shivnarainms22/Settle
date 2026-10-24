"""The verifier must pass on an honest run and catch each kind of tampering independently."""

import json

import pytest

from settle import verify
from tests.conftest import make_world


@pytest.fixture
def run(cfg):
    w = make_world(cfg, oracle=True)
    w.advance(92)
    return w


def failed(w) -> set[str]:
    return {c["name"] for c in verify.verify(w.conn)["checks"] if not c["ok"]}


def one(w, sql, *args):
    return dict(w.conn.execute(sql, args).fetchone())


def test_honest_run_passes_every_check(run):
    rep = verify.verify(run.conn)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    assert {c["name"] for c in rep["checks"]} >= {
        "chain",
        "provenance",
        "policy_replay",
        "guardrails",
        "invoice_replay",
        "ledger",
        "messages",
        "memory",
        "work_items",
    }


def test_unaudited_invoice_change_is_caught(run):
    inv = one(run, "SELECT id FROM invoices WHERE status='paid' AND issued_on>='2026-07-01' LIMIT 1")["id"]
    run.conn.execute("UPDATE invoices SET status='open', balance_cents=100 WHERE id=?", (inv,))
    assert {"invoice_replay", "ledger"} <= failed(run)


def test_tampered_tier_is_caught_by_policy_replay(run):
    d = one(run, "SELECT id FROM decisions WHERE tier=2 AND action='propose_credit_memo' LIMIT 1")
    run.conn.execute("UPDATE decisions SET tier=0 WHERE id=?", (d["id"],))
    assert "policy_replay" in failed(run)


def test_executed_blocked_action_is_caught(run):
    d = one(run, "SELECT id FROM decisions WHERE tier=3 LIMIT 1")
    run.conn.execute("UPDATE decisions SET status='executed' WHERE id=?", (d["id"],))
    assert "guardrails" in failed(run)


def test_tampered_provenance_input_is_caught(run):
    r = one(run, "SELECT id, input_json FROM agent_runs WHERE component='heuristic' LIMIT 1")
    forged = json.loads(r["input_json"])
    forged["today"] = "1999-01-01"
    run.conn.execute("UPDATE agent_runs SET input_json=? WHERE id=?", (json.dumps(forged), r["id"]))
    assert "provenance" in failed(run)


def test_memory_without_a_human_or_outcome_is_caught(run):
    d = one(run, "SELECT id FROM decisions WHERE approver IS NULL LIMIT 1")
    run.conn.execute(
        "INSERT INTO memories(type, customer_id, content, approved_by, source_decision_id, created_at)"
        " VALUES('episodic','C-01','agent guessed this','heuristic',?, '2026-09-30')",
        (d["id"],),
    )
    assert "memory" in failed(run)


def test_forged_audit_event_is_caught(run):
    e = one(run, "SELECT id, event_json FROM audit_log WHERE event_type='gl_post' LIMIT 1")
    forged = json.loads(e["event_json"])
    forged["amount_cents"] += 1  # someone quietly edits a posted amount
    run.conn.execute("UPDATE audit_log SET event_json=? WHERE id=?", (json.dumps(forged), e["id"]))
    assert "chain" in failed(run)


def test_unaudited_email_is_caught(run):
    run.conn.execute(
        "INSERT INTO emails VALUES('E-99999','T-x','C-01',NULL,'out','ar@northwind-robotics.com','s','b','2026-09-30')"
    )
    assert "messages" in failed(run)


def test_scaled_world_verifies(cfg):
    w = make_world(cfg, oracle=True)
    w.reset(memory=True, scale=3)
    assert w.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 36
    w.advance(92)
    rep = verify.verify(w.conn)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    # every clone got its own fraud attempt, all blocked
    assert w.conn.execute("SELECT COUNT(*) FROM decisions WHERE tier=3").fetchone()[0] == 6
