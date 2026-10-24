"""Determinism: same seed (and same recordings) => same world digest, same decisions, same audit chain head."""

import dataclasses
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from settle import audit
from settle.bitdeer import Bitdeer, BitdeerError, safe
from settle.recorder import Recorder, ReplayMiss
from tests.conftest import make_world

TABLES = {
    "decisions": "SELECT work_item_id, sim_date, action, args_json, tier, status, correct FROM decisions ORDER BY id",
    "gl": "SELECT sim_date, debit_acct, credit_acct, amount_cents, ref_id, invoice_id FROM gl_entries ORDER BY id",
    "emails": "SELECT id, direction, subject, body FROM emails ORDER BY id",
    "activity": "SELECT sim_date, kind, title FROM activity ORDER BY id",
    "memories": "SELECT type, customer_id, content FROM memories ORDER BY id",
}


def snapshot(w):
    return {k: [tuple(r) for r in w.conn.execute(sql)] for k, sql in TABLES.items()}


def test_two_runs_same_seed_are_identical(cfg):
    a, b = make_world(cfg, oracle=True), make_world(cfg, oracle=True)
    a.advance(92)
    b.advance(92)
    assert audit.head(a.conn) == audit.head(b.conn)
    assert snapshot(a) == snapshot(b)
    assert a.state()["world_digest"] == b.state()["world_digest"]


def test_memory_ablation_shares_world_but_diverges(cfg):
    on, off = make_world(cfg, memory=True, oracle=True), make_world(cfg, memory=False, oracle=True)
    assert on.state()["world_digest"] == off.state()["world_digest"]
    on.advance(92)
    off.advance(92)
    assert audit.head(on.conn) != audit.head(off.conn)


def test_different_seed_changes_world_digest(cfg):
    a = make_world(cfg)
    b = make_world(dataclasses.replace(cfg, seed=cfg.seed + 1))
    assert a.state()["world_digest"] != b.state()["world_digest"]


def test_eval_reports_reproducibility(cfg):
    from settle.eval import run_ablation

    res = run_ablation(cfg)
    assert res["determinism"]["identical"] is True
    assert res["runs"][0]["trace"]["decision_provenance_coverage"] == 1.0


class ScriptedClaude:
    """Stands in for the Anthropic API: a fixed, valid submit_decision for every request."""

    def __init__(self):
        self.calls = 0
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls += 1
        raw = {
            "action": "no_action",
            "args_json": "{}",
            "rationale": "scripted",
            "evidence": [],
            "memory_ids": [],
            "confidence": 0.95,
            "trigger": "other",
        }
        return NS(
            content=[NS(type="tool_use", name="submit_decision", input=raw, id="t")],
            stop_reason="tool_use",
            usage=NS(input_tokens=10, output_tokens=5),
        )


