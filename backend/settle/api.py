"""FastAPI app. See docs/api-contract.md. One World per process, guarded by a lock."""

import asyncio
import csv
import hashlib
import io
import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from settle import audit, forecast, ledger
from settle import verify as verify_mod
from settle.auth import AuthError, Directory, User, check_approval
from settle.bitdeer import looks_like_instruction
from settle.config import load_config
from settle.db import get_meta, loads
from settle.engine import NotFound, World
from settle.eval import load_latest, run_ablation
from settle.models import ACTIONS, MONEY_MOVING, Decision

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("settle.api")

cfg = load_config()
lock = threading.RLock()
world: World | None = None
directory = Directory()
PUBLIC_PATHS = ("/api/health", "/api/login", "/api/users")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global world
    world = World(cfg)
    with lock:
        world.ensure_seeded()
    yield


def auth_gate(request: Request) -> None:
    """Every /api route needs a valid token (header, or ?token= for EventSource); the SPA, login, the user picker
    and /api/health don't."""
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_PATHS:
        return
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token")
    request.state.user = directory.verify(token)


def current_user(request: Request) -> User:
    return request.state.user


def need(role: str):
    def dep(user: Annotated[User, Depends(current_user)]) -> User:
        if not user.at_least(role):
            raise AuthError(403, f"{user.role} cannot do this (needs {role})")
        return user

    return dep


CurrentUser = Annotated[User, Depends(current_user)]
Clerk = Annotated[User, Depends(need("ar_clerk"))]
Controller = Annotated[User, Depends(need("controller"))]

app = FastAPI(title="Settle", lifespan=lifespan, dependencies=[Depends(auth_gate)])


@app.exception_handler(AuthError)
async def _auth_error(_request: Request, exc: AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception):
    """Never leave a half-written transaction behind, and give the user an id they can quote."""
    rid = uuid.uuid4().hex[:12]
    log.exception("request %s %s failed (id %s)", request.method, request.url.path, rid)
    if world is not None:

        def rollback():
            with lock:
                world.conn.rollback()

        await asyncio.to_thread(rollback)
    return JSONResponse({"detail": f"internal error (request id {rid})", "request_id": rid}, status_code=500)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def W() -> World:
    if world is None:
        raise HTTPException(503, "world not initialised")
    return world


# ---- serializers ---------------------------------------------------------------------------------------


def _names() -> dict[str, str]:
    return {r["id"]: r["name"] for r in W().conn.execute("SELECT id, name FROM customers")}


def ser_decision(row, names=None) -> dict:
    names = names or _names()
    w = W().conn.execute("SELECT kind, ref, summary FROM work_items WHERE id=?", (row["work_item_id"],)).fetchone()
    return {
        "id": row["id"],
        "sim_date": row["sim_date"],
        "work_item": {"kind": w["kind"], "ref": w["ref"], "summary": w["summary"]} if w else None,
        "customer_id": row["customer_id"],
        "customer_name": names.get(row["customer_id"]),
        "source": row["source"],
        "action": row["action"],
        "args": loads(row["args_json"], {}),
        "rationale": row["rationale"],
        "evidence": loads(row["evidence_json"], []),
        "memory_ids": loads(row["memory_ids_json"], []),
        "playbook_id": row["playbook_id"],
        "confidence": row["confidence"],
        "tier": row["tier"],
        "tier_reasons": loads(row["tier_reasons_json"], []),
        "status": row["status"],
        "approver": row["approver"],
        "amount_cents": row["amount_cents"],
        "trigger": row["trigger"],
        "original": loads(row["original_json"]),
    }


def ser_memory(r) -> dict:
    return {
        k: r[k]
        for k in (
            "id",
            "type",
            "customer_id",
            "content",
            "source_decision_id",
            "approved_by",
            "created_at",
            "trigger",
            "action",
        )
    }


