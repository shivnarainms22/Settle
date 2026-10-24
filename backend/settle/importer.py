"""Bring your own books: load a real AR aging export and a bank statement, then run the same agent, policy engine,
audit trail and verifier on them. There are no personas and no ground truth: nothing is simulated except time.

Accepted CSV headers (case-insensitive; common QuickBooks / Xero / NetSuite export names are recognized):
  invoices: invoice id, customer, amount, issue date, due date, [open balance], [PO], [customer email], [description]
  bank:     date, amount, payer / description, [memo / remittance / reference]
Money accepts "$1,234.56", "1234.56", "(12.00)"; dates accept YYYY-MM-DD, MM/DD/YYYY, DD-Mon-YYYY.
"""

import csv
import io
import re
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from settle import ledger
from settle.db import dumps, set_meta

MAX_BYTES = 5_000_000
MAX_ROWS = 20_000

INVOICE_COLUMNS = {
    "invoice_id": ("invoice_id", "invoice", "invoice #", "invoice no", "invoice number", "num", "number", "doc number"),
    "customer": ("customer", "customer name", "name", "client", "bill to"),
    "amount": ("amount", "total", "invoice amount", "original amount"),
    "balance": ("open balance", "balance", "amount due", "outstanding", "balance due"),
    "issued_on": ("issued_on", "date", "invoice date", "issue date", "txn date"),
    "due_on": ("due_on", "due date", "due"),
    "po_number": ("po", "po number", "p.o. number", "purchase order", "customer po"),
    "email": ("email", "customer email", "billing email", "ap email"),
    "description": ("description", "memo", "item", "product/service"),
}
BANK_COLUMNS = {
    "date": ("date", "posted date", "transaction date", "value date"),
    "amount": ("amount", "credit", "deposit", "amount received"),
    "payer": ("payer", "payer name", "description", "name", "counterparty", "originator"),
    "remittance": ("remittance", "memo", "reference", "remittance info", "details", "narrative"),
}


