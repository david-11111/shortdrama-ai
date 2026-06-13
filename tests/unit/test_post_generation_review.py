from app.services.post_generation_review import (
    media_candidate,
    review_image_candidate,
    review_video_candidate,
)


def test_blocked_image_candidate_requires_regeneration():
    review = review_image_candidate(
        {
            "director_preflight": {
                "risk_level": "blocked",
                "missing_refs": [],
            }
        },
        "/media/shot-1.png",
    )

    assert review["media_type"] == "image"
    assert review["status"] == "regenerate"
    assert review["score"] < 50
    assert review["actions"]


def test_warning_image_candidate_with_missing_refs_needs_review():
    review = review_image_candidate(
        {
            "director_preflight": {
                "risk_level": "warning",
                "missing_refs": ["character", "scene"],
            }
        },
        "/media/shot-2.png",
    )

    assert review["status"] == "needs_review"
    assert 50 <= review["score"] < 72
    assert any("character" in note and "scene" in note for note in review["notes"])


def test_clean_image_candidate_is_usable():
    review = review_image_candidate(
        {
            "director_preflight": {
                "risk_level": "ready",
                "missing_refs": [],
            }
        },
        "/media/shot-3.png",
    )

    assert review["status"] == "usable"
    assert review["score"] >= 72


def test_clean_video_candidate_with_selected_image_is_cuttable():
    review = review_video_candidate(
        {
            "selected_image": "/media/shot-4.png",
            "duration": 5,
            "director_preflight": {
                "risk_level": "ready",
                "missing_refs": [],
            },
        },
        "/media/shot-4.mp4",
    )

    assert review["media_type"] == "video"
    assert review["status"] == "cuttable"
    assert review["score"] >= 74


def test_media_candidate_copies_review_summary_fields():
    review = {
        "status": "usable",
        "score": 86,
        "notes": [],
        "actions": [],
    }

    candidate = media_candidate("/media/shot.png", review)

    assert candidate["url"] == "/media/shot.png"
    assert candidate["review"] is review
    assert candidate["review_status"] == "usable"
    assert candidate["review_score"] == 86
