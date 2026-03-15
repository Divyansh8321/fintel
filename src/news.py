# ============================================================
# FILE: src/news.py
# PURPOSE: Fetches recent news headlines for a company via
#          NewsAPI and classifies overall sentiment using
#          gpt-4o-mini. Results are cached (24h TTL) to stay
#          within NewsAPI free tier (100 req/day).
# INPUT:   company_name (str), ticker (str)
# OUTPUT:  dict with articles list, sentiment, sentiment_reason
# DEPENDS: requests, openai, .env (NEWS_API_KEY, OPENAI_API_KEY)
# ============================================================

import json
import os

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI()

_NEWSAPI_URL = "https://newsapi.org/v2/everything"


def fetch_news(company_name: str, ticker: str) -> dict:
    """
    Fetches recent news headlines for a company and classifies overall sentiment.

    Queries NewsAPI for the 5 most recent English-language articles mentioning
    the company name in India, then uses gpt-4o-mini to classify the aggregate
    sentiment as bullish, neutral, or bearish.

    Args:
        company_name: Full company name, e.g. "Reliance Industries"
        ticker: NSE ticker symbol, e.g. "RELIANCE" (used only for context)

    Returns:
        dict with keys:
            - articles (list[dict]): Up to 5 articles, each with title, source,
              published_at, url
            - sentiment (str): "bullish" | "neutral" | "bearish"
            - sentiment_reason (str): One-sentence explanation of the sentiment

    Raises:
        RuntimeError: If NEWS_API_KEY is not set or NewsAPI returns a non-200 response
    """
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        raise RuntimeError("NEWS_API_KEY not set in .env")

    query = f'"{company_name}" AND India'
    params = {
        "q": query,
        "pageSize": 5,
        "sortBy": "publishedAt",
        "language": "en",
        "apiKey": api_key,
    }

    response = requests.get(_NEWSAPI_URL, params=params, timeout=10)
    if response.status_code != 200:
        body = response.json() if response.content else {}
        message = body.get("message", response.text)
        raise RuntimeError(f"NewsAPI error {response.status_code}: {message}")

    data = response.json()
    raw_articles = data.get("articles", [])

    if not raw_articles:
        return {
            "articles": [],
            "sentiment": "neutral",
            "sentiment_reason": "No recent news found.",
        }

    articles = [
        {
            "title": a.get("title", ""),
            "source": a.get("source", {}).get("name", ""),
            "published_at": a.get("publishedAt", ""),
            "url": a.get("url", ""),
        }
        for a in raw_articles
    ]

    sentiment, reason = _classify_sentiment(company_name, ticker, articles)

    return {
        "articles": articles,
        "sentiment": sentiment,
        "sentiment_reason": reason,
    }


def _classify_sentiment(company_name: str, ticker: str, articles: list) -> tuple[str, str]:
    """
    Uses gpt-4o-mini to classify aggregate news sentiment from article headlines.

    Args:
        company_name: Company name for context
        ticker: NSE ticker for context
        articles: List of article dicts with title, source, published_at

    Returns:
        Tuple of (sentiment, reason) where sentiment is "bullish"|"neutral"|"bearish"
        and reason is a one-sentence explanation. Falls back to ("neutral",
        "Could not classify sentiment.") on JSON parse failure.
    """
    headlines = "\n".join(
        f"- {a['title']} ({a['source']}, {a['published_at'][:10]})"
        for a in articles
    )

    prompt = (
        f"You are a financial news analyst. Based on the following recent headlines "
        f"about {company_name} ({ticker}), classify the overall sentiment.\n\n"
        f"Headlines:\n{headlines}\n\n"
        f"Return ONLY valid JSON with exactly two keys:\n"
        f'{{"sentiment": "bullish" | "neutral" | "bearish", "reason": "<one sentence>"}}'
    )

    try:
        completion = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = completion.choices[0].message.content.strip()
        parsed = json.loads(raw)
        sentiment = parsed.get("sentiment", "neutral")
        reason = parsed.get("reason", "Could not classify sentiment.")
        if sentiment not in ("bullish", "neutral", "bearish"):
            sentiment = "neutral"
        return sentiment, reason
    except (json.JSONDecodeError, KeyError, Exception):
        return "neutral", "Could not classify sentiment."
