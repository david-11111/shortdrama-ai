# -*- coding: utf-8 -*-
"""Director AI services package for SaaS.

Exposes the main public functions from each director module.
Business logic is unchanged from the original app/services/director_*.py files.
"""
from __future__ import annotations

from .presets import get_director_presets, get_director_evaluation_rubric, resolve_director_preset
from .paths import safe_path_segment
from .store import ensure_director_tables
from .trace import log_director_event, load_trace_records, summarize_library_hits
from .memory import (
    get_project_memory,
    update_project_profile,
    upsert_character_profile,
    add_rework_note,
    build_memory_context,
)
from .reasoning import diagnose_task, recommend_mode, diagnose_and_recommend
from .evaluator import evaluate_run
from .rework import suggest_rework
from .evolution import record_case, list_patterns
from .explainer import explain_decision, explain_run
from .evolution_index import get_evolution_index

__all__ = [
    "get_director_presets",
    "get_director_evaluation_rubric",
    "resolve_director_preset",
    "safe_path_segment",
    "ensure_director_tables",
    "log_director_event",
    "load_trace_records",
    "summarize_library_hits",
    "get_project_memory",
    "update_project_profile",
    "upsert_character_profile",
    "add_rework_note",
    "build_memory_context",
    "diagnose_task",
    "recommend_mode",
    "diagnose_and_recommend",
    "evaluate_run",
    "suggest_rework",
    "record_case",
    "list_patterns",
    "explain_decision",
    "explain_run",
    "get_evolution_index",
]
