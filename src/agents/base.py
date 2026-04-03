# ============================================================
# FILE: src/agents/base.py
# PURPOSE: Shared utilities for all analyst agents. Currently
#          provides the _safe() list accessor used by value.py
#          and contrarian.py to safely read time-series data
#          from scraper output without index errors.
# INPUT:   list values, integer index
# OUTPUT:  value at index or None
# DEPENDS: nothing
# ============================================================


def _safe(values, idx):
    """
    Safely retrieve values[idx], returning None on any failure.

    Used by agents to read time-series lists from scraper output
    (e.g. pl_table["net_profit"][0]) without risking IndexError
    or TypeError when data is missing or malformed.

    Args:
        values: A list (or anything else).
        idx:    Integer index (positive or negative).

    Returns:
        The value at that index, or None if out-of-range / not a list / None value.
    """
    if not isinstance(values, list) or len(values) == 0:
        return None
    try:
        v = values[idx]
        return v if v is not None else None
    except IndexError:
        return None
