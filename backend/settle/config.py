"""Runtime configuration from environment (optionally backend/.env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# Anthropic first-party prices, USD per million tokens (input, output).
MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass(frozen=True)
class Config:
    db_path: str
    seed: int
    agent_kind: str  # "claude" | "heuristic"
    agent_model: str
    anthropic_workspace_id: str | None
    persona_model: str
    persona_llm: bool
    moss_project_id: str | None
    moss_project_key: str | None
    cache_dir: Path
    replay: bool  # never call external services; serve recordings only (see recorder.py)
    agent_concurrency: int  # parallel agent deliberations per phase of a sim day
    bitdeer_api_key: str | None
    bitdeer_base_url: str
    bitdeer_chat_model: str
    bitdeer_rerank_model: str


def load_config() -> Config:
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    forced = os.getenv("SETTLE_AGENT", "").strip().lower()
    agent_kind = forced if forced in ("claude", "heuristic") else ("claude" if has_key else "heuristic")
    return Config(
        db_path=os.getenv("SETTLE_DB", str(BACKEND_DIR / "data" / "settle.db")),
        seed=int(os.getenv("SETTLE_SEED", "7")),
        agent_kind=agent_kind,
        agent_model=os.getenv("SETTLE_AGENT_MODEL", "claude-opus-5-5"),
        anthropic_workspace_id=os.getenv("ANTHROPIC_WORKSPACE_ID") or None,
        persona_model=os.getenv("SETTLE_PERSONA_MODEL", "claude-opus-5-5"),
        persona_llm=os.getenv("SETTLE_PERSONA_LLM", "0") == "1",
        moss_project_id=os.getenv("MOSS_PROJECT_ID") or None,
        moss_project_key=os.getenv("MOSS_PROJECT_KEY") or None,
        cache_dir=Path(os.getenv("SETTLE_CACHE_DIR", str(BACKEND_DIR / "cache"))),
        replay=os.getenv("SETTLE_REPLAY", "0") == "1",
        agent_concurrency=max(1, int(os.getenv("SETTLE_AGENT_CONCURRENCY", "8") or "8")),
        bitdeer_api_key=os.getenv("BITDEER_API_KEY") or None,
        bitdeer_base_url=os.getenv("BITDEER_BASE_URL", "https://api-inference.bitdeer.ai/v1"),
        bitdeer_chat_model=os.getenv("SETTLE_BITDEER_CHAT_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash"),
        bitdeer_rerank_model=os.getenv("SETTLE_BITDEER_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
    )


def llm_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = MODEL_PRICES.get(model, MODEL_PRICES["claude-opus-5-5"])
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
