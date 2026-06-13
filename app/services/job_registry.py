"""Async job registry with status tracking.

Provides a central registry for all async jobs (video generation, reference images, etc.)
so the frontend can poll a single contract instead of guessing from file existence.

Job lifecycle: queued → running → done | failed | expired
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class Job:
    job_id: str
    session_id: str
    job_type: str
    user_id: str = ""
    status: JobStatus = JobStatus.QUEUED
    stage_key: str = ""
    stage_text: str = ""
    progress: int = 0
    result: dict = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    max_duration: float = 600.0

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "job_type": self.job_type,
            "user_id": self.user_id,
            "status": self.status.value,
            "stage_key": self.stage_key,
            "stage_text": self.stage_text,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --- Registry (in-memory, thread-safe) ---

_RESULT_TTL = 3600.0  # keep completed jobs for 1 hour
_MAX_JOBS = 500       # evict oldest when exceeded

_lock = threading.Lock()
_jobs: dict[str, Job] = {}


def create_job(session_id: str, job_type: str, max_duration: float = 600.0, *, user_id: str = "") -> Job:
    job = Job(
        job_id=uuid4().hex[:16],
        session_id=session_id,
        user_id=user_id,
        job_type=job_type,
        max_duration=max_duration,
    )
    with _lock:
        _jobs[job.job_id] = job
        _evict_if_needed()
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
    if job:
        _check_expired(job)
    return job


def get_jobs_by_session(session_id: str) -> list[Job]:
    with _lock:
        jobs = [j for j in _jobs.values() if j.session_id == session_id]
    for j in jobs:
        _check_expired(j)
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    stage_key: str | None = None,
    stage_text: str | None = None,
    progress: int | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if status is not None:
            job.status = status
        if stage_key is not None:
            job.stage_key = stage_key
        if stage_text is not None:
            job.stage_text = stage_text
        if progress is not None:
            job.progress = min(max(progress, 0), 100)
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        job.updated_at = time.time()
    return job


def _check_expired(job: Job) -> None:
    if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.EXPIRED):
        return
    elapsed = time.time() - job.created_at
    if elapsed > job.max_duration:
        job.status = JobStatus.EXPIRED
        job.error = job.error or f"job exceeded max duration ({job.max_duration:.0f}s)"
        job.updated_at = time.time()


def _evict_if_needed() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    now = time.time()
    expired_ids = [
        jid for jid, j in _jobs.items()
        if j.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.EXPIRED)
        and (now - j.updated_at) > _RESULT_TTL
    ]
    for jid in expired_ids:
        del _jobs[jid]
    if len(_jobs) > _MAX_JOBS:
        oldest = sorted(_jobs.values(), key=lambda j: j.updated_at)
        for j in oldest[:len(_jobs) - _MAX_JOBS]:
            del _jobs[j.job_id]
