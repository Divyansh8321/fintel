# ============================================================
# FILE: src/llm.py
# PURPOSE: Centralised LLM clients for all LLM calls in fintel.
#          Provides three wrappers — each measures latency, reads
#          token usage from the API response, and calls
#          telemetry.record_call() to persist cost + latency data.
#
#            call_deepseek()   — brief + chat (gpt-5-mini in dev,
#                                DeepSeek V3 in prod; set BRIEF_MODEL)
#            call_fast_model() — gpt-4o-mini for news sentiment + filings
#            call_analysis_model() — gpt-4o-mini (legacy; unused in v2)
#
# INPUT:   system/user prompt strings, max_tokens, optional
#          response_format / messages list, optional ticker for telemetry
# OUTPUT:  Raw string content from the model response
# DEPENDS: openai, src/telemetry.py,
#          .env (OPENAI_API_KEY, BRIEF_MODEL, optionally DEEPSEEK_API_KEY)
#
# DEV vs PROD routing for call_deepseek():
#   BRIEF_MODEL=openai    → gpt-5-mini via OpenAI (default)
#   BRIEF_MODEL=deepseek  → DeepSeek V3 (requires DEEPSEEK_API_KEY)
# ============================================================

import logging
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

# Single OpenAI client for gpt-4o, gpt-4o-mini, and the dev brief fallback.
_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# DeepSeek client — only active when BRIEF_MODEL=deepseek.
_deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY") or "placeholder-set-DEEPSEEK_API_KEY-in-env",
    base_url="https://api.deepseek.com",
)

_ANALYSIS_MODEL = "gpt-4o-mini"
_FAST_MODEL     = "gpt-4o-mini"
_DEEPSEEK_MODEL = "deepseek-chat"
_BRIEF_DEV_MODEL = "gpt-5-mini"

# Dev default: gpt-4o-mini (cheap, fast, good enough for testing).
# Flip to "deepseek" before prod deploy.
_BRIEF_BACKEND  = os.getenv("BRIEF_MODEL", "openai").lower()
_BRIEF_MODEL    = _BRIEF_DEV_MODEL

# Legacy alias.
_client = _openai_client


def _record(model: str, call_type: str, response, t0: float, ticker: str = "") -> None:
    """
    Extract token usage from an OpenAI response object and call record_call().

    Imported lazily to avoid a circular import at module load time
    (telemetry imports DB_PATH which imports nothing from llm).

    Args:
        model:     Model name string.
        call_type: Label for the call site, e.g. "brief", "news", "filing".
        response:  Raw OpenAI ChatCompletion response object.
        t0:        time.monotonic() timestamp taken just before the API call.
        ticker:    Ticker symbol for context (optional).
    """
    try:
        from src.telemetry import record_call
        usage      = response.usage
        latency_ms = (time.monotonic() - t0) * 1000
        record_call(
            model=model,
            call_type=call_type,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
            ticker=ticker,
        )
    except Exception as e:
        logger.warning("Telemetry record failed (%s/%s): %s", model, call_type, e)


def call_deepseek(
    system: str,
    user: str,
    max_tokens: int,
    response_format: dict | None = None,
    ticker: str = "",
) -> str:
    """
    Call the brief/chat model and record cost + latency telemetry.

    Routes to DeepSeek V3 or gpt-5-mini depending on BRIEF_MODEL:
      BRIEF_MODEL=openai   → gpt-5-mini via OPENAI_API_KEY (dev default)
      BRIEF_MODEL=deepseek → DeepSeek V3 via DEEPSEEK_API_KEY (prod)

    Args:
        system:          System prompt string.
        user:            User prompt string.
        max_tokens:      Maximum tokens in the response.
        response_format: Optional dict, e.g. {"type": "json_object"}.
        ticker:          Ticker symbol passed through to telemetry (optional).

    Returns:
        Raw string content of the model's first choice message.

    Raises:
        openai.OpenAIError: on API-level failures (auth, quota, timeout).
    """
    if _BRIEF_BACKEND == "deepseek":
        client, model, call_type = _deepseek_client, _DEEPSEEK_MODEL, "brief_deepseek"
    else:
        client, model, call_type = _openai_client, _BRIEF_MODEL, "brief"

    kwargs: dict = {
        "model":                 model,
        "messages":              [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_completion_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    t0       = time.monotonic()
    response = client.chat.completions.create(**kwargs)
    _record(model, call_type, response, t0, ticker)
    return response.choices[0].message.content or ""


def call_analysis_model(
    system: str,
    user: str,
    max_tokens: int,
    response_format: dict | None = None,
    ticker: str = "",
) -> str:
    """
    Call gpt-4o-mini and record cost + latency telemetry.

    Legacy wrapper — used by v1 agents (now deleted). Kept so any external
    callers that import it don't break.

    Args:
        system:          System prompt string.
        user:            User prompt string.
        max_tokens:      Maximum tokens in the response.
        response_format: Optional dict, e.g. {"type": "json_object"}.
        ticker:          Ticker symbol passed through to telemetry (optional).

    Returns:
        Raw string content of the model's first choice message.

    Raises:
        openai.OpenAIError: on API-level failures (auth, quota, timeout).
    """
    kwargs: dict = {
        "model":       _ANALYSIS_MODEL,
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": 0.2,
        "max_tokens":  max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    t0       = time.monotonic()
    response = _openai_client.chat.completions.create(**kwargs)
    _record(_ANALYSIS_MODEL, "analysis", response, t0, ticker)
    return response.choices[0].message.content or ""


def call_fast_model(
    messages: list[dict],
    max_tokens: int,
    temperature: float = 0.1,
    call_type: str = "fast",
    ticker: str = "",
) -> str:
    """
    Call gpt-4o-mini and record cost + latency telemetry.

    Used by news.py (_classify_sentiment) and filings.py (_summarise_pdf).

    Args:
        messages:    List of message dicts in OpenAI format.
        max_tokens:  Maximum tokens in the response.
        temperature: Sampling temperature (default 0.1).
        call_type:   Telemetry label: "news", "filing", or "fast" (default).
        ticker:      Ticker symbol passed through to telemetry (optional).

    Returns:
        Raw string content of the model's first choice message.

    Raises:
        openai.OpenAIError: on API-level failures (auth, quota, timeout).
    """
    t0       = time.monotonic()
    response = _openai_client.chat.completions.create(
        model=_FAST_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    _record(_FAST_MODEL, call_type, response, t0, ticker)
    return response.choices[0].message.content or ""
