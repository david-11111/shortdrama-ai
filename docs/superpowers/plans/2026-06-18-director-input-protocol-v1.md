# Director Input Protocol V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal "总导演输入协议 v1" layer so script, reference image, video, and edit tasks carry one consistent director packet before reaching Doubao, Seedream, Joy-Echo/LTX, or ffmpeg.

**Architecture:** Introduce a small service that builds and normalizes a `director_input_protocol` dict from existing request/body/asset metadata. Inject the protocol into provider payloads through the existing `provider_prompt_adapter`, and block downstream video/edit progression when the protocol says `allowed_next_step=false`. Keep existing routes and task queues intact.

**Tech Stack:** FastAPI, Celery, PostgreSQL JSONB metadata, pytest, existing provider adapter and workbench/director routes.

---

## File Structure

- Create `app/services/director_input_protocol.py`: owns the protocol defaults, normalization, prompt block rendering, and approval helpers.
- Modify `app/services/provider_prompt_adapter.py`: appends protocol constraints to Doubao, Seedream, and video provider prompts.
- Modify `app/services/ref_resolver.py`: carries protocol fields from shot/assets into image/video payloads when present.
- Modify `app/routes/workbench.py`: accepts `director_input_protocol` in continue requests and prevents `generate_videos` when protocol is not approved.
- Test `tests/unit/test_director_input_protocol.py`: service-level tests for defaults, live-action guardrails, approval gates, and prompt block rendering.
- Test `tests/unit/test_provider_prompt_adapter.py`: adapter injects protocol constraints into Seedream/video payloads without replacing existing prompt text.
- Test `tests/unit/test_project_continue.py`: continue video dispatch rejects unapproved reference/keyframe protocols.

---

### Task 1: Protocol Service

**Files:**
- Create: `app/services/director_input_protocol.py`
- Test: `tests/unit/test_director_input_protocol.py`

- [ ] **Step 1: Write the failing protocol defaults test**

Add `tests/unit/test_director_input_protocol.py`:

```python
from app.services.director_input_protocol import (
    DIRECTOR_PROTOCOL_VERSION,
    build_director_input_protocol,
    director_protocol_prompt_block,
    director_protocol_allows_next_step,
)


def test_build_director_input_protocol_defaults_to_live_action_guardrails():
    protocol = build_director_input_protocol(
        {
            "task_type": "reference_image",
            "asset_kind": "character",
            "creative_intent": "锁定陆沉舟真人短剧角色参考图",
            "subject": {"name": "陆沉舟"},
        }
    )

    assert protocol["version"] == DIRECTOR_PROTOCOL_VERSION
    assert protocol["project_style"].startswith("类真人影视短剧")
    assert "anime" in protocol["global_must_avoid"]
    assert protocol["approval_status"] == "draft"
    assert protocol["allowed_next_step"] is False
    assert protocol["subject"]["name"] == "陆沉舟"


def test_director_protocol_prompt_block_contains_execution_constraints():
    protocol = build_director_input_protocol(
        {
            "task_type": "reference_image",
            "asset_kind": "character",
            "creative_intent": "表现一个习惯被忽视的人",
            "must_keep": ["真实布料", "克制眼神"],
            "must_avoid": ["动漫脸", "网游服装"],
        }
    )

    block = director_protocol_prompt_block(protocol, target="seedream")

    assert "[director_input_protocol_v1]" in block
    assert "project_style=类真人影视短剧" in block
    assert "creative_intent=表现一个习惯被忽视的人" in block
    assert "must_keep=真实布料; 克制眼神" in block
    assert "must_avoid=anime; manga; cartoon" in block


def test_director_protocol_allows_next_step_only_when_approved():
    draft = build_director_input_protocol({"approval_status": "draft", "allowed_next_step": True})
    approved = build_director_input_protocol({"approval_status": "approved", "allowed_next_step": True})

    assert director_protocol_allows_next_step(draft) is False
    assert director_protocol_allows_next_step(approved) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests\unit\test_director_input_protocol.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.director_input_protocol'`.

