"""Core value types shared by the agent, policy engine and executor."""

from dataclasses import dataclass, field

ACTIONS = (
    "send_reminder",
    "reissue_invoice",
    "propose_credit_memo",
    "propose_payment_plan",
    "apply_payment",
    "request_balance",
    "escalate",
    "hold_dunning",
    "issue_refund",
    "update_bank_details",
    "write_off",
    "attach_po",
    "request_dispute_evidence",
    "no_action",
)
MONEY_MOVING = {"propose_credit_memo", "propose_payment_plan", "apply_payment", "issue_refund", "write_off"}


@dataclass
class WorkItem:
    id: int
    sim_date: str
    kind: str  # overdue | email | bank_line | deduction | invoice_issue
    ref: str
    customer_id: str | None
    summary: str
    gt: dict = field(default_factory=dict)


@dataclass
class Decision:
    action: str
    args: dict
    rationale: str
    evidence: list[str] = field(default_factory=list)
    memory_ids: list[int] = field(default_factory=list)
    confidence: float = 0.5
    source: str = "agent"  # agent | playbook | deterministic
    playbook_id: int | None = None
    llm_calls: int = 0
    trigger: str = ""  # Settle's own classification of the situation, used to group memories into playbooks
    provenance: dict = field(default_factory=dict)  # which component decided, from what, how (see agent_runs)

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}")
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def check_shape(self) -> list[str]:
        """Structural validation of args (types and required keys), independent of database state. Any decision
        that fails this can never be executed; LLM output that fails it is rejected before it is recorded."""
        a, errs = self.args, []

        def is_int(v) -> bool:
            return isinstance(v, int) and not isinstance(v, bool)

        if not isinstance(a, dict):
            return ["args must be an object"]
        for key in ("invoice_id", "bank_line_id", "customer_id", "po_number", "to_account", "bank_account"):
            if key in a and a[key] is not None and not isinstance(a[key], str):
                errs.append(f"{key} must be a string")
        if "amount_cents" in a and not is_int(a["amount_cents"]):
            errs.append("amount_cents must be an integer")
        if self.action == "apply_payment":
            allocs = a.get("allocations")
            if not isinstance(allocs, list) or not allocs:
                errs.append("allocations must be a non-empty list")
            elif not all(
                isinstance(x, dict) and isinstance(x.get("invoice_id"), str) and is_int(x.get("amount_cents"))
                for x in allocs
            ):
                errs.append("each allocation needs invoice_id (string) and amount_cents (integer)")
            elif len({x["invoice_id"] for x in allocs}) != len(allocs):
                errs.append("allocations repeat an invoice")
        if self.action == "propose_payment_plan":
            inst = a.get("installments")
            if not isinstance(inst, list) or not inst:
                errs.append("installments must be a non-empty list")
            elif not all(
                isinstance(x, dict) and isinstance(x.get("date"), str) and is_int(x.get("amount_cents")) for x in inst
            ):
                errs.append("each installment needs date (YYYY-MM-DD) and amount_cents (integer)")
            else:
                from datetime import date

                try:
                    for x in inst:
                        date.fromisoformat(x["date"])
                except ValueError:
                    errs.append("installment dates must be YYYY-MM-DD")
        if self.action == "reissue_invoice" and not isinstance(a.get("changes", {}), dict):
            errs.append("changes must be an object")
        return errs

    def amount_cents(self) -> int | None:
        if self.check_shape():
            return None
        a = self.args
        if self.action == "apply_payment":
            return sum(int(x["amount_cents"]) for x in a.get("allocations", []))
        if self.action == "propose_payment_plan":
            return sum(int(x["amount_cents"]) for x in a.get("installments", []))
        if "amount_cents" in a:
            return int(a["amount_cents"])
        return None
