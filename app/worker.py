from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.celery_app import celery_app
from app.config import get_settings

PER_KEY_CONCURRENCY = {
    "video": 2,
    "image": 5,
    "text": 10,
}


class CeleryDispatchProxy:
    def send_task(self, task_name: str, *args: Any, **kwargs: Any):
        return celery_app.send_task(task_name, args=args, kwargs=kwargs)


executor = CeleryDispatchProxy()


def recommended_concurrency(queue: str) -> int:
    key_count = max(len(get_settings().ark_api_key_list), 1)
    return key_count * PER_KEY_CONCURRENCY.get(queue, 1)


def build_worker_argv(
    queues: Sequence[str] | None = None,
    *,
    loglevel: str = "INFO",
    pool: str = "threads",
    concurrency: int | None = None,
) -> list[str]:
    selected_queues = list(queues or ["video", "image", "text"])
    argv = ["worker", "--loglevel", loglevel, "--pool", pool]
    if selected_queues:
        argv.extend(["-Q", ",".join(selected_queues)])
    if concurrency is None and len(selected_queues) == 1:
        concurrency = recommended_concurrency(selected_queues[0])
    if concurrency is not None:
        argv.extend(["-c", str(concurrency)])
    return argv


def worker_main(argv: Sequence[str] | None = None) -> int:
    celery_app.worker_main(list(argv) if argv else build_worker_argv())
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())
