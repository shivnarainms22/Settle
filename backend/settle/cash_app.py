"""Cash application pass 1: deterministic matching (no LLM). Leftovers go to the agent (pass 2)."""

import itertools
import re
import sqlite3

from settle.memory import MemoryStore
from settle.models import Decision

SUBSET_MAX_INVOICES = 12
SUBSET_MAX_SIZE = 6
_SUFFIXES = {"INC", "LLC", "CORP", "CO", "LTD", "CORPORATION", "COMPANY", "THE"}
OPEN = "('open','reminded','blocked','disputed','plan','partially_paid','escalated','on_hold')"


def normalize_name(name: str) -> str:
    tokens = re.findall(r"[A-Z0-9]+", name.upper())
    return " ".join(t for t in tokens if t not in _SUFFIXES)


def invoice_refs(text: str) -> list[str]:
    return [f"INV-{n}" for n in re.findall(r"INV[- ]?(\d{4,})", text.upper())]


def resolve_refs(conn: sqlite3.Connection, text: str) -> list[str]:
    """Invoice ids referenced by a remittance, tolerant of real-world numbering: "INV 5103" matches an invoice whose
    id is "INV-5103" or "5103", and a customer PO number ("NB-4410") matches the open invoice carrying that PO."""
    up = (text or "").upper()
    found: list[str] = []
    for n in re.findall(r"INV[- #]*(\d{3,})", up):
        for candidate in (f"INV-{n}", n):
            if conn.execute("SELECT 1 FROM invoices WHERE id=?", (candidate,)).fetchone():
                found.append(candidate)
                break
        else:
            found.append(f"INV-{n}")  # unknown reference: kept, so the exact-match rule fails closed
    if not found:
        tokens = set(re.findall(r"[A-Z0-9][A-Z0-9-]{2,}", up))
        if tokens:
            rows = conn.execute(
                f"SELECT id, po_number FROM invoices WHERE status IN {OPEN} AND UPPER(po_number) IN"
                f" ({','.join('?' * len(tokens))}) ORDER BY id",
                sorted(tokens),
            ).fetchall()
            found = [r["id"] for r in rows]
    return list(dict.fromkeys(found))


def open_invoices(conn: sqlite3.Connection, customer_id: str | None = None) -> list[sqlite3.Row]:
    sql = f"SELECT * FROM invoices WHERE status IN {OPEN} AND balance_cents > 0"
    params: tuple = ()
    if customer_id:
        sql += " AND customer_id=?"
        params = (customer_id,)
    return conn.execute(sql + " ORDER BY due_on, id", params).fetchall()


def identify_payer(conn: sqlite3.Connection, payer_name: str, memory: MemoryStore) -> tuple[str | None, str]:
    """Returns (customer_id, how) where how is 'name' | 'alias' | 'name_in_description' | ''."""
    target = normalize_name(payer_name)
    for c in conn.execute("SELECT id, name FROM customers ORDER BY id"):
        if normalize_name(c["name"]) == target:
            return c["id"], "name"
    if memory.enabled:
        for c in conn.execute("SELECT id FROM customers ORDER BY id"):
            if any(normalize_name(a) == target for a in memory.profile(c["id"])["aliases"]):
                return c["id"], "alias"
    # Real bank descriptions wrap the payer in prefixes ("ACH CREDIT ...", "WIRE IN ..."): accept a customer whose
    # full normalized name appears as a whole-word run inside the description, but only if exactly one does.
    padded = f" {target} "
    hits = [
        c["id"]
        for c in conn.execute("SELECT id, name FROM customers ORDER BY id")
        if (n := normalize_name(c["name"])) and len(n) >= 4 and f" {n} " in padded
    ]
    if len(hits) == 1:
        return hits[0], "name_in_description"
    return None, ""


def _alloc(rows) -> list[dict]:
    return [{"invoice_id": r["id"], "amount_cents": r["balance_cents"]} for r in rows]


