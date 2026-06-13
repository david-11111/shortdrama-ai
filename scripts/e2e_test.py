from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from sqlalchemy import text
    from app.db import AsyncSessionLocal
    DB_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - script dependency guard
    AsyncSessionLocal = None
    text = None
    DB_IMPORT_ERROR = str(exc)

try:
    import websockets
except Exception as exc:  # pragma: no cover - optional dependency guard
    websockets = None
    WEBSOCKETS_IMPORT_ERROR = str(exc)
else:
    WEBSOCKETS_IMPORT_ERROR = None

from lib.assertions import require


DEFAULT_BASE_URL = "http://localhost:80"
DEFAULT_PASSWORD = "Test123456"
DEFAULT_TOPIC = "A young woman shoots a clean beauty advertisement at an autumn street corner."
SHOT_COUNT = 4
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)


@dataclass
class State:
    base_url: str
    skip_generation: bool
    email: str
    password: str
    display_name: str
    token: str = ""
    user_id: int | None = None
    project_id: str = ""
    asset_id: str = ""
    asset_front_url: str = ""
    initial_balance: int = 0
    image_price: int = 2
    video_price: int = 10
    shot_rows: list[dict[str, Any]] = field(default_factory=list)
    image_task_ids: list[str] = field(default_factory=list)
    video_task_ids: list[str] = field(default_factory=list)
    results: list[tuple[str, str, float, str]] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}


class SkipStep(Exception):
    pass


def ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse(("wss" if parsed.scheme == "https" else "ws", parsed.netloc, "/ws/tasks", "", "", ""))


def need_db() -> None:
    if AsyncSessionLocal is None or text is None:
        raise RuntimeError(f"DB helpers unavailable: {DB_IMPORT_ERROR}")


async def fetch_user_id(email: str) -> int | None:
    need_db()
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(text("SELECT id FROM users WHERE email = :email LIMIT 1"), {"email": email})
        ).mappings().first()
    return int(row["id"]) if row else None


