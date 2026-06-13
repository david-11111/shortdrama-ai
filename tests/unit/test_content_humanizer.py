from app.services.content_humanizer import humanize_generated_copy, normalize_strength


def test_humanizer_light_removes_common_ai_cliches_without_changing_structure():
    text = "在当今这个快节奏的时代，AI写作提供了全新的解决方案。\n\n总而言之，内容要服务用户。"

    result = humanize_generated_copy(text, strength="light")

    assert "在当今这个快节奏的时代" not in result["text"]
    assert "提供了全新的解决方案" not in result["text"]
    assert "\n\n" in result["text"]
    assert result["strength"] == "light"
    assert result["changed_count"] >= 2


def test_humanizer_medium_breaks_long_sentences_and_naturalizes_words():
    text = "因此我们需要进行内容改写但是不能破坏原本结构和核心表达否则用户会觉得内容变得面目全非。"

    result = humanize_generated_copy(text, strength="medium")

    assert "因此" not in result["text"]
    assert "进行" not in result["text"]
    assert "。但是" in result["text"]
    assert result["strength"] == "medium"


def test_humanizer_deep_varies_numbered_openers_and_adds_light_rhythm():
    text = "一、首先说明这个方法为什么有效。它不是把内容全部推倒重写，而是在保留框架的前提下调整表达节奏、词语选择和段落呼吸感，让读者读起来更像真人写的内容。"

    result = humanize_generated_copy(text, strength="deep")

    assert not result["text"].startswith("一、")
    assert "这一点很关键。" in result["text"]
    assert result["strength"] == "deep"


def test_normalize_strength_accepts_chinese_aliases():
    assert normalize_strength("轻度") == "light"
    assert normalize_strength("中度") == "medium"
    assert normalize_strength("深度") == "deep"
    assert normalize_strength("unknown") == "light"