def ser_playbook(r, names=None) -> dict:
    names = names or _names()
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "customer_name": names.get(r["customer_id"]),
        "trigger": r["trigger"],
        "action": r["action"],
        "args": loads(r["args_json"], {}),
        "description": r["description"],
        "status": r["status"],
        "source_memory_ids": loads(r["source_memory_ids_json"], []),
        "times_fired": r["times_fired"],
        "version": r["version"],
    }


def ser_activity(r, names=None) -> dict:
    names = names or _names()
    d = dict(r)
    d["customer_name"] = names.get(r["customer_id"])
    return d


def ser_invoice(r, today: str) -> dict:
    d = {
        k: r[k]
        for k in (
            "id",
            "customer_id",
            "po_number",
            "amount_cents",
            "balance_cents",
            "issued_on",
            "due_on",
            "status",
            "reminder_count",
        )
    }
    open_ = r["status"] not in ("paid", "scheduled")
    d["days_overdue"] = max(0, (date.fromisoformat(today) - date.fromisoformat(r["due_on"])).days) if open_ else 0
    return d


def customer_summary(c, names) -> dict:
    w = W()
    today = w.today
    prof = w.memory.profile(c["id"])
    ar = w.conn.execute(
        "SELECT COALESCE(SUM(balance_cents),0) FROM invoices WHERE customer_id=? AND status NOT IN"
        " ('scheduled','paid')",
        (c["id"],),
    ).fetchone()[0]
    overdue = w.conn.execute(
        "SELECT COUNT(*) FROM invoices WHERE customer_id=? AND status NOT IN ('scheduled','paid')"
        " AND balance_cents>0 AND due_on<?",
        (c["id"], today),
    ).fetchone()[0]
    pbs = w.conn.execute(
        "SELECT COUNT(*) FROM playbooks WHERE customer_id=? AND status='active'", (c["id"],)
    ).fetchone()[0]
    return {
        "id": c["id"],
        "name": c["name"],
        "tier": c["tier"],
        "open_ar_cents": ar,
        "overdue_count": overdue,
        "avg_days_late": prof["avg_days_late"],
        "owner_in_sales": c["owner_in_sales"],
        "active_playbooks": pbs,
    }


# ---- sim -----------------------------------------------------------------------------------------------


class AdvanceBody(BaseModel):
    days: int | None = Field(default=None, ge=1, le=92)
    to: str | None = None


class ResetBody(BaseModel):
    memory: bool = True
    seed: int | None = None


@app.get("/api/state")
def get_state():
    with lock:
        return W().state()


@app.post("/api/sim/advance", dependencies=[Depends(need("ar_clerk"))])
def advance(body: AdvanceBody):
    if body.to is None and not body.days:
        raise HTTPException(400, "pass {'days': n}, {'to': 'month_end'} or {'to': 'YYYY-MM-DD'}")
    with lock:
        w = W()
        d = date.fromisoformat(w.today)
        if body.to == "month_end":
            days = ((d.replace(day=28) + timedelta(days=4)).replace(day=1) - d).days
        elif body.to is not None:
            try:
                target = date.fromisoformat(body.to)
            except ValueError as exc:
                raise HTTPException(400, f"'to' must be 'month_end' or YYYY-MM-DD, not {body.to!r}") from exc
            last = w.end_date + timedelta(days=1)
            if not d < target <= last:
                raise HTTPException(400, f"'to' must be after {d} and no later than {last}")
            days = (target - d).days
        else:
            days = body.days
    for _ in range(days):
        with lock:  # released between days so the stream and other reads stay live during a long advance
            if W().done:
                break
            W().step()
    with lock:
        return W().state()


@app.post("/api/sim/reset", dependencies=[Depends(need("controller"))])
def reset(body: ResetBody):
    with lock:
        W().reset(memory=body.memory, seed=body.seed)
        return W().state()


