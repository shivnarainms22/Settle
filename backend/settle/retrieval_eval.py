"""Does each retrieval component earn its place? Measured, not assumed.

Setting: cross-customer precedent search ("how did we handle a situation like this before?"). That is what the
agent's search_memory tool does when it omits customer_id, and it is the hard case: the right memories compete with
~100 near-identical "paid N days late" observations, and new situations are described in different words than the
memories that record them.

Corpus: the real episodic memory of a 92-day memory-ON run (unmodified). Queries: 3 paraphrases per situation,
written the way a customer or controller would describe it (deliberately not copying the memory wording).
Relevance: a memory is relevant if it records that situation (by its trigger/action/outcome fields).

Systems: SQLite FTS5 (bm25) | Moss (hybrid, alpha 0.6) | each + Bitdeer bge-reranker-v2-m3 over its top 15.
Every external call goes through the Recorder, so a re-run replays the identical numbers offline.

    uv run python -m settle.retrieval_eval
"""

import dataclasses
import json
import time

from settle.bench import offline_cfg
from settle.bitdeer import Bitdeer, safe
from settle.config import load_config
from settle.db import connect
from settle.engine import World
from settle.memory import FtsIndex, MossIndex, corpus_digest, fuse
from settle.recorder import Recorder

K = 5
POOL = 15

SITUATIONS = {
    "po_rejection": (
        lambda m: m["trigger"] == "ap_reject_missing_po" or m["action"] == "attach_po",
        [
            "their payables department bounced our bill because there was no purchase order reference on it",
            "customer says the invoice cannot be processed until we quote their order number",
            "AP portal refused the invoice, asking for the buyer's PO",
        ],
    ),
    "damaged_goods": (
        lambda m: m["trigger"] == "dispute" or m["action"] == "propose_credit_memo",
        [
            "a few of the shipped parts were broken on arrival and they want money back for those units",
            "customer refuses to pay in full because some items in the delivery were defective",
            "partial credit for faulty hardware in the shipment",
        ],
    ),
    "installments": (
        lambda m: m["trigger"] == "plan_request" or m["action"] == "propose_payment_plan",
        [
            "customer is short on cash and wants to pay the bill over several months",
            "they asked if they can break the balance into monthly chunks",
            "spread the payment out because of a cash flow problem",
        ],
    ),
    "unearned_discount": (
        lambda m: m["trigger"] == "short_pay" or m["action"] == "request_balance",
        [
            "they paid a little less than the invoice and claimed a prompt payment discount even though they paid late",
            "deduction taken from the remittance that our terms don't allow",
            "payment came in two percent short",
        ],
    ),
    "payer_alias": (
        lambda m: m["trigger"] == "alias_learned",
        [
            "money arrived from a bank account name we don't recognize, probably a parent company paying",
            "wire from an abbreviated shared-services entity with no remittance advice",
            "which customer is behind this unfamiliar payer name on the bank statement",
        ],
    ),
    "reliable_late_payer": (
        lambda m: m["action"] == "hold_dunning",
        [
            "this client always pays about three weeks after the due date, should we keep chasing them",
            "consistently late but never misses a payment, hold off on collections",
            "stop sending reminders to a customer who reliably pays late",
        ],
    ),
    "churn_risk": (
        lambda m: m["trigger"] == "churn_risk",
        [
            "customer is unhappy with service and is thinking about leaving us for another supplier",
            "they threatened not to renew the contract over this bill",
            "relationship at risk, executive wants to talk before paying",
        ],
    ),
    "pattern_drift": (
        lambda m: m["approved_by"] == "outcome:missed_forecast",
        [
            "a customer who used to pay predictably is suddenly much later than expected",
            "our payment forecast for this account was wrong, they did not pay when we thought",
            "learned payment habit no longer holds after their accounting system change",
        ],
    ),
}


def build_corpus():
    world = World(offline_cfg(), connect(":memory:"), oracle=True)
    world.reset(memory=True)
    world.advance(92)
    mems = {r["id"]: dict(r) for r in world.conn.execute("SELECT * FROM memories ORDER BY id")}
    return world, mems


def _metrics(ranked: list[int], relevant: set[int]) -> tuple[float, float]:
    top = ranked[:K]
    recall = len(relevant & set(top)) / min(len(relevant), K)
    rr = next((1 / (i + 1) for i, mid in enumerate(ranked[:POOL]) if mid in relevant), 0.0)
    return recall, rr


