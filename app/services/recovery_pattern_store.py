"""Recovery Pattern Store — persistent learning from fallback resolutions.

Two-tier storage:
1. In-memory LRU cache (fast path, single-process, reset on restart)
2. PostgreSQL ``recovery_patterns`` table (persistent, cross-session)

When a fallback resolution succeeds (resolved + high confidence), a pattern
is stored so that the same situation can be resolved without an LLM call
on subsequent occurrences.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATTERN_CACHE_TTL_SECONDS = 3600  # 1 hour in-memory TTL
PATTERN_DB_TTL_DAYS = 90  # Auto-expire patterns after 90 days
MIN_CONFIDENCE_FOR_MATCH = 0.7  # Minimum confidence to use a stored pattern
MIN_FREQUENCY_FOR_MATCH = 3  # Must have resolved at least this many times
MIN_CONFIDENCE_FOR_STORE = 0.8  # Minimum confidence to persist a new pattern

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_pattern_cache: dict[str, dict[str, Any]] = {}
"""Simple in-memory store. In production, replace with ``cachetools.TTLCache``."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def match_pattern(
    db: AsyncSession,
    *,
    trigger_source: str,
    trigger_kind: str,
    trigger_reason: str,
    missing_items: list[str] | None = None,
) -> dict[str, Any] | None:
    """Look up a recovery pattern by trigger signature.

    Checks the in-memory cache first, then the DB. Returns the pattern dict
    or ``None``.
    """
    signature = _compute_signature(trigger_source, trigger_kind, trigger_reason, missing_items)

    # 1. In-memory fast path
    cached = _pattern_cache.get(signature)
    if cached is not None:
        confidence = float(cached.get("confidence", 0))
        frequency = int(cached.get("frequency", 0))
        if confidence >= MIN_CONFIDENCE_FOR_MATCH and frequency >= MIN_FREQUENCY_FOR_MATCH:
            logger.debug("Recovery pattern cache HIT: %.20s (conf=%.2f, freq=%d)", signature, confidence, frequency)
            return cached

    # 2. DB-backed path
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT pattern_id, trigger_signature, recommendation_action,
                           confidence, frequency, metadata
                    FROM recovery_patterns
                    WHERE trigger_signature = :signature
                      AND confidence >= :min_conf
                      AND frequency >= :min_freq
                      AND expires_at > NOW()
                    ORDER BY frequency DESC
                    LIMIT 1
                    """
                ),
                {
                    "signature": signature,
                    "min_conf": MIN_CONFIDENCE_FOR_MATCH,
                    "min_freq": MIN_FREQUENCY_FOR_MATCH,
                },
            )
        ).mappings().first()
    except Exception as exc:
        logger.warning("Recovery pattern DB query failed (non-blocking): %s", exc)
        return None

    if row is not None:
        pattern = dict(row)
        _pattern_cache[signature] = pattern
        logger.debug("Recovery pattern DB HIT: %.20s (conf=%.2f, freq=%d)", signature, pattern.get("confidence", 0), pattern.get("frequency", 0))
        return pattern

    return None


async def record_pattern(
    db: AsyncSession,
    *,
    trigger_source: str,
    trigger_kind: str,
    trigger_reason: str,
    missing_items: list[str] | None,
    recommendation_action: str,
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Store or update a recovery pattern after a successful fallback.

    Only stores if ``confidence >= MIN_CONFIDENCE_FOR_STORE``.
    Returns the ``pattern_id`` or ``None``.
    """
    if confidence < MIN_CONFIDENCE_FOR_STORE:
        return None

    signature = _compute_signature(trigger_source, trigger_kind, trigger_reason, missing_items)
    pattern_id = str(uuid4())
    now = datetime.now(timezone.utc)
    meta = metadata or {}

    # Update in-memory cache
    _pattern_cache[signature] = {
        "pattern_id": pattern_id,
        "trigger_signature": signature,
        "recommendation_action": recommendation_action,
        "confidence": confidence,
        "frequency": 1,
        "metadata": meta,
    }

    # Try DB UPSERT
    try:
        await db.execute(
            text(
                """
                INSERT INTO recovery_patterns
                    (pattern_id, trigger_signature, recommendation_action,
                     confidence, frequency, first_observed_at, last_used_at,
                     expires_at, metadata)
                VALUES
                    (:pattern_id, :signature, :action,
                     :confidence, 1, :now, :now,
                     :expires_at, :metadata::jsonb)
                ON CONFLICT (trigger_signature) DO UPDATE SET
                    frequency = recovery_patterns.frequency + 1,
                    confidence = GREATEST(recovery_patterns.confidence, :confidence),
                    last_used_at = :now,
                    metadata = CASE
                        WHEN :metadata::jsonb != '{}'::jsonb
                        THEN recovery_patterns.metadata || :metadata::jsonb
                        ELSE recovery_patterns.metadata
                    END
                """
            ),
            {
                "pattern_id": pattern_id,
                "signature": signature,
                "action": recommendation_action,
                "confidence": confidence,
                "now": now,
                "expires_at": now + timedelta(days=PATTERN_DB_TTL_DAYS),
                "metadata": _serialise_metadata(meta),
            },
        )
        await db.commit()
        logger.info("Recovery pattern stored: %.20s -> %s (conf=%.2f)", signature, recommendation_action, confidence)
        return pattern_id
    except Exception as exc:
        logger.warning("Recovery pattern DB write failed (non-blocking): %s", exc)
        await db.rollback()
        # Pattern is already cached in-memory, so it still helps within this session
        return pattern_id


async def cleanup_expired_patterns(db: AsyncSession) -> int:
    """Remove expired patterns from the DB. Returns count of deleted rows."""
    try:
        result = await db.execute(
            text("DELETE FROM recovery_patterns WHERE expires_at <= NOW()")
        )
        await db.commit()
        count = result.rowcount
        if count:
            logger.info("Cleaned up %d expired recovery patterns", count)
        return count
    except Exception as exc:
        logger.warning("Recovery pattern cleanup failed: %s", exc)
        await db.rollback()
        return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_signature(
    trigger_source: str,
    trigger_kind: str,
    trigger_reason: str,
    missing_items: list[str] | None = None,
) -> str:
    """Compute a deterministic SHA-256 signature for a trigger situation.

    The signature captures:
    - The trigger source (runtime_decision, gate_recovery_empty, etc.)
    - The trigger kind (reject, ask, blocked, etc.)
    - The trigger reason (capability_not_registered, etc.)
    - The top-3 missing items (if applicable)
    """
    items = sorted(str(m) for m in (missing_items or []))[:3]
    raw = f"{trigger_source}:{trigger_kind}:{trigger_reason}:{':'.join(items)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _serialise_metadata(meta: dict[str, Any]) -> str:
    import json
    try:
        return json.dumps(meta, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


# ---------------------------------------------------------------------------
# DB migration
# ---------------------------------------------------------------------------

DB_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS recovery_patterns (
    pattern_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_signature TEXT NOT NULL UNIQUE,
    recommendation_action TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    frequency INTEGER NOT NULL DEFAULT 1,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '90 days'),
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_recovery_patterns_trigger
    ON recovery_patterns(trigger_signature);

CREATE INDEX IF NOT EXISTS idx_recovery_patterns_frequency
    ON recovery_patterns(frequency DESC);
"""
"""SQL to create the ``recovery_patterns`` table and indexes.

Run this as a one-off migration, e.g. via Alembic or an init script.
"""
