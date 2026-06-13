from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TRIM_MARKER = "\n...[context trimmed]...\n"


@dataclass(frozen=True)
class ContextBudget:
    max_messages: int = 48
    max_message_chars: int = 8000
    max_total_chars: int = 256000
    preserve_last_user: bool = True
    allowed_roles: set[str] = field(default_factory=lambda: {"system", "user", "assistant"})


@dataclass(frozen=True)
class ContextBudgetReport:
    input_messages: int = 0
    output_messages: int = 0
    input_chars: int = 0
    output_chars: int = 0
    dropped_messages: int = 0
    dropped_chars: int = 0
    truncated_messages: int = 0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_messages": self.input_messages,
            "output_messages": self.output_messages,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "dropped_messages": self.dropped_messages,
            "dropped_chars": self.dropped_chars,
            "truncated_messages": self.truncated_messages,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PromptMessageBudget:
    max_system_chars: int = 32000
    max_user_chars: int = 64000
    max_total_chars: int = 128000
    history_budget: ContextBudget = field(default_factory=ContextBudget)


@dataclass(frozen=True)
class PromptMessageBudgetReport:
    system_chars: int
    history_chars: int
    final_user_chars: int
    total_chars: int
    history_report: ContextBudgetReport
    trimmed_system: bool = False
    trimmed_final_user: bool = False
    dropped_history_for_total: int = 0
    reason: str = "within_budget"

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_chars": self.system_chars,
            "history_chars": self.history_chars,
            "final_user_chars": self.final_user_chars,
            "total_chars": self.total_chars,
            "history_report": self.history_report.as_dict(),
            "trimmed_system": self.trimmed_system,
            "trimmed_final_user": self.trimmed_final_user,
            "dropped_history_for_total": self.dropped_history_for_total,
            "reason": self.reason,
        }


def build_prompt_messages(
    *,
    system_prompt: Any,
    history: Any,
    final_user_prompt: Any,
    budget: PromptMessageBudget | None = None,
) -> tuple[list[dict[str, str]], PromptMessageBudgetReport]:
    budget = budget or PromptMessageBudget()
    system_text, trimmed_system = compact_text(system_prompt, budget.max_system_chars)
    final_text, trimmed_final = compact_text(final_user_prompt, budget.max_user_chars)
    history_messages, history_report = trim_messages(history, budget.history_budget)

    dropped_for_total = 0

    def _total() -> int:
        return len(system_text) + len(final_text) + sum(len(msg["content"]) for msg in history_messages)

    while history_messages and _total() > budget.max_total_chars:
        history_messages.pop(0)
        dropped_for_total += 1

    if _total() > budget.max_total_chars:
        history_messages = []
        if len(final_text) >= budget.max_total_chars:
            final_text, _ = compact_text(final_text, budget.max_total_chars)
            system_text = ""
            trimmed_final = True
            trimmed_system = True
        else:
            available_for_system = max(0, budget.max_total_chars - len(final_text))
            if len(system_text) > available_for_system:
                system_text, _ = compact_text(system_text, available_for_system)
                trimmed_system = True

    messages: list[dict[str, str]] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.extend(history_messages)
    if final_text:
        messages.append({"role": "user", "content": final_text})

    total_chars = sum(len(msg["content"]) for msg in messages)
    reason = "within_budget"
    if dropped_for_total:
        reason = "dropped_history_for_total"
    elif trimmed_system or trimmed_final or history_report.truncated_messages:
        reason = "trimmed"

    report = PromptMessageBudgetReport(
        system_chars=len(system_text),
        history_chars=sum(len(msg["content"]) for msg in history_messages),
        final_user_chars=len(final_text),
        total_chars=total_chars,
        history_report=history_report,
        trimmed_system=trimmed_system,
        trimmed_final_user=trimmed_final,
        dropped_history_for_total=dropped_for_total,
        reason=reason,
    )
    return messages, report


def compact_text(value: Any, max_chars: int) -> tuple[str, bool]:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text, False
    if max_chars <= len(TRIM_MARKER) + 20:
        return text[:max_chars], True
    head = max_chars // 2
    tail = max_chars - head - len(TRIM_MARKER)
    return text[:head].rstrip() + TRIM_MARKER + text[-tail:].lstrip(), True


def trim_messages(raw_messages: Any, budget: ContextBudget | None = None) -> tuple[list[dict[str, str]], ContextBudgetReport]:
    budget = budget or ContextBudget()
    if not isinstance(raw_messages, list):
        return [], ContextBudgetReport(reason="invalid_messages")

    normalized: list[dict[str, str]] = []
    input_chars = 0
    truncated = 0
    max_message_chars = min(budget.max_message_chars, budget.max_total_chars)
    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "user").strip().lower()
        if role not in budget.allowed_roles:
            role = "user"
        original = " ".join(str(raw.get("content") or "").split())
        input_chars += len(original)
        content, was_truncated = compact_text(original, max_message_chars)
        if not content:
            continue
        if was_truncated:
            truncated += 1
        normalized.append({"role": role, "content": content})

    must_keep = _last_user_message(normalized) if budget.preserve_last_user else None
    kept: list[dict[str, str]] = []
    total_chars = 0
    reason = ""

    for msg in reversed(normalized):
        if must_keep is not None and msg is must_keep:
            continue
        next_total = total_chars + len(msg["content"])
        if kept and next_total > budget.max_total_chars:
            reason = "max_total_chars"
            break
        kept.append(msg)
        total_chars = next_total
        if len(kept) >= budget.max_messages:
            reason = "max_messages"
            break

    kept.reverse()
    if must_keep is not None and must_keep not in kept:
        must_len = len(must_keep["content"])
        while kept and (len(kept) >= budget.max_messages or total_chars + must_len > budget.max_total_chars):
            removed = kept.pop(0)
            total_chars -= len(removed["content"])
            reason = reason or "preserve_last_user"
        kept.append(must_keep)
        total_chars += must_len

    output_chars = sum(len(item["content"]) for item in kept)
    dropped_messages = max(0, len(normalized) - len(kept))
    report = ContextBudgetReport(
        input_messages=len(normalized),
        output_messages=len(kept),
        input_chars=input_chars,
        output_chars=output_chars,
        dropped_messages=dropped_messages,
        dropped_chars=max(0, input_chars - output_chars),
        truncated_messages=truncated,
        reason=reason or ("truncated" if truncated else "within_budget"),
    )
    return kept, report


def limit_text(value: Any, max_chars: int) -> str:
    return compact_text(value, max_chars)[0]


def _last_user_message(messages: list[dict[str, str]]) -> dict[str, str] | None:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg
    return None