class ImportError_(ValueError):
    """Raised with every problem found, so a user can fix the file in one pass."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:20]) + (f" (+{len(errors) - 20} more)" if len(errors) > 20 else ""))
        self.errors = errors


def parse_money(raw: str) -> int:
    text = (raw or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        cents = int((Decimal(text) * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {raw!r}") from exc
    return -cents if negative else cents


def parse_date(raw: str) -> date:
    text = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {raw!r}")


def _rows(text: str, columns: dict, required: tuple[str, ...], what: str) -> list[dict]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ImportError_([f"{what}: file is larger than {MAX_BYTES // 1_000_000} MB"])
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ImportError_([f"{what}: no header row"])
    header = {h.strip().lower(): h for h in reader.fieldnames if h}
    mapping = {}
    for key, names in columns.items():
        found = next((header[n] for n in names if n in header), None)
        if found:
            mapping[key] = found
    missing = [k for k in required if k not in mapping]
    if missing:
        raise ImportError_([f"{what}: missing column(s) {', '.join(missing)}; found {', '.join(reader.fieldnames)}"])
    out = []
    for n, row in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            raise ImportError_([f"{what}: more than {MAX_ROWS} rows"])
        if not any((v or "").strip() for v in row.values()):
            continue
        out.append({"_line": n, **{k: (row.get(col) or "").strip() for k, col in mapping.items()}})
    return out


def parse_invoices(text: str) -> list[dict]:
    rows = _rows(text, INVOICE_COLUMNS, ("invoice_id", "customer", "amount", "issued_on", "due_on"), "invoices")
    errors, out, seen = [], [], set()
    for r in rows:
        line = r["_line"]
        try:
            amount = parse_money(r["amount"])
            balance = parse_money(r["balance"]) if r.get("balance") else amount
            issued, due = parse_date(r["issued_on"]), parse_date(r["due_on"])
        except ValueError as exc:
            errors.append(f"invoices line {line}: {exc}")
            continue
        inv_id = r["invoice_id"]
        if not inv_id or not r["customer"]:
            errors.append(f"invoices line {line}: invoice id and customer are required")
        elif inv_id in seen:
            errors.append(f"invoices line {line}: duplicate invoice id {inv_id!r}")
        elif amount <= 0:
            errors.append(f"invoices line {line}: amount must be positive")
        elif not 0 <= balance <= amount:
            errors.append(f"invoices line {line}: open balance must be between 0 and the amount")
        elif due < issued:
            errors.append(f"invoices line {line}: due date is before issue date")
        else:
            seen.add(inv_id)
            out.append(
                {
                    "invoice_id": inv_id,
                    "customer": r["customer"],
                    "amount": amount,
                    "balance": balance,
                    "issued_on": issued,
                    "due_on": due,
                    "po_number": r.get("po_number") or None,
                    "email": r.get("email") or "",
                    "description": r.get("description") or "",
                }
            )
    if errors:
        raise ImportError_(errors)
    if not out:
        raise ImportError_(["invoices: no invoice rows"])
    return out


def parse_bank(text: str) -> list[dict]:
    if not text.strip():
        return []
    rows = _rows(text, BANK_COLUMNS, ("date", "amount", "payer"), "bank")
    errors, out = [], []
    for r in rows:
        try:
            amount, on = parse_money(r["amount"]), parse_date(r["date"])
        except ValueError as exc:
            errors.append(f"bank line {r['_line']}: {exc}")
            continue
        if amount > 0:  # debits (money out) are not customer payments
            out.append({"date": on, "amount": amount, "payer": r["payer"], "remittance": r.get("remittance") or ""})
    if errors:
        raise ImportError_(errors)
    return out


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())[:40] or "customer"


def seed_import(conn: sqlite3.Connection, invoices: list[dict], bank: list[dict], memory_enabled: bool) -> dict:
    """Load parsed books into an empty schema. The run starts at the earliest of the latest invoice date and the
    first bank date, and ends 30 days after the last bank line (or due date), so every payment is processed."""
    from settle.personas import schedule

    last_issue = max(i["issued_on"] for i in invoices)
    start = min([last_issue] + [b["date"] for b in bank])
    end = max([b["date"] for b in bank] + [max(i["due_on"] for i in invoices)]) + timedelta(days=30)
    set_meta(conn, "mode", "import")
    set_meta(conn, "seed", "0")
    set_meta(conn, "start_date", start.isoformat())
    set_meta(conn, "end_date", end.isoformat())
    set_meta(conn, "sim_date", start.isoformat())
    set_meta(conn, "memory_enabled", "1" if memory_enabled else "0")

    customers: dict[str, str] = {}
    for inv in sorted(invoices, key=lambda x: (x["customer"].lower(), x["invoice_id"])):
        name = inv["customer"]
        if name in customers:
            continue
        cid = f"C-I{len(customers) + 1:03d}"
        customers[name] = cid
        email = next((i["email"] for i in invoices if i["customer"] == name and "@" in i["email"]), "")
        domain = email.split("@")[-1].lower() if email else f"{_slug(name)}.unverified"
        conn.execute(
            "INSERT INTO customers VALUES(?,?,?,?,?,?,?)",
            (cid, name, "standard", domain, email or f"ap@{domain}", "unknown", "Unassigned (AE)"),
        )
        conn.execute("INSERT INTO profiles(customer_id) VALUES(?)", (cid,))
        conn.execute(
            "INSERT INTO crm_notes VALUES(?,?,?,?,?)",
            (f"N-{cid}-owner", cid, None, "account", f"Imported customer {name}. AP contact: {email or 'n/a'}."),
        )
    for inv in invoices:
        cid = customers[inv["customer"]]
        future = inv["issued_on"] > start
        conn.execute(
            "INSERT INTO invoices(id, customer_id, po_number, amount_cents, balance_cents, issued_on, due_on, status,"
            " description) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                inv["invoice_id"],
                cid,
                inv["po_number"],
                inv["amount"],
                inv["balance"],
                inv["issued_on"].isoformat(),
                inv["due_on"].isoformat(),
                "scheduled" if future else ("paid" if inv["balance"] == 0 else "open"),
                inv["description"],
            ),
        )
        if future:
            schedule(conn, inv["issued_on"], "issue_invoice", cid, {"invoice_id": inv["invoice_id"]})
            continue
        ledger.post(
            conn,
            inv["issued_on"].isoformat(),
            ledger.AR,
            ledger.REVENUE,
            inv["amount"],
            "invoice",
            inv["invoice_id"],
            f"Opening balance {inv['invoice_id']}",
            audited=False,
        )
        paid = inv["amount"] - inv["balance"]
        if paid:
            ledger.post(
                conn,
                inv["issued_on"].isoformat(),
                ledger.CASH,
                ledger.AR,
                paid,
                "invoice",
                inv["invoice_id"],
                f"Opening collection {inv['invoice_id']}",
                audited=False,
            )
    for b in sorted(bank, key=lambda x: (x["date"], x["payer"], x["amount"])):
        schedule(
            conn,
            b["date"],
            "payment",
            None,
            {
                "bank_line": {
                    "amount_cents": b["amount"],
                    "payer_name": b["payer"],
                    "remittance_text": b["remittance"],
                },
                "gt": {},
            },
        )
    from settle.seed_data import world_digest

    set_meta(conn, "world_digest", world_digest(conn))
    summary = {
        "customers": len(customers),
        "invoices": len(invoices),
        "bank_lines": len(bank),
        "open_ar_cents": sum(i["balance"] for i in invoices if i["issued_on"] <= start),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    set_meta(conn, "import_summary", dumps(summary))
    conn.commit()
    return summary
