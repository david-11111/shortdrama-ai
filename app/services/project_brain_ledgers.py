"""Compatibility shim — delegates to ``app.services.ledgers``.

All new code should import from ``app.services.ledgers`` directly.
This module exists only to preserve existing call sites during the
migration; it will be removed in a future cleanup pass.
"""
from __future__ import annotations

from typing import Any

from app.services.ledgers import (
    build_director_ledgers,
    director_ledger_missing_items,
    director_ledger_risks,
    director_ledger_signals,
)

__all__ = [
    "build_director_ledgers",
    "director_ledger_signals",
    "director_ledger_risks",
    "director_ledger_missing_items",
]

# Legacy helper exports — kept for callers that imported them directly
PASS_IMAGE_STATUSES = {"usable", "pass", "passed", "approved", "ok"}
PASS_VIDEO_STATUSES = {"cuttable", "pass", "passed", "approved", "ok"}
BAD_REVIEW_STATUSES = {"regenerate", "failed", "fail", "rejected", "blocked"}
DONE_STATUSES = {"video_done", "done", "final_done", "exported"}
