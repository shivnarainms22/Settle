"""The executor: the only component that changes invoices, the ledger and outbound email.

Every mutation goes through an audited helper (`update_invoice`, `send_email`, `ledger.post`) that records the
before/after values, the actor and the decision that caused it, so any invoice's history can be traced end to end.
"""

import sqlite3
from datetime import date, timedelta

from settle import audit, ledger, personas
from settle.cash_app import normalize_name
from settle.db import dumps, get_meta, loads, set_meta
from settle.memory import MemoryStore

INVOICE_FIELDS = {
    "po_number",
    "balance_cents",
    "status",
    "reminder_count",
    "last_reminder_on",
    "hold_until",
    "plan_json",
    "paid_on",
}


def next_id(conn: sqlite3.Connection, prefix: str) -> str:
    n = int(get_meta(conn, f"seq_{prefix}", "0")) + 1
    set_meta(conn, f"seq_{prefix}", str(n))
    return f"{prefix}-{n}"


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def log_activity(
    conn: sqlite3.Connection,
    sim_date: str,
    kind: str,
    title: str,
    detail: str = "",
    customer_id: str | None = None,
    decision_id: int | None = None,
    tier: int | None = None,
    agent_state: str | None = None,
    amount_cents: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO activity(sim_date, kind, title, detail, customer_id, decision_id, tier, agent_state,"
        " amount_cents) VALUES(?,?,?,?,?,?,?,?,?)",
        (sim_date, kind, title, detail, customer_id, decision_id, tier, agent_state, amount_cents),
    )
    return cur.lastrowid


def update_invoice(
    conn: sqlite3.Connection,
    invoice_id: str,
    changes: dict,
    actor: str,
    decision_id: int | None = None,
    reason: str = "",
) -> dict:
    """The single write path for invoice state. Audits the field-level diff."""
    unknown = set(changes) - INVOICE_FIELDS
    if unknown:
        raise ValueError(f"cannot update invoice fields {sorted(unknown)}")
    row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if row is None:
        raise KeyError(f"invoice {invoice_id} not found")
    diff = {k: {"old": row[k], "new": v} for k, v in sorted(changes.items()) if row[k] != v}
    if not diff:
        return dict(row)
    conn.execute(
        f"UPDATE invoices SET {', '.join(f'{k}=?' for k in diff)} WHERE id=?",
        [*(d["new"] for d in diff.values()), invoice_id],
    )
    audit.append(
        conn,
        "invoice_updated",
        {"invoice_id": invoice_id, "changes": diff, "actor": actor, "reason": reason, "decision_id": decision_id},
        refs=[
            f"invoice:{invoice_id}",
            f"customer:{row['customer_id']}",
            f"decision:{decision_id}" if decision_id else None,
        ],
    )
    return dict(conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone())


def send_email(
    conn: sqlite3.Connection,
    today: str,
    customer_id: str,
    invoice_id: str | None,
    subject: str,
    body: str,
    decision_id: int | None = None,
    thread_id: str | None = None,
) -> str:
    eid = next_id(conn, "E")
    thread = thread_id or f"T-{invoice_id or customer_id}"
    conn.execute(
        "INSERT INTO emails VALUES(?,?,?,?,?,?,?,?,?)",
        (eid, thread, customer_id, invoice_id, "out", "ar@northwind-robotics.com", subject, body, today),
    )
    audit.append(
        conn,
        "email_sent",
        {"email_id": eid, "thread_id": thread, "subject": subject, "body": body, "decision_id": decision_id},
        refs=[
            f"email:{eid}",
            f"customer:{customer_id}",
            f"invoice:{invoice_id}" if invoice_id else None,
            f"decision:{decision_id}" if decision_id else None,
        ],
        sim_date=today,
    )
    return eid


class Executor:
    def __init__(self, conn: sqlite3.Connection, memory: MemoryStore):
        self.conn = conn
        self.memory = memory

    # -- helpers
    def _inv(self, invoice_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if row is None:
            raise KeyError(f"invoice {invoice_id} not found")
        return dict(row)

    def _cust(self, customer_id: str) -> dict:
        return dict(self.conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone())

    def _upd(self, invoice_id: str, d: dict | None, reason: str, **changes) -> dict:
        actor = f"settle:{d['source']}" if d else "settle:billing"
        if d and d.get("approver"):
            actor += f"+{d['approver']}"
        return update_invoice(self.conn, invoice_id, changes, actor, d["id"] if d else None, reason)

    def _email(self, d: dict | None, today: str, inv: dict, subject: str, body: str) -> str:
        return send_email(self.conn, today, inv["customer_id"], inv["id"], subject, body, d["id"] if d else None)

    def issue_invoice(self, invoice_id: str, today: str) -> dict:
        self._upd(invoice_id, None, "invoice issued", status="open")
        inv = self._inv(invoice_id)
        ledger.post(
            self.conn,
            today,
            ledger.AR,
            ledger.REVENUE,
            inv["amount_cents"],
            "invoice",
            invoice_id,
            f"Invoice {invoice_id} issued",
        )
        collected = inv["amount_cents"] - inv["balance_cents"]
        if collected > 0:  # imported books: part was paid before the import, so AR carries only the balance
            ledger.post(
                self.conn,
                today,
                ledger.CASH,
                ledger.AR,
                collected,
                "invoice",
                invoice_id,
                f"Collected before import {invoice_id}",
            )
            if inv["balance_cents"] == 0:
                inv = self._upd(invoice_id, None, "fully paid before import", status="paid")
        po = f" (PO {inv['po_number']})" if inv["po_number"] else ""
        self._email(
            None,
            today,
            inv,
            f"Invoice {invoice_id}{po}",
            f"Please find attached invoice {invoice_id}{po} for {money(inv['amount_cents'])}, due"
            f" {inv['due_on']}.\n\n{inv['description']}\n\nNorthwind Robotics Accounts Receivable",
        )
        personas.on_invoice_sent(self.conn, inv, date.fromisoformat(today))
        return inv

    # -- dispatch
    def execute(self, decision_id: int, today: str) -> None:
        d = dict(self.conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())
        if d["tier"] == 3:
            raise PermissionError(f"decision {decision_id} is tier 3 and can never be executed")
        args = loads(d["args_json"], {})
        handler = getattr(self, f"_do_{d['action']}", None)
        if handler is None:
            raise ValueError(f"no executor for action {d['action']}")
        title = handler(d, args, today)
        self.conn.execute(
            "UPDATE decisions SET status=CASE WHEN status='pending_approval' THEN 'approved'"
            " WHEN status IN ('approved','edited') THEN status ELSE 'executed' END WHERE id=?",
            (decision_id,),
        )
        invoices = [a["invoice_id"] for a in args.get("allocations", [])] or (
            [args["invoice_id"]] if args.get("invoice_id") else []
        )
        audit.append(
            self.conn,
            "decision_executed",
            {
                "decision_id": decision_id,
                "action": d["action"],
                "result": title,
                "approver": d["approver"],
                "status_from": d["status"],
                "status_to": {"pending_approval": "approved", "approved": "approved", "edited": "edited"}.get(
                    d["status"], "executed"
                ),
            },
            refs=[
                f"decision:{decision_id}",
                f"work_item:{d['work_item_id']}",
                f"customer:{d['customer_id']}" if d["customer_id"] else None,
                f"bank:{args['bank_line_id']}" if args.get("bank_line_id") else None,
                *(f"invoice:{i}" for i in invoices),
            ],
            sim_date=today,
        )
        log_activity(
            self.conn,
            today,
            "decision",
            title,
            d["rationale"],
            d["customer_id"],
            decision_id,
            d["tier"],
            "Agent Working",
            d["amount_cents"],
        )
        if d["action"] in ("propose_credit_memo", "escalate") and d["customer_id"]:
            cust = self._cust(d["customer_id"])
            log_activity(
                self.conn,
                today,
                "system",
                f"Looped in {cust['owner_in_sales']} on {cust['name']}",
                args.get("summary", ""),
                d["customer_id"],
                decision_id,
            )
            audit.append(
                self.conn,
                "handoff",
                {"to": cust["owner_in_sales"], "decision_id": decision_id},
                refs=[f"decision:{decision_id}", f"customer:{d['customer_id']}"],
                sim_date=today,
            )

    def _do_send_reminder(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        count = inv["reminder_count"] + 1
        firm = args.get("tone") == "firm" or count > 1
        days = (date.fromisoformat(today) - date.fromisoformat(inv["due_on"])).days
        body = (
            f"Hi,\n\nA friendly reminder that invoice {inv['id']} for {money(inv['balance_cents'])} was due on"
            f" {inv['due_on']}. Could you let us know when payment is scheduled?\n\nThanks,\nNorthwind AR"
            if not firm
            else f"Hello,\n\nInvoice {inv['id']} for {money(inv['balance_cents'])} is now {days} days past due."
            f" Please arrange payment this week or let us know if something is blocking it.\n\nNorthwind AR"
        )
        self._email(d, today, inv, f"{'Reminder' if not firm else 'Past due'}: {inv['id']}", body)
        status = "reminded" if inv["status"] in ("open", "on_hold") else inv["status"]
        inv = self._upd(inv["id"], d, f"reminder #{count}", reminder_count=count, last_reminder_on=today, status=status)
        personas.on_reminder(self.conn, inv, count, date.fromisoformat(today))
        return f"{'Firm' if firm else 'Friendly'} reminder #{count} sent for {inv['id']}"

    def _do_reissue_invoice(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        po = (args.get("changes") or {}).get("po_number") or inv["po_number"]
        inv = self._upd(inv["id"], d, "reissued with corrections", po_number=po, status="open")
        self._email(
            d,
            today,
            inv,
            f"Corrected invoice {inv['id']} (PO {po})",
            f"Hi,\n\nApologies for the trouble. Attached is invoice {inv['id']} reissued with PO {po}"
            f" referenced, for {money(inv['balance_cents'])}.\n\nNorthwind AR",
        )
        personas.on_reissue(self.conn, inv, date.fromisoformat(today))
        return f"Reissued {inv['id']} with PO {po}"

    def _do_attach_po(self, d, args, today):
        self._upd(args["invoice_id"], d, "PO attached before sending", po_number=args["po_number"])
        return f"Attached PO {args['po_number']} to {args['invoice_id']} before sending"

    def _do_propose_credit_memo(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        amount = int(args["amount_cents"])
        ledger.post(
            self.conn,
            today,
            ledger.RETURNS,
            ledger.AR,
            amount,
            "credit_memo",
            inv["id"],
            f"Credit memo on {inv['id']}: {args.get('reason', '')}",
            d["id"],
        )
        inv = self._upd(
            inv["id"], d, f"credit memo {money(amount)}", balance_cents=inv["balance_cents"] - amount, status="open"
        )
        self._email(
            d,
            today,
            inv,
            f"Credit memo for {inv['id']}",
            f"Hi,\n\nWe've issued a credit memo of {money(amount)} against {inv['id']} ({args.get('reason')})."
            f" The remaining balance is {money(inv['balance_cents'])}.\n\nNorthwind AR",
        )
        personas.on_credit_memo(self.conn, inv, amount, date.fromisoformat(today))
        return f"Credit memo {money(amount)} issued on {inv['id']}"

    def _do_propose_payment_plan(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        plan = args["installments"]
        inv = self._upd(inv["id"], d, "payment plan agreed", status="plan", plan_json=dumps(plan))
        lines = "\n".join(f"  {p['date']}: {money(int(p['amount_cents']))}" for p in plan)
        self._email(
            d,
            today,
            inv,
            f"Payment plan for {inv['id']}",
            f"Hi,\n\nHappy to help. Here is a payment plan for {inv['id']}:\n{lines}\n\nNorthwind AR",
        )
        personas.on_payment_plan(self.conn, inv, plan, date.fromisoformat(today))
        return f"Payment plan agreed on {inv['id']} ({len(plan)} installments)"

    def _do_request_balance(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        amount = int(args["amount_cents"])
        self._email(
            d,
            today,
            inv,
            f"Remaining balance on {inv['id']}",
            f"Hi,\n\nThanks for your payment on {inv['id']}. A deduction of {money(amount)} was taken as an"
            f" early-payment discount, but our terms are net 30 with no discount and the payment arrived"
            f" after the due date. Please remit the remaining {money(amount)}.\n\nNorthwind AR",
        )
        personas.on_balance_request(self.conn, inv, amount, date.fromisoformat(today))
        return f"Requested {money(amount)} short-paid balance on {inv['id']}"

    def _do_escalate(self, d, args, today):
        inv_id = args.get("invoice_id")
        inv = self._inv(inv_id) if inv_id else None
        if inv and args.get("pause_dunning"):
            inv = self._upd(inv_id, d, "escalated; dunning paused", status="escalated")
        personas.on_escalation(self.conn, inv, date.fromisoformat(today))
        return f"Escalated {inv_id or 'item'} to {args.get('to', 'a human')}" + (
            " and paused dunning" if args.get("pause_dunning") else ""
        )

    def _do_hold_dunning(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        until = args.get("expected_pay_date") or (date.fromisoformat(today) + timedelta(days=14)).isoformat()
        until = (date.fromisoformat(until) + timedelta(days=3)).isoformat()
        status = inv["status"] if inv["status"] == "paid" else "on_hold"
        self._upd(inv["id"], d, "dunning held for forecast pay date", hold_until=until, status=status)
        return f"Holding dunning on {inv['id']}; forecast payment ~{args.get('expected_pay_date', until)}"

    def _do_request_dispute_evidence(self, d, args, today):
        inv = self._inv(args["invoice_id"])
        self._email(
            d,
            today,
            inv,
            f"Re: {inv['id']}: details needed",
            f"Hi,\n\nThanks for letting us know. To review a claim on {inv['id']} we need specifics: which"
            f" items are affected, photos, and any carrier exception noted at delivery. Our delivery record"
            f" {args.get('delivery_ref', '')} shows the shipment signed for without exceptions. Until we"
            f" receive details, the invoice remains due.\n\nNorthwind AR",
        )
        personas.on_evidence_request(self.conn, inv, date.fromisoformat(today))
        return f"Asked for evidence on the {inv['id']} claim"

    def _do_no_action(self, d, args, today):
        return f"No action needed: {d['rationale'][:80]}"

    def _do_apply_payment(self, d, args, today):
        line = dict(self.conn.execute("SELECT * FROM bank_lines WHERE id=?", (args["bank_line_id"],)).fetchone())
        if line["matched"]:
            raise ValueError(f"bank line {line['id']} is already applied")
        applied = 0
        paid_ids = []
        for a in args["allocations"]:
            inv = self._inv(a["invoice_id"])
            amt = int(a["amount_cents"])
            ledger.post(
                self.conn,
                today,
                ledger.CASH,
                ledger.AR,
                amt,
                "bank_line",
                line["id"],
                f"Cash applied to {inv['id']}",
                d["id"],
                invoice_id=inv["id"],
            )
            new_bal = inv["balance_cents"] - amt
            status = "paid" if new_bal == 0 else ("plan" if inv["status"] == "plan" else "partially_paid")
            self._upd(
                inv["id"],
                d,
                f"cash {money(amt)} applied from {line['id']}",
                balance_cents=new_bal,
                status=status,
                paid_on=today if new_bal == 0 else None,
            )
            applied += amt
            if new_bal == 0:
                paid_ids.append(inv["id"])
        if line["amount_cents"] > applied:
            ledger.post(
                self.conn,
                today,
                ledger.CASH,
                ledger.UNAPPLIED,
                line["amount_cents"] - applied,
                "bank_line",
                line["id"],
                "Unapplied remainder",
                d["id"],
            )
        self.conn.execute("UPDATE bank_lines SET matched=1 WHERE id=?", (line["id"],))
        audit.append(
            self.conn,
            "bank_line_matched",
            {
                "bank_line_id": line["id"],
                "applied_cents": applied,
                "unapplied_cents": line["amount_cents"] - applied,
                "decision_id": d["id"],
            },
            refs=[f"bank:{line['id']}", f"decision:{d['id']}"],
            sim_date=today,
        )
        log_activity(
            self.conn,
            today,
            "payment",
            f"Payment {line['id']} {money(line['amount_cents'])} applied to"
            f" {', '.join(a['invoice_id'] for a in args['allocations'])}",
            line["remittance_text"],
            d["customer_id"],
            d["id"],
            d["tier"],
            amount_cents=line["amount_cents"],
        )
        if d["approver"] and args.get("customer_id"):
            self._learn_alias(args["customer_id"], line["payer_name"], d)
        for inv_id in paid_ids:
            self._learn_from_paid(inv_id, today)
        return f"Applied {money(applied)} from {line['id']} across {len(args['allocations'])} invoice(s)"

    # -- learning from confirmed outcomes
    def _learn_alias(self, customer_id: str, payer_name: str, d: dict) -> None:
        cust = self._cust(customer_id)
        if normalize_name(payer_name) == normalize_name(cust["name"]):
            return
        if self.memory.add_alias(customer_id, payer_name, d["id"]):
            self.memory.write(
                "episodic",
                customer_id,
                f"Payer name '{payer_name}' on bank lines is {cust['name']} ({customer_id});"
                f" confirmed by {d['approver']}.",
                d["approver"],
                "alias_learned",
                "apply_payment",
                d["id"],
            )
            log_activity(
                self.conn,
                d["sim_date"],
                "memory",
                f"Learned alias '{payer_name}' → {cust['name']}",
                "",
                customer_id,
                d["id"],
                agent_state="Self-Learning",
            )

    def _learn_from_paid(self, invoice_id: str, today: str) -> None:
        if not self.memory.enabled:
            return
        inv = self._inv(invoice_id)
        cust = self._cust(inv["customer_id"])
        days_late = (date.fromisoformat(today) - date.fromisoformat(inv["due_on"])).days
        after = (
            (date.fromisoformat(today) - date.fromisoformat(inv["last_reminder_on"])).days
            if inv["last_reminder_on"]
            else None
        )
        self.memory.observe_payment(inv["customer_id"], days_late, invoice_id, inv["reminder_count"], after)
        when = (
            f"{days_late} days late" if days_late > 0 else ("on time" if days_late == 0 else f"{-days_late} days early")
        )
        self.memory.write(
            "episodic",
            inv["customer_id"],
            f"{cust['name']} paid {invoice_id} ({money(inv['amount_cents'])}) {when} after"
            f" {inv['reminder_count']} reminder(s).",
            "outcome:paid",
            "payment_observed",
            "paid",
        )
        self.confirm_outcomes(invoice_id, today, "paid in full", "outcome:paid")
        log_activity(
            self.conn,
            today,
            "memory",
            f"Learned from outcome: {cust['name']} paid {invoice_id} {when}",
            "",
            inv["customer_id"],
            agent_state="Self-Learning",
        )

    def confirm_outcomes(self, invoice_id: str, today: str, outcome: str, approved_by: str) -> int:
        """Turn executed resolution decisions on an invoice into episodic memories once the world confirms them
        (customer AP accepted the fix, or the invoice got paid). Each decision is confirmed at most once."""
        if not self.memory.enabled:
            return 0
        inv = self._inv(invoice_id)
        cust = self._cust(inv["customer_id"])
        rows = self.conn.execute(
            "SELECT d.* FROM decision_invoices di JOIN decisions d ON d.id=di.decision_id WHERE di.invoice_id=?"
            " AND d.status IN ('executed','approved','edited') AND d.action"
            " IN ('reissue_invoice','propose_credit_memo','propose_payment_plan','request_balance','escalate',"
            "'attach_po','hold_dunning') AND NOT EXISTS (SELECT 1 FROM memories m WHERE m.source_decision_id=d.id"
            " AND m.approved_by LIKE 'outcome:%') ORDER BY d.id",
            (invoice_id,),
        ).fetchall()
        for r in rows:
            took = (date.fromisoformat(today) - date.fromisoformat(r["sim_date"])).days
            self.memory.write(
                "episodic",
                inv["customer_id"],
                f"{cust['name']}: {r['trigger'].replace('_', ' ')} on {invoice_id} → {r['action']}"
                f" ({r['rationale'][:140]}). Outcome: {outcome} {took} days later.",
                approved_by,
                r["trigger"],
                r["action"],
                r["id"],
            )
            if r["trigger"] == "ap_reject_missing_po":
                self.memory.set_needs_po(inv["customer_id"], r["id"])
                self.memory.add_note(inv["customer_id"], "AP rejects invoices without a PO number.", r["id"])
        return len(rows)
