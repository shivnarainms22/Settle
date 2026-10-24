import sys
import types

import pytest

from settle.db import connect, create_schema
from settle.memory import FtsIndex, MemoryStore, MossIndex


def _conn():
    conn = connect(":memory:")
    create_schema(conn)
    conn.execute("INSERT INTO customers VALUES('C-1','Acme','standard','acme.com','ap@acme.com','****1','Pat')")
    conn.execute("INSERT INTO profiles(customer_id) VALUES('C-1')")
    return conn


def test_fts_search_scoped_to_customer_and_handles_punctuation():
    conn = _conn()
    store = MemoryStore(conn, True, FtsIndex(conn))
    a = store.write("episodic", "C-1", "Globex AP rejected INV-1031 for missing PO 4471", "dana", "t", "a")
    store.write("episodic", "C-2", "Another customer rejected an invoice", "dana", "t", "a")
    hits = store.search("rejected: missing PO?!", "C-1")
    assert [m["id"] for m in hits] == [a]
    assert store.search("!!!", "C-1") == []


def test_disabled_store_is_inert():
    conn = _conn()
    store = MemoryStore(conn, False, FtsIndex(conn))
    assert store.write("episodic", "C-1", "x", "me") is None
    store.observe_payment("C-1", 20, "INV-1")
    assert store.add_alias("C-1", "ACME HOLDINGS", 1) is False
    assert store.search("x", "C-1") == []
    assert store.profile("C-1")["payments_observed"] == 0
    assert store.consolidate() == []


def test_reliable_late_payer_needs_three_consistent_payments():
    conn = _conn()
    store = MemoryStore(conn, True, FtsIndex(conn))
    for late in (21, 22):
        store.observe_payment("C-1", late, "INV-1")
    assert store.profile("C-1")["reliable_late_payer"] is False
    store.observe_payment("C-1", 20, "INV-2")
    assert store.profile("C-1")["reliable_late_payer"] is True
    store.observe_payment("C-1", 40, "INV-3")  # erratic now
    assert store.profile("C-1")["reliable_late_payer"] is False
    # every profile change is audited with old and new values
    from settle import audit as audit_mod

    ev = [e for e in audit_mod.trace(conn, "customer:C-1") if e["event"]["field"] == "late_days"]
    assert len(ev) == 4 and all(e["event_type"] == "profile_updated" for e in ev)
    assert ev[-1]["event"]["old"] == "[21,22,20]" and ev[-1]["event"]["new"] == "[21,22,20,40]"


def test_reminder_responsive_customer_is_never_a_reliable_late_payer():
    """Correlation is not cause: a customer who always pays ~2 days after a reminder pays BECAUSE of the reminder."""
    conn = _conn()
    store = MemoryStore(conn, True, FtsIndex(conn))
    assert "dunning_guidance" not in store.profile("C-1")  # nothing learned yet: profile unchanged
    for i, late in enumerate((20, 21, 19)):
        store.observe_payment("C-1", late, f"INV-{i}", reminders=3, days_after_reminder=2)
    p = store.profile("C-1")
    assert p["reliable_late_payer"] is False and p["reminder_response"].startswith("3/3")
    assert p["dunning_guidance"].startswith("reminder-responsive")
    other = _conn()
    s2 = MemoryStore(other, True, FtsIndex(other))
    for i, late in enumerate((20, 21, 19)):
        s2.observe_payment("C-1", late, f"INV-{i}", reminders=3, days_after_reminder=6)
    assert s2.profile("C-1")["reliable_late_payer"] is True


@pytest.fixture
def fake_moss(monkeypatch):
    state = {"docs": {}, "fail": False}

    class Session:
        async def add_docs(self, docs):
            if state["fail"]:
                raise ConnectionError("moss down")
            for d in docs:
                state["docs"][d.id] = d.text

        async def query(self, q, opts):
            if state["fail"]:
                raise ConnectionError("moss down")
            return types.SimpleNamespace(docs=[types.SimpleNamespace(id=i) for i in state["docs"]])

    class Client:
        def __init__(self, *a):
            pass

        async def session(self, name):
            return Session()

    mod = types.ModuleType("moss")
    mod.MossClient = Client
    mod.DocumentInfo = lambda id, text, metadata: types.SimpleNamespace(id=id, text=text)
    mod.QueryOptions = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "moss", mod)
    return state


def test_moss_index_used_then_falls_back_to_fts_on_failure(fake_moss, tmp_path):
    conn = _conn()
    from settle.recorder import Recorder

    rec = Recorder(tmp_path / "rec.json")
    idx = MossIndex(conn, "pid", "key", "s", rec)
    store = MemoryStore(conn, True, idx)
    a = store.write("episodic", "C-1", "Acme pays 21 days late", "outcome:paid")
    assert fake_moss["docs"] == {str(a): "Acme pays 21 days late"}
    assert [m["id"] for m in store.search("late", "C-1")] == [a]
    assert store.backend == "moss"
    fake_moss["fail"] = True
    # an unrecorded query hits the network, fails, and is served by FTS (SQLite is the source of truth)
    assert [m["id"] for m in store.search("acme pays", "C-1")] == [a]
    assert store.backend == "sqlite-fts" and "moss down" in idx.failed_reason


def test_moss_query_is_recorded_and_replays_without_network(fake_moss, tmp_path):
    from settle.recorder import Recorder

    conn = _conn()
    live = MemoryStore(conn, True, MossIndex(conn, "pid", "key", "s", Recorder(tmp_path / "rec.json")))
    a = live.write("episodic", "C-1", "Acme pays 21 days late", "outcome:paid")
    assert [m["id"] for m in live.search("late", "C-1")] == [a]
    fake_moss["fail"] = True  # network gone; replay must not touch it
    replay_idx = MossIndex(conn, None, None, "s", Recorder(tmp_path / "rec.json", replay=True))
    replay = MemoryStore(conn, True, replay_idx)
    assert [m["id"] for m in replay.search("late", "C-1")] == [a]
    assert replay.backend == "moss" and replay_idx.failed_reason is None