class ImportBody(BaseModel):
    invoices_csv: str = Field(min_length=1, max_length=5_000_000)
    bank_csv: str = Field(default="", max_length=5_000_000)
    memory: bool = True
    autonomy: Literal["shadow", "supervised", "autonomous"] = "shadow"  # a pilot on real books starts read-only


@app.post("/api/import", dependencies=[Depends(need("controller"))])
def import_books(body: ImportBody):
    """Bring your own books: an AR aging export + bank statement CSV replace the simulated company."""
    from settle.importer import ImportError_

    with lock:
        try:
            summary = W().load_import(body.invoices_csv, body.bank_csv, body.memory, body.autonomy)
        except ImportError_ as exc:
            raise HTTPException(422, {"message": "could not import", "errors": exc.errors}) from exc
        return {"summary": summary, "state": W().state()}


@app.get("/api/import/samples")
def import_samples():
    """The sample QuickBooks-style exports, so the import can be demoed without real books."""
    base = Path(__file__).resolve().parent.parent / "samples"
    return {name: (base / name).read_text(encoding="utf-8") for name in ("ar_aging.csv", "bank_statement.csv")}


@app.get("/api/activity")
def activity(after_id: int = 0, limit: int = 200):
    with lock:
        names = _names()
        rows = (
            W()
            .conn.execute("SELECT * FROM activity WHERE id>? ORDER BY id LIMIT ?", (after_id, min(max(limit, 1), 1000)))
            .fetchall()
        )
        return [ser_activity(r, names) for r in rows]


class StreamCursor:
    """Where one live client is in the activity feed. A reset or import starts a new run whose activity ids restart
    at 1, so the cursor rewinds and reports it; otherwise the client would wait for ids past the old maximum."""

    BACKFILL = 50

    def __init__(self):
        with lock:
            c = W().conn
            self.run = get_meta(c, "run_id")
            self.last = max(0, c.execute("SELECT COALESCE(MAX(id),0) FROM activity").fetchone()[0] - self.BACKFILL)

    def poll(self, limit: int = 500) -> tuple[list[dict], bool]:
        with lock:
            c = W().conn
            run = get_meta(c, "run_id")
            reset = run != self.run
            if reset:
                self.run, self.last = run, 0
            names = _names()
            rows = c.execute("SELECT * FROM activity WHERE id>? ORDER BY id LIMIT ?", (self.last, limit)).fetchall()
            events = [ser_activity(r, names) for r in rows]
            if events:
                self.last = events[-1]["id"]
            return events, reset


@app.get("/api/stream")
async def stream():
    def state():
        with lock:
            return W().state()

    async def gen():
        cursor = await asyncio.to_thread(StreamCursor)
        need_state = True
        while True:
            events, reset = await asyncio.to_thread(cursor.poll)
            if reset:  # carries the new run id so the client doesn't treat the following state as another reset
                yield f"event: reset\ndata: {json.dumps({'run_id': cursor.run})}\n\n"
            for ev in events:
                yield f"event: activity\ndata: {json.dumps(ev)}\n\n"
            if events or reset or need_state:
                need_state = False
                yield f"event: state\ndata: {json.dumps(await asyncio.to_thread(state))}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ---- approvals & decisions -----------------------------------------------------------------------------


def _check_action(v: str | None) -> str | None:
    if v is not None and v not in ACTIONS:
        raise ValueError(f"unknown action {v!r}")
    return v


class ApprovalBody(BaseModel):
    verdict: Literal["approve", "reject", "edit", "dismiss"]
    action: str | None = None
    args: dict | None = None
    note: str = Field(default="", max_length=1000)

    @field_validator("action")
    @classmethod
    def _act_action(cls, v):
        return _check_action(v)


@app.get("/api/approvals")
def approvals():
    with lock:
        names = _names()
        rows = W().conn.execute("SELECT * FROM decisions WHERE status='pending_approval' ORDER BY id").fetchall()
        return [{**ser_decision(r, names), "stale": _stale_reasons(r)} for r in rows]


