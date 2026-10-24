"""Regression tests for import atomicity, ambiguous cash matches, imported partial balances, plan forecasts,
run-relative dates and the live stream across resets."""

import json
from pathlib import Path

import pytest

from settle import cash_app, forecast, importer, ledger, verify
from settle.db import connect, create_schema, dumps
from settle.engine import World
from settle.importer import ImportError_, parse_money
from settle.memory import FtsIndex, MemoryStore
from tests.conftest import auth_headers, make_world

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
AR = (SAMPLES / "ar_aging.csv").read_text(encoding="utf-8")
BANK = (SAMPLES / "bank_statement.csv").read_text(encoding="utf-8")


def _invoice_count(w: World) -> int:
    return w.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]


# ---- a failed import must leave the current run intact ---------------------------------------------------------


def test_oversized_amount_is_rejected_at_parse_time():
    with pytest.raises(ValueError, match="too large"):
        parse_money("99999999999999999999.00")


def test_oversized_amount_in_a_file_keeps_the_current_run(cfg):
    w = make_world(cfg)
    before, head = _invoice_count(w), w.state()["audit_head"]
    bad = AR.replace("5,525.00", "99999999999999999999.00", 1)
    assert bad != AR
    with pytest.raises(ImportError_):
        w.load_import(bad, BANK)
    assert _invoice_count(w) == before and w.state()["audit_head"] == head


def test_any_failure_while_loading_keeps_the_current_run(cfg, monkeypatch):
    """Even a failure that parsing can't foresee (here: mid-way through loading) must not destroy the run."""
    w = make_world(cfg)
    before, head = _invoice_count(w), w.state()["audit_head"]
    real = importer.seed_import

    def explode(conn, *a, **k):
        real(conn, *a, **k)
        raise OverflowError("Python int too large to convert to SQLite INTEGER")

    monkeypatch.setattr(importer, "seed_import", explode)
    with pytest.raises(OverflowError):
        w.load_import(AR, BANK)
    assert _invoice_count(w) == before and w.state()["audit_head"] == head
    assert verify.verify(w.conn)["ok"] is True
    w.step()  # and the run keeps working


def test_import_swap_works_on_a_file_database_in_wal_mode(cfg):
    w = World(cfg, connect(cfg.db_path))  # the production path: a file database in WAL mode
    w.reset()
    w.load_import(AR, BANK)
    assert w.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert w.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    w.step()
    reopened = connect(cfg.db_path)
    assert reopened.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 18


def test_successful_import_still_replaces_the_run(cfg):
    w = make_world(cfg)
    w.load_import(AR, BANK)
    assert _invoice_count(w) == 18 and w.state()["mode"] == "import"
    assert verify.verify(w.conn)["ok"] is True


# ---- ambiguous cash must go to review, not be applied at confidence 1.0 -----------------------------------------


def _cash_conn(amounts: list[int]):
    conn = connect(":memory:")
    create_schema(conn)
    conn.execute("INSERT INTO customers VALUES('C-1','Acme Corp','standard','acme.com','ap@acme.com','****1','Pat')")
    conn.execute("INSERT INTO profiles(customer_id) VALUES('C-1')")
    for i, amt in enumerate(amounts):
        conn.execute(
            "INSERT INTO invoices(id, customer_id, po_number, amount_cents, balance_cents, issued_on, due_on, status,"
            " description) VALUES(?,?,?,?,?,?,?,?,?)",
            (f"INV-{i + 1}", "C-1", None, amt, amt, "2026-07-01", f"2026-07-{10 + i}", "open", "x"),
        )
    return conn, MemoryStore(conn, True, FtsIndex(conn))


def _line(conn, amount: int):
    conn.execute("INSERT INTO bank_lines VALUES('B-1',?,?,?,?,0)", (amount, "ACME CORP", "", "2026-07-20"))
    return conn.execute("SELECT * FROM bank_lines WHERE id='B-1'").fetchone()


def test_two_consecutive_runs_matching_is_ambiguous_and_goes_to_a_human():
    from settle.policy import PolicyContext, assign_tier

    conn, mem = _cash_conn([10_000, 10_000, 10_000])  # $200 = INV-1+INV-2 or INV-2+INV-3
    decision, cust = cash_app.match(conn, _line(conn, 20_000), mem)
    assert cust == "C-1" and decision is not None
    assert decision.confidence < 1.0 and "2 runs" in decision.rationale
    assert [a["invoice_id"] for a in decision.args["allocations"]] == ["INV-1", "INV-2"]  # oldest first, proposed
    assert decision.provenance["candidates"] == [["INV-1", "INV-2"], ["INV-2", "INV-3"]]
    tier, reasons = assign_tier(
        decision, PolicyContext(customer_tier="standard", verified_domain="acme.com", bank_account_on_file="****1")
    )
    assert tier == 2, reasons


def test_a_unique_consecutive_run_is_still_matched():
    conn, mem = _cash_conn([10_000, 25_000, 40_000])
    decision, _ = cash_app.match(conn, _line(conn, 35_000), mem)
    assert decision is not None and decision.confidence == 1.0
    assert [a["invoice_id"] for a in decision.args["allocations"]] == ["INV-1", "INV-2"]


# ---- imported invoices issued after the start keep the ledger tied out -----------------------------------------


def test_partially_paid_future_invoice_keeps_ar_equal_to_balances(cfg):
    w = World(cfg, connect(":memory:"))
    w.reset()
    invoices = [
        {
            "invoice_id": "A-1",
            "customer": "Acme",
            "email": "ap@acme.com",
            "po_number": None,
            "amount": 50_000,
            "balance": 50_000,
            "issued_on": _d("2026-10-01"),
            "due_on": _d("2026-10-31"),
            "description": "a",
        },
        {
            "invoice_id": "A-2",
            "customer": "Acme",
            "email": "ap@acme.com",
            "po_number": None,
            "amount": 10_000,
            "balance": 6_000,
            "issued_on": _d("2026-10-05"),
            "due_on": _d("2026-11-04"),
            "description": "b",
        },
    ]
    bank = [{"date": _d("2026-10-02"), "amount": 1_000, "payer": "Someone Else", "remittance": ""}]
    staging_ok = w.load_import_parsed(invoices, bank)
    assert staging_ok["invoices"] == 2
    while w.today <= "2026-10-06":
        w.step()
    assert w.conn.execute("SELECT status FROM invoices WHERE id='A-2'").fetchone()[0] != "scheduled"
    ar = next(a for a in ledger.trial_balance(w.conn) if a["account"] == ledger.AR)
    open_balances = w.conn.execute(
        "SELECT SUM(balance_cents) FROM invoices WHERE status NOT IN ('scheduled')"
    ).fetchone()[0]
    assert ar["balance_cents"] == open_balances
    ledger_check = next(c for c in verify.verify(w.conn)["checks"] if c["name"] == "ledger")
    assert ledger_check["ok"], ledger_check


def _d(s):
    from datetime import date

    return date.fromisoformat(s)
