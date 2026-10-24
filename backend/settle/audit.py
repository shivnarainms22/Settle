"""Tamper-evident, hash-chained audit log with entity references for tracing.

Every state change Settle makes is appended here. `refs` (e.g. "invoice:INV-1088", "decision:12") index the event so
the full history of any entity can be traced. The hash covers only deterministic content (event JSON incl. sim
date), so the same seed and the same recorded external responses reproduce the same chain head.
"""

import hashlib
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime

from settle.db import dumps, get_meta, loads

GENESIS = "0" * 64


def _hash(prev_hash: str, event_json: str) -> str:
    return hashlib.sha256((prev_hash + event_json).encode("utf-8")).hexdigest()


def append(
    conn: sqlite3.Connection,
    event_type: str,
    event: dict,
    refs: Iterable[str | None] = (),
    sim_date: str | None = None,
) -> int:
    sim_date = sim_date or get_meta(conn, "sim_date") or ""
    refs = sorted({r for r in refs if r})
    prev_hash = head(conn)
    event_json = dumps({"type": event_type, "sim_date": sim_date, "refs": refs, **event})
    cur = conn.execute(
        "INSERT INTO audit_log(event_type, event_json, prev_hash, hash, created_at, sim_date) VALUES(?,?,?,?,?,?)",
        (event_type, event_json, prev_hash, _hash(prev_hash, event_json), datetime.now(UTC).isoformat(), sim_date),
    )
    aid = cur.lastrowid
    conn.executemany("INSERT INTO audit_refs(audit_id, ref) VALUES(?,?)", [(aid, r) for r in refs])
    return aid


def head(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    return row["hash"] if row else GENESIS


def verify(conn: sqlite3.Connection) -> dict:
    prev_hash = GENESIS
    length = 0
    for row in conn.execute("SELECT id, event_json, prev_hash, hash FROM audit_log ORDER BY id"):
        length += 1
        if row["prev_hash"] != prev_hash or row["hash"] != _hash(prev_hash, row["event_json"]):
            return {"ok": False, "length": length, "broken_at": row["id"], "head": None}
        prev_hash = row["hash"]
    return {"ok": True, "length": length, "broken_at": None, "head": prev_hash}


def trace(conn: sqlite3.Connection, ref: str, limit: int = 500) -> list[dict]:
    rows = conn.execute(
        "SELECT a.* FROM audit_log a JOIN audit_refs r ON r.audit_id=a.id WHERE r.ref=? ORDER BY a.id LIMIT ?",
        (ref, limit),
    ).fetchall()
    return [serialize(r) for r in rows]


def serialize(row: sqlite3.Row) -> dict:
    event = loads(row["event_json"], {})
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "sim_date": row["sim_date"],
        "refs": event.get("refs", []),
        "event": {k: v for k, v in event.items() if k not in ("type", "sim_date", "refs")},
        "prev_hash": row["prev_hash"],
        "hash": row["hash"],
        "created_at": row["created_at"],
    }
