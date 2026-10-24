"""Scale benchmark (offline, free): how the full 92-day pipeline + end-to-end verification grows with the customer base,
and how much concurrent deliberation saves when each agent call has real LLM-like latency.

    uv run python -m settle.bench                 # scales 1, 5, 10, 25 + concurrency comparison
"""

import dataclasses
import json
import sys
import time

from settle import verify
from settle.agent import HeuristicAgent
from settle.config import load_config
from settle.db import connect
from settle.engine import World

SIMULATED_LLM_LATENCY_S = 0.2


class LatencyAgent(HeuristicAgent):
    """The deterministic agent, plus a fixed sleep per decision standing in for an LLM round trip. Labeled as a
    simulation in the output: it measures orchestration, not model quality."""

    kind = "heuristic"

    def decide(self, ctx):
        time.sleep(SIMULATED_LLM_LATENCY_S)
        return super().decide(ctx)


def offline_cfg(**overrides):
    return dataclasses.replace(
        load_config(),
        agent_kind="heuristic",
        moss_project_id=None,
        moss_project_key=None,
        bitdeer_api_key=None,
        persona_llm=False,
        replay=False,
        **overrides,
    )


def run_scale(scale: int, days: int = 92) -> dict:
    w = World(offline_cfg(), connect(":memory:"), oracle=True)
    t0 = time.perf_counter()
    w.reset(memory=True, scale=scale)
    t1 = time.perf_counter()
    w.advance(days)
    t2 = time.perf_counter()
    rep = verify.verify(w.conn)
    t3 = time.perf_counter()
    c = w.conn
    n = {
        k: c.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0]
        for k in ("customers", "invoices", "decisions", "audit_log", "memories")
    }
    return {
        "scale": scale,
        **n,
        "seed_s": round(t1 - t0, 2),
        "sim_s": round(t2 - t1, 2),
        "verify_s": round(t3 - t2, 2),
        "decisions_per_s": round(n["decisions"] / max(t2 - t1, 1e-9)),
        "verified": rep["ok"],
    }


def run_concurrency(workers: int, days: int = 10, scale: int = 5) -> dict:
    w = World(offline_cfg(agent_concurrency=workers), connect(":memory:"), oracle=True)
    w.reset(memory=True, scale=scale)
    w.agent = LatencyAgent()
    t0 = time.perf_counter()
    w.advance(days)
    dt = time.perf_counter() - t0
    agent_calls = w.conn.execute("SELECT COUNT(*) FROM decisions WHERE source='agent'").fetchone()[0]
    from settle import audit

    return {"workers": workers, "agent_calls": agent_calls, "wall_s": round(dt, 2), "head": audit.head(w.conn)}


def main(scales=(1, 5, 10, 25)) -> int:
    report = {"scales": [], "concurrency": None, "simulated_llm_latency_ms": SIMULATED_LLM_LATENCY_S * 1000}
    print(
        f"{'scale':>5} {'customers':>9} {'invoices':>8} {'decisions':>9} {'audit':>7} {'memories':>8} "
        f"{'seed s':>7} {'sim s':>7} {'verify s':>8} {'dec/s':>6}  verified"
    )
    ok = True
    for s in scales:
        r = run_scale(s)
        report["scales"].append(r)
        ok &= r["verified"]
        print(
            f"{r['scale']:>5} {r['customers']:>9} {r['invoices']:>8} {r['decisions']:>9} {r['audit_log']:>7} "
            f"{r['memories']:>8} {r['seed_s']:>7} {r['sim_s']:>7} {r['verify_s']:>8} {r['decisions_per_s']:>6}  "
            f"{r['verified']}"
        )
    print(
        f"\nConcurrent deliberation, {SIMULATED_LLM_LATENCY_S * 1000:.0f} ms simulated LLM latency per call,"
        " 60 customers, 10 days:"
    )
    one, eight = run_concurrency(1), run_concurrency(8)
    for r in (one, eight):
        print(f"  workers={r['workers']}: {r['agent_calls']} agent calls in {r['wall_s']} s")
    same = one["head"] == eight["head"]
    report["concurrency"] = {
        "workers_1_s": one["wall_s"],
        "workers_8_s": eight["wall_s"],
        "agent_calls": one["agent_calls"],
        "speedup": round(one["wall_s"] / eight["wall_s"], 1),
        "identical_audit_head": same,
        "customers": 60,
        "days": 10,
    }
    path = load_config().cache_dir / "bench_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  speedup {one['wall_s'] / eight['wall_s']:.1f}x; identical audit head: {same}")
    return 0 if ok and same else 1


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    sys.exit(main(tuple(args) if args else (1, 5, 10, 25)))
