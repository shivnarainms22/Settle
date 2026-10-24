import pytest

from settle.models import Decision
from settle.policy import PolicyContext, assign_tier

STD = PolicyContext("standard", "acme.com", "****8812")
KEY = PolicyContext("key_account", "globex-industrial.com", "****4417")


def d(action, args=None, confidence=0.95, source="agent", playbook_id=None):
    return Decision(
        action=action, args=args or {}, rationale="r", confidence=confidence, source=source, playbook_id=playbook_id
    )


def test_reminder_is_tier0():
    assert assign_tier(d("send_reminder", {"invoice_id": "INV-1"}), STD)[0] == 0


def test_reissue_on_key_account_is_tier1_not_tier2():
    tier, _ = assign_tier(d("reissue_invoice", {"invoice_id": "INV-1", "changes": {"po_number": "4471"}}), KEY)
    assert tier == 1


def test_playbook_action_on_key_account_is_tier0():
    tier, reasons = assign_tier(d("reissue_invoice", {}, source="playbook", playbook_id=4), KEY)
    assert tier == 0 and "playbook #4" in reasons[0]


def test_large_credit_memo_needs_approval():
    tier, reasons = assign_tier(d("propose_credit_memo", {"invoice_id": "I", "amount_cents": 320_000}), STD)
    assert tier == 2 and "$3,200.00" in reasons[0]


def test_small_credit_memo_is_tier1():
    assert assign_tier(d("propose_credit_memo", {"invoice_id": "I", "amount_cents": 50_000}), STD)[0] == 1


def test_low_confidence_needs_approval():
    assert assign_tier(d("send_reminder", {}, confidence=0.5), STD)[0] == 2


@pytest.mark.parametrize("conf,tier", [(0.95, 1), (0.85, 2), (0.6, 2)])
def test_agent_cash_match_thresholds(conf, tier):
    dec = d(
        "apply_payment",
        {"bank_line_id": "B-1", "allocations": [{"invoice_id": "I", "amount_cents": 100}]},
        confidence=conf,
    )
    assert assign_tier(dec, STD)[0] == tier


def test_deterministic_cash_match_tier0_even_on_key_account():
    dec = d(
        "apply_payment",
        {"allocations": [{"invoice_id": "I", "amount_cents": 100}]},
        confidence=1.0,
        source="deterministic",
    )
    assert assign_tier(dec, KEY)[0] == 0


def test_agent_money_moving_on_key_account_is_tier2():
    dec = d("propose_payment_plan", {"installments": [{"date": "2026-08-01", "amount_cents": 1000}]})
    assert assign_tier(dec, KEY)[0] == 2


def test_unverified_sender_domain_blocks_anything():
    ctx = PolicyContext("standard", "acme.com", "****8812", sender_domain="acme-c0rp.com")
    tier, reasons = assign_tier(d("no_action", {}), ctx)
    assert tier == 3 and "acme-c0rp.com" in reasons[0]


def test_refund_to_new_account_is_tier3_even_from_verified_domain():
    ctx = PolicyContext("standard", "acme.com", "****8812", sender_domain="acme.com")
    tier, reasons = assign_tier(d("issue_refund", {"amount_cents": 100, "to_account": "****9931"}), ctx)
    assert tier == 3 and any("****9931" in r for r in reasons)


def test_escalation_is_tier2():
    assert assign_tier(d("escalate", {"to": "sales", "pause_dunning": True}), KEY)[0] == 2


def test_plan_limits():
    inst = [{"date": "2026-08-01", "amount_cents": 400_000}] * 4
    assert assign_tier(d("propose_payment_plan", {"installments": inst}), STD)[0] == 2
    assert (
        assign_tier(d("propose_payment_plan", {"installments": inst[:3]}), PolicyContext("standard", "x.com", "1"))[0]
        == 2
    )  # 12k > 10k
    small = [{"date": "2026-08-01", "amount_cents": 200_000}] * 3
    assert assign_tier(d("propose_payment_plan", {"installments": small}), STD)[0] == 1


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        d("transfer_everything")
