"""Autonomy tiers, enforced in code after the agent decides. Precedence: 3 -> 2 -> 0 -> 1."""

from dataclasses import dataclass

from settle.models import MONEY_MOVING, Decision

CREDIT_MEMO_LIMIT_CENTS = 50_000
PLAN_MAX_INSTALLMENTS = 3
PLAN_LIMIT_CENTS = 1_000_000
MIN_CONFIDENCE = 0.7
MIN_CASH_MATCH_CONFIDENCE = 0.9


@dataclass(frozen=True)
class PolicyContext:
    customer_tier: str | None  # "standard" | "key_account" | None (unknown payer)
    verified_domain: str | None
    bank_account_on_file: str | None
    sender_domain: str | None = None  # set when the work item is an inbound email


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def assign_tier(d: Decision, ctx: PolicyContext) -> tuple[int, list[str]]:
    a = d.args

    t3 = []
    if d.action == "update_bank_details":
        t3.append("changing customer bank details is never autonomous")
    if d.action == "issue_refund":
        t3.append("refunds are never autonomous")
    to_account = a.get("to_account") or a.get("bank_account")
    if to_account and ctx.bank_account_on_file and to_account != ctx.bank_account_on_file:
        t3.append(f"payment instruction to {to_account} does not match account on file {ctx.bank_account_on_file}")
    if ctx.sender_domain and ctx.verified_domain and ctx.sender_domain.lower() != ctx.verified_domain.lower():
        t3.append(f"sender domain {ctx.sender_domain} is not the verified domain {ctx.verified_domain}")
    if t3:
        return 3, t3

    t2 = []
    amount = d.amount_cents() or 0
    if d.action == "propose_credit_memo" and amount > CREDIT_MEMO_LIMIT_CENTS:
        t2.append(f"credit memo {_money(amount)} > {_money(CREDIT_MEMO_LIMIT_CENTS)}")
    if d.action == "write_off":
        t2.append("write-offs need approval")
    if d.action == "propose_payment_plan":
        n = len(a.get("installments", []))
        if n > PLAN_MAX_INSTALLMENTS:
            t2.append(f"payment plan has {n} installments > {PLAN_MAX_INSTALLMENTS}")
        if amount > PLAN_LIMIT_CENTS:
            t2.append(f"payment plan total {_money(amount)} > {_money(PLAN_LIMIT_CENTS)}")
    if d.action == "escalate":
        t2.append(f"escalation hands the item to {a.get('to', 'a human')}")
        if a.get("pause_dunning") and ctx.customer_tier == "key_account":
            t2.append("pausing dunning on a key account")
    if d.action in MONEY_MOVING and ctx.customer_tier == "key_account" and d.source == "agent":
        t2.append("money-moving action on a key account")
    if d.confidence < MIN_CONFIDENCE:
        t2.append(f"confidence {d.confidence:.2f} < {MIN_CONFIDENCE}")
    elif d.action == "apply_payment" and d.source == "agent" and d.confidence < MIN_CASH_MATCH_CONFIDENCE:
        t2.append(f"agent cash match confidence {d.confidence:.2f} < {MIN_CASH_MATCH_CONFIDENCE}")
    if t2:
        return 2, t2

    if d.source == "playbook":
        return 0, [f"action from active playbook #{d.playbook_id}"]
    if d.action in ("send_reminder", "hold_dunning", "no_action"):
        return 0, [f"{d.action} is routine"]
    if d.action == "apply_payment" and d.source == "deterministic":
        return 0, ["exact deterministic cash match"]
    return 1, [f"{d.action} within policy limits; human notified"]