def test_claude_run_replays_byte_for_byte_without_network(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    live_cfg = dataclasses.replace(cfg, agent_kind="claude")
    live = make_world(live_cfg, oracle=True)
    fake = ScriptedClaude()
    live.agent.client = fake
    live.advance(40)
    assert fake.calls > 0
    assert live.conn.execute("SELECT COUNT(*) FROM agent_runs WHERE replay='live'").fetchone()[0] == fake.calls

    replay = make_world(dataclasses.replace(live_cfg, replay=True), oracle=True)
    assert replay.agent.client is None  # no API client exists in replay mode
    replay.advance(40)
    assert audit.head(replay.conn) == audit.head(live.conn)
    a, b = snapshot(replay), snapshot(live)
    assert "REPLAY" in a["activity"][0][2]  # the deployment banner says so; it is display-only, not hashed
    a["activity"], b["activity"] = a["activity"][1:], b["activity"][1:]
    assert a == b
    assert replay.conn.execute("SELECT COUNT(*) FROM agent_runs WHERE replay='miss'").fetchone()[0] == 0
    assert replay.conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0


# ---- recorder + Bitdeer ------------------------------------------------------------------------------


def test_recorder_replay_miss_raises_and_live_records(tmp_path):
    rec = Recorder(tmp_path / "r.json")
    key, val = rec.lookup("k", {"a": 1})
    assert val is None
    rec.put("k", key, [1, 2])
    replay = Recorder(tmp_path / "r.json", replay=True)
    assert replay.lookup("k", {"a": 1})[1] == [1, 2]
    with pytest.raises(ReplayMiss):
        replay.lookup("k", {"a": 2})


def bitdeer_with(handler, tmp_path, replay=False, key="bd-key"):
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api-inference.bitdeer.ai/v1")
    return Bitdeer(
        key,
        "unused",
        "deepseek-ai/DeepSeek-V4.1-Flash",
        "BAAI/bge-reranker-v2-m3",
        Recorder(tmp_path / "r.json", replay=replay),
        http=http,
    )


def test_bitdeer_rerank_orders_by_score_then_index_and_records(tmp_path):
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append((req.url.path, req.headers["authorization"], body))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.5},
                ]
            },
        )

    bd = bitdeer_with(handler, tmp_path)
    assert bd.rerank("q", ["a", "b", "c"], 3) == [2, 0, 1]
    path, auth, body = seen[0]
    assert path.endswith("/rerank") and auth == "Bearer bd-key" and body["model"] == "BAAI/bge-reranker-v2-m3"
    # replay: no transport available, identical answer
    replay = bitdeer_with(lambda r: httpx.Response(500), tmp_path, replay=True, key=None)
    assert replay.rerank("q", ["a", "b", "c"], 3) == [2, 0, 1]


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(503, text="busy"),
        httpx.Response(200, json={"nope": 1}),
        httpx.Response(200, json={"results": [{"index": 9, "relevance_score": 1}]}),
    ],
)
def test_bitdeer_bad_responses_degrade_to_default(tmp_path, resp):
    bd = bitdeer_with(lambda r: resp, tmp_path)
    order, err = safe(lambda: bd.rerank("q", ["a", "b"], 2), None, "rerank")
    assert order is None and err


def test_bitdeer_classify_maps_free_text_to_label(tmp_path):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Label: ACK."}}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 2},
            },
        )

    bd = bitdeer_with(handler, tmp_path)
    assert bd.classify_intent("Accepted", "scheduled for payment") == "ack"
    assert bd.usage["input_tokens"] == 30


def test_bitdeer_without_key_raises(tmp_path):
    bd = bitdeer_with(lambda r: httpx.Response(200, json={}), tmp_path, key=None)
    with pytest.raises(BitdeerError):
        bd.rerank("q", ["a", "b"], 1)


def test_torn_recording_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "r.jsonl"
    rec = Recorder(path)
    key, _ = rec.lookup("k", {"a": 1})
    rec.put("k", key, 1)
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"kind": "k", "key": "torn-by-a-crash')  # partial final line
    again = Recorder(path)
    assert again.skipped_lines == 1 and again.lookup("k", {"a": 1})[1] == 1
    key2, _ = again.lookup("k", {"a": 2})
    again.put("k", key2, 2)  # appending after a torn line still works
    assert Recorder(path).lookup("k", {"a": 2})[1] == 2


def test_recorder_is_append_only(tmp_path):
    path = tmp_path / "r.jsonl"
    rec = Recorder(path)
    for i in range(50):
        k, _ = rec.lookup("k", {"i": i})
        rec.put("k", k, i)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 50
    assert len(Recorder(path).data["k"]) == 50


class JitteryClaude(ScriptedClaude):
    """Answers after a random delay so concurrent deliberations finish in a scrambled order."""

    def create(self, **kw):
        import random
        import time

        time.sleep(random.uniform(0, 0.01))
        return super().create(**kw)


def test_concurrent_deliberation_is_deterministic(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    heads, threads_seen = [], set()
    for workers in (1, 8):
        c = dataclasses.replace(cfg, agent_kind="claude", agent_concurrency=workers, cache_dir=tmp_path / f"c{workers}")
        w = make_world(c, oracle=True)
        fake = JitteryClaude()
        original = fake.create

        def tracking(_original=original, **kw):
            import threading

            threads_seen.add(threading.current_thread().name)
            return _original(**kw)

        fake.beta.messages.create = tracking
        w.agent.client = fake
        w.advance(20)
        heads.append(audit.head(w.conn))
    assert heads[0] == heads[1]
    assert any(name.startswith("settle-agent") for name in threads_seen)  # really ran in parallel
