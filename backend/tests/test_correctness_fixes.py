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
