# Joy-Echo API Design

## Goal

Expose Joy-Echo through the same provider API shape used by the existing LTX API, with mandatory Bearer key authentication, so SaaS can call `joy-echo` over HTTP instead of using an ad hoc SSH bridge.

## Scope

Build a small standalone Joy-Echo API service under `provider_servers/joy_echo_api/`.

The service will be deployed to the Joy-Echo GPU host and will call the existing official JoyAI-Echo repository entrypoint:

```text
/root/autodl-tmp/joyai/JoyAI-Echo/JoyAI-Echo-code/inference.py
```

The service will not modify `D:\LTX2.3` or `D:\LTX2.3API`. Those directories remain reference material only.

## API Contract

The Joy-Echo API will intentionally mirror the LTX API contract where useful:

```text
GET  /health
POST /v1/video/generate
GET  /v1/tasks/{task_id}
GET  /v1/files/{file_id}
```

All `/v1/*` endpoints require:

```text
Authorization: Bearer <JOY_ECHO_API_KEY>
```

`/health` remains unauthenticated so SaaS can check availability.

## Generate Request

`POST /v1/video/generate` accepts:

```json
{
  "prompt": "string",
  "prompts": ["optional", "multi-shot"],
  "duration": 30,
  "width": 1280,
  "height": 736,
  "fps": 25,
  "seed": 20260625
}
```

The API returns immediately with a task ID:

```json
{
  "task_id": "uuid",
  "id": "uuid",
  "status": "pending"
}
```

The task runner writes a prompt JSON into the JoyAI-Echo repo, runs `inference.py`, finds `combined_shots.mp4`, and stores a local output file under the API service storage directory.

## Task Response

`GET /v1/tasks/{task_id}` returns:

```json
{
  "task_id": "uuid",
  "id": "uuid",
  "status": "completed",
  "progress": {"percentage": 100, "message": "Completed"},
  "output": {
    "file_id": "uuid",
    "url": "/v1/files/uuid",
    "duration": 30
  },
  "outputs": [
    {
      "id": "uuid",
      "type": "video",
      "mime_type": "video/mp4",
      "url": "/v1/files/uuid"
    }
  ],
  "error_message": null
}
```

This shape matches the existing SaaS LTX adapter expectations in `app/services/comfy_video.py`.

## Authentication

The service uses a single configured API key:

```text
JOY_ECHO_API_KEY=<secret>
```

Requests with missing or wrong Bearer tokens return `401`.

No API key or password should be logged or returned in API responses.

## SaaS Integration

Add settings:

```text
JOY_ECHO_API_BASE_URL=
JOY_ECHO_API_KEY=
```

Then change `joy-echo` provider routing to prefer the HTTP API when `JOY_ECHO_API_BASE_URL` is configured. The existing SSH bridge remains as fallback during migration.

The SaaS-facing result shape remains:

```json
{
  "url": "/api/media/local/ltx/<file>.mp4",
  "provider": "joy_echo_api",
  "duration": 30
}
```

## Error Handling

The API stores task failures with a concise `error_message` and returns `status: "failed"` from task polling.

The service does not swallow `inference.py` failures. It records the process exit code and the tail of stdout/stderr in the task error field, capped to avoid huge responses.

## Testing

Unit tests cover:

- Bearer auth rejects missing and wrong keys.
- `/health` is unauthenticated.
- `POST /v1/video/generate` creates a task.
- The runner can be monkeypatched to produce a fake mp4 and mark the task completed.
- SaaS adapter sends `Authorization: Bearer <JOY_ECHO_API_KEY>` and parses the LTX-compatible task output.

## Deployment

The source of truth lives in the SaaS repository:

```text
provider_servers/joy_echo_api/
```

Deployment copies that directory to the Joy-Echo GPU host, installs its Python dependencies, sets `JOY_ECHO_API_KEY`, and starts Uvicorn on a chosen port.

