# ============================================================
# FILE: src/telemetry.py
# PURPOSE: Per-call cost and latency tracking for all LLM calls.
#          Writes one row per LLM call to fintel.db (llm_calls table).
#          Provides get_stats() for the /telemetry API endpoint and
#          the frontend dashboard panel.
# INPUT:   model (str), call_type (str), tokens_in/out (int), latency_ms (float)
# OUTPUT:  Rows in llm_calls table; summary dict from get_stats()
# DEPENDS: stdlib sqlite3, datetime — no extra deps
#          DB file: data/cache/fintel.db (shared with cache.py and memory.py)
# ============================================================

import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "fintel.db")
)

# ---------------------------------------------------------------------------
# Pricing table — $ per 1M tokens (input / output)
# Update when OpenAI changes pricing.
# ---------------------------------------------------------------------------
_PRICE_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o":          {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":     {"input": 0.15,  "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "deepseek-chat":   {"input": 0.07,  "output": 0.28},
}
_FALLBACK_PRICE = {"input": 2.50, "output": 10.00}  # assume gpt-4o if unknown


def _price(model: str, tokens_in: int, tokens_out: int) -> float:
    """
    Compute the USD cost for a single LLM call.

    Args:
        model:      Model name string, e.g. "gpt-4o-mini".
        tokens_in:  Prompt token count.
        tokens_out: Completion token count.

    Returns:
        Cost in USD as a float.
    """
    rates = _PRICE_PER_1M.get(model, _FALLBACK_PRICE)
    return (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000


def init_telemetry_table() -> None:
    """
    Creates the llm_calls table if it does not exist.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    Must be called at application startup alongside init_db() and
    init_memory_tables().

    Table schema:
        id           INTEGER  autoincrement primary key
        called_at    TEXT     UTC ISO-8601 timestamp
        model        TEXT     model name, e.g. "gpt-4o-mini"
        call_type    TEXT     label for the call site, e.g. "brief", "news", "filing"
        ticker       TEXT     ticker context (may be empty)
        tokens_in    INTEGER  prompt tokens
        tokens_out   INTEGER  completion tokens
        cost_usd     REAL     computed cost in USD
        latency_ms   REAL     wall-clock time from request to response in ms

    Returns:
        None

    Raises:
        sqlite3.OperationalError: if the DB directory is not writable.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_calls (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                called_at  TEXT    NOT NULL,
                model      TEXT    NOT NULL,
                call_type  TEXT    NOT NULL,
                ticker     TEXT    NOT NULL DEFAULT '',
                tokens_in  INTEGER NOT NULL DEFAULT 0,
                tokens_out INTEGER NOT NULL DEFAULT 0,
                cost_usd   REAL    NOT NULL DEFAULT 0.0,
                latency_ms REAL    NOT NULL DEFAULT 0.0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_called_at ON llm_calls(called_at DESC)"
        )
        conn.commit()


def record_call(
    model: str,
    call_type: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: float,
    ticker: str = "",
) -> None:
    """
    Persist one LLM call record to the llm_calls table.

    Failures are logged and swallowed — a telemetry write failure must
    never break the analysis pipeline.

    Args:
        model:       Model name, e.g. "gpt-4o-mini".
        call_type:   Label for where the call originated: "brief", "chat",
                     "news", "filing".
        tokens_in:   Prompt token count from the API response usage object.
        tokens_out:  Completion token count.
        latency_ms:  Wall-clock duration in milliseconds.
        ticker:      Ticker symbol for context (optional, "" if unknown).

    Returns:
        None
    """
    try:
        cost = _price(model, tokens_in, tokens_out)
        called_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO llm_calls
                    (called_at, model, call_type, ticker, tokens_in, tokens_out, cost_usd, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (called_at, model, call_type, ticker, tokens_in, tokens_out, cost, latency_ms),
            )
            conn.commit()
    except Exception as e:
        logger.warning("telemetry.record_call() failed: %s", e)


def get_stats(limit_calls: int = 50) -> dict:
    """
    Return aggregated and recent telemetry for the /telemetry endpoint.

    Args:
        limit_calls: How many recent individual call rows to include.

    Returns:
        dict with keys:
            total_calls    (int):   all-time call count
            total_cost_usd (float): all-time total cost
            avg_latency_ms (float): all-time average latency
            by_model       (list):  per-model aggregates
                                    [{model, calls, cost_usd, avg_latency_ms}]
            by_type        (list):  per-call-type aggregates
                                    [{call_type, calls, cost_usd, avg_latency_ms}]
            recent         (list):  last `limit_calls` individual rows
                                    [{called_at, model, call_type, ticker,
                                      tokens_in, tokens_out, cost_usd, latency_ms}]
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            totals = conn.execute(
                "SELECT COUNT(*) as calls, SUM(cost_usd) as cost, AVG(latency_ms) as lat FROM llm_calls"
            ).fetchone()

            by_model = conn.execute(
                """
                SELECT model,
                       COUNT(*)          AS calls,
                       SUM(cost_usd)     AS cost_usd,
                       AVG(latency_ms)   AS avg_latency_ms
                FROM llm_calls
                GROUP BY model
                ORDER BY cost_usd DESC
                """
            ).fetchall()

            by_type = conn.execute(
                """
                SELECT call_type,
                       COUNT(*)          AS calls,
                       SUM(cost_usd)     AS cost_usd,
                       AVG(latency_ms)   AS avg_latency_ms
                FROM llm_calls
                GROUP BY call_type
                ORDER BY cost_usd DESC
                """
            ).fetchall()

            recent = conn.execute(
                """
                SELECT called_at, model, call_type, ticker,
                       tokens_in, tokens_out, cost_usd, latency_ms
                FROM llm_calls
                ORDER BY called_at DESC
                LIMIT ?
                """,
                (limit_calls,),
            ).fetchall()

        return {
            "total_calls":    totals["calls"] or 0,
            "total_cost_usd": round(totals["cost"] or 0.0, 6),
            "avg_latency_ms": round(totals["lat"] or 0.0, 1),
            "by_model": [
                {
                    "model":         r["model"],
                    "calls":         r["calls"],
                    "cost_usd":      round(r["cost_usd"], 6),
                    "avg_latency_ms": round(r["avg_latency_ms"], 1),
                }
                for r in by_model
            ],
            "by_type": [
                {
                    "call_type":     r["call_type"],
                    "calls":         r["calls"],
                    "cost_usd":      round(r["cost_usd"], 6),
                    "avg_latency_ms": round(r["avg_latency_ms"], 1),
                }
                for r in by_type
            ],
            "recent": [
                {
                    "called_at":  r["called_at"],
                    "model":      r["model"],
                    "call_type":  r["call_type"],
                    "ticker":     r["ticker"],
                    "tokens_in":  r["tokens_in"],
                    "tokens_out": r["tokens_out"],
                    "cost_usd":   round(r["cost_usd"], 6),
                    "latency_ms": round(r["latency_ms"], 1),
                }
                for r in recent
            ],
        }
    except Exception as e:
        logger.warning("telemetry.get_stats() failed: %s", e)
        return {
            "total_calls": 0, "total_cost_usd": 0.0, "avg_latency_ms": 0.0,
            "by_model": [], "by_type": [], "recent": [],
        }
