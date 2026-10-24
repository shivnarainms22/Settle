"""Regression tests for the traceability/determinism review findings."""

import dataclasses
import json
from types import SimpleNamespace as NS

import pytest

from settle import audit
from settle.bitdeer import parse_label
from settle.engine import NotFound
from settle.models import Decision
from tests.conftest import make_world


def rows(w, sql, *args):
    return [dict(r) for r in w.conn.execute(sql, args)]


class GarbageClaude:
    """Returns schema-valid but semantically malformed args (amount as text)."""

    def __init__(self):
        self.calls = 0
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls += 1
        raw = {
            "action": "propose_credit_memo",
            "args_json": json.dumps({"invoice_id": "INV-1080", "amount_cents": "about 500"}),
            "rationale": "x",
            "evidence": [],
            "memory_ids": [],
            "confidence": 0.9,
            "trigger": "dispute",
        }
        return NS(
            content=[NS(type="tool_use", name="submit_decision", input=raw, id="t")],
            stop_reason="tool_use",
            usage=NS(input_tokens=1, output_tokens=1),
        )


def test_malformed_llm_output_falls_back_and_never_wedges_the_sim(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    ccfg = dataclasses.replace(cfg, agent_kind="claude")
    live = make_world(ccfg, oracle=True)
    live.agent.client = GarbageClaude()
    live.advance(20)  # must not raise
    runs = rows(live, "SELECT replay, config_json FROM agent_runs WHERE component='heuristic'")
    assert runs and all(r["replay"] == "error" for r in runs)
    assert "malformed args" in runs[0]["config_json"]
    # the fallback itself was recorded, so a replay reproduces the run exactly
    replay = make_world(dataclasses.replace(ccfg, replay=True), oracle=True)
    replay.advance(20)
    assert audit.head(replay.conn) == audit.head(live.conn)


def test_policy_never_crashes_on_malformed_decision(world):
    world.advance(14)
    item = world._new_item(world.today, "overdue", "INV-1080", "C-04", "x", {})
    bad = Decision("propose_payment_plan", {"invoice_id": "INV-1080", "installments": [{"date": "x"}]}, "r")
    did = world._route(item, bad, "{}", {})
    d = rows(world, "SELECT * FROM decisions WHERE id=?", did)[0]
    assert d["tier"] == 2 and "malformed args" in d["tier_reasons_json"]
    with pytest.raises(ValueError, match="cannot approve"):
        world.resolve(did, "approve")


def test_failed_resolve_leaves_no_partial_state(world):
    world.advance(30)
    pend = rows(world, "SELECT * FROM decisions WHERE status='pending_approval' ORDER BY id")[0]
    before = audit.verify(world.conn)["length"]
    with pytest.raises(ValueError):
        world.resolve(
            pend["id"],
            "edit",
            "dana",
            "propose_payment_plan",
            {"invoice_id": "INV-1080", "installments": [{"amount_cents": 1}]},
        )
    assert rows(world, "SELECT status FROM decisions WHERE id=?", pend["id"])[0]["status"] == "pending_approval"
    assert audit.verify(world.conn)["length"] == before
    with pytest.raises(NotFound):
        world.resolve(987654, "approve")


def test_stale_approval_is_refused_and_sends_nothing(world):
    world.advance(30)
    pend = rows(world, "SELECT * FROM decisions WHERE status='pending_approval' AND action='propose_credit_memo'")[0]
    inv = json.loads(pend["args_json"])["invoice_id"]
    world.conn.execute("UPDATE invoices SET status='paid', balance_cents=0 WHERE id=?", (inv,))
    emails_before = rows(world, "SELECT COUNT(*) n FROM emails")[0]["n"]
    with pytest.raises(ValueError, match="stale"):
        world.resolve(pend["id"], "approve", "dana")
    assert rows(world, "SELECT COUNT(*) n FROM emails")[0]["n"] == emails_before


@pytest.mark.parametrize(
    "allocs,customer,msg",
    [
        (
            [{"invoice_id": "INV-1080", "amount_cents": 100}, {"invoice_id": "INV-1080", "amount_cents": 100}],
            None,
            "repeat",
        ),
        ([{"invoice_id": "INV-1080", "amount_cents": 100}], "C-99", "does not exist"),
        ([{"invoice_id": "INV-1080", "amount_cents": 100}], "C-02", "not C-02"),
    ],
)
def test_apply_payment_allocation_integrity(world, allocs, customer, msg):
    world.advance(20)
    line = rows(world, "SELECT id FROM bank_lines WHERE matched=1 LIMIT 1")[0]
    world.conn.execute("UPDATE bank_lines SET matched=0 WHERE id=?", (line["id"],))
    args = {"bank_line_id": line["id"], "allocations": allocs}
    if customer:
        args["customer_id"] = customer
    errs = world.validate(Decision("apply_payment", args, "r"), None)
    assert any(msg in e for e in errs), errs


def test_disabled_playbook_is_not_reproposed(cfg):
    w = make_world(cfg)
    w.advance(33)
    pb = rows(w, "SELECT * FROM playbooks ORDER BY id")[0]
    w.memory.set_playbook_status(pb["id"], "disabled", "dana")
    w.advance(30)
    same = rows(w, "SELECT * FROM playbooks WHERE customer_id=? AND action=?", pb["customer_id"], pb["action"])
    assert len(same) == 1 and same[0]["status"] == "disabled"


def test_label_parsing_is_exact():
    assert parse_label("Label: ACK.") == "ack"
    assert parse_label("not an ack") == "other"
    assert parse_label("ACK is likely") == "other"


def test_flag_is_persisted_on_the_decision(cfg):
    w = make_world(cfg, oracle=True)
    w.advance(10)
    d = rows(w, "SELECT id FROM decisions WHERE status='executed' ORDER BY id LIMIT 1")[0]
    w.flag_decision(d["id"], "wrong call", "dana", "send_reminder")
    flag = json.loads(rows(w, "SELECT flag_json FROM decisions WHERE id=?", d["id"])[0]["flag_json"])
    assert flag["by"] == "dana" and flag["correct_action"] == "send_reminder"
    with pytest.raises(NotFound):
        w.flag_decision(999999, "x")


def test_tier3_work_items_are_closed_as_blocked(cfg):
    w = make_world(cfg)
    w.advance(25)
    items = rows(w, "SELECT w.status FROM work_items w JOIN decisions d ON d.id=w.decision_id WHERE d.tier=3")
    assert items and all(i["status"] == "blocked" for i in items)


def test_agent_steps_are_stored_untruncated(tmp_path):
    from settle.agent import ClaudeAgent
    from settle.recorder import Recorder
    from tests.test_claude_agent import SUBMIT, block_tool, ctx, resp

    big = [
        {"id": f"INV-{i}", "customer_id": "C-03", "balance_cents": 10000, "description": "x" * 100} for i in range(40)
    ]
    c = ctx()
    c.find_open_invoices = lambda customer_id=None, amount_cents=None: big

    class Client:
        def __init__(self):
            self.r = [
                resp([block_tool("find_open_invoices", {"customer_id": None, "amount_cents": None})]),
                resp([block_tool("submit_decision", SUBMIT, "t2")]),
            ]
            self.beta = NS(messages=NS(create=lambda **kw: self.r.pop(0)))

    agent = ClaudeAgent("claude-opus-5-5", lambda *a: None, Recorder(tmp_path / "r.json"), client=Client())
    d = agent.decide(c)
    assert len(d.provenance["steps"][0]["output"]) > 2000 and json.loads(d.provenance["steps"][0]["output"]) == big
