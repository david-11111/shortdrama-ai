# Main Chain Implementation Contract

**Authoritative chain:**

goal -> agent_run -> unified facts -> DecisionTickResult -> dispatch gateway -> lane handler -> terminal observation -> next decision

## 7-Layer Map

- L1 Authoritative Run
- L2 Unified Facts
- L3 Decision Packet
- L4 Dispatch Gateway
- L5 Lane Execution
- L6 Terminal Observation
- L7 Next Decision

## Invariants

1. Production writes in an agent run must pass through `dispatch_authoritative_packet`.
2. Canonical production packets must come from `load_run_facts_from_snapshot -> evaluate_decision_tick`.
3. B lane may answer, diagnose, defer, or request an action, but it must not queue provider tasks directly.
4. Direct batch APIs are platform/direct-task paths, not agent main-chain paths.
5. A run is complete only when L7 returns `complete`, not merely when current sibling tasks are terminal.

## Allowed Main-Chain Entry Points

- `POST /api/agent-runs`
- `POST /api/agent-runs/{run_id}/actions/continue-step`
- `POST /api/projects/{project_id}/brain/continue`
- terminal task hook in `app/tasks/_shared.py`

## Platform-Only Direct Task Entry Points

- `POST /api/batch/generate-videos`
- `POST /api/batch/generate-images`
- `POST /api/tts/generate`

These endpoints may queue tasks directly for manual SaaS operations. They must not be used by agent main-chain routes to perform autonomous production.

## Agent Runtime Foundation Invariants

1. B lane can recommend, diagnose, explain, and request actions; it cannot execute provider work.
2. C lane can execute assigned missions; it cannot choose the global next action.
3. Every autonomous production dispatch must pass the gateway capability whitelist.
4. Decision mailbox events provide the durable audit trail for pending, completed, rejected, recovered, and cancelled decisions.
5. L7 observation must verify task state and expected DB writeback separately.
6. DeepSeek and Doubao mailbox outputs are recommendations/artifacts, not authority.
7. Seedream and Seedance jobs require active observation: progress, heartbeat, timeout, user control, provider result, and DB writeback verification.
8. Decision mailbox records store `decision_rationale` and `thinking_artifacts`, not hidden chain-of-thought.
9. Gateway checks `CAPABILITY_REQUIREMENTS` before executing any provider/tool handler.
10. Required artifacts are verified as a set; missing outputs produce `MISSING_ARTIFACT` or `WRITEBACK_FAILED`.
11. Dangerous actions and high-risk packets are blocked by the controller safety circuit breaker before gateway dispatch.
