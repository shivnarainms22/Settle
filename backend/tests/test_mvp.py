"""MVP surface: auth & roles, separation of duties, autonomy modes, health, worklist, exports, advance-to-date."""

import csv
import io
import json

import pytest

from settle.auth import AuthError, Directory, check_approval
from settle.models import MONEY_MOVING
from tests.conftest import auth_headers


def test_every_api_route_needs_a_token_except_health_login_and_users(anon):
    assert anon.get("/api/state").status_code == 401
    assert anon.get("/api/stream").status_code == 401
    assert anon.get("/api/health").status_code == 200
    assert {u["username"] for u in anon.get("/api/users").json()} == {"dana", "sam", "vic"}
    assert all("password" not in u for u in anon.get("/api/users").json())
    assert anon.post("/api/login", json={"username": "dana", "password": "nope"}).status_code == 401
    assert anon.post("/api/login", json={"username": "ghost", "password": "demo"}).status_code == 401
    h = auth_headers(anon, "dana")
    token = h["Authorization"][7:]
    assert anon.get("/api/me", headers=h).json()["role"] == "controller"
    assert anon.get(f"/api/me?token={token}").json()["username"] == "dana"  # EventSource can't set headers
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert anon.get("/api/me", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    assert anon.get("/api/no-such-route", headers=h).status_code == 404


def test_tokens_expire_and_do_not_survive_a_different_secret(monkeypatch):
    d = Directory(secret="a")
    tok = d.login("dana", "demo")
    assert d.verify(tok).username == "dana"
    with pytest.raises(AuthError):
        Directory(secret="b").verify(tok)
    monkeypatch.setattr("settle.auth.time.time", lambda: 10**12)
    with pytest.raises(AuthError, match="expired"):
        d.verify(tok)


def test_directory_rejects_bad_users():
    with pytest.raises(ValueError, match="role"):
        Directory([{"username": "x", "password": "p", "role": "god"}])
    with pytest.raises(ValueError, match="reserved"):
        Directory([{"username": "outcome:paid", "password": "p", "role": "viewer"}])


def test_separation_of_duties_rules():
    d = Directory(secret="s")
    sam, vic, dana = d.users["sam"], d.users["vic"], d.users["dana"]
    check_approval(sam, 50_000, False, True)
    check_approval(dana, 10**9, True, True)
    with pytest.raises(AuthError, match="limit"):
        check_approval(sam, 100_001, False, True)
    with pytest.raises(AuthError, match="key accounts"):
        check_approval(sam, 1, True, True)
    check_approval(sam, 0, True, False)  # a reminder on a key account is not money moving
    with pytest.raises(AuthError, match="viewer"):
        check_approval(vic, 0, False, False)


def test_viewer_is_read_only_and_clerk_cannot_administer(client):
    vic, sam = auth_headers(client, "vic"), auth_headers(client, "sam")
    assert client.get("/api/state", headers=vic).status_code == 200
    assert client.post("/api/sim/advance", json={"days": 1}, headers=vic).status_code == 403
    assert client.post("/api/sim/reset", json={}, headers=sam).status_code == 403
    assert client.post("/api/autonomy", json={"mode": "shadow", "reason": "x"}, headers=sam).status_code == 403
    assert client.post("/api/sim/advance", json={"days": 1}, headers=sam).status_code == 200


def test_clerk_approvals_follow_limits_and_key_accounts(client):
    sam = auth_headers(client, "sam")
    client.post("/api/sim/advance", json={"to": "month_end"})
    tiers = {c["id"]: c["tier"] for c in client.get("/api/customers").json()}
    pending = client.get("/api/approvals").json()
    assert pending
    outcomes = set()
    for p in pending:
        blocked = (p["action"] in MONEY_MOVING and tiers[p["customer_id"]] == "key_account") or (
            p["amount_cents"] or 0
        ) > 100_000
        r = client.post(f"/api/approvals/{p['id']}", json={"verdict": "reject", "note": "t"}, headers=sam)
        assert (r.status_code == 403) == blocked, (p, r.text)
        outcomes.add(blocked)
        if not blocked:
            assert r.status_code == 200 and r.json()["approver"] == "sam"
    viewer = auth_headers(client, "vic")
    left = client.get("/api/approvals").json()
    if left:
        assert (
            client.post(f"/api/approvals/{left[0]['id']}", json={"verdict": "reject"}, headers=viewer).status_code
            == 403
        )


def test_clerk_cannot_launder_a_big_edit_through_a_small_decision(client):
    sam = auth_headers(client, "sam")
    client.post("/api/sim/advance", json={"to": "month_end"})
    tiers = {c["id"]: c["tier"] for c in client.get("/api/customers").json()}
    small = next((p for p in client.get("/api/approvals").json() if tiers[p["customer_id"]] != "key_account"), None)
    if small is None:
        pytest.skip("no non-key-account approval in month 1")
    inv = next((e.split(":", 1)[1] for e in small["evidence"] if e.startswith("invoice:")), "INV-1")
    body = {"verdict": "edit", "action": "write_off", "args": {"invoice_id": inv, "amount_cents": 5_000_000}}
    r = client.post(f"/api/approvals/{small['id']}", json=body, headers=sam)
    assert r.status_code == 403 and "limit" in r.json()["detail"]


def test_supervised_mode_queues_everything_and_shadow_executes_nothing(client):
    assert client.post("/api/autonomy", json={"mode": "supervised", "reason": ""}).status_code == 422
    r = client.post("/api/autonomy", json={"mode": "supervised", "reason": "quarter close freeze"})
    assert r.status_code == 200 and r.json()["changed_by"] == "dana" and r.json()["mode"] == "supervised"
    assert client.get("/api/state").json()["autonomy"] == "supervised"
    before = max([d["id"] for d in client.get("/api/decisions?limit=1").json()] or [0])
    client.post("/api/sim/advance", json={"days": 5})
    new = [d for d in client.get("/api/decisions?limit=1000").json() if d["id"] > before]
    assert new and all(d["tier"] >= 2 and d["status"] in ("pending_approval", "blocked") for d in new)
    assert all(any("supervised" in r for r in d["tier_reasons"]) or d["tier"] == 3 for d in new)

    client.post("/api/autonomy", json={"mode": "shadow", "reason": "pilot"})
    before = max(d["id"] for d in client.get("/api/decisions?limit=1").json())
    ledger_before = client.get("/api/ledger").json()
    client.post("/api/sim/advance", json={"days": 5})
    new = [d for d in client.get("/api/decisions?limit=1000").json() if d["id"] > before]
    assert new and {d["status"] for d in new} <= {"shadow", "blocked"} and any(d["status"] == "shadow" for d in new)
    # invoices still get issued by billing; but no agent action moved cash, credits or write-offs
    agent_accts = {"Cash", "Sales Returns & Allowances", "Bad Debt Expense", "Unapplied Cash"}

    def acct(tb):
        return {a["account"]: a for a in tb["accounts"] if a["account"] in agent_accts}

    assert acct(client.get("/api/ledger").json()) == acct(ledger_before)
    for d in new[:5]:
        assert not client.get(f"/api/decisions/{d['id']}").json()["gl_entries"]
    rep = client.get("/api/verify").json()
    assert rep["ok"] is True, [c for c in rep["checks"] if not c["ok"]]
    ev = client.get("/api/trace", params={"ref": "run"}).json()["events"]
    changes = [e for e in ev if e["event_type"] == "autonomy_changed"]
    assert [(e["event"]["from"], e["event"]["to"]) for e in changes] == [
        ("autonomous", "supervised"),
        ("supervised", "shadow"),
    ]


def test_health_reports_every_component(anon):
    h = anon.get("/api/health").json()
    assert h["ok"] is True and h["autonomy"] == "autonomous"
    assert {c["name"] for c in h["components"]} == {"database", "agent", "memory_index", "bitdeer", "recorder"}
    assert next(c for c in h["components"] if c["name"] == "agent")["status"] == "off"


def test_worklist_is_ranked_and_explained(client):
    client.post("/api/sim/advance", json={"days": 45})
    rows = client.get("/api/worklist?limit=20").json()
    assert rows and len(rows) <= 20
    assert [r["priority"] for r in rows] == sorted((r["priority"] for r in rows), reverse=True)
    assert all(r["reasons"] or r["risk"] == "low" for r in rows) and all(r["next_action"] for r in rows)
    assert all(r["balance_cents"] > 0 and r["status"] != "paid" for r in rows)


def test_audit_export_is_verifiable_jsonl(client):
    client.post("/api/sim/advance", json={"days": 10})
    r = client.get("/api/export/audit")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().split("\n")
    report = json.loads(lines[0])["verification"]
    events = [json.loads(x) for x in lines[1:]]
    assert report["ok"] is True and events[-1]["hash"] == report["head"]
    assert all(e["prev_hash"] == p["hash"] for p, e in zip(events, events[1:], strict=False))
    assert report["head"][:12] in r.headers["content-disposition"]


def test_decisions_csv_export_neutralises_formulas(client):
    from settle.api import _csv_safe

    assert _csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _csv_safe(["a", "b"]) == "a; b" and _csv_safe(3) == 3
    client.post("/api/sim/advance", json={"days": 10})
    r = client.get("/api/export/decisions.csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == len(client.get("/api/decisions?limit=1000").json())
    assert rows[0]["action"] and "rationale" in rows[0]


def test_advance_to_a_date(client):
    assert client.post("/api/sim/advance", json={"to": "2026-07-15"}).json()["sim_date"] == "2026-07-15"
    assert client.post("/api/sim/advance", json={"to": "2026-07-10"}).status_code == 400  # the past
    assert client.post("/api/sim/advance", json={"to": "someday"}).status_code == 400
    assert client.post("/api/sim/advance", json={"to": "2027-01-01"}).status_code == 400  # beyond the run


def test_import_starts_in_shadow_mode_by_default(client):
    samples = client.get("/api/import/samples").json()
    r = client.post(
        "/api/import", json={"invoices_csv": samples["ar_aging.csv"], "bank_csv": samples["bank_statement.csv"]}
    )
    assert r.json()["state"]["autonomy"] == "shadow"
    client.post("/api/sim/advance", json={"days": 14})
    assert all(d["status"] != "executed" for d in client.get("/api/decisions?limit=1000").json())
    assert client.get("/api/verify").json()["ok"] is True


def test_worklist_puts_overdue_cash_above_bigger_invoices_not_yet_due(world):
    rows = world.worklist(500)
    overdue = [r for r in rows if r["days_overdue"] > 14]
    not_due = [r for r in rows if r["days_overdue"] == 0 and r["status"] == "open" and not r["pending_decision_id"]]
    assert overdue and not_due
    pos = {r["invoice_id"]: i for i, r in enumerate(rows)}
    assert max(pos[r["invoice_id"]] for r in overdue) < min(pos[r["invoice_id"]] for r in not_due)
    assert not any("key account" in r["reasons"] for r in not_due)
    assert not any(" 1 days" in x or x.startswith("1 days") for r in rows for x in r["reasons"])


def test_shadow_mode_never_marks_disputes_or_writes_memory(world):
    from settle import verify as verify_mod
    from settle.executor import update_invoice

    world.set_autonomy("shadow", "dana", "pilot")
    profiles_before = [dict(r) for r in world.conn.execute("SELECT * FROM profiles ORDER BY customer_id")]
    for _ in range(25):  # covers the Calloway damaged-goods dispute and the Vireo churn threat
        world.step()
    shadow = world.conn.execute(
        "SELECT * FROM decisions WHERE status='shadow' AND trigger IN ('dispute','churn_risk')"
    ).fetchall()
    assert shadow, "the first 25 days include dispute and churn emails"
    assert world.conn.execute("SELECT COUNT(*) FROM invoices WHERE status='disputed'").fetchone()[0] == 0
    assert [dict(r) for r in world.conn.execute("SELECT * FROM profiles ORDER BY customer_id")] == profiles_before
    assert verify_mod.verify(world.conn)["ok"] is True
    # and the verifier catches it if a shadow decision ever does cause a side effect
    inv = next(e.split(":", 1)[1] for e in json_loads(shadow[0]["evidence_json"]) if e.startswith("invoice:"))
    update_invoice(world.conn, inv, {"status": "disputed"}, "settle:agent", shadow[0]["id"], "bug")
    rep = verify_mod.verify(world.conn)
    guard = next(c for c in rep["checks"] if c["name"] == "guardrails")
    assert not guard["ok"] and any("caused invoice_updated" in f for f in guard["examples"])


def json_loads(s):
    return json.loads(s) if s else []


def test_non_ascii_token_is_401_not_500(anon):
    assert anon.get("/api/me?token=abc.%C3%A9").status_code == 401
    with pytest.raises(AuthError):
        Directory(secret="s").verify("abc.é")


def test_demo_users_can_be_disabled_for_deploys(monkeypatch):
    monkeypatch.setenv("SETTLE_ALLOW_DEMO_USERS", "0")
    with pytest.raises(ValueError, match="SETTLE_USERS"):
        Directory()
    monkeypatch.setenv("SETTLE_USERS", '[{"username":"ana","password":"pw","role":"controller"}]')
    assert list(Directory().users) == ["ana"]


def test_clerk_cannot_flag_a_decision_they_could_not_approve(client):
    sam = auth_headers(client, "sam")
    client.post("/api/sim/advance", json={"to": "month_end"})
    tiers = {c["id"]: c["tier"] for c in client.get("/api/customers").json()}
    ds = client.get("/api/decisions?limit=1000").json()
    big = next(
        d
        for d in ds
        if d["status"] in ("executed", "approved")
        and (
            (d["amount_cents"] or 0) > 100_000
            or (tiers.get(d["customer_id"]) == "key_account" and d["action"] in MONEY_MOVING)
        )
    )
    r = client.post(f"/api/decisions/{big['id']}/flag", json={"note": "wrong"}, headers=sam)
    assert r.status_code == 403


def test_approvals_flag_decisions_the_world_has_overtaken(client):
    client.post("/api/sim/advance", json={"to": "2026-08-01"})
    pend = client.get("/api/approvals").json()
    assert all(isinstance(p["stale"], list) for p in pend)
    stale = [p for p in pend if p["stale"]]
    assert stale, "Pellucid's escalation is overtaken by its payment before month end"
    r = client.post(f"/api/approvals/{stale[0]['id']}", json={"verdict": "approve"})
    assert r.status_code == 400 and "stale" in r.json()["detail"]
    mem_before = len(client.get(f"/api/customers/{stale[0]['customer_id']}").json()["memories"])
    viewer = auth_headers(client, "vic")
    assert (
        client.post(f"/api/approvals/{stale[0]['id']}", json={"verdict": "dismiss"}, headers=viewer).status_code == 403
    )
    ok = client.post(f"/api/approvals/{stale[0]['id']}", json={"verdict": "dismiss"})
    assert ok.status_code == 200 and ok.json()["status"] == "superseded"
    # closing an overtaken decision is bookkeeping: no correction memory that would teach the agent the wrong lesson
    assert len(client.get(f"/api/customers/{stale[0]['customer_id']}").json()["memories"]) == mem_before
    fresh = next((p for p in client.get("/api/approvals").json() if not p["stale"]), None)
    if fresh:
        assert client.post(f"/api/approvals/{fresh['id']}", json={"verdict": "dismiss"}).status_code == 400
    assert client.get("/api/verify").json()["ok"] is True


def test_decision_detail_calls_out_ignored_prompt_injection(client):
    client.post("/api/sim/advance", json={"to": "2026-08-02"})
    ds = client.get("/api/decisions?limit=1000").json()
    flagged = []
    for d in ds:
        if d["customer_name"] and d["customer_name"].startswith("Halvorsen") and d["work_item"]["kind"] == "email":
            det = client.get(f"/api/decisions/{d['id']}").json()
            flagged += det["security_flags"]
            assert det["action"] not in ("write_off", "propose_credit_memo") or det["status"] != "executed"
    assert flagged and "not obeyed" in flagged[0]
    benign = next(d for d in ds if d["action"] == "send_reminder")
    assert client.get(f"/api/decisions/{benign['id']}").json()["security_flags"] == []
