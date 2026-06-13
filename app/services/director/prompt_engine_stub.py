# -*- coding: utf-8 -*-
"""Compatibility wrapper for legacy director imports.

Director services now use the real prompt-library engine. This module remains
only to keep older imports working during rollout.
"""
from __future__ import annotations

from app.services.prompt.engine import (
    get_library_filters as _get_library_filters,
    resolve_filtered_library_ids as _resolve_filtered_library_ids,
)


def get_library_filters() -> dict:
    return _get_library_filters()


def resolve_filtered_library_ids(filter_mode: str = "", filter_value: str = "") -> set[str] | None:
    return _resolve_filtered_library_ids(filter_mode, filter_value)