def _stale_reasons(row) -> list[str]:
    """Why approving this queued decision would now be refused (the world moved on), so the UI can say so up front."""
    current = Decision(
        row["action"],
        loads(row["args_json"], {}),
        row["rationale"],
        loads(row["evidence_json"], []),
        loads(row["memory_ids_json"], []),
        row["confidence"],
    )
    return W().validate(current, row["customer_id"])


def _authorize_verdict(user: User, row, action: str | None = None, args: dict | None = None) -> None:
    """Separation of duties: the money at stake is the larger of what was proposed and what an edit would do."""
    cust = W().conn.execute("SELECT tier FROM customers WHERE id=?", (row["customer_id"],)).fetchone()
    amounts, actions = [row["amount_cents"] or 0], {row["action"]}
    if action is not None or args is not None:
        edited = Decision(action or row["action"], args if args is not None else loads(row["args_json"], {}), "")
        amounts.append(edited.amount_cents() or 0)
        actions.add(edited.action)
    key_account = cust is not None and cust["tier"] == "key_account"
    check_approval(user, max(amounts), key_account, bool(actions & MONEY_MOVING))


@app.post("/api/approvals/{decision_id}")
def approve(decision_id: int, body: ApprovalBody, user: CurrentUser):
    with lock:
        row = W().conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"decision {decision_id} not found")
        editing = body.verdict == "edit"
        if body.verdict == "dismiss":  # closing an overtaken decision moves no money
            if not user.at_least("ar_clerk"):
                raise AuthError(403, f"{user.role} cannot close decisions")
        else:
            _authorize_verdict(user, row, body.action if editing else None, body.args if editing else None)
        try:
            W().resolve(decision_id, body.verdict, user.username, body.action, body.args, body.note)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return ser_decision(W().conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())


@app.get("/api/decisions")
def decisions(limit: int = 100):
    with lock:
        names = _names()
        rows = W().conn.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 1000),))
        return [ser_decision(r, names) for r in rows.fetchall()]


def _resolve_ref(ref: str) -> dict:
    kind, _, rid = ref.partition(":")
    c = W().conn
    if kind == "email":
        r = c.execute("SELECT * FROM emails WHERE id=?", (rid,)).fetchone()
        text = f"{r['sender']} — {r['subject']}\n\n{r['body']}" if r else "(missing)"
    elif kind == "invoice":
        r = c.execute("SELECT * FROM invoices WHERE id=?", (rid,)).fetchone()
        text = (
            (
                f"{rid}: ${r['amount_cents'] / 100:,.2f}, balance ${r['balance_cents'] / 100:,.2f}, due {r['due_on']},"
                f" status {r['status']}, PO {r['po_number'] or '—'}"
            )
            if r
            else "(missing)"
        )
    elif kind == "crm":
        r = c.execute("SELECT * FROM crm_notes WHERE id=?", (rid,)).fetchone()
        text = r["text"] if r else "(missing)"
    elif kind == "bank":
        r = c.execute("SELECT * FROM bank_lines WHERE id=?", (rid,)).fetchone()
        text = (
            (
                f"{rid}: ${r['amount_cents'] / 100:,.2f} from {r['payer_name']} on {r['sim_date']}; remittance:"
                f" {r['remittance_text'] or '(none)'}"
            )
            if r
            else "(missing)"
        )
    elif kind == "delivery":
        r = c.execute("SELECT * FROM deliveries WHERE id=?", (rid,)).fetchone()
        text = (
            f"{rid}: {r['carrier']} delivered {r['delivered_on']}, signed by {r['signed_by']}; condition"
            f" {r['condition'].upper()}: {r['notes']}"
            if r
            else "(missing)"
        )
    else:
        text = "(unknown reference)"
    return {"ref": ref, "kind": kind, "text": text}