async def seed_shots(project_id: str, user_id: int) -> None:
    need_db()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for idx in range(SHOT_COUNT):
                await session.execute(
                    text(
                        """
                        INSERT INTO shot_rows (
                            project_id, user_id, shot_index, prompt, duration, status, selected,
                            character_refs_json, scene_refs_json, style_refs_json,
                            image_candidates_json, video_variants_json, last_error
                        ) VALUES (
                            :project_id, :user_id, :shot_index, :prompt, 5.0, 'draft', FALSE,
                            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                            '[]'::jsonb, '[]'::jsonb, NULL
                        )
                        ON CONFLICT (project_id, shot_index) DO UPDATE SET
                            prompt = EXCLUDED.prompt,
                            status = 'draft',
                            selected = FALSE,
                            selected_image = NULL,
                            selected_video = NULL,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "project_id": project_id,
                        "user_id": user_id,
                        "shot_index": idx,
                        "prompt": f"E2E shot {idx + 1}: clean beauty commercial frame",
                    },
                )


async def cleanup_user(user_id: int) -> None:
    need_db()
    statements = (
        "DELETE FROM webhooks WHERE user_id = :uid",
        "DELETE FROM orders WHERE user_id = :uid",
        "DELETE FROM tasks WHERE user_id = :uid",
        "DELETE FROM assets WHERE user_id = :uid",
        "DELETE FROM shot_rows WHERE user_id = :uid",
        "DELETE FROM projects WHERE user_id = :uid",
        "DELETE FROM credit_transactions WHERE user_id = :uid",
        "DELETE FROM credit_accounts WHERE user_id = :uid",
        "DELETE FROM api_keys WHERE user_id = :uid",
        "DELETE FROM users WHERE id = :uid",
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for statement in statements:
                await session.execute(text(statement), {"uid": user_id})


class Scenario:
    def __init__(self, state: State) -> None:
        self.s = state
        self.client: httpx.Client | None = None

    def request(self, method: str, path: str, *, auth: bool = False, expected: int | tuple[int, ...] | None = None, **kwargs: Any) -> httpx.Response:
        require(self.client is not None, "HTTP client not initialized")
        headers = dict(kwargs.pop("headers", {}))
        if auth:
            headers.update(self.s.headers)
        response = self.client.request(method, path, headers=headers, **kwargs)
        if expected is not None:
            expected_set = expected if isinstance(expected, tuple) else (expected,)
            require(response.status_code in expected_set, f"{method} {path} returned unexpected status", response.text[:500])
        return response

    def data(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception as exc:
            raise AssertionError(f"invalid JSON: {exc}; body={response.text[:500]}") from exc

    def poll_task(self, task_id: str, timeout_s: int) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        last: dict[str, Any] | None = None
        while time.time() < deadline:
            payload = self.data(self.request("GET", f"/api/tasks/{task_id}", auth=True, expected=200))
            last = payload
            if payload.get("status") in {"done", "failed", "cancelled"}:
                return payload
            time.sleep(5)
        raise TimeoutError(f"task timeout: {task_id}; last={last}")

    def run_step(self, name: str) -> None:
        started = time.perf_counter()
        status = "PASS"
        try:
            detail = str(getattr(self, name)() or "PASS")
        except SkipStep as exc:
            status, detail = "SKIP", str(exc)
        except Exception as exc:
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - started
        self.s.results.append((name, status, elapsed, detail))
        print(f"[{status}] {name} ({elapsed:.2f}s) - {detail}")
        if status == "FAIL":
            raise RuntimeError(f"{name} failed: {detail}")

    def run(self) -> int:
        steps = (
            "register", "login", "check_credits", "create_project", "create_asset",
            "director_script", "director_done", "verify_shots", "ready_rows", "submit_images",
            "images_done_videos_queued", "videos_done_credits", "websocket", "summary",
        )
        with httpx.Client(base_url=self.s.base_url, timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            self.client = client
            try:
                health = self.request("GET", "/health")
                print(f"[INFO] /health -> {health.status_code}")
                for name in steps:
                    self.run_step(name)
            finally:
                self.cleanup()
        return 0

    def register(self) -> str:
        response = self.request(
            "POST",
            "/api/auth/register",
            json={"email": self.s.email, "password": self.s.password, "display_name": self.s.display_name},
        )
        if response.status_code == 409:
            return "user already exists"
        require(response.status_code == 201, "unexpected register status", response.text[:500])
        body = self.data(response)
        require(body.get("access_token"), "register response missing token", body)
        self.s.token = body["access_token"]
        return "registered"

    def login(self) -> str:
        body = self.data(self.request("POST", "/api/auth/login", json={"email": self.s.email, "password": self.s.password}, expected=200))
        require(body.get("access_token") and body.get("refresh_token"), "login response missing tokens", body)
        self.s.token = body["access_token"]
        me = self.data(self.request("GET", "/api/auth/me", auth=True, expected=200))
        self.s.user_id = int(me["id"])
        return "authenticated"

    def check_credits(self) -> str:
        credits = self.data(self.request("GET", "/api/credits", auth=True, expected=200))
        self.s.initial_balance = int(credits.get("balance", 0))
        require(self.s.initial_balance >= 50, "initial balance too low", credits)
        pricing = self.data(self.request("GET", "/api/credits/pricing", expected=200)).get("pricing", [])
        price = {item["operation"]: int(item["credits_cost"]) for item in pricing}
        self.s.image_price = price.get("image_gen", self.s.image_price)
        self.s.video_price = price.get("video_gen_5s", self.s.video_price)
        return f"balance={self.s.initial_balance}, image={self.s.image_price}, video={self.s.video_price}"

    def create_project(self) -> str:
        body = self.data(self.request("POST", "/api/projects", auth=True, json={"name": f"[E2E] {time.strftime('%Y%m%d_%H%M%S')}"}, expected=(200, 201)))
        require(body.get("project_id"), "project_id missing", body)
        self.s.project_id = str(body["project_id"])
        return self.s.project_id

    def create_asset(self) -> str:
        require(self.s.project_id, "project_id missing")
        self.s.asset_front_url = "https://via.placeholder.com/512/FF0000"
        body = self.data(
            self.request(
                "POST",
                f"/api/projects/{self.s.project_id}/assets",
                auth=True,
                expected=(200, 201),
                json={
                    "asset_type": "character",
                    "file_url": "https://via.placeholder.com/512",
                    "metadata_json": {"pack": True, "primary": "front", "views": {"front": self.s.asset_front_url}, "e2e": True},
                },
            )
        )
        require(body.get("asset_id"), "asset_id missing", body)
        self.s.asset_id = str(body["asset_id"])
        return self.s.asset_id

    def director_script(self) -> str:
        if self.s.skip_generation:
            raise SkipStep("--skip-generation")
        body = self.data(
            self.request(
                "POST",
                "/api/director/script",
                auth=True,
                expected=(200, 202),
                json={"project_id": self.s.project_id, "topic": DEFAULT_TOPIC, "shot_count": SHOT_COUNT},
            )
        )
        require(body.get("task_id") and body.get("status") == "queued", "director task not queued", body)
        self.director_task_id = str(body["task_id"])
        return self.director_task_id

    def director_done(self) -> str:
        if self.s.skip_generation:
            require(self.s.user_id is not None and self.s.project_id, "missing DB seed scope")
            asyncio.run(seed_shots(self.s.project_id, self.s.user_id))
            return "seeded shots"
        payload = self.poll_task(self.director_task_id, 120)
        require(payload.get("status") != "failed", "director task failed", payload)
        return str(payload.get("status"))

    def verify_shots(self) -> str:
        body = self.data(self.request("GET", f"/api/projects/{self.s.project_id}/shot-rows", auth=True, expected=200))
        self.s.shot_rows = list(body.get("items", []))
        require(len(self.s.shot_rows) == SHOT_COUNT, "wrong shot count", body)
        for row in self.s.shot_rows:
            require(row.get("prompt") and row.get("status") == "draft", "bad shot row", row)
        return f"{len(self.s.shot_rows)} rows"

    def ready_rows(self) -> str:
        for row in self.s.shot_rows:
            self.request(
                "PUT",
                f"/api/projects/{self.s.project_id}/shot-rows/{int(row['shot_index'])}",
                auth=True,
                expected=200,
                json={"status": "ready", "selected": True, "character_refs_json": [self.s.asset_id]},
            )
        return f"{len(self.s.shot_rows)} ready"

    def submit_images(self) -> str:
        if self.s.skip_generation:
            raise SkipStep("--skip-generation")
        body = self.data(
            self.request(
                "POST",
                "/api/batch/generate-images",
                auth=True,
                expected=202,
                json={"items": [{"shot_row": row, "provider": "seedream"} for row in self.s.shot_rows]},
            )
        )
        self.s.image_task_ids = [str(task_id) for task_id in body.get("child_task_ids", [])]
        require(len(self.s.image_task_ids) == SHOT_COUNT, "wrong image task count", body)
        return f"{len(self.s.image_task_ids)} image tasks"

    def images_done_videos_queued(self) -> str:
        if self.s.skip_generation:
            raise SkipStep("--skip-generation")
        image_status = {task_id: self.poll_task(task_id, 300) for task_id in self.s.image_task_ids}
        failed = {task_id: item for task_id, item in image_status.items() if item.get("status") == "failed"}
        require(not failed, "image tasks failed", failed)
        video_items = []
        for row in self.s.shot_rows:
            shot = dict(row)
            shot["selected_image"] = shot.get("selected_image") or self.s.asset_front_url
            video_items.append({"shot_row": shot, "provider": "seedance", "duration": 5, "prompt": shot.get("prompt", "")})
        body = self.data(self.request("POST", "/api/batch/generate-videos", auth=True, expected=202, json={"items": video_items, "provider": "seedance"}))
        self.s.video_task_ids = [str(task_id) for task_id in body.get("child_task_ids", [])]
        require(len(self.s.video_task_ids) == SHOT_COUNT, "wrong video task count", body)
        return f"{len(self.s.video_task_ids)} video tasks"

    def videos_done_credits(self) -> str:
        if self.s.skip_generation:
            raise SkipStep("--skip-generation")
        video_status = {task_id: self.poll_task(task_id, 300) for task_id in self.s.video_task_ids}
        failed = {task_id: item for task_id, item in video_status.items() if item.get("status") == "failed"}
        require(not failed, "video tasks failed", failed)
        credits = self.data(self.request("GET", "/api/credits", auth=True, expected=200))
        final_balance = int(credits.get("balance", 0))
        expected = SHOT_COUNT * (self.s.image_price + self.s.video_price)
        actual = self.s.initial_balance - final_balance
        require(actual >= expected, "credit deduction too small", {"expected": expected, "actual": actual})
        return f"deducted={actual}"

    async def websocket_probe(self) -> str:
        if websockets is None:
            raise RuntimeError(f"websockets import failed: {WEBSOCKETS_IMPORT_ERROR}")
        async with websockets.connect(ws_url(self.s.base_url) + f"?token={self.s.token}") as ws:
            await ws.send(json.dumps({"type": "subscribe", "task_ids": self.s.image_task_ids or self.s.video_task_ids}))
            await ws.send(json.dumps({"type": "ping"}))
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                except asyncio.TimeoutError:
                    return "no message"
                message = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                if any(token in message for token in ("task_update", "status", "pong")):
                    return message[:200]
        return "no message"

    def websocket(self) -> str:
        if self.s.skip_generation:
            raise SkipStep("--skip-generation")
        return asyncio.run(self.websocket_probe())

    def summary(self) -> str:
        passed = sum(1 for _, status, _, _ in self.s.results if status == "PASS")
        skipped = sum(1 for _, status, _, _ in self.s.results if status == "SKIP")
        failed = sum(1 for _, status, _, _ in self.s.results if status == "FAIL")
        return f"{passed}/14 passed, {failed} failed, {skipped} skipped"

    def cleanup(self) -> None:
        try:
            user_id = self.s.user_id or asyncio.run(fetch_user_id(self.s.email))
            if user_id is not None:
                asyncio.run(cleanup_user(user_id))
                print(f"[INFO] cleanup user_id={user_id}")
        except Exception as exc:
            print(f"[WARN] cleanup failed: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-end API smoke test. Requires the app stack to be running.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--skip-generation", action="store_true", help="Skip real AI generation and cover auth/CRUD/basic flow.")
    parser.add_argument("--email", default="", help="Defaults to a generated unique test email.")
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--display-name", default="E2E Tester")
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    state = State(
        base_url=args.base_url.rstrip("/"),
        skip_generation=bool(args.skip_generation),
        email=args.email or f"test_e2e_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}@example.com",
        password=args.password,
        display_name=f"[E2E] {args.display_name}",
    )
    try:
        return Scenario(state).run()
    except Exception as exc:
        print(f"[FAIL] E2E aborted: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
