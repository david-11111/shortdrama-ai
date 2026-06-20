# LTX 2.3 API Handoff

Last updated: 2026-06-15

## Scope

This note preserves the current LTX 2.3 integration state before machine restart.

Current scope is LTX 2.3 only. Do not change Seedance, Kling, Wan, Doubao CDP, or
the external `D:\LTX2.3API` service unless explicitly requested.

Do not store or echo real API keys in repo files or assistant replies.

## External LTX API

Reference path provided by user:

```text
D:\LTX2.3API\测试api
D:\LTX2.3API\测试api\ltx_desktop_custom_api\custom_video_api_client.py
D:\LTX2.3API\测试api\start_ltx_desktop_custom_api.ps1
```

Observed API contract:

```text
POST /v1/files/upload
POST /v1/video/generate
GET  /v1/tasks/{task_id}
GET  /v1/files/{file_id}
```

Auth:

```text
Authorization: Bearer <api_key>
```

Startup script variables used by SaaS after the latest changes:

```text
LTX_CUSTOM_VIDEO_API_BASE_URL
LTX_CUSTOM_VIDEO_API_KEY
LTX_CUSTOM_VIDEO_WIDTH
LTX_CUSTOM_VIDEO_HEIGHT
LTX_CUSTOM_VIDEO_DURATION
LTX_CUSTOM_VIDEO_STEPS
LTX_CUSTOM_VIDEO_MODE
LTX_CUSTOM_VIDEO_PROFILE
LTX_CUSTOM_VIDEO_CFG_SCALE
LTX_CUSTOM_VIDEO_STG_SCALE
```

## SaaS Files Changed For LTX 2.3

Backend implementation:

```text
app/services/comfy_video.py
app/services/provider_prompt_adapter.py
```

Smoke script:

```text
scripts/smoke_ltx_public_provider.py
```

Tests:

```text
tests/unit/test_comfy_video.py
tests/unit/test_ltx_smoke_script.py
tests/unit/test_provider_prompt_adapter.py
```

## Important Behavior

`app/services/comfy_video.py` now:

- reads `LTX_CUSTOM_VIDEO_API_BASE_URL` and `LTX_CUSTOM_VIDEO_API_KEY` as aliases
  when `ltx_api_base_url` / `ltx_api_key` are empty;
- supports LTX 2.3 env defaults for width, height, duration, steps, mode, profile,
  cfg scale, and stg scale;
- accepts upload response `file_id` or `id`;
- accepts completed output from `output`, `result`, `data`, `video`, or `outputs[]`;
- downloads LTX result files locally under `storage/ltx_downloads`;
- returns SaaS-local media URLs such as `/api/media/local/ltx/<file_id>.mp4`.

`app/services/provider_prompt_adapter.py` now:

- routes `provider="ltx2.3"` to `adapt_ltx_payload()`;
- avoids applying Seedance prompt/negative-prompt rules to LTX 2.3;
- still keeps generic video continuity/temporal hints that are injected before
  provider-specific adapter selection.

`scripts/smoke_ltx_public_provider.py` now:

- uses `provider="ltx2.3"`;
- still requires an explicit real `--image` path.

## Verified Results

Unit verification:

```text
python -m pytest -q tests/unit/test_provider_prompt_adapter.py tests/unit/test_claude_repair_contracts.py tests/unit/test_comfy_video.py tests/unit/test_ltx_smoke_script.py tests/unit/test_ltx_media_proxy.py tests/unit/test_agent_runs_wan_provider.py
```

Result:

```text
26 passed in 2.21s
```

Earlier LTX group after first LTX API changes:

```text
python -m pytest -q tests/unit/test_comfy_video.py tests/unit/test_ltx_smoke_script.py tests/unit/test_ltx_media_proxy.py tests/unit/test_agent_runs_wan_provider.py
```

Result:

```text
17 passed in 2.13s
```

Real LTX 2.3 smoke was run once through SaaS:

```text
python scripts\smoke_ltx_public_provider.py --image storage\debug_frames\ltx_frame_001.png --width 832 --height 480 --duration 3 --steps 24 --timeout-seconds 1800
```

Result summary:

```text
provider: ltx_api_ltx2.3
width: 832
height: 480
duration: 3.0
local_url: /api/media/local/ltx/8931fd84-f44c-4b47-b115-c7aa015589d1.mp4
local_file: storage/ltx_downloads/8931fd84-f44c-4b47-b115-c7aa015589d1.mp4
local_file_size: 574334 bytes
```

Do not rerun the real smoke unless needed, because it consumes external provider
quota.

## Resume Checklist

After restart, before continuing:

1. Read `AGENTS.md`, `CLAUDE.md`, and use `karpathy-guidelines`.
2. Do not edit without printing the required Chinese edit gate.
3. Check current diff:

```text
git status --short
git diff -- app/services/comfy_video.py app/services/provider_prompt_adapter.py scripts/smoke_ltx_public_provider.py tests/unit/test_comfy_video.py tests/unit/test_ltx_smoke_script.py tests/unit/test_provider_prompt_adapter.py docs/ltx2-3-handoff.md
```

4. Re-run the focused verification if needed:

```text
python -m pytest -q tests/unit/test_provider_prompt_adapter.py tests/unit/test_claude_repair_contracts.py tests/unit/test_comfy_video.py tests/unit/test_ltx_smoke_script.py tests/unit/test_ltx_media_proxy.py tests/unit/test_agent_runs_wan_provider.py
```

## Known Next Steps

Recommended next step is not more LTX API changes. The LTX 2.3 main API path is
connected and smoke-tested.

If continuing contract cleanup, prefer:

- verify real director video generation selects `provider="ltx2.3"` and reaches
  `generate_comfy_video`;
- verify task result writeback stores selected video URL and review metadata;
- avoid changing Doubao CDP bridge unless the user explicitly asks.