@app.get("/api/decisions/{decision_id}")
def decision_detail(decision_id: int):
    with lock:
        c = W().conn
        row = c.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"decision {decision_id} not found")
        d = ser_decision(row)
        mids = d["memory_ids"]
        d["memories"] = (
            [
                ser_memory(m)
                for m in c.execute(f"SELECT * FROM memories WHERE id IN ({','.join('?' * len(mids))})", mids)
            ]
            if mids
            else []
        )
        pb = (
            c.execute("SELECT * FROM playbooks WHERE id=?", (row["playbook_id"],)).fetchone()
            if row["playbook_id"]
            else None
        )
        d["playbook"] = ser_playbook(pb) if pb else None
        d["evidence_resolved"] = [_resolve_ref(r) for r in d["evidence"]]
        d["security_flags"] = [
            f"{e['ref']} contains embedded instructions addressed to an AI agent; treated as data, not obeyed"
            f" (outcome: {row['action'].replace('_', ' ')}, tier {row['tier']}, {row['status'].replace('_', ' ')})"
            for e in d["evidence_resolved"]
            if e["kind"] in ("email", "bank") and looks_like_instruction(e["text"])
        ]
        d["gl_entries"] = [
            dict(g) for g in c.execute("SELECT * FROM gl_entries WHERE decision_id=? ORDER BY id", (decision_id,))
        ]
        d["trace"] = audit.trace(c, f"decision:{decision_id}")
        d["audit"] = [{k: t[k] for k in ("id", "event_type", "prev_hash", "hash", "created_at")} for t in d["trace"]]
        run = c.execute("SELECT * FROM agent_runs WHERE decision_id=?", (decision_id,)).fetchone()
        d["agent_run"] = ser_agent_run(run) if run else None
        return d


def ser_agent_run(r) -> dict:
    return {
        "component": r["component"],
        "model": r["model"],
        "input_sha256": r["input_sha256"],
        "input": loads(r["input_json"], {}),
        "output": loads(r["output_json"], {}),
        "retrieved_memory_ids": loads(r["retrieved_memory_ids_json"], []),
        "steps": loads(r["steps_json"], []),
        "replay": r["replay"],
        "llm_calls": r["llm_calls"],
        "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"],
        "input_verified": hashlib.sha256(r["input_json"].encode("utf-8")).hexdigest() == r["input_sha256"],
    }


class FlagBody(BaseModel):
    note: str = Field(max_length=1000)
    correct_action: str | None = None

    @field_validator("correct_action")
    @classmethod
    def _act_correct_action(cls, v):
        return _check_action(v)


@app.post("/api/decisions/{decision_id}/flag")
def flag_decision(decision_id: int, body: FlagBody, user: Clerk):
    with lock:
        row = W().conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"decision {decision_id} not found")
        _authorize_verdict(user, row, body.correct_action)
        try:
            return W().flag_decision(decision_id, body.note, user.username, body.correct_action)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


TRACE_KINDS = ("invoice", "email", "bank", "decision", "customer", "memory", "playbook", "work_item", "gl", "run")


@app.get("/api/trace")
def trace(ref: str, limit: int = 500):
    """Full audit history of one entity, e.g. ?ref=invoice:INV-1088, oldest first, with hashes."""
    kind, _, ident = ref.partition(":")
    if kind not in TRACE_KINDS or (kind != "run" and not ident):
        raise HTTPException(400, f"ref must look like <kind>:<id> with kind in {', '.join(TRACE_KINDS)}")
    with lock:
        events = audit.trace(W().conn, ref, min(max(limit, 1), 2000))
        return {"ref": ref, "events": events, "count": len(events)}


@app.get("/api/forecast")
def get_forecast():
    with lock:
        w = W()
        as_of = min(w.today, w.end_date.isoformat())
        fc = forecast.forecast(w.conn, w.memory, as_of)
        fc["snapshots"] = [
            a
            for a in (
                forecast.accuracy(w.conn, r["as_of"], w.today)
                for r in w.conn.execute("SELECT as_of FROM forecasts ORDER BY as_of")
            )
            if a
        ]
        return fc


