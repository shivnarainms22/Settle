"""Three memory layers: episodic (searchable index), semantic (customer profiles), procedural (playbooks).

Write path: only human approvals/corrections and observed outcomes are written, and every write (including each
profile field change, with old and new value) is audited with its provenance. With memory disabled (ablation),
every write is a no-op and every read returns nothing beyond static master data.

Read path is deterministic: results are ordered by score then id, Moss responses go through the Recorder, and an
optional Bitdeer rerank is recorded too. `search_traced` returns what was retrieved and how, for provenance.
"""

import asyncio
import hashlib
import logging
import re
import sqlite3
import statistics
import threading

from settle import audit
from settle.db import dumps, get_meta, loads, set_meta
from settle.recorder import Recorder, ReplayMiss

log = logging.getLogger("settle.memory")

RELIABLE_MIN_PAYMENTS = 3
RELIABLE_MIN_DAYS_LATE = 14
RELIABLE_MAX_SPREAD = 6
PLAYBOOK_MIN_EPISODES = 3
DRIFT_NOTE = "Payment pattern contradicted"
RERANK_POOL = 3  # retrieve k * RERANK_POOL candidates before reranking


# ---- episodic index backends ------------------------------------------------------------------------


def fuse(*rankings: list[int]) -> list[int]:
    """Union of candidate lists, interleaved by rank (round robin), de-duplicated. Keyword and semantic retrieval fail
    on different queries (see retrieval_eval.py), so the reranker gets the best of both pools."""
    out: list[int] = []
    seen: set[int] = set()
    for i in range(max((len(r) for r in rankings), default=0)):
        for r in rankings:
            if i < len(r) and r[i] not in seen:
                seen.add(r[i])
                out.append(r[i])
    return out


def corpus_digest(conn: sqlite3.Connection) -> str:
    """Rolling sha256 over every memory written so far (id, customer, content), maintained on write in O(1), so
    recorded index results are only reused for the identical corpus."""
    return get_meta(conn, "corpus_digest", "0" * 64)


def _extend_corpus_digest(conn: sqlite3.Connection, memory_id: int, customer_id: str | None, content: str) -> None:
    prev = corpus_digest(conn)
    nxt = hashlib.sha256((prev + dumps([memory_id, customer_id, content])).encode("utf-8")).hexdigest()
    set_meta(conn, "corpus_digest", nxt)


class FtsIndex:
    name = "sqlite-fts"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, memory_id: int, customer_id: str | None, text: str) -> None:
        self.conn.execute(
            "INSERT INTO memories_fts(content, customer_id, memory_id) VALUES(?,?,?)",
            (text, customer_id or "", memory_id),
        )

    def search(self, query: str, customer_id: str | None, k: int) -> list[int]:
        terms = sorted({t.lower() for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 1})[:24]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        sql = "SELECT memory_id FROM memories_fts WHERE memories_fts MATCH ?"
        params: list = [match]
        if customer_id:
            sql += " AND customer_id=?"
            params.append(customer_id)
        sql += " ORDER BY round(bm25(memories_fts), 6), CAST(memory_id AS INTEGER) DESC LIMIT ?"
        params.append(k)
        return [int(r["memory_id"]) for r in self.conn.execute(sql, params)]


