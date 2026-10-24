"""ClaudeAgent loop against a fake Anthropic client (the network is the only thing faked)."""

import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest

from settle.agent import AgentContext, ClaudeAgent
from settle.models import WorkItem
from settle.recorder import Recorder


def block_tool(name, inp, id_="tu_1"):
    return NS(type="tool_use", name=name, input=inp, id=id_)


def resp(blocks, stop="tool_use", tin=100, tout=50):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=tin, output_tokens=tout))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ctx():
    item = WorkItem(1, "2026-07-10", "bank_line", "B-1", None, "$100.00 from MYSTERY CO")
    return AgentContext(
        item=item,
        today="2026-07-10",
        customer=None,
        profile=None,
        bank_line={"id": "B-1", "amount_cents": 10000, "payer_name": "MYSTERY CO", "remittance_text": ""},
        find_open_invoices=lambda customer_id=None, amount_cents=None: [
            {"id": "INV-1", "customer_id": "C-03", "balance_cents": 10000}
        ],
        search_memory=lambda q, c=None: [],
    )


SUBMIT = {
    "action": "apply_payment",
    "args_json": json.dumps(
        {"bank_line_id": "B-1", "customer_id": "C-03", "allocations": [{"invoice_id": "INV-1", "amount_cents": 10000}]}
    ),
    "rationale": "Unique amount match.",
    "evidence": ["bank:B-1", "invoice:INV-1"],
    "memory_ids": [],
    "confidence": 0.8,
    "trigger": "unidentified_payment",
}


def make_agent(client, tmp_path, usage, replay=False):
    rec = Recorder(tmp_path / "recordings.jsonl", replay=replay)
    return ClaudeAgent("claude-opus-5-5", lambda *a: usage.append(a), rec, client=client)


def test_tool_loop_then_submit_records_usage_and_caches(tmp_path):
    client = FakeClient(
        [
            resp([block_tool("find_open_invoices", {"customer_id": None, "amount_cents": 10000})]),
            resp([block_tool("submit_decision", SUBMIT, "tu_2")]),
        ]
    )
    usage = []
    agent = make_agent(client, tmp_path, usage)
    d = agent.decide(ctx())
    assert d.action == "apply_payment" and d.args["customer_id"] == "C-03" and d.llm_calls == 2
    assert len(usage) == 2 and usage[0][1] == "claude-opus-5-5"
    # tool result was sent back with the matching id
    tool_msg = client.calls[1]["messages"][-1]["content"][0]
    assert tool_msg["tool_use_id"] == "tu_1" and "INV-1" in tool_msg["content"]
    # request shape: strict tools, auto tool choice, server-side fallbacks
    kw = client.calls[0]
    assert kw["tool_choice"] == {"type": "auto"} and kw["fallbacks"] == "default"
    assert all(t["strict"] for t in kw["tools"])
    # provenance carries the tool transcript and hashes the exact input
    assert d.provenance["replay"] == "live" and d.provenance["steps"][0]["tool"] == "find_open_invoices"
    assert len(d.provenance["input_sha256"]) == 64
    # replay mode serves the identical decision and transcript with no API call
    again = make_agent(FakeClient([]), tmp_path, usage, replay=True).decide(ctx())
    assert again.action == "apply_payment" and again.llm_calls == 0 and again.args == d.args
    assert again.provenance["replay"] == "hit" and again.provenance["steps"] == d.provenance["steps"]


def test_replay_miss_falls_back_deterministically(tmp_path):
    d = make_agent(None, tmp_path, [], replay=True).decide(ctx())
    assert d.provenance["replay"] == "miss" and d.provenance["component"] == "heuristic"
    assert d.rationale.startswith("[replay miss")


def test_tool_error_is_returned_to_model_not_swallowed(tmp_path):
    client = FakeClient(
        [resp([block_tool("nonexistent_tool", {})]), resp([block_tool("submit_decision", SUBMIT, "tu_2")])]
    )
    make_agent(client, tmp_path, []).decide(ctx())
    result = client.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "unknown tool" in result["content"]


def test_api_failure_falls_back_to_heuristic(tmp_path):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = FakeClient([anthropic.APIConnectionError(request=req)])
    d = make_agent(client, tmp_path, []).decide(ctx())
    assert d.rationale.startswith("[LLM unavailable: APIConnectionError") and d.action == "apply_payment"


@pytest.mark.parametrize(
    "bad",
    [
        resp([], stop="refusal"),
        resp([block_tool("submit_decision", {**SUBMIT, "args_json": "[1,2]"})]),
        resp([block_tool("submit_decision", {**SUBMIT, "action": "launch_rockets"})]),
    ],
)
def test_bad_model_output_falls_back(tmp_path, bad):
    d = make_agent(FakeClient([bad]), tmp_path, []).decide(ctx())
    assert "[LLM unavailable" in d.rationale


def test_no_tool_call_reprompts_then_gives_up(tmp_path):
    text = NS(type="text", text="thinking out loud")
    client = FakeClient([resp([text], stop="end_turn")] * 6)
    d = make_agent(client, tmp_path, []).decide(ctx())
    assert len(client.calls) == 6 and "[LLM unavailable" in d.rationale


def test_environment_errors_are_not_recorded_so_they_retry_live(tmp_path):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad = anthropic.BadRequestError(
        "needs anthropic-workspace-id header", response=httpx.Response(400, request=req), body=None
    )
    d = make_agent(FakeClient([bad]), tmp_path, []).decide(ctx())
    assert d.provenance["replay"] == "error" and "[LLM unavailable" in d.rationale
    # nothing was recorded: once the environment is fixed, the next attempt calls the model again
    client = FakeClient([resp([block_tool("submit_decision", SUBMIT)])])
    again = make_agent(client, tmp_path, []).decide(ctx())
    assert again.provenance["replay"] == "live" and len(client.calls) == 1


def test_workspace_id_header_is_sent():
    from settle.agent import anthropic_client

    c = anthropic_client("wrkspc_test")
    assert c.default_headers.get("anthropic-workspace-id") == "wrkspc_test"
    assert "anthropic-workspace-id" not in anthropic_client(None).default_headers
