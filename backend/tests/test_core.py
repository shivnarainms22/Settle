import json

from settle import audit, cash_app, ledger
from settle.db import connect, create_schema
from tests.conftest import make_world


def q(w, sql, *args):
    return [dict(r) for r in w.conn.execute(sql, args)]


# ---- audit chain


def test_audit_chain_verifies_and_detects_tampering():
    conn = connect(":memory:")
    create_schema(conn)
    for i in range(5):
        audit.append(conn, "evt", {"n": i, "b": {"z": 1, "a": 2}})
    result = audit.verify(conn)
    assert result["ok"] and result["length"] == 5 and result["head"] == audit.head(conn)
    conn.execute("UPDATE audit_log SET event_json=? WHERE id=3", ('{"n":99}',))
    result = audit.verify(conn)
    assert result["ok"] is False and result["broken_at"] == 3


def test_empty_audit_chain_is_ok():
    conn = connect(":memory:")
    create_schema(conn)
    assert audit.verify(conn)["ok"] is True


# ---- ledger


def test_ledger_rejects_nonpositive_and_unknown_accounts():
    conn = connect(":memory:")
    create_schema(conn)
    import pytest

    with pytest.raises(ValueError):
        ledger.post(conn, "2026-07-01", ledger.CASH, ledger.AR, 0, "x", "1", "m")
    with pytest.raises(ValueError):
        ledger.post(conn, "2026-07-01", "Petty Cash", ledger.AR, 10, "x", "1", "m")


def test_ledger_balances_after_full_run(cfg):
    w = make_world(cfg, oracle=True)
    w.advance(92)
    tb = {a["account"]: a for a in ledger.trial_balance(w.conn)}
    assert sum(a["debit_cents"] for a in tb.values()) == sum(a["credit_cents"] for a in tb.values())
    open_ar = ledger.open_ar_cents(w.conn, "2026-10-01")
    assert tb[ledger.AR]["balance_cents"] == open_ar  # subledger ties to GL


# ---- cash application


def test_name_normalization():
    assert cash_app.normalize_name("OSTRANDER METALWORKS INC") == cash_app.normalize_name("Ostrander Metalworks")
    assert cash_app.invoice_refs("PAYMENT INV-1088 / inv 1090") == ["INV-1088", "INV-1090"]


def test_combined_payment_split_across_three_invoices(world):
    world.advance(92)
    combined = q(
        world,
        "SELECT d.* FROM decisions d JOIN work_items w ON w.id=d.work_item_id WHERE w.kind='bank_line'"
        " AND w.gt_json LIKE '%\"combined\"%'",
    )
    assert combined, "expected Ostrander combined payments"
    for d in combined:
        assert d["source"] == "deterministic" and d["correct"] == 1
        # a unique run applies itself; when two runs fit the amount it is proposed for a human to confirm
        assert d["tier"] == 0 or (d["tier"] == 2 and "runs of consecutive open invoices" in d["rationale"])
    assert any(d["tier"] == 2 for d in combined), "seed 7 has one genuinely ambiguous Ostrander wire (Aug 13)"


def test_alias_payment_needs_human_first_then_auto_with_memory(cfg):
    w = make_world(cfg, memory=True, oracle=True)
    w.advance(92)
    alias = q(
        w,
        "SELECT d.* FROM decisions d JOIN work_items w ON w.id=d.work_item_id WHERE w.kind='bank_line'"
        " AND w.gt_json LIKE '%\"alias\"%' ORDER BY d.id",
    )
    assert len(alias) >= 3
    assert alias[0]["tier"] == 2
    assert all(d["tier"] == 0 and d["source"] == "deterministic" for d in alias[1:])
    assert "MRWBRDG SHARED SVCS AP" in w.memory.profile("C-03")["aliases"]


def test_alias_payment_always_needs_human_without_memory(cfg):
    w = make_world(cfg, memory=False, oracle=True)
    w.advance(92)
    tiers = [
        d["tier"]
        for d in q(
            w,
            "SELECT d.tier FROM decisions d JOIN work_items w ON w.id=d.work_item_id WHERE"
            " w.kind='bank_line' AND w.gt_json LIKE '%\"alias\"%'",
        )
    ]
    assert tiers and all(t == 2 for t in tiers)


def test_short_pay_opens_deduction_and_requests_balance(world):
    world.advance(92)
    ded = q(world, "SELECT d.* FROM decisions d JOIN work_items w ON w.id=d.work_item_id WHERE w.kind='deduction'")
    assert ded and all(d["action"] == "request_balance" and d["tier"] == 1 for d in ded)
    assert {d["customer_id"] for d in ded} == {"C-09"}  # plan installments are not deductions
    # the balance request led to payment in full
    inv = ded[0]["args_json"].split('"invoice_id":"')[1].split('"')[0]
    assert q(world, "SELECT status FROM invoices WHERE id=?", inv)[0]["status"] == "paid"


# ---- scenarios through the engine


def test_missing_po_rejection_is_reissued_with_crm_po(world):
    world.advance(20)
    d = q(world, "SELECT * FROM decisions WHERE action='reissue_invoice' ORDER BY id LIMIT 1")[0]
    assert d["tier"] == 1 and d["customer_id"] == "C-02"
    note = q(
        world, "SELECT text FROM crm_notes WHERE invoice_id=?", d["args_json"].split('"invoice_id":"')[1].split('"')[0]
    )[0]["text"]
    assert d["args_json"].split('"po_number":"')[1].split('"')[0] in note