def match(conn: sqlite3.Connection, line: sqlite3.Row, memory: MemoryStore) -> tuple[Decision | None, str | None]:
    """Returns (decision or None, identified customer_id or None)."""
    amount = line["amount_cents"]
    ev = [f"bank:{line['id']}"]

    refs = resolve_refs(conn, line["remittance_text"])
    if refs:
        rows = conn.execute(
            f"SELECT * FROM invoices WHERE id IN ({','.join('?' * len(refs))}) AND status IN {OPEN} ORDER BY id", refs
        ).fetchall()
        if len(rows) == len(refs) and len({r["customer_id"] for r in rows}) == 1:
            cust = rows[0]["customer_id"]
            ev += [f"invoice:{r['id']}" for r in rows]
            total = sum(r["balance_cents"] for r in rows)
            if total == amount:
                return Decision(
                    "apply_payment",
                    {"bank_line_id": line["id"], "allocations": _alloc(rows)},
                    f"Remittance references {', '.join(refs)}; amount equals open balance.",
                    ev,
                    confidence=1.0,
                    source="deterministic",
                    provenance={"component": "cash_app", "rule": "remittance_exact"},
                ), cust
            if len(rows) == 1 and 0 < amount < total and rows[0]["status"] == "plan":
                return Decision(
                    "apply_payment",
                    {
                        "bank_line_id": line["id"],
                        "allocations": [{"invoice_id": rows[0]["id"], "amount_cents": amount}],
                    },
                    f"Installment on agreed payment plan for {refs[0]}: applying {amount / 100:,.2f}; remaining"
                    f" {(total - amount) / 100:,.2f} stays on the plan.",
                    ev,
                    confidence=1.0,
                    source="deterministic",
                    provenance={"component": "cash_app", "rule": "plan_installment"},
                ), cust
            if len(rows) == 1 and 0 < amount < total:
                return Decision(
                    "apply_payment",
                    {
                        "bank_line_id": line["id"],
                        "allocations": [{"invoice_id": rows[0]["id"], "amount_cents": amount}],
                        "short_pay_remaining_cents": total - amount,
                    },
                    f"Remittance references {refs[0]} but pays {amount / 100:,.2f} of {total / 100:,.2f}; applying"
                    f" what was paid and flagging the {(total - amount) / 100:,.2f} deduction.",
                    ev,
                    confidence=1.0,
                    source="deterministic",
                    provenance={"component": "cash_app", "rule": "remittance_short_pay"},
                ), cust

    cust, how = identify_payer(conn, line["payer_name"], memory)
    if cust is None:
        return None, None
    memory_ids = []
    if how == "alias":
        row = conn.execute(
            "SELECT id FROM memories WHERE customer_id=? AND trigger='alias_learned' ORDER BY id DESC LIMIT 1", (cust,)
        ).fetchone()
        memory_ids = [row["id"]] if row else []
    cust_name = conn.execute("SELECT name FROM customers WHERE id=?", (cust,)).fetchone()["name"]
    why = (
        f"payer '{line['payer_name']}' is a known alias of {cust_name} (learned from memory)"
        if how == "alias"
        else f"payer '{line['payer_name']}' is {cust_name}"
    )
    candidates = open_invoices(conn, cust)
    exact = [r for r in candidates if r["balance_cents"] == amount]
    if len(exact) == 1:
        return Decision(
            "apply_payment",
            {"bank_line_id": line["id"], "allocations": _alloc(exact)},
            f"{why[0].upper() + why[1:]}; amount matches exactly one open invoice {exact[0]['id']}.",
            [*ev, f"invoice:{exact[0]['id']}"],
            memory_ids,
            confidence=1.0,
            source="deterministic",
            provenance={"component": "cash_app", "rule": "payer_exact_amount", "how": how},
        ), cust
    pool = candidates[:SUBSET_MAX_INVOICES]
    # Batch payers usually pay consecutive invoices: try contiguous runs (oldest first) before arbitrary subsets,
    # which are often ambiguous when many invoices share round amounts.
    runs = [tuple(pool[i : i + n]) for n in range(2, SUBSET_MAX_SIZE + 1) for i in range(len(pool) - n + 1)]
    run_hits = [r for r in runs if sum(x["balance_cents"] for x in r) == amount]
    hits = run_hits[:1] if run_hits else []
    for size in range(2, min(SUBSET_MAX_SIZE, len(pool)) + 1):
        if run_hits:
            break
        for combo in itertools.combinations(pool, size):
            if sum(r["balance_cents"] for r in combo) == amount:
                hits.append(combo)
                if len(hits) > 1:
                    break
        if hits:
            break
    if len(hits) == 1:
        combo = hits[0]
        return Decision(
            "apply_payment",
            {"bank_line_id": line["id"], "allocations": _alloc(combo)},
            f"{why[0].upper() + why[1:]}; no remittance, but the amount equals exactly one combination of"
            f" {len(combo)} open invoices ({', '.join(r['id'] for r in combo)}).",
            [*ev, *(f"invoice:{r['id']}" for r in combo)],
            memory_ids,
            confidence=1.0,
            source="deterministic",
            provenance={"component": "cash_app", "rule": "payer_invoice_set", "how": how},
        ), cust
    return None, cust
