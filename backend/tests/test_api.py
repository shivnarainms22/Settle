def test_state_and_reset(client):
    s = client.get("/api/state").json()
    assert s["sim_date"] == "2026-07-01" and s["month"] == 1 and s["agent_kind"] == "heuristic"
    assert s["kpis"]["open_ar_cents"] > 0
    s = client.post("/api/sim/reset", json={"memory": False}).json()
    assert s["memory_enabled"] is False and s["day_index"] == 0


def test_advance_produces_activity_and_validates_body(client):
    assert client.post("/api/sim/advance", json={}).status_code == 400
    assert client.post("/api/sim/advance", json={"days": 0}).status_code == 422
    s = client.post("/api/sim/advance", json={"days": 7}).json()
    assert s["sim_date"] == "2026-07-08"
    acts = client.get("/api/activity?after_id=0").json()
    assert acts and acts == sorted(acts, key=lambda a: a["id"])
    assert any(a["kind"] == "decision" for a in acts)


def test_approval_flow_and_decision_detail(client):
    client.post("/api/sim/advance", json={"to": "month_end"})
    pend = client.get("/api/approvals").json()
    assert pend, "month 1 should leave something for a human"
    cm = next(p for p in pend if p["action"] == "propose_credit_memo")
    assert cm["tier"] == 2 and cm["tier_reasons"]
    r = client.post(f"/api/approvals/{cm['id']}", json={"verdict": "approve", "approver": "dana"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    again = client.post(f"/api/approvals/{cm['id']}", json={"verdict": "approve"})
    assert again.status_code == 400
    det = client.get(f"/api/decisions/{cm['id']}").json()
    assert det["gl_entries"] and det["audit"] and det["evidence_resolved"]
    assert client.get("/api/decisions/999999").status_code == 404
    assert client.post("/api/approvals/999999", json={"verdict": "approve"}).status_code == 404


def test_bad_verdict_is_400(client):
    client.post("/api/sim/advance", json={"to": "month_end"})
    pid = client.get("/api/approvals").json()[0]["id"]
    assert client.post(f"/api/approvals/{pid}", json={"verdict": "yolo"}).status_code == 422
    # the approver is always the authenticated user: a body field can't impersonate outcome-based learning
    client.post(f"/api/approvals/{pid}", json={"verdict": "reject", "approver": "outcome:paid", "note": "no"})
    assert client.get(f"/api/decisions/{pid}").json()["approver"] == "dana"
    pid = client.get("/api/approvals").json()[0]["id"]
    assert client.post(f"/api/approvals/{pid}", json={"verdict": "edit", "action": "launch"}).status_code == 422


def test_customers_playbooks_ledger_audit(client):
    client.post("/api/sim/advance", json={"days": 35})
    cs = client.get("/api/customers").json()
    assert len(cs) == 12
    det = client.get("/api/customers/C-02").json()
    assert det["invoices"] and det["emails"] and "profile" in det
    assert client.get("/api/customers/C-99").status_code == 404
    pbs = client.get("/api/playbooks").json()
    assert pbs, "weekly consolidation should have proposed playbooks by day 35"
    r = client.post(f"/api/playbooks/{pbs[0]['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert client.post(f"/api/playbooks/{pbs[0]['id']}/approve").status_code == 400
    assert client.post("/api/playbooks/999/disable").status_code == 404
    tb = client.get("/api/ledger").json()["accounts"]
    assert sum(a["debit_cents"] for a in tb) == sum(a["credit_cents"] for a in tb)
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_eval_endpoints(client):
    assert client.get("/api/eval").status_code == 404
    res = client.post("/api/eval/run", json={}).json()
    assert len(res["runs"]) == 2 and len(res["runs"][0]["months"]) == 3
    assert client.get("/api/eval").json()["seed"] == res["seed"]


def test_trace_provenance_flag_and_forecast_endpoints(client):
    client.post("/api/sim/advance", json={"days": 33})
    for pb in client.get("/api/playbooks").json():
        assert client.post(f"/api/playbooks/{pb['id']}/approve").status_code == 200
    client.post("/api/sim/advance", json={"days": 20})
    s = client.get("/api/state").json()
    assert len(s["audit_head"]) == 64 and len(s["world_digest"]) == 64
    assert client.get("/api/audit/verify").json()["head"] == s["audit_head"]
    t = client.get("/api/trace", params={"ref": "invoice:INV-1080"}).json()
    assert t["count"] > 0 and [e["id"] for e in t["events"]] == sorted(e["id"] for e in t["events"])
    assert client.get("/api/trace", params={"ref": "nonsense"}).status_code == 400
    dec = next(d for d in client.get("/api/decisions?limit=500").json() if d["source"] == "playbook")
    det = client.get(f"/api/decisions/{dec['id']}").json()
    assert det["agent_run"]["input_verified"] is True and det["agent_run"]["component"] == "playbook"
    assert det["trace"][0]["event_type"] == "decision"
    assert client.post(f"/api/decisions/{dec['id']}/flag", json={"note": ""}).status_code == 400
    r = client.post(f"/api/decisions/{dec['id']}/flag", json={"note": "wrong for this customer", "approver": "dana"})
    assert r.status_code == 200 and r.json()["playbook_suspended"] == dec["playbook_id"]
    assert client.post("/api/decisions/999999/flag", json={"note": "x"}).status_code == 404
    fc = client.get("/api/forecast").json()
    assert len(fc["weeks"]) == 4 and fc["snapshots"]


def test_verify_endpoint(client):
    client.post("/api/sim/advance", json={"days": 20})
    rep = client.get("/api/verify").json()
    assert rep["ok"] is True and len(rep["head"]) == 64
    assert {c["name"] for c in rep["checks"]} >= {"chain", "policy_replay", "invoice_replay", "memory"}