class MossIndex:
    """Moss session index (hybrid keyword + semantic, alpha=0.6). Every query is recorded, so a replay needs no
    network; on any failure it degrades to SQLite FTS loudly. SQLite stays the source of truth."""

    name = "moss"

    def __init__(
        self,
        conn: sqlite3.Connection,
        project_id: str | None,
        project_key: str | None,
        session_name: str,
        recorder: Recorder,
    ):
        self.conn = conn
        self.fallback = FtsIndex(conn)
        self.recorder = recorder
        self.failed_reason: str | None = None
        self._session = None
        if recorder.replay:
            return  # replay serves recorded query results only
        from moss import MossClient  # optional dependency

        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="moss-loop").start()
        self._client = MossClient(project_id, project_key)
        self._session = self._run(self._client.session(session_name))

    def _run(self, coro, timeout: float = 10.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _fail(self, exc: Exception) -> None:
        if self.failed_reason is None:
            log.error("Moss unavailable, falling back to SQLite FTS: %s", exc)
        self.failed_reason = str(exc)
        self.name = "sqlite-fts"

    def add(self, memory_id: int, customer_id: str | None, text: str) -> None:
        self.fallback.add(memory_id, customer_id, text)
        if self.failed_reason or self._session is None:
            return
        try:
            from moss import DocumentInfo

            doc = DocumentInfo(id=str(memory_id), text=text, metadata={"customer_id": customer_id or ""})
            self._run(self._session.add_docs([doc]))
        except Exception as exc:  # network/SDK errors: degrade, never crash the sim
            self._fail(exc)

    def search(self, query: str, customer_id: str | None, k: int) -> list[int]:
        if self.failed_reason:
            return self.fallback.search(query, customer_id, k)
        payload = {"q": query, "customer_id": customer_id, "k": k, "corpus": corpus_digest(self.conn)}
        try:
            key, ids = self.recorder.lookup("moss_query", payload)
        except ReplayMiss as exc:
            self._fail(exc)
            return self.fallback.search(query, customer_id, k)
        if ids is None:
            try:
                from moss import QueryOptions

                result = self._run(self._session.query(query, QueryOptions(top_k=k * 4, alpha=0.6)))
                scored = sorted(
                    (
                        (round(float(getattr(d, "score", 0.0)), 6), int(d.id))
                        for d in result.docs
                        if str(d.id).isdigit()
                    ),
                    key=lambda x: (-x[0], x[1]),
                )
                ids = [i for _, i in scored]
            except Exception as exc:
                self._fail(exc)
                return self.fallback.search(query, customer_id, k)
            self.recorder.put("moss_query", key, ids)
        if customer_id and ids:
            allowed = {
                r["id"]
                for r in self.conn.execute(
                    f"SELECT id FROM memories WHERE customer_id=? AND id IN ({','.join('?' * len(ids))})",
                    [customer_id, *ids],
                )
            }
            ids = [i for i in ids if i in allowed]
        return ids[:k]


# ---- memory store -----------------------------------------------------------------------------------


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection, enabled: bool, index, reranker=None):
        self.conn = conn
        self.enabled = enabled
        self.index = index
        self.reranker = reranker  # settle.bitdeer.Bitdeer or None

    @property
    def backend(self) -> str:
        return self.index.name

    def _today(self) -> str:
        return get_meta(self.conn, "sim_date") or ""

    # -- episodic
    def write(
        self,
        mtype: str,
        customer_id: str | None,
        content: str,
        approved_by: str,
        trigger: str | None = None,
        action: str | None = None,
        source_decision_id: int | None = None,
    ) -> int | None:
        if not self.enabled:
            return None
        cur = self.conn.execute(
            "INSERT INTO memories(type, customer_id, content, trigger, action, source_decision_id, approved_by,"
            " created_at) VALUES(?,?,?,?,?,?,?,?)",
            (mtype, customer_id, content, trigger, action, source_decision_id, approved_by, self._today()),
        )
        mid = cur.lastrowid
        _extend_corpus_digest(self.conn, mid, customer_id, content)
        self.index.add(mid, customer_id, content)
        audit.append(
            self.conn,
            "memory_write",
            {
                "memory_id": mid,
                "type": mtype,
                "content": content,
                "trigger": trigger,
                "action": action,
                "approved_by": approved_by,
                "source_decision_id": source_decision_id,
            },
            refs=[
                f"memory:{mid}",
                f"customer:{customer_id}" if customer_id else None,
                f"decision:{source_decision_id}" if source_decision_id else None,
            ],
        )
        return mid

    def search(self, query: str, customer_id: str | None = None, k: int = 5) -> list[dict]:
        return self.search_traced(query, customer_id, k)[0]

    def search_traced(
        self,
        query: str,
        customer_id: str | None = None,
        k: int = 5,
        exclude_customer: str | None = None,
        exclude_actions: tuple[str, ...] = (),
    ) -> tuple[list[dict], dict]:
        """Retrieval as measured in settle/retrieval_eval.py: keyword (FTS5) and semantic (Moss) candidates are fused,
        then reranked by Bitdeer bge-reranker-v2-m3 when available; each stage degrades independently."""
        info = {
            "query": query[:500],
            "customer_id": customer_id,
            "k": k,
            "backend": self.backend,
            "candidates": [],
            "reranker": None,
            "rerank_error": None,
        }
        if not self.enabled:
            info["backend"] = "disabled"
            return [], info
        pool = k * RERANK_POOL  # constant, so recorded index queries match whether or not a reranker is up
        if isinstance(self.index, MossIndex) and not self.index.failed_reason:
            keyword = self.index.fallback.search(query, customer_id, pool)
            semantic = self.index.search(query, customer_id, pool)
            ids = fuse(keyword, semantic)
            info["by_source"] = {"keyword": keyword, "semantic": semantic}
            info["backend"] = "moss+fts" if not self.index.failed_reason else "sqlite-fts"
        else:
            ids = self.index.search(query, customer_id, pool)
            info["backend"] = self.backend
        info["candidates"] = ids
        if not ids:
            return [], info
        rows = self.conn.execute(f"SELECT * FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        by_id = {r["id"]: dict(r) for r in rows}
        ids = [
            i
            for i in ids
            if i in by_id and by_id[i]["customer_id"] != exclude_customer and by_id[i]["action"] not in exclude_actions
        ]
        if len(ids) > k and self.reranker is not None and self.reranker.available:
            from settle.bitdeer import safe

            order, err = safe(
                lambda: self.reranker.rerank(query, [by_id[i]["content"] for i in ids], k), None, "rerank"
            )
            if order is not None:
                ids = [ids[j] for j in order]
                info["reranker"] = self.reranker.rerank_model
            info["rerank_error"] = err
        return [by_id[i] for i in ids[:k]], info

    def for_customer(self, customer_id: str, limit: int = 50) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM memories WHERE customer_id=? ORDER BY id DESC LIMIT ?", (customer_id, limit)
            )
        ]

    # -- semantic
    def profile(self, customer_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()
        cust = self.conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        late = loads(row["late_days_json"], []) if row else []
        notes = loads(row["notes_json"], []) if row else []
        obs = loads(row["payment_obs_json"], []) if row else []
        # Causal feature: did they pay because we reminded them? A customer whose payments arrive right after a
        # reminder is reminder-responsive, and holding dunning would stop the very thing that gets them to pay.
        prompted = sum(1 for o in obs if o.get("days_after_reminder") is not None and o["days_after_reminder"] <= 3)
        responsive = len(obs) >= 2 and prompted * 2 >= len(obs)
        reliable = (
            len(late) >= RELIABLE_MIN_PAYMENTS
            and statistics.mean(late) >= RELIABLE_MIN_DAYS_LATE
            and max(late) - min(late) <= RELIABLE_MAX_SPREAD
            and not any(n.startswith(DRIFT_NOTE) for n in notes)
            and not responsive
        )
        causal = {}
        if obs:  # only once something has been learned, so a memory-less profile is unchanged
            causal = {
                "reminder_response": f"{prompted}/{len(obs)} payments arrived within 3 days of a reminder",
                "dunning_guidance": (
                    "reminder-responsive: they pay because they are reminded; keep the normal reminder cadence"
                    if responsive
                    else "reliable late payer: hold dunning and forecast the pay date"
                    if reliable
                    else "no reliable late-payer pattern: follow the normal reminder cadence"
                ),
            }
        return {
            "aliases": loads(row["aliases_json"], []) if row else [],
            "avg_days_late": round(statistics.mean(late), 1) if late else None,
            "payments_observed": len(late),
            "late_days": late,
            "needs_po": None if not row or row["needs_po"] is None else bool(row["needs_po"]),
            "reliable_late_payer": reliable,
            "bank_account_on_file": cust["bank_account_on_file"] if cust else "",
            "verified_domain": cust["verified_domain"] if cust else "",
            "dispute_count": row["dispute_count"] if row else 0,
            "notes": loads(row["notes_json"], []) if row else [],
            **causal,
        }

    def _set_profile(self, customer_id: str, column: str, value, source: str, refs=()) -> None:
        """Single audited write path for semantic memory."""
        if column not in (
            "late_days_json",
            "payment_obs_json",
            "aliases_json",
            "needs_po",
            "notes_json",
            "dispute_count",
        ):
            raise ValueError(f"unknown profile column {column}")
        old = self.conn.execute(f"SELECT {column} FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()[0]
        if old == value:
            return
        self.conn.execute(f"UPDATE profiles SET {column}=? WHERE customer_id=?", (value, customer_id))
        audit.append(
            self.conn,
            "profile_updated",
            {
                "customer_id": customer_id,
                "field": column.removesuffix("_json"),
                "old": old,
                "new": value,
                "source": source,
            },
            refs=[f"customer:{customer_id}", *refs],
        )

    def observe_payment(
        self,
        customer_id: str,
        days_late: int,
        invoice_id: str,
        reminders: int = 0,
        days_after_reminder: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        obs = loads(
            self.conn.execute("SELECT payment_obs_json FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()[
                0
            ],
            [],
        )
        self._set_profile(
            customer_id,
            "payment_obs_json",
            dumps(
                [
                    *obs,
                    {
                        "invoice_id": invoice_id,
                        "days_late": days_late,
                        "reminders": reminders,
                        "days_after_reminder": days_after_reminder,
                    },
                ]
            ),
            f"payment of {invoice_id}",
            [f"invoice:{invoice_id}"],
        )
        late = loads(
            self.conn.execute("SELECT late_days_json FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()[0],
            [],
        )
        self._set_profile(
            customer_id,
            "late_days_json",
            dumps([*late, days_late]),
            f"payment of {invoice_id}",
            [f"invoice:{invoice_id}"],
        )

    def add_alias(self, customer_id: str, alias: str, decision_id: int) -> bool:
        if not self.enabled:
            return False
        aliases = loads(
            self.conn.execute("SELECT aliases_json FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()[0], []
        )
        if alias in aliases:
            return False
        self._set_profile(
            customer_id,
            "aliases_json",
            dumps([*aliases, alias]),
            "human-confirmed cash match",
            [f"decision:{decision_id}"],
        )
        return True

    def set_needs_po(self, customer_id: str, decision_id: int) -> None:
        if self.enabled:
            self._set_profile(customer_id, "needs_po", 1, "confirmed PO reissue outcome", [f"decision:{decision_id}"])

    def add_note(self, customer_id: str, note: str, decision_id: int | None = None) -> None:
        if not self.enabled:
            return
        notes = loads(
            self.conn.execute("SELECT notes_json FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()[0], []
        )
        if note not in notes:
            self._set_profile(
                customer_id,
                "notes_json",
                dumps([*notes, note]),
                "learned note",
                [f"decision:{decision_id}" if decision_id else None],
            )

    def bump_disputes(self, customer_id: str, decision_id: int) -> None:
        if self.enabled:
            n = self.conn.execute("SELECT dispute_count FROM profiles WHERE customer_id=?", (customer_id,)).fetchone()[
                0
            ]
            self._set_profile(customer_id, "dispute_count", n + 1, "dispute raised", [f"decision:{decision_id}"])

    # -- procedural
    def active_playbook(self, customer_id: str, trigger: str) -> dict | None:
        if not self.enabled:
            return None
        row = self.conn.execute(
            "SELECT * FROM playbooks WHERE customer_id=? AND trigger=? AND status='active'"
            " ORDER BY version DESC, id DESC LIMIT 1",
            (customer_id, trigger),
        ).fetchone()
        return dict(row) if row else None

    def playbooks_for(self, customer_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute("SELECT * FROM playbooks WHERE customer_id=? ORDER BY id", (customer_id,))
        ]

    def consolidate(self) -> list[int]:
        """Propose playbooks from repeated confirmed outcomes and learned profiles. Returns new playbook ids."""
        if not self.enabled:
            return []
        created = []
        groups = self.conn.execute(
            "SELECT customer_id, trigger, action, COUNT(*) n, GROUP_CONCAT(id) ids FROM memories"
            " WHERE type='episodic' AND trigger IS NOT NULL GROUP BY customer_id, trigger, action"
            " ORDER BY customer_id, trigger, action"
        ).fetchall()
        for g in groups:
            if g["n"] < PLAYBOOK_MIN_EPISODES:
                continue
            if (g["trigger"], g["action"]) == ("ap_reject_missing_po", "reissue_invoice"):
                pid = self._propose(
                    g["customer_id"],
                    "invoice_issue",
                    "attach_po",
                    {},
                    "Attach the customer PO from CRM before sending any invoice; AP rejects invoices without one.",
                    sorted(int(x) for x in g["ids"].split(",")),
                )
                if pid:
                    created.append(pid)
        for c in self.conn.execute("SELECT id FROM customers ORDER BY id"):
            prof = self.profile(c["id"])
            if prof["reliable_late_payer"]:
                grace = int(round(prof["avg_days_late"])) + 3
                src = sorted(
                    m["id"] for m in self.for_customer(c["id"]) if m["trigger"] in ("payment_observed", "overdue")
                )
                pid = self._propose(
                    c["id"],
                    "overdue",
                    "hold_dunning",
                    {"grace_days": grace},
                    f"Reliable late payer: pays ~{prof['avg_days_late']:.0f} days after due across"
                    f" {prof['payments_observed']} payments. Hold dunning for {grace} days past due"
                    f" and forecast the pay date instead of escalating.",
                    src[-10:],
                )
                if pid:
                    created.append(pid)
        return created

    def _propose(
        self, customer_id: str, trigger: str, action: str, args: dict, description: str, source_ids: list[int]
    ) -> int | None:
        exists = self.conn.execute(
            "SELECT 1 FROM playbooks WHERE customer_id=? AND trigger=? AND action=?"
            " AND status IN ('proposed','active','needs_review','disabled')",  # a human's disable is sticky
            (customer_id, trigger, action),
        ).fetchone()
        if exists:
            return None
        cur = self.conn.execute(
            "INSERT INTO playbooks(customer_id, trigger, action, args_json, description, status,"
            " source_memory_ids_json) VALUES(?,?,?,?,?,?,?)",
            (customer_id, trigger, action, dumps(args), description, "proposed", dumps(source_ids)),
        )
        pid = cur.lastrowid
        audit.append(
            self.conn,
            "playbook_proposed",
            {
                "playbook_id": pid,
                "trigger": trigger,
                "action": action,
                "args": args,
                "description": description,
                "source_memory_ids": source_ids,
            },
            refs=[f"playbook:{pid}", f"customer:{customer_id}", *(f"memory:{m}" for m in source_ids)],
        )
        return pid

    def set_playbook_status(self, playbook_id: int, status: str, actor: str, reason: str = "", refs=()) -> dict:
        if status not in ("active", "disabled", "needs_review"):
            raise ValueError(status)
        row = self.conn.execute("SELECT * FROM playbooks WHERE id=?", (playbook_id,)).fetchone()
        if row is None:
            raise KeyError(playbook_id)
        if status == "active" and row["status"] not in ("proposed", "needs_review"):
            raise ValueError(
                f"playbook {playbook_id} is {row['status']}, only proposed or needs_review playbooks can be approved"
            )
        if status == "needs_review" and row["status"] != "active":
            raise ValueError(f"playbook {playbook_id} is {row['status']}, only active playbooks can be suspended")
        if row["status"] == status:
            return dict(row)
        version = row["version"] + 1 if status == "active" and row["status"] == "needs_review" else row["version"]
        self.conn.execute("UPDATE playbooks SET status=?, version=? WHERE id=?", (status, version, playbook_id))
        audit.append(
            self.conn,
            f"playbook_{status}",
            {"playbook_id": playbook_id, "actor": actor, "from": row["status"], "version": version, "reason": reason},
            refs=[f"playbook:{playbook_id}", f"customer:{row['customer_id']}", *refs],
        )
        return dict(self.conn.execute("SELECT * FROM playbooks WHERE id=?", (playbook_id,)).fetchone())


def build_index(conn: sqlite3.Connection, cfg, session_name: str, recorder: Recorder):
    if (cfg.moss_project_id and cfg.moss_project_key) or (cfg.replay and recorder.data.get("moss_query")):
        try:
            return MossIndex(conn, cfg.moss_project_id, cfg.moss_project_key, session_name, recorder)
        except Exception as exc:
            log.error("Moss init failed, using SQLite FTS: %s", exc)
    return FtsIndex(conn)
