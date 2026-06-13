import pytest

from app.middleware import rate_limit


class _Row:
    window_seconds = 60
    max_count = 5


class _Result:
    def fetchone(self):
        return _Row()


class _Db:
    async def execute(self, *_args, **_kwargs):
        return _Result()


class _ExplodingGlobalRedis:
    def __getattr__(self, name):
        raise AssertionError(f"global redis_client must not be used for rate-limit operation: {name}")


class _Pipe:
    def __init__(self, calls):
        self.calls = calls

    def zremrangebyscore(self, key, start, end):
        self.calls.append(("zremrangebyscore", key, start, end))

    def zcard(self, key):
        self.calls.append(("zcard", key))

    async def execute(self):
        self.calls.append(("execute",))
        return [0, 0]


class _FreshRedis:
    def __init__(self):
        self.calls = []
        self.closed = False

    def pipeline(self):
        self.calls.append(("pipeline",))
        return _Pipe(self.calls)

    async def zadd(self, key, values):
        self.calls.append(("zadd", key, values))

    async def expire(self, key, ttl):
        self.calls.append(("expire", key, ttl))

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_check_rate_limit_uses_fresh_redis_client(monkeypatch):
    fresh = _FreshRedis()

    monkeypatch.setattr(rate_limit, "redis_client", _ExplodingGlobalRedis(), raising=False)
    monkeypatch.setattr(rate_limit, "make_redis_client", lambda: fresh, raising=False)

    result = await rate_limit.check_rate_limit(7, "free", "video_gen", _Db())

    assert result["remaining"] == 4
    assert ("pipeline",) in fresh.calls
    assert any(call[0] == "zadd" for call in fresh.calls)
    assert fresh.closed is True