def test_dispute_credit_memo_waits_for_approval_then_posts_gl(world):
    world.advance(30)
    pending = q(world, "SELECT * FROM decisions WHERE action='propose_credit_memo'")
    assert pending and pending[0]["status"] == "pending_approval" and pending[0]["amount_cents"] == 320_000
    world.resolve(pending[0]["id"], "approve", "dana")
    gl = q(world, "SELECT * FROM gl_entries WHERE decision_id=?", pending[0]["id"])
    assert gl and gl[0]["debit_acct"] == ledger.RETURNS and gl[0]["amount_cents"] == 320_000
    mem = q(world, "SELECT * FROM memories WHERE source_decision_id=?", pending[0]["id"])
    assert mem and mem[0]["approved_by"] == "dana"


def test_fraud_emails_are_blocked_never_executed(cfg):
    w = make_world(cfg, oracle=True)
    w.advance(92)
    blocked = q(w, "SELECT * FROM decisions WHERE tier=3")
    assert len(blocked) == 2 and all(d["status"] == "blocked" for d in blocked)
    assert not q(w, "SELECT * FROM gl_entries WHERE decision_id IN (SELECT id FROM decisions WHERE tier=3)")


def test_tier3_cannot_be_approved(cfg):
    import pytest

    w = make_world(cfg)
    w.advance(25)
    d = q(w, "SELECT id FROM decisions WHERE tier=3")[0]
    with pytest.raises(ValueError):
        w.resolve(d["id"], "approve")


def test_edit_validation_rejects_hallucinated_invoice(world):
    import pytest

    world.advance(30)
    d = q(world, "SELECT id FROM decisions WHERE status='pending_approval' LIMIT 1")[0]
    with pytest.raises(ValueError, match="does not exist"):
        world.resolve(d["id"], "edit", "ctrl", "send_reminder", {"invoice_id": "INV-9999", "tone": "firm"})


def test_validation_flags_nonexistent_evidence(world):
    from settle.models import Decision

    d = Decision("send_reminder", {"invoice_id": "INV-1001"}, "r", ["email:E-999999", "crm:N-nope"], [12345])
    errs = world.validate(d, None)
    assert len(errs) == 4 and any("already paid" in e for e in errs)  # INV-1001 was paid before deployment


def test_reliable_late_payer_playbook_fires_then_drift_suspends_it(cfg):
    w = make_world(cfg, oracle=True)
    w.advance(92)
    pb = q(w, "SELECT * FROM playbooks WHERE customer_id='C-01'")
    assert pb and pb[0]["times_fired"] > 0
    # Pellucid's AP migration (persona drift) makes a held invoice miss its forecast window: the playbook is suspended
    assert pb[0]["status"] == "needs_review"
    ev = q(w, "SELECT * FROM audit_log WHERE event_type='playbook_needs_review'")
    assert len(ev) == 1 and "unpaid after" in ev[0]["event_json"]
    assert not w.memory.profile("C-01")["reliable_late_payer"]
    assert not q(w, "SELECT * FROM decisions WHERE customer_id='C-01' AND action='escalate' AND status!='edited'")


def test_memory_off_writes_nothing(cfg):
    w = make_world(cfg, memory=False, oracle=True)
    w.advance(92)
    assert q(w, "SELECT COUNT(*) n FROM memories")[0]["n"] == 0
    assert q(w, "SELECT COUNT(*) n FROM playbooks")[0]["n"] == 0


def test_ablation_memory_reduces_human_touches_and_agent_calls(cfg):
    from settle.eval import run_ablation

    res = run_ablation(cfg)
    on, off = res["runs"]
    assert on["memory"] and not off["memory"]
    assert on["months"][0]["human_touches"] == off["months"][0]["human_touches"]  # nothing learned yet in month 1
    assert on["totals"]["human_touches"] < off["totals"]["human_touches"]
    assert on["totals"]["agent_calls"] < off["totals"]["agent_calls"]
    assert on["totals"]["unsafe_actions"] == off["totals"]["unsafe_actions"] == 0
    assert (cfg.cache_dir / "eval_latest.json").exists()


def test_deterministic_runs(cfg):
    a, b = make_world(cfg, oracle=True), make_world(cfg, oracle=True)
    a.advance(40)
    b.advance(40)
    rows = "SELECT action, args_json, tier FROM decisions ORDER BY id"
    assert q(a, rows) == q(b, rows)


def test_stall_is_challenged_genuine_claim_is_credited(cfg):
    w = make_world(cfg, oracle=True)
    w.advance(92)
    specs = {r["customer_id"]: json.loads(r["spec_json"]) for r in w.conn.execute("SELECT * FROM personas")}
    stall, genuine = specs["C-07"]["stall_invoice"], specs["C-04"]["dispute_invoice"]
    stall_d = q(
        w,
        "SELECT d.* FROM decisions d JOIN decision_invoices di ON di.decision_id=d.id"
        " WHERE di.invoice_id=? AND d.trigger='dispute'",
        stall,
    )
    assert stall_d and stall_d[0]["action"] == "request_dispute_evidence" and stall_d[0]["tier"] == 1
    assert "delivery:DL-" in stall_d[0]["evidence_json"]  # the decision cites the proof of delivery
    assert q(w, "SELECT status FROM invoices WHERE id=?", stall)[0]["status"] == "paid"  # the stall collapsed
    credits = q(w, "SELECT invoice_id, amount_cents FROM gl_entries WHERE debit_acct='Sales Returns & Allowances'")
    assert credits == [{"invoice_id": genuine, "amount_cents": 320_000}]  # only the genuine claim was credited


def test_working_capital_metrics(cfg):
    from settle.eval import run_ablation

    on, off = run_ablation(cfg)["runs"]
    assert on["totals"]["credit_leakage_cents"] == 0
    assert on["totals"]["touchless_cash_rate"] > off["totals"]["touchless_cash_rate"]
    assert on["totals"]["dispute_cycle_days"] is not None
