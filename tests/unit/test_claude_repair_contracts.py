import sys
import types
from pathlib import Path

from app.services.provider_prompt_adapter import adapt_provider_payload
from app.tasks import _shared


ROOT = Path(__file__).resolve().parents[2]


def test_reflect_before_retry_applies_adjusted_params_without_logger_name_error(monkeypatch):
    class Settings:
        llm_error_reflection_enabled = True
        deepseek_api_key = "test-key"

    class Reflection:
        retry_strategy = "immediate"
        adjusted_params = {"prompt": "fixed prompt", "duration": 15}

    module = types.ModuleType("app.services.error_reflection")
    module.reflect_on_failure_sync = lambda *args, **kwargs: Reflection()
    monkeypatch.setitem(sys.modules, "app.services.error_reflection", module)
    monkeypatch.setattr(_shared, "get_settings", lambda: Settings())

    strategy, adjusted = _shared.reflect_before_retry(
        "task-1",
        RuntimeError("provider failed"),
        retry_count=1,
        task_type="video_gen",
        payload={"prompt": "old prompt", "shot_row": {"prompt": "old prompt"}},
        shot_context={"shot_index": 1},
    )

    assert strategy == "retry"
    assert adjusted["prompt"] == "fixed prompt"
    assert adjusted["duration"] == 15
    assert adjusted["shot_row"]["prompt"] == "fixed prompt"


def test_unready_auto_regenerate_path_is_not_active_against_shot_rows_meta():
    source = (ROOT / "app" / "services" / "main_chain_terminal.py").read_text(encoding="utf-8")
    handlers = (ROOT / "app" / "services" / "main_chain_handlers.py").read_text(encoding="utf-8")

    assert "shot_rows.meta" not in source
    assert "_auto_regenerate_on_review_failure" not in source
    assert "auto_regenerate_on_review_failure" not in handlers


def test_temporal_motion_prompt_is_video_only():
    image_payload = {
        "provider": "seedream",
        "prompt": "gold ring keyframe",
        "shot_index": 1,
        "total_shots": 8,
        "shot_row": {"shot_index": 1, "total_shots": 8},
    }
    video_payload = {
        "provider": "ltx2.3",
        "prompt": "gold ring camera move",
        "shot_index": 1,
        "total_shots": 8,
        "shot_row": {"shot_index": 1, "total_shots": 8},
    }

    image = adapt_provider_payload(image_payload, task_type="image_gen", provider="seedream")
    video = adapt_provider_payload(video_payload, task_type="video_gen", provider="ltx2.3")

    assert "时序位置" not in image["prompt"]
    assert "时序位置" in video["prompt"]