- [ ] **Step 3: Implement the protocol service**

Create `app/services/director_input_protocol.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

DIRECTOR_PROTOCOL_VERSION = "director_input_protocol_v1"

DEFAULT_PROJECT_STYLE = (
    "类真人影视短剧，photorealistic live-action Chinese costume drama, "
    "真实皮肤、真实布料、克制光线、生活细节"
)

GLOBAL_MUST_AVOID = [
    "anime",
    "manga",
    "cartoon",
    "2D illustration",
    "game CG",
    "plastic skin",
    "idol filter",
    "fantasy poster",
    "excessive golden glow",
    "generic xianxia beauty",
]


def build_director_input_protocol(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    data = deepcopy(raw or {})
    return {
        "version": DIRECTOR_PROTOCOL_VERSION,
        "project_id": str(data.get("project_id") or ""),
        "series_title": str(data.get("series_title") or ""),
        "episode": str(data.get("episode") or ""),
        "project_style": str(data.get("project_style") or DEFAULT_PROJECT_STYLE),
        "global_must_avoid": _string_list(data.get("global_must_avoid")) or GLOBAL_MUST_AVOID,
        "task_type": str(data.get("task_type") or ""),
        "asset_kind": str(data.get("asset_kind") or ""),
        "creative_intent": str(data.get("creative_intent") or ""),
        "subject": data.get("subject") if isinstance(data.get("subject"), dict) else {},
        "must_keep": _string_list(data.get("must_keep")),
        "must_avoid": _dedupe([*GLOBAL_MUST_AVOID, *_string_list(data.get("must_avoid"))]),
        "approval_status": str(data.get("approval_status") or "draft"),
        "allowed_next_step": bool(data.get("allowed_next_step")),
        "director_note": str(data.get("director_note") or "未通过人工确认前，不允许进入下一步生成。"),
    }


def director_protocol_allows_next_step(protocol: dict[str, Any] | None) -> bool:
    data = build_director_input_protocol(protocol)
    return data["approval_status"] == "approved" and bool(data["allowed_next_step"])


def director_protocol_prompt_block(protocol: dict[str, Any] | None, *, target: str) -> str:
    data = build_director_input_protocol(protocol)
    lines = [
        f"[{DIRECTOR_PROTOCOL_VERSION}]",
        f"target={target}",
        f"project_style={data['project_style']}",
    ]
    if data["task_type"]:
        lines.append(f"task_type={data['task_type']}")
    if data["asset_kind"]:
        lines.append(f"asset_kind={data['asset_kind']}")
    if data["creative_intent"]:
        lines.append(f"creative_intent={data['creative_intent']}")
    subject = data.get("subject") or {}
    if subject.get("name"):
        lines.append(f"subject_name={subject['name']}")
    if data["must_keep"]:
        lines.append("must_keep=" + "; ".join(data["must_keep"]))
    if data["must_avoid"]:
        lines.append("must_avoid=" + "; ".join(data["must_avoid"]))
    if data["director_note"]:
        lines.append(f"director_note={data['director_note']}")
    return "\n".join(lines)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests\unit\test_director_input_protocol.py -q
```

Expected: `3 passed`.

---

### Task 2: Provider Prompt Injection

**Files:**
- Modify: `app/services/provider_prompt_adapter.py`
- Test: `tests/unit/test_provider_prompt_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

Append to `tests/unit/test_provider_prompt_adapter.py`:

```python
from app.services.provider_prompt_adapter import adapt_provider_payload


