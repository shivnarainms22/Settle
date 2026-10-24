"""Bring-your-own-books: parsing at the boundary, and the full pipeline on real-format data."""

from pathlib import Path

import pytest

from settle import audit, verify
from settle.db import connect
from settle.engine import World
from settle.importer import ImportError_, parse_bank, parse_date, parse_invoices, parse_money

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
AR = (SAMPLES / "ar_aging.csv").read_text(encoding="utf-8")
BANK = (SAMPLES / "bank_statement.csv").read_text(encoding="utf-8")


@pytest.mark.parametrize("raw,cents", [("$1,234.56", 123456), ("1234.5", 123450), ("(45.00)", -4500), ("0", 0)])
def test_parse_money(raw, cents):
    assert parse_money(raw) == cents


@pytest.mark.parametrize("raw", ["", "abc", "$", "1.2.3"])
def test_parse_money_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_money(raw)


@pytest.mark.parametrize("raw", ["2026-10-05", "10/05/2026", "05-Oct-2026"])
def test_parse_date_formats(raw):
    assert parse_date(raw).isoformat() == "2026-10-05"


def test_quickbooks_headers_are_recognized():
    rows = parse_invoices(AR)
    assert len(rows) == 18 and rows[10]["balance"] == 552500 and rows[1]["po_number"] == "HF-2231"
    assert len(parse_bank(BANK)) == 7  # the bank fee (a debit) is not a customer payment


def test_missing_columns_are_reported_with_what_was_found():
    with pytest.raises(ImportError_, match="missing column.*due_on.*found"):
        parse_invoices("Num,Customer,Amount,Date\n1,A,10,2026-01-01\n")


def test_every_row_problem_is_reported_at_once():
    bad = (
        "Num,Customer,Amount,Date,Due Date\n"
        "1,A,10,2026-01-01,2026-02-01\n"
        "1,A,10,2026-01-01,2026-02-01\n"  # duplicate
        "2,B,-5,2026-01-01,2026-02-01\n"  # negative
        "3,C,10,2026-03-01,2026-02-01\n"  # due before issue
        "4,D,ten,2026-01-01,2026-02-01\n"
    )  # not money
    with pytest.raises(ImportError_) as exc:
        parse_invoices(bad)
    assert len(exc.value.errors) == 4 and all("line" in e for e in exc.value.errors)


def offline(cfg):
    w = World(cfg, connect(":memory:"))
    w.load_import(AR, BANK)
    w.advance(400)
    return w


def test_full_pipeline_on_real_format_books(cfg):
    w = offline(cfg)
    rules = [
        r[0]
        for r in w.conn.execute(
            "SELECT COALESCE(json_extract(a.output_json,'$.rule'), a.component) FROM decisions d JOIN work_items w"
            " ON w.id=d.work_item_id JOIN agent_runs a ON a.decision_id=d.id WHERE w.kind='bank_line' ORDER BY d.id"
        )
    ]
    assert rules[:3] == ["remittance_exact", "payer_invoice_set", "remittance_short_pay"]
    assert rules[6] == "remittance_exact"  # matched by the customer's PO number
    assert (
        w.conn.execute(
            "SELECT action FROM decisions d JOIN work_items w ON w.id=d.work_item_id WHERE w.kind='deduction'"
        ).fetchone()[0]
        == "request_balance"
    )
    pending = {
        r[0]
        for r in w.conn.execute(
            "SELECT w.ref FROM decisions d JOIN work_items w ON w.id=d.work_item_id"
            " WHERE w.kind='bank_line' AND d.tier=2"
        )
    }
    assert pending == {"B-4", "B-6"}  # the unknown alias and the anonymous deposit need a person
    assert verify.verify(w.conn)["ok"]
    assert w.state()["mode"] == "import"


def test_import_is_deterministic(cfg):
    assert audit.head(offline(cfg).conn) == audit.head(offline(cfg).conn)


def test_import_api(client):
    samples = client.get("/api/import/samples").json()
    bad = client.post("/api/import", json={"invoices_csv": "Num,Customer\n1,A\n"})
    assert bad.status_code == 422 and bad.json()["detail"]["errors"]
    assert client.get("/api/state").json()["mode"] == "simulation"  # a bad file never destroys the current run
    ok = client.post(
        "/api/import", json={"invoices_csv": samples["ar_aging.csv"], "bank_csv": samples["bank_statement.csv"]}
    )
    assert ok.status_code == 200 and ok.json()["summary"]["invoices"] == 18
    assert ok.json()["state"]["mode"] == "import"
    client.post("/api/sim/advance", json={"days": 30})
    assert client.get("/api/verify").json()["ok"] is True
