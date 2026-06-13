import pytest

from app.services.post_generation_review import review_image_candidate, review_video_candidate
from app.services.vision_review import set_vision_review_provider


@pytest.fixture(autouse=True)
def reset_provider():
    set_vision_review_provider(None)
    yield
    set_vision_review_provider(None)


def test_vision_unavailable_falls_back_to_rule_review():
    review = review_image_candidate(
        {
            "director_preflight": {
                "risk_level": "ready",
                "missing_refs": [],
            }
        },
        "/media/shot.png",
    )

    assert review["status"] == "usable"
    assert review["review_source"] == "rule"
    assert {item["name"] for item in review["checks"]} >= {"face_clarity", "reference_match"}


def test_vision_high_risk_image_becomes_regenerate():
    def provider(media_type, shot, media_url, refs):
        return {
            "checks": {
                "face_clarity": {"score": 32, "note": "主体人脸模糊。"},
                "person_count": {"score": 82},
                "subject_consistency": {"score": 78},
                "reference_match": {"score": 80},
                "composition_cleanliness": {"score": 74},
            }
        }

    set_vision_review_provider(provider)
    review = review_image_candidate({"director_preflight": {"risk_level": "ready"}}, "/media/shot.png")

    assert review["status"] == "regenerate"
    assert review["review_source"] == "vision"
    assert review["score"] < 72
    assert any(item["name"] == "face_clarity" and item["status"] == "fail" for item in review["checks"])
    assert "重新生成图片" in review["actions"]


def test_vision_clean_image_is_usable():
    def provider(media_type, shot, media_url, refs):
        return {
            "checks": {
                "face_clarity": 91,
                "person_count": 88,
                "subject_consistency": 90,
                "reference_match": 86,
                "composition_cleanliness": 89,
            }
        }

    set_vision_review_provider(provider)
    review = review_image_candidate({"director_preflight": {"risk_level": "ready"}}, "/media/shot.png")

    assert review["status"] == "usable"
    assert review["score"] >= 72
    assert "可进入视频生成" in review["actions"]


def test_vision_clean_video_is_cuttable():
    def provider(media_type, shot, media_url, refs):
        return {
            "checks": {
                "face_clarity": 88,
                "person_count": 90,
                "subject_consistency": 87,
                "reference_match": 84,
                "composition_cleanliness": 89,
                "video_motion_stability": 86,
                "identity_drift": 91,
            }
        }

    set_vision_review_provider(provider)
    review = review_video_candidate(
        {"selected_image": "/media/shot.png", "duration": 5, "director_preflight": {"risk_level": "ready"}},
        "/media/shot.mp4",
    )

    assert review["status"] == "cuttable"
    assert review["score"] >= 74
    assert {item["name"] for item in review["checks"]} >= {"video_motion_stability", "identity_drift"}
    assert "可进入剪辑" in review["actions"]