def run(cfg=None) -> dict:
    cfg = cfg or load_config()
    world, mems = build_corpus()
    conn = world.conn
    rec = Recorder(cfg.cache_dir / "recordings.jsonl", replay=cfg.replay)
    fts = FtsIndex(conn)
    systems = {"sqlite_fts": lambda q: fts.search(q, None, POOL)}
    notes = {}
    if cfg.moss_project_id and cfg.moss_project_key or cfg.replay:
        moss = MossIndex(
            conn, cfg.moss_project_id, cfg.moss_project_key, f"settle-reteval-{corpus_digest(conn)[:12]}", rec
        )
        if not rec.replay:
            for m in mems.values():  # the run's FTS already holds them; load the same corpus into Moss
                moss.add(m["id"], m["customer_id"], m["content"])
        systems["moss"] = lambda q: moss.search(q, None, POOL)
    else:
        notes["moss"] = "MOSS_PROJECT_ID/KEY not set"
    bd = None
    if cfg.bitdeer_api_key or cfg.replay:
        bd = Bitdeer(cfg.bitdeer_api_key, cfg.bitdeer_base_url, cfg.bitdeer_chat_model, cfg.bitdeer_rerank_model, rec)
    else:
        notes["rerank"] = "BITDEER_API_KEY not set"

    def reranked(base):
        def search(q):
            ids = base(q)
            order, err = safe(lambda: bd.rerank(q, [mems[i]["content"] for i in ids], len(ids)), None, "rerank")
            return [ids[j] for j in order] if order is not None else ids

        return search

    if "moss" in systems:
        systems["fused"] = lambda q: fuse(systems["sqlite_fts"](q), systems["moss"](q))
    if bd is not None:
        for name in list(systems):
            systems[f"{name}+rerank"] = reranked(systems[name])

    results = {name: {"recall_at_5": [], "mrr": [], "latency_ms": []} for name in systems}
    per_situation = {}
    for sit, (is_relevant, queries) in SITUATIONS.items():
        relevant = {mid for mid, m in mems.items() if is_relevant(m)}
        if not relevant:
            notes[sit] = "no relevant memory in corpus; skipped"
            continue
        per_situation[sit] = {"relevant": len(relevant)}
        for name, search in systems.items():
            rs = []
            for q in queries:
                t = time.perf_counter()
                ranked = search(q)
                results[name]["latency_ms"].append((time.perf_counter() - t) * 1000)
                r, rr = _metrics(ranked, relevant)
                results[name]["recall_at_5"].append(r)
                results[name]["mrr"].append(rr)
                rs.append(r)
            per_situation[sit][name] = round(sum(rs) / len(rs), 3)
    summary = {
        name: {
            "recall_at_5": round(sum(v["recall_at_5"]) / len(v["recall_at_5"]), 3),
            "mrr": round(sum(v["mrr"]) / len(v["mrr"]), 3),
            "median_latency_ms": round(sorted(v["latency_ms"])[len(v["latency_ms"]) // 2], 1),
            "queries": len(v["recall_at_5"]),
        }
        for name, v in results.items()
        if v["recall_at_5"]
    }
    out = {
        "corpus_memories": len(mems),
        "distractors": sum(1 for m in mems.values() if m["action"] == "paid"),
        "situations": len(per_situation),
        "k": K,
        "summary": summary,
        "per_situation": per_situation,
        "notes": notes,
    }
    path = cfg.cache_dir / "retrieval_eval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    import sys

    c = load_config()
    if "--replay" in sys.argv:
        c = dataclasses.replace(c, replay=True)
    r = run(c)
    print(
        f"corpus: {r['corpus_memories']} memories ({r['distractors']} 'paid' distractors), {r['situations']} situations"
    )
    print(f"{'system':<22}{'recall@5':>10}{'MRR':>8}{'median ms':>11}")
    for name, s in r["summary"].items():
        print(f"{name:<22}{s['recall_at_5']:>10}{s['mrr']:>8}{s['median_latency_ms']:>11}")
    print("per situation recall@5:")
    for sit, v in r["per_situation"].items():
        print(f"  {sit:<20} rel={v['relevant']:<3} " + "  ".join(f"{k}={v[k]}" for k in r["summary"]))
    if r["notes"]:
        print("notes:", r["notes"])
