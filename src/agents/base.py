# ============================================================
# FILE: src/agents/base.py
# PURPOSE: Shared utilities for all analyst agents. Re-exports
#          _safe() from signals.py so agents have a single
#          canonical list accessor without duplicating logic.
# INPUT:   list values, integer index
# OUTPUT:  value at index or None
# DEPENDS: src/signals.py
# ============================================================

from src.signals import _safe  # noqa: F401  — re-exported for agent use