# ---- customers, playbooks, audit, ledger ----------------------------------------------------------------


@app.get("/api/customers")
def customers():
    with lock:
        names = _names()
        return [customer_summary(c, names) for c in W().conn.execute("SELECT * FROM customers ORDER BY id").fetchall()]


@app.get("/api/customers/{customer_id}")
def customer(customer_id: str):
    with lock:
        w = W()
        c = w.conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if c is None:
            raise HTTPException(404, f"customer {customer_id} not found")
        names = _names()
        out = customer_summary(c, names)
        out["profile"] = w.memory.profile(customer_id)
        out["invoices"] = [
            ser_invoice(r, w.today)
            for r in w.conn.execute(
                "SELECT * FROM invoices WHERE customer_id=? AND status!='scheduled' ORDER BY issued_on DESC",
                (customer_id,),
            )
        ]
        out["emails"] = [
            dict(r)
            for r in w.conn.execute(
                "SELECT * FROM emails WHERE customer_id=? ORDER BY sim_date DESC, rowid DESC LIMIT 100", (customer_id,)
            )
        ]
        out["memories"] = [
            ser_memory(m)
            for m in w.conn.execute(
                "SELECT * FROM memories WHERE customer_id=? ORDER BY id DESC LIMIT 100", (customer_id,)
            )
        ]
        out["playbooks"] = [
            ser_playbook(p, names)
            for p in w.conn.execute("SELECT * FROM playbooks WHERE customer_id=? ORDER BY id", (customer_id,))
        ]
        return out


@app.get("/api/playbooks")
def playbooks():
    with lock:
        names = _names()
        return [ser_playbook(p, names) for p in W().conn.execute("SELECT * FROM playbooks ORDER BY id").fetchall()]


def _set_playbook(playbook_id: int, status: str, user: User):
    with lock:
        w = W()
        try:
            w.memory.set_playbook_status(playbook_id, status, user.username)
        except KeyError as exc:
            raise HTTPException(404, f"playbook {playbook_id} not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        p = w.conn.execute(
            "SELECT p.*, c.name FROM playbooks p JOIN customers c ON c.id=p.customer_id WHERE p.id=?", (playbook_id,)
        ).fetchone()
        from settle.executor import log_activity

        log_activity(
            w.conn,
            min(w.today, w.end_date.isoformat()),
            "playbook",
            f"Playbook #{playbook_id} {'activated' if status == 'active' else 'disabled'} for {p['name']}"
            f" (v{p['version']}) by {user.name}",
            p["description"],
            p["customer_id"],
            agent_state="Self-Learning",
        )
        w.conn.commit()
        return ser_playbook(p)


@app.post("/api/playbooks/{playbook_id}/approve")
def approve_playbook(playbook_id: int, user: Controller):
    return _set_playbook(playbook_id, "active", user)


@app.post("/api/playbooks/{playbook_id}/disable")
def disable_playbook(playbook_id: int, user: Controller):
    return _set_playbook(playbook_id, "disabled", user)


@app.get("/api/verify")
def verify_run():
    """End-to-end verification of the live run: chain, provenance, policy replay, guardrails, invoice replay,
    ledger tie-out, messages, memory provenance and work-item consistency (see settle/verify.py)."""
    with lock:
        return verify_mod.verify(W().conn)


@app.get("/api/audit/verify")
def verify_audit():
    with lock:
        return audit.verify(W().conn)


@app.get("/api/ledger")
def get_ledger():
    with lock:
        return {"accounts": ledger.trial_balance(W().conn)}


# ---- eval ----------------------------------------------------------------------------------------------


class EvalBody(BaseModel):
    seed: int | None = None


