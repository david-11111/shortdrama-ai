"""Production state machine — policies, gates, and status evaluation.

Replaces the former flat ``agent_run_state_machine.py`` with a structured
package.  Key improvements:

1. **Single-pass statistics** — ``_StatsAccumulator`` traverses shots/tasks
   once instead of 13 independent list comprehensions.
2. **Typed models** — ``ProductionPolicy`` is a Pydantic model, not a
   positional tuple; ``GateResult`` comes from ``app.core.types``.
3. **No circular imports** — ``_resolve_node_id`` is injected as a
   dependency rather than imported at runtime.
4. **Testable** — every function accepts plain data and returns plain data.
"""

from __future__ import annotations

from app.services.state_machine.models import (
    PRODUCTION_POLICIES,
    PRODUCTION_STAGES,
    POLICY_BY_STAGE_ID,
    POLICY_VERSION,
    STAGE_BY_ACTION,
    STAGE_BY_ID,
    validate_policy_graph,
)
from app.services.state_machine.evaluator import (
    evaluate_action_gate,
    evaluate_production_stages,
    recommend_next_action,
    should_escalate,
)
from app.services.state_machine.intent import (
    infer_continue_action,
    infer_continue_action_decision,
)

__all__ = [
    "PRODUCTION_POLICIES",
    "PRODUCTION_STAGES",
    "POLICY_BY_STAGE_ID",
    "POLICY_VERSION",
    "STAGE_BY_ACTION",
    "STAGE_BY_ID",
    "validate_policy_graph",
    "evaluate_action_gate",
    "evaluate_production_stages",
    "recommend_next_action",
    "infer_continue_action",
    "infer_continue_action_decision",
    "should_escalate",
]
