# ============================================================
# FILE: src/memory.py
# PURPOSE: Persistent memory layer for Fintel. Extends the
#          existing fintel.db SQLite database with two new
#          tables: analyst_history (every analysis ever run
#          for a ticker) and watchlist (user-curated tickers
#          with optional notes).
# INPUT:   ticker (str), result dict (from /analyze pipeline)
# OUTPUT:  list of history rows, list of watchlist rows
# DEPENDS: stdlib sqlite3, json, datetime — no extra deps
#          DB file: data/cache/fintel.db (shared with cache.py)
# ============================================================

import json
import os
import sqlite3
from datetime import datetime, timezone

# Reuse the same DB file as cache.py — anchored to this file's location
# so it works regardless of where uvicorn/streamlit is launched from.
DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "fintel.db")
)


def init_memory_tables() -> None:
    """
    Creates the analyst_history and watchlist tables if they don't exist.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    Must be called at application startup alongside cache.init_db().

    Table schemas:
        analyst_history — one row per analysis run per ticker.
            id          INTEGER  autoincrement primary key
            ticker      TEXT     NSE symbol, e.g. "RELIANCE"
            run_at      TEXT     ISO-8601 UTC timestamp of the run
            consensus   REAL     weighted consensus score 1–10 (NULL if unavailable)
            verdict     TEXT     "buy" | "hold" | "sell" | "avoid" (NULL if unavailable)
            agents_json TEXT     JSON blob of the full agents dict
            signals_json TEXT    JSON blob of the signals dict

        watchlist — user-managed list of tickers to track.
            ticker      TEXT     PRIMARY KEY — NSE symbol
            added_at    TEXT     ISO-8601 UTC timestamp when added
            note        TEXT     free-text user note (may be empty)

    Returns:
        None

    Raises:
        sqlite3.OperationalError: if the DB directory is not writable.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        # History table — append-only, never updated after insert
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyst_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT    NOT NULL,
                run_at       TEXT    NOT NULL,
                consensus    REAL,
                verdict      TEXT,
                agents_json  TEXT    NOT NULL,
                signals_json TEXT    NOT NULL
            )
            """
        )
        # Watchlist — one row per ticker, user can add/remove freely
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker    TEXT PRIMARY KEY,
                added_at  TEXT NOT NULL,
                note      TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()


def save_analysis(ticker: str, result: dict) -> None:
    """
    Persists a completed analysis run to the analyst_history table.

    Extracts the consensus score and verdict from result["synthesis"]
    (if present) and the agents dict from result["agents"] (if present).
    Falls back gracefully when Phase 3+ fields are missing so this
    function works even if called with a Phase 2 result dict.

    Args:
        ticker: NSE/BSE symbol (uppercase), e.g. "RELIANCE".
        result: Full pipeline result dict — the same dict cached by
                cache.set_cached(). Expected top-level keys:
                  signals  (dict)
                  synthesis (dict, optional)  — Phase 3+
                  agents   (dict, optional)   — Phase 3+

    Returns:
        None

    Raises:
        sqlite3.OperationalError: if init_memory_tables() was not called.
        TypeError: if result contains non-JSON-serialisable values.
    """
    run_at = datetime.now(timezone.utc).isoformat()

    # Extract synthesis fields — None if not yet computed (pre-Phase 3 run)
    synthesis = result.get("synthesis") or {}
    consensus = synthesis.get("consensus_score")
    verdict = synthesis.get("verdict")

    # Agents dict — default to empty if pre-Phase 3
    agents = result.get("agents") or {}

    # Signals are always present in Phase 2+
    signals = result.get("signals") or {}

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO analyst_history
                (ticker, run_at, consensus, verdict, agents_json, signals_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                run_at,
                consensus,
                verdict,
                json.dumps(agents),
                json.dumps(signals),
            ),
        )
        conn.commit()


def get_history(ticker: str) -> list[dict]:
    """
    Returns all historical analysis runs for a ticker, newest first.

    Each row in the returned list represents one analysis run and contains:
        id          (int)   — autoincrement row ID
        ticker      (str)   — NSE symbol
        run_at      (str)   — ISO-8601 UTC timestamp
        consensus   (float|None) — weighted consensus score 1–10
        verdict     (str|None)   — "buy"|"hold"|"sell"|"avoid"
        agents      (dict)  — per-agent scores and notes
        signals     (dict)  — full signals dict for that run

    Args:
        ticker: NSE/BSE symbol (uppercase), e.g. "RELIANCE".

    Returns:
        List of dicts, ordered by run_at DESC. Empty list if no history.

    Raises:
        sqlite3.OperationalError: if init_memory_tables() was not called.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, ticker, run_at, consensus, verdict, agents_json, signals_json
            FROM analyst_history
            WHERE ticker = ?
            ORDER BY run_at DESC
            """,
            (ticker,),
        ).fetchall()

    result = []
    for row in rows:
        # Decode JSON blobs — treat malformed JSON as empty dict rather than crashing
        try:
            agents = json.loads(row["agents_json"])
        except json.JSONDecodeError:
            agents = {}
        try:
            signals = json.loads(row["signals_json"])
        except json.JSONDecodeError:
            signals = {}

        result.append(
            {
                "id": row["id"],
                "ticker": row["ticker"],
                "run_at": row["run_at"],
                "consensus": row["consensus"],
                "verdict": row["verdict"],
                "agents": agents,
                "signals": signals,
            }
        )

    return result


def add_to_watchlist(ticker: str, note: str = "") -> None:
    """
    Adds a ticker to the watchlist. If the ticker is already present,
    updates the note but preserves the original added_at timestamp.

    Args:
        ticker: NSE/BSE symbol (uppercase), e.g. "RELIANCE".
        note:   Optional free-text note, e.g. "Watch for Q3 results".

    Returns:
        None

    Raises:
        sqlite3.OperationalError: if init_memory_tables() was not called.
    """
    # Use INSERT OR IGNORE to avoid overwriting added_at on duplicates,
    # then update the note in a separate statement.
    added_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, added_at, note) VALUES (?, ?, ?)",
            (ticker, added_at, note),
        )
        # Always update the note so the caller can change it after first add
        conn.execute(
            "UPDATE watchlist SET note = ? WHERE ticker = ?",
            (note, ticker),
        )
        conn.commit()


def remove_from_watchlist(ticker: str) -> bool:
    """
    Removes a ticker from the watchlist.

    Args:
        ticker: NSE/BSE symbol (uppercase), e.g. "RELIANCE".

    Returns:
        True if the ticker was removed, False if it was not in the watchlist.

    Raises:
        sqlite3.OperationalError: if init_memory_tables() was not called.
    """
    with sqlite3.connect(DB_PATH) as conn:
        deleted = conn.execute(
            "DELETE FROM watchlist WHERE ticker = ?", (ticker,)
        ).rowcount
        conn.commit()
    return deleted > 0


def get_watchlist() -> list[dict]:
    """
    Returns all tickers in the watchlist, ordered alphabetically.

    Each item in the returned list contains:
        ticker    (str) — NSE symbol
        added_at  (str) — ISO-8601 UTC timestamp when added
        note      (str) — free-text user note (may be empty string)

    Returns:
        List of dicts, ordered by ticker ASC. Empty list if watchlist is empty.

    Raises:
        sqlite3.OperationalError: if init_memory_tables() was not called.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, added_at, note FROM watchlist ORDER BY ticker ASC"
        ).fetchall()

    return [dict(row) for row in rows]
