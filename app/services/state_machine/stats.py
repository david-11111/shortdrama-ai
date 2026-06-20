"""Single-pass statistics accumulator for production stages.

Replaces the old pattern of 13 separate list comprehensions over shots
and tasks with a single traversal that computes every metric at once.
"""

from __future__ import annotations

from typing import Any

from app.core.types import ProductionStatus


class StatsAccumulator:
    """Accumulate all stage metrics in a single pass.

    Usage::

        acc = StatsAccumulator()
        for shot in shots: acc.add_shot(shot)
        for task in tasks: acc.add_task(task)
        acc.set_production_run(production_run)
        stats = acc.finalize()
    """

    def __init__(self) -> None:
        # Shot counters
        self._shot_count: int = 0
        self._prompt_count: int = 0
        self._selected_image_count: int = 0
        self._selected_video_count: int = 0
        self._image_review_blocking: int = 0
        self._video_review_blocking: int = 0
        self._image_blocking_shots: list[int] = []
        self._video_blocking_shots: list[int] = []

        # Task counters
        self._image_total: int = 0
        self._image_active: int = 0
        self._image_done: int = 0
        self._image_failed: int = 0
        self._video_total: int = 0
        self._video_active: int = 0
        self._video_done: int = 0
        self._video_failed: int = 0
        self._video_deferred: int = 0

        # Production run
        self._production_status: str = ""
        self._final_video_url: str = ""

        # Helpers cached from imported enums
        self._terminal_done = ProductionStatus.terminal_done()
        self._terminal_failed = ProductionStatus.terminal_failed()
        self._active_set = ProductionStatus.active()
        self._deferred_tokens = frozenset(
            {"saturated", "backpressure", "too many requests", "429", "rate limit"}
        )

    # ── Shot processing ─────────────────────────────────────────────────

    def add_shot(self, shot: dict[str, Any]) -> None:
        # 跳过被用户标记为"跳过"的镜头（skip_shot）
        if not shot.get("selected", True):
            return
        self._shot_count += 1
        shot_index = int(shot.get("shot_index") or 0)
        if str(shot.get("prompt") or "").strip():
            self._prompt_count += 1
        if str(shot.get("selected_image") or "").strip():
            self._selected_image_count += 1
        if str(shot.get("selected_video") or "").strip():
            self._selected_video_count += 1
        if self._is_review_blocking(shot, "image"):
            self._image_review_blocking += 1
            self._image_blocking_shots.append(shot_index)
        if self._is_review_blocking(shot, "video"):
            self._video_review_blocking += 1
            self._video_blocking_shots.append(shot_index)

    @staticmethod
    def _is_review_blocking(shot: dict[str, Any], media_type: str) -> bool:
        for key in (f"{media_type}_candidate", f"selected_{media_type}_candidate",
                    f"{media_type}_review", f"{media_type}_review_result"):
            val = shot.get(key)
            if not isinstance(val, dict):
                continue
            if StatsAccumulator._candidate_review_blocking(val):
                return True
        list_keys = (
            ("image_candidates", "keyframe_candidates", "image_variants")
            if media_type == "image"
            else ("video_variants", "video_candidates")
        )
        selected_url = str(shot.get(f"selected_{media_type}") or "").strip()
        for key in list_keys:
            val = shot.get(key)
            if not isinstance(val, list):
                continue
            candidates = [item for item in val if isinstance(item, dict)]
            selected_candidates = [
                item
                for item in candidates
                if selected_url and StatsAccumulator._candidate_matches_selected(item, selected_url)
            ]
            review_candidates = selected_candidates or candidates
            if any(StatsAccumulator._candidate_review_blocking(item) for item in review_candidates):
                return True
        return False

    @staticmethod
    def _candidate_review_blocking(candidate: dict[str, Any]) -> bool:
        blocking_statuses = {"needs_review", "regenerate", "failed", "fail", "rejected", "blocked"}
        status = str(candidate.get("review_status") or candidate.get("status") or "").strip().lower()
        if status in blocking_statuses:
            return True
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        return str(review.get("status") or "").strip().lower() in blocking_statuses

    @staticmethod
    def _candidate_matches_selected(candidate: dict[str, Any], selected_url: str) -> bool:
        for key in ("url", "image_url", "video_url", "selected_image", "selected_video"):
            if str(candidate.get(key) or "").strip() == selected_url:
                return True
        return False

    # ── Task processing ─────────────────────────────────────────────────

    def add_task(self, task: dict[str, Any], *, production_status: str = "") -> None:
        task_type = str(task.get("task_type") or "").strip()
        status = str(task.get("status") or "").strip().lower()
        is_video = task_type == "video_gen"
        is_image = task_type == "image_gen"

        if not (is_video or is_image):
            return

        if is_image:
            self._image_total += 1
            if status in self._active_set:
                self._image_active += 1
            if status in self._terminal_done:
                self._image_done += 1
            if status in self._terminal_failed:
                self._image_failed += 1
            return

        if is_video:
            self._video_total += 1
            deferred = self._is_deferred_failure(task, production_status or self._production_status)
            if deferred:
                self._video_deferred += 1
                self._video_active += 1  # deferred counts as active
            elif status in self._active_set:
                self._video_active += 1
            if status in self._terminal_done:
                self._video_done += 1
            if status in self._terminal_failed and not deferred:
                self._video_failed += 1

    @staticmethod
    def _is_deferred_failure(task: dict[str, Any], production_status: str) -> bool:
        if production_status != "provider_waiting":
            return False
        if str(task.get("task_type") or "") != "video_gen":
            return False
        if str(task.get("status") or "").strip().lower() not in {"failed", "dead_letter", "cancelled"}:
            return False
        msg = str(task.get("error_message") or "").lower()
        return any(t in msg for t in ("saturated", "backpressure", "too many requests", "429", "rate limit"))

    # ── Run-level data ──────────────────────────────────────────────────

    def set_production_run(self, run: dict[str, Any] | None) -> None:
        if not run:
            return
        self._production_status = str(run.get("status") or "").strip().lower()
        self._final_video_url = str(run.get("final_video_url") or "").strip()

    # ── Finalize ────────────────────────────────────────────────────────

    def finalize(self) -> dict[str, Any]:
        # Coverge booleans: have ALL shots been generated for this media type?
        # "Complete" means either:
        #   (a) every shot has a selected file, OR
        #   (b) at least one exists and no active/failed generation tasks remain.
        video_gen_complete = bool(
            (self._shot_count > 0 and self._selected_video_count >= self._shot_count)
            or (self._selected_video_count > 0
                and self._video_active == 0
                and self._video_failed == 0)
        )
        image_gen_complete = bool(
            (self._shot_count > 0 and self._selected_image_count >= self._shot_count)
            or (self._selected_image_count > 0
                and self._image_active == 0
                and self._image_failed == 0)
        )
        return {
            "shot_count": self._shot_count,
            "prompt_count": self._prompt_count,
            "selected_image_count": self._selected_image_count,
            "selected_video_count": self._selected_video_count,
            "image_review_blocking_count": self._image_review_blocking,
            "video_review_blocking_count": self._video_review_blocking,
            "image_blocking_shots": self._image_blocking_shots,
            "video_blocking_shots": self._video_blocking_shots,
            "image_task_count": self._image_total,
            "image_task_active_count": self._image_active,
            "image_task_done_count": self._image_done,
            "image_task_failed_count": self._image_failed,
            "video_task_count": self._video_total,
            "video_task_active_count": self._video_active,
            "video_task_done_count": self._video_done,
            "video_task_failed_count": self._video_failed,
            "video_task_deferred_count": self._video_deferred,
            "final_video_url": self._final_video_url,
            "production_status": self._production_status,
            "video_generation_complete": video_gen_complete,
            "image_generation_complete": image_gen_complete,
        }
