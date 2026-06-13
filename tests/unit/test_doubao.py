from app.services import doubao


def test_generate_text_honors_payload_timeout_seconds(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"total_tokens": 1},
            }

    class FakeClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["body"] = json
            return FakeResponse()

    monkeypatch.setattr(doubao.httpx, "Client", FakeClient)

    result = doubao.generate_text(
        "test-key",
        {
            "prompt": "hello",
            "timeout_seconds": 4,
            "max_tokens": 16,
        },
    )

    assert result["text"] == "ok"
    assert captured["timeout"].read == 4.0
    assert captured["timeout"].connect == 4.0
