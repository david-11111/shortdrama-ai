from app.services.voice_delivery_rules import infer_voice_controls, prepare_tts_payload, shape_tts_text


def test_shape_tts_text_adds_pauses_for_long_unpunctuated_line():
    text = "等一下我想先确认一件事你刚才说的到底是不是真的"

    result = shape_tts_text(text)

    assert "，" in result
    assert result.replace("，", "") == text


def test_shape_tts_text_preserves_existing_punctuation():
    text = "等一下，我想先确认一件事。"

    assert shape_tts_text(text) == text


def test_infer_voice_controls_for_warning_pressure():
    result = infer_voice_controls("黑暗反派低声冷笑：听懂了吗！")

    assert result["delivery_profile"] == "warning_slow_pressure"
    assert result["speed"] < 1.0
    assert result["volume"] > 1.0


def test_prepare_tts_payload_keeps_user_speed_and_infers_volume():
    payload = {
        "text": "下一个不是就到我了",
        "emotion": "紧张，轻声低语，呼吸放缓，断续停顿",
        "speed": 0.8,
    }

    result = prepare_tts_payload(payload)

    assert result["speed"] == 0.8
    assert result["volume"] == 0.95
    assert result["delivery_profile"] == "tense_breathing_pauses"
    assert "，" in result["text"]