def _cached(name: str):
    try:
        with open(cfg.cache_dir / name, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


@app.get("/api/stack")
def stack_value():
    """Measured value of each component: retrieval benchmark (FTS vs Moss vs fused, with/without Bitdeer rerank)
    and the scale benchmark. 404 parts are reported as null until their CLI has been run."""
    return {"retrieval": _cached("retrieval_eval.json"), "bench": _cached("bench_latest.json")}


@app.get("/api/eval")
def get_eval():
    result = load_latest(cfg)
    if result is None:
        raise HTTPException(404, "eval has not been run yet")
    return result


eval_lock = threading.Lock()


@app.post("/api/eval/run", dependencies=[Depends(need("controller"))])
def post_eval(body: EvalBody):
    if not eval_lock.acquire(blocking=False):
        raise HTTPException(409, "an eval run is already in progress")
    try:
        return run_ablation(cfg, body.seed)
    finally:
        eval_lock.release()


# ---- auth, operations, exports (v4) ----------------------------------------------------------------------


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/login")
def login(body: LoginBody):
    token = directory.login(body.username, body.password)
    return {"token": token, "user": directory.users[body.username].public()}


@app.get("/api/me")
def me(user: CurrentUser):
    return user.public()


@app.get("/api/users")
def users():
    return [u.public() for u in directory.users.values()]


@app.get("/api/health")
def health():
    if world is None:
        return JSONResponse({"ok": False, "status": "degraded", "components": [], "detail": "starting"}, 503)
    with lock:
        return W().health()


class AutonomyBody(BaseModel):
    mode: Literal["shadow", "supervised", "autonomous"]
    reason: str = Field(min_length=1, max_length=500)


@app.get("/api/autonomy")
def get_autonomy():
    with lock:
        return W().autonomy_info()


@app.post("/api/autonomy")
def set_autonomy(body: AutonomyBody, user: Controller):
    with lock:
        try:
            return W().set_autonomy(body.mode, user.username, body.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/worklist")
def worklist(limit: int = 50):
    with lock:
        return W().worklist(min(max(limit, 1), 500))


@app.get("/api/export/audit")
def export_audit():
    """The whole hash chain as JSONL, preceded by the verifier's report, so an auditor can re-check it offline."""
    with lock:
        c = W().conn
        report = verify_mod.verify(c)
        head = audit.head(c)
        lines = [json.dumps({"verification": report}, sort_keys=True)]
        lines += [
            json.dumps(audit.serialize(r), sort_keys=True) for r in c.execute("SELECT * FROM audit_log ORDER BY id")
        ]
    return Response(
        "\n".join(lines) + "\n",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="settle-audit-{head[:12]}.jsonl"'},
    )


DECISION_COLUMNS = (
    "id",
    "sim_date",
    "customer_id",
    "customer_name",
    "source",
    "action",
    "amount_cents",
    "tier",
    "status",
    "approver",
    "confidence",
    "trigger",
    "rationale",
    "tier_reasons",
    "evidence",
)


def _csv_safe(v):
    """Neutralise spreadsheet formula injection: customer-influenced text must not start with = + - @."""
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v)
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


@app.get("/api/export/decisions.csv")
def export_decisions():
    with lock:
        names = _names()
        rows = [ser_decision(r, names) for r in W().conn.execute("SELECT * FROM decisions ORDER BY id").fetchall()]
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(DECISION_COLUMNS)
    for d in rows:
        out.writerow([_csv_safe(d[k]) for k in DECISION_COLUMNS])
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="settle-decisions.csv"'},
    )


# ---- single-port deploy: serve the built frontend (registered last so every /api route wins) ---------------


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/") or not FRONTEND_DIST.is_dir():
        raise HTTPException(404, "not found")
    base = FRONTEND_DIST.resolve()
    target = (base / path).resolve()
    if path and target.is_file() and target.is_relative_to(base):
        return FileResponse(target)
    return FileResponse(base / "index.html")
