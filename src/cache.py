# ============================================================
# FILE: src/cache.py
# PURPOSE: SQLite-backed 24-hour TTL cache for Screener.in
#          company data. Prevents redundant scraping when the
#          same ticker is requested multiple times in a day.
# INPUT:   ticker (str), data (dict)
# OUTPUT:  dict or None
# DEPENDS: stdlib sqlite3, json, datetime — no extra deps
# ============================================================

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = "data/cache/fintel.db"
TTL_HOURS = 24


def init_db() -> None:
    """
    Creates the cache database and table if they don't already exist.

    Must be called once at application startup (e.g. in FastAPI lifespan).
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.

    Returns:
        None

    Raises:
        sqlite3.OperationalError: if the DB directory is not writable.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                ticker     TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_cached(ticker: str) -> dict | None:
    """
    Returns cached company data for the ticker if it exists and is fresh.

    A cache entry is considered fresh if it was fetched within the last
    TTL_HOURS (24 hours). Expired entries are treated as cache misses.

    Args:
        ticker: NSE/BSE stock symbol, e.g. "RELIANCE". Case-sensitive —
                callers should normalise to uppercase before calling.

    Returns:
        The cached dict if a fresh entry exists, or None on cache miss.

    Raises:
        sqlite3.OperationalError: if the table does not exist (init_db
                                   was not called first).
    """
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT data, fetched_at FROM cache WHERE ticker = ?",
            (ticker,),
        ).fetchone()

    if row is None:
        return None

    data_json, fetched_at_str = row
    fetched_at = datetime.fromisoformat(fetched_at_str)

    # Expire entries older than TTL_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TTL_HOURS)
    if fetched_at < cutoff:
        return None

    return json.loads(data_json)


def set_cached(ticker: str, data: dict) -> None:
    """
    Inserts or replaces the cached entry for a ticker.

    The fetched_at timestamp is set to the current UTC time. Uses
    INSERT OR REPLACE so repeat calls for the same ticker refresh
    the entry rather than raising.

    Args:
        ticker: NSE/BSE stock symbol, e.g. "RELIANCE".
        data:   Full company data dict from fetch_company_data().

    Returns:
        None

    Raises:
        sqlite3.OperationalError: if the table does not exist.
        TypeError: if data contains values that cannot be JSON-serialised.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (ticker, data, fetched_at) VALUES (?, ?, ?)",
            (ticker, json.dumps(data), fetched_at),
        )
        conn.commit()
