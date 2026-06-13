"""Director ledgers — deterministic project-state summarization.

Key improvements over the original flat ``project_brain_ledgers.py``:

1. **Single-pass shot analysis** — ``ShotAnalysis`` traverses shots once.
2. **Pydantic models** — every ledger has a typed return model.
3. **No magic numbers** — all weights and thresholds are named constants.
4. **No repeated list comprehensions** — ``high_risk_shot_count`` and
   similar values are computed once and reused.
"""

from __future__ import annotations

from app.services.ledgers.builder import build_director_ledgers
from app.services.ledgers.models import (
    CreativeLedger,
    ContinuityLedger,
    CostRiskLedger,
    QualityLedger,
)
from app.services.ledgers.signals import director_ledger_signals, director_ledger_risks, director_ledger_missing_items

__all__ = [
    "build_director_ledgers",
    "CreativeLedger",
    "ContinuityLedger",
    "CostRiskLedger",
    "QualityLedger",
    "director_ledger_signals",
    "director_ledger_risks",
    "director_ledger_missing_items",
]
