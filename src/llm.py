# ============================================================
# FILE: src/llm.py
# PURPOSE: Centralised OpenAI client for all LLM calls in fintel.
#          Provides two thin wrappers — one for the analysis model
#          (gpt-4o, used by analyst agents + synthesis) and one for
#          the fast model (gpt-4o-mini, used by news sentiment +
#          filing summaries). Eliminates the duplicated client
#          instantiation and model-name hardcoding that previously
#          appeared in 8 separate modules.
# INPUT:   system/user prompt strings, max_tokens, optional
#          response_format / messages list
# OUTPUT:  Raw string content from the model response
# DEPENDS: openai, .env (OPENAI_API_KEY)
# ============================================================

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Single client instance shared across the whole process.
# OpenAI() reads OPENAI_API_KEY from the environment automatically.
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_ANALYSIS_MODEL = "gpt-4o"
_FAST_MODEL     = "gpt-4o-mini"


def call_analysis_model(
    system: str,
    user: str,
    max_tokens: int,
    response_format: dict | None = None,
) -> str:
    """
    Call the analysis model (gpt-4o) with a system + user prompt.

    Used by all five analyst agents and synthesis.py. Callers are
    responsible for JSON parsing and validation of the returned string.

    Args:
        system:          System prompt string.
        user:            User prompt string.
        max_tokens:      Maximum tokens in the response. Callers set this
                         explicitly — agents use 500, synthesis uses 600.
        response_format: Optional dict passed to the API, e.g.
                         {"type": "json_object"} to force JSON output.

    Returns:
        Raw string content of the model's first choice message.

    Raises:
        openai.OpenAIError: on API-level failures (auth, quota, timeout).
    """
    kwargs = {
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

    response = _client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def call_fast_model(
    messages: list[dict],
    max_tokens: int,
    temperature: float = 0.1,
) -> str:
    """
    Call the fast model (gpt-4o-mini) with an arbitrary messages list.

    Used by news.py (_classify_sentiment) and filings.py (_summarise_pdf).
    Callers are responsible for JSON parsing and validation of the returned string.

    Args:
        messages:    List of message dicts in OpenAI format,
                     e.g. [{"role": "user", "content": "..."}].
        max_tokens:  Maximum tokens in the response. Callers set this
                     explicitly — filings use 200, news has no hard limit.
        temperature: Sampling temperature (default 0.1 for factual tasks).

    Returns:
        Raw string content of the model's first choice message.

    Raises:
        openai.OpenAIError: on API-level failures (auth, quota, timeout).
    """
    response = _client.chat.completions.create(
        model=_FAST_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