def test_seedream_adapter_injects_director_input_protocol():
    payload = adapt_provider_payload(
        {
            "prompt": "陆沉舟半身正面",
            "director_input_protocol": {
                "task_type": "reference_image",
                "asset_kind": "character",
                "creative_intent": "类真人角色锁定",
                "must_avoid": ["动漫脸"],
            },
        },
        task_type="image_gen",
        provider="seedream",
    )

    assert "陆沉舟半身正面" in payload["prompt"]
    assert "[director_input_protocol_v1]" in payload["prompt"]
    assert "creative_intent=类真人角色锁定" in payload["prompt"]
    assert "动漫脸" in payload["prompt"]


def test_video_adapter_injects_director_input_protocol():
    payload = adapt_provider_payload(
        {
            "prompt": "镜头缓慢推进",
            "director_input_protocol": {
                "task_type": "video",
                "asset_kind": "shot_keyframe",
                "creative_intent": "保留参考图人物身份和压抑情绪",
            },
        },
        task_type="video_gen",
        provider="ltx2.3",
    )

    assert "镜头缓慢推进" in payload["prompt"]
    assert "[director_input_protocol_v1]" in payload["prompt"]
    assert "保留参考图人物身份和压抑情绪" in payload["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests\unit\test_provider_prompt_adapter.py -q
```

Expected: FAIL because prompts do not include `[director_input_protocol_v1]`.

- [ ] **Step 3: Inject protocol block in provider adapter**

Modify `app/services/provider_prompt_adapter.py`:

```python
from app.services.director_input_protocol import director_protocol_prompt_block
```

Add helper:

```python
def _inject_director_protocol(payload: dict[str, Any], *, target: str) -> None:
    protocol = payload.get("director_input_protocol")
    if not isinstance(protocol, dict):
        return
    payload["prompt"] = _append_once(
        str(payload.get("prompt") or ""),
        director_protocol_prompt_block(protocol, target=target),
    )
```

Call it before visual/video quality controls:

```python
def adapt_seedream_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = _semantic(payload)
    _inject_director_protocol(payload, target="seedream")
    ...
```

```python
def adapt_seedance_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = _semantic(payload)
    _inject_director_protocol(payload, target="video")
    ...
```

```python
def adapt_ltx_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _inject_director_protocol(payload, target="video")
    return _attach_adapter_meta(payload, applied=isinstance(payload.get("director_input_protocol"), dict), provider="ltx2.3", task_type="video_gen")
```

- [ ] **Step 4: Run adapter tests**

Run:

```powershell
python -m pytest tests\unit\test_provider_prompt_adapter.py tests\unit\test_director_input_protocol.py -q
```

Expected: all tests pass.

---

### Task 3: Carry Protocol Through Reference Resolver

**Files:**
- Modify: `app/services/ref_resolver.py`
- Test: `tests/unit/test_ref_resolver_prompt_layers.py`

- [ ] **Step 1: Write failing resolver test**

Append to `tests/unit/test_ref_resolver_prompt_layers.py`:

```python
from app.services.ref_resolver import build_image_generation_payload, build_video_generation_payload


def test_ref_resolver_preserves_director_input_protocol():
    shot = {
        "project_id": "p1",
        "shot_index": 1,
        "prompt": "陆沉舟站在测骨台前",
        "selected_image": "/api/projects/p1/assets/a1/public-file",
        "director_input_protocol": {
            "task_type": "video",
            "asset_kind": "shot_keyframe",
            "creative_intent": "真人短剧压抑情绪",
            "approval_status": "approved",
            "allowed_next_step": True,
        },
    }

    image_payload = build_image_generation_payload(shot, strict=False, assets_by_id={})
    video_payload = build_video_generation_payload(shot, strict=False, assets_by_id={})

    assert image_payload["director_input_protocol"]["creative_intent"] == "真人短剧压抑情绪"
    assert video_payload["director_input_protocol"]["approval_status"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests\unit\test_ref_resolver_prompt_layers.py -q
```

Expected: FAIL because payloads do not carry `director_input_protocol`.

- [ ] **Step 3: Preserve protocol in image/video payloads**

In `app/services/ref_resolver.py`, where image and video payload dicts are returned, copy through:

```python
protocol = row.get("director_input_protocol")
if isinstance(protocol, dict):
    payload["director_input_protocol"] = protocol
```

Do this in both `build_image_generation_payload()` and `build_video_generation_payload()`.

- [ ] **Step 4: Run resolver tests**

Run:

```powershell
python -m pytest tests\unit\test_ref_resolver_prompt_layers.py tests\unit\test_director_input_protocol.py -q
```

Expected: all tests pass.

---

### Task 4: Continue Gate For Unapproved Video

**Files:**
- Modify: `app/routes/workbench.py`
- Test: `tests/unit/test_project_continue.py`

- [ ] **Step 1: Write failing approval-gate test**

Append to `tests/unit/test_project_continue.py`:

```python
import pytest
from app.routes import workbench


def test_generate_video_requires_approved_director_protocol():
    with pytest.raises(workbench.HTTPException) as exc:
        workbench._guard_director_protocol_next_step(
            "generate_videos",
            {
                "approval_status": "draft",
                "allowed_next_step": False,
                "task_type": "reference_image",
            },
        )

    assert exc.value.status_code == 400
    assert "director input protocol" in str(exc.value.detail)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests\unit\test_project_continue.py::test_generate_video_requires_approved_director_protocol -q
```

Expected: FAIL because `_guard_director_protocol_next_step` does not exist.

- [ ] **Step 3: Implement the guard**

In `app/routes/workbench.py` import:

```python
from app.services.director_input_protocol import director_protocol_allows_next_step
```

Add helper:

```python
def _guard_director_protocol_next_step(action: str, protocol: dict[str, Any] | None) -> None:
    if action != "generate_videos" or not isinstance(protocol, dict):
        return
    if not director_protocol_allows_next_step(protocol):
        raise HTTPException(
            status_code=400,
            detail="director input protocol is not approved for next-step video generation",
        )
```

In `continue_project_brain()`, after resolving `action`, call:

```python
_guard_director_protocol_next_step(
    action,
    (body or {}).get("director_input_protocol") if isinstance((body or {}).get("director_input_protocol"), dict) else None,
)
```

Pass the same `director_input_protocol` into `semantic_control` so `_continue_generate_batch()` can carry it to provider payloads if needed.

- [ ] **Step 4: Run gate test**

Run:

```powershell
python -m pytest tests\unit\test_project_continue.py::test_generate_video_requires_approved_director_protocol -q
```

Expected: PASS.

---

### Task 5: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests\unit\test_director_input_protocol.py tests\unit\test_provider_prompt_adapter.py tests\unit\test_ref_resolver_prompt_layers.py tests\unit\test_project_continue.py::test_generate_video_requires_approved_director_protocol -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Compile changed Python files**

Run:

```powershell
python -m py_compile app\services\director_input_protocol.py app\services\provider_prompt_adapter.py app\services\ref_resolver.py app\routes\workbench.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Container smoke if local code is hot-mounted**

Run:

```powershell
docker compose exec -T -e PYTHONPATH=/app api python - <<'PY'
from app.services.director_input_protocol import build_director_input_protocol, director_protocol_prompt_block
p = build_director_input_protocol({"task_type": "reference_image", "asset_kind": "character"})
print(p["approval_status"], "[director_input_protocol_v1]" in director_protocol_prompt_block(p, target="seedream"))
PY
```

Expected output contains:

```text
draft True
```

---

## Self-Review

- Spec coverage: The plan defines the protocol object, provider prompt injection, reference resolver carry-through, and a video gate for unapproved assets.
- Scope: This is intentionally minimal. It does not redesign the UI, add migrations, or replace existing agent routing.
- Ambiguity: `allowed_next_step=true` alone is not enough; `approval_status` must be `approved`.
- Cost control: No provider calls are added by the protocol service. The only runtime effect is prompt text injection and a preflight gate.
