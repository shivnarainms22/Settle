"""General ledger postings and AR metrics."""

import sqlite3
from datetime import date, timedelta

from settle import audit

CASH = "Cash"
AR = "Accounts Receivable"
REVENUE = "Revenue"
RETURNS = "Sales Returns & Allowances"
BAD_DEBT = "Bad Debt Expense"
UNAPPLIED = "Unapplied Cash"

ACCOUNTS = [CASH, AR, REVENUE, RETURNS, BAD_DEBT, UNAPPLIED]
DEBIT_NORMAL = {CASH, AR, RETURNS, BAD_DEBT}


def post(
    conn: sqlite3.Connection,
    sim_date: str,
    debit: str,
    credit: str,
    amount_cents: int,
    ref_type: str,
    ref_id: str,
    memo: str,
    decision_id: int | None = None,
    audited: bool = True,
    invoice_id: str | None = None,
) -> int:
    if amount_cents <= 0:
        raise ValueError(f"GL amount must be positive, got {amount_cents}")
    if debit not in ACCOUNTS or credit not in ACCOUNTS:
        raise ValueError(f"unknown account in {debit!r} / {credit!r}")
    cur = conn.execute(
        "INSERT INTO gl_entries(sim_date, debit_acct, credit_acct, amount_cents, ref_type, ref_id, memo, decision_id,"
        " invoice_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            sim_date,
            debit,
            credit,
            amount_cents,
            ref_type,
            ref_id,
            memo,
            decision_id,
            invoice_id or (ref_id if ref_type in ("invoice", "credit_memo") else None),
        ),
    )
    if audited:
        entity = {"invoice": "invoice", "credit_memo": "invoice", "bank_line": "bank"}.get(ref_type, ref_type)
        audit.append(
            conn,
            "gl_post",
            {
                "gl_id": cur.lastrowid,
                "debit": debit,
                "credit": credit,
                "amount_cents": amount_cents,
                "ref": f"{ref_type}:{ref_id}",
                "memo": memo,
                "decision_id": decision_id,
            },
            refs=[
                f"gl:{cur.lastrowid}",
                f"{entity}:{ref_id}",
                f"decision:{decision_id}" if decision_id else None,
                f"invoice:{invoice_id}" if invoice_id else None,
            ],
            sim_date=sim_date,
        )
    return cur.lastrowid


def trial_balance(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for acct in ACCOUNTS:
        debit = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM gl_entries WHERE debit_acct=?", (acct,)
        ).fetchone()[0]
        credit = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM gl_entries WHERE credit_acct=?", (acct,)
        ).fetchone()[0]
        balance = debit - credit if acct in DEBIT_NORMAL else credit - debit
        out.append({"account": acct, "debit_cents": debit, "credit_cents": credit, "balance_cents": balance})
    return out


def open_ar_cents(conn: sqlite3.Connection, sim_date: str) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(balance_cents),0) FROM invoices WHERE status NOT IN ('scheduled','paid')"
        " AND issued_on <= ?",
        (sim_date,),
    ).fetchone()[0]


def dso(conn: sqlite3.Connection, sim_date: str, window_days: int = 90) -> float:
    """Days sales outstanding = open AR / credit sales over the trailing window * window."""
    start = (date.fromisoformat(sim_date) - timedelta(days=window_days)).isoformat()
    sales = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM invoices WHERE issued_on > ? AND issued_on <= ?", (start, sim_date)
    ).fetchone()[0]
    if sales == 0:
        return 0.0
    return round(open_ar_cents(conn, sim_date) / sales * window_days, 1)
