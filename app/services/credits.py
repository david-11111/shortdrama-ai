"""Compatibility shim — delegates to ``app.services.credits.service``.

The module-level ``credit_service`` singleton is preserved so existing
callers like ``credit_service.reserve(...)`` continue to work.
"""
from __future__ import annotations

# Recreate the legacy ``AsyncSessionLocal`` — bound at module load time.
# New callers should construct ``CreditService(session_factory)`` explicitly.

import importlib.util
from pathlib import Path

from app.db import AsyncSessionLocal as _session_factory

_service_path = Path(__file__).with_name("credits") / "service.py"
_service_spec = importlib.util.spec_from_file_location("_shortdrama_credit_service", _service_path)
if _service_spec is None or _service_spec.loader is None:
    raise ImportError(f"Cannot load credit service implementation from {_service_path}")
_service_module = importlib.util.module_from_spec(_service_spec)
_service_spec.loader.exec_module(_service_module)

CreditAccountNotFoundError = _service_module.CreditAccountNotFoundError
CreditError = _service_module.CreditError
CreditService = _service_module.CreditService
InsufficientCreditsError = _service_module.InsufficientCreditsError
UnknownCreditOperationError = _service_module.UnknownCreditOperationError

__all__ = [
    "CreditService",
    "CreditError",
    "InsufficientCreditsError",
    "CreditAccountNotFoundError",
    "UnknownCreditOperationError",
    "credit_service",
    "DEFAULT_PRICING",
]

DEFAULT_PRICING = {
    "video_gen_5s": 80,
    "video_gen_8s": 120,
    "video_gen_10s": 160,
    "video_gen_15s": 240,
    "image_gen": 12,
    "llm_refine": 6,
    "llm_director_chat": 6,
    "final_cut_ai_plan": 6,
    "pipeline_analysis": 15,
    "tts_synthesis": 1,
}

# Module-level singleton (backward-compatible)
credit_service = CreditService(session_factory=_session_factory)

# Legacy error classes (re-exported)
CreditService = CreditService
CreditError = CreditError
InsufficientCreditsError = InsufficientCreditsError
CreditAccountNotFoundError = CreditAccountNotFoundError
UnknownCreditOperationError = UnknownCreditOperationError
