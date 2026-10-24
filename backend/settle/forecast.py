"""Cash-collection forecast from learned payment behavior (semantic memory).

With memory, each open invoice is expected at due date + the customer's learned average lateness (agreed plan
installments on their dates, disputed/escalated items flagged at risk). Without memory the only information is the
contract, so invoices are expected on their due date. Snapshots taken at each month start are scored afterwards
against actual cash applied (weighted absolute percentage error), which turns "memory helps" into a forecast-accuracy
number.
"""

import sqlite3
from datetime import date, timedelta

from settle.db import dumps, loads
from settle.memory import MemoryStore

HORIZON_WEEKS = 4
MIN_PAYMENTS_FOR_LAG = 2


def forecast(conn: sqlite3.Connection, memory: MemoryStore, as_of: str, weeks: int = HORIZON_WEEKS) -> dict:
    today = date.fromisoformat(as_of)
    lines, at_risk = [], []
    rows = conn.execute(
        "SELECT * FROM invoices WHERE status NOT IN ('scheduled','paid') AND balance_cents>0 AND issued_on<=?"
        " ORDER BY id",
        (as_of,),
    ).fetchall()
    for inv in rows:
        due = date.fromisoformat(inv["due_on"])
        if inv["status"] in ("disputed", "escalated"):
            at_risk.append(
                {
                    "invoice_id": inv["id"],
                    "customer_id": inv["customer_id"],
                    "amount_cents": inv["balance_cents"],
                    "reason": inv["status"],
                }
            )
            continue
        if inv["plan_json"]:
            for p in loads(inv["plan_json"], []):
                d = max(date.fromisoformat(p["date"]), today)
                lines.append(
                    {
                        "invoice_id": inv["id"],
                        "customer_id": inv["customer_id"],
                        "date": d.isoformat(),
                        "amount_cents": min(int(p["amount_cents"]), inv["balance_cents"]),
                        "basis": "plan",
                    }
                )
            continue
        prof = memory.profile(inv["customer_id"]) if memory.enabled else None
        if prof and prof["payments_observed"] >= MIN_PAYMENTS_FOR_LAG:
            expected, basis = due + timedelta(days=round(prof["avg_days_late"])), "learned"
        else:
            expected, basis = due, "contract"
        if expected < today:  # already past its expected date: assume it lands soon, but flag it
            at_risk.append(
                {
                    "invoice_id": inv["id"],
                    "customer_id": inv["customer_id"],
                    "amount_cents": inv["balance_cents"],
                    "reason": f"past expected date {expected}",
                }
            )
            expected = today + timedelta(days=3)
        lines.append(
            {
                "invoice_id": inv["id"],
                "customer_id": inv["customer_id"],
                "date": expected.isoformat(),
                "amount_cents": inv["balance_cents"],
                "basis": basis,
            }
        )
    buckets = []
    for w in range(weeks):
        start, end = today + timedelta(days=7 * w), today + timedelta(days=7 * (w + 1) - 1)
        amt = sum(x["amount_cents"] for x in lines if start.isoformat() <= x["date"] <= end.isoformat())
        buckets.append({"week": w + 1, "start": start.isoformat(), "end": end.isoformat(), "expected_cents": amt})
    return {
        "as_of": as_of,
        "method": "learned" if memory.enabled else "contract",
        "weeks": buckets,
        "lines": lines,
        "at_risk": at_risk,
    }


def snapshot(conn: sqlite3.Connection, memory: MemoryStore, as_of: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO forecasts(as_of, payload_json) VALUES(?,?)",
        (as_of, dumps(forecast(conn, memory, as_of))),
    )


def accuracy(conn: sqlite3.Connection, as_of: str, today: str | None = None) -> dict | None:
    """Score a snapshot: forecast vs actual cash applied, per week, to the invoices open at snapshot time.
    Only weeks that have fully elapsed before `today` are scored (all weeks when today is None)."""
    row = conn.execute("SELECT payload_json FROM forecasts WHERE as_of=?", (as_of,)).fetchone()
    if row is None:
        return None
    fc = loads(row["payload_json"])
    invoices = sorted({x["invoice_id"] for x in fc["lines"]} | {x["invoice_id"] for x in fc["at_risk"]})
    weeks = []
    abs_err = actual_total = 0
    for b in fc["weeks"]:
        if today is not None and b["end"] >= today:
            continue
        actual = (
            conn.execute(
                "SELECT COALESCE(SUM(amount_cents),0) FROM gl_entries WHERE debit_acct='Cash' AND credit_acct="
                f"'Accounts Receivable' AND invoice_id IN ({','.join('?' * len(invoices))})"
                " AND sim_date BETWEEN ? AND ?",
                [*invoices, b["start"], b["end"]],
            ).fetchone()[0]
            if invoices
            else 0
        )
        weeks.append({**b, "actual_cents": actual})
        abs_err += abs(b["expected_cents"] - actual)
        actual_total += actual
    return {
        "as_of": as_of,
        "method": fc["method"],
        "weeks": weeks,
        "complete": len(weeks) == len(fc["weeks"]),
        "wape": round(abs_err / actual_total, 4) if actual_total else None,
    }
