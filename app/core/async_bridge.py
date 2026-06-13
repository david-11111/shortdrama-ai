"""Async ↔ sync bridge — single threaded-pool for all services.

Resolves two classic problems:
  1. ``asyncio.run()`` from inside a running loop raises ``RuntimeError``.
  2. Creating a ``ThreadPoolExecutor`` per call wastes ~100 ms overhead.

Usage::

    from app.core.async_bridge import run_async

    result = run_async(fetch_asset(asset_id))
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

log = logging.getLogger(__name__)

_T = TypeVar("_T")

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="async_bridge")


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Return the running loop, or start a new one on the pool thread."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def run_async(coro: asyncio.Future[_T]) -> _T:
    """Execute *coro* in an async context, detecting running loop.

    * If already inside a running loop → schedule as a task, block with
      ``Future.result()`` on pool thread.
    * If no loop → ``asyncio.run()`` on the pool thread.
    """
    from app.config import get_settings

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — use asyncio.run on a pool thread.
        fut = _POOL.submit(asyncio.run, coro)
        return fut.result()

    # Running loop — submit to that loop from a pool thread, then wait.
    fut: concurrent.futures.Future[_T] = _POOL.submit(
        _schedule_and_wait, loop, coro
    )
    return fut.result()


def _schedule_and_wait(loop: asyncio.AbstractEventLoop, coro: asyncio.Future[_T]) -> _T:
    """Schedule *coro* on *loop* and block until done."""
    import concurrent.futures as cf

    inner: cf.Future[_T] = cf.Future()

    async def _run() -> None:
        try:
            result = await coro
            inner.set_result(result)
        except BaseException as exc:
            inner.set_exception(exc)

    loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_run()))
    return inner.result()
