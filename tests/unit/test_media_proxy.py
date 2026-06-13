import pytest
from fastapi import HTTPException

from app.services.media_proxy import (
    blob_streaming_response,
    extract_media_url,
    infer_media_type,
    validate_public_media_url,
)


def test_extract_media_url_prefers_explicit_url():
    assert extract_media_url({"url": "https://cdn/a.mp4", "video_url": "https://cdn/b.mp4"}) == "https://cdn/a.mp4"
    assert extract_media_url({"image_url": "https://cdn/a.jpg"}) == "https://cdn/a.jpg"


def test_infer_media_type_from_video_result():
    ext, content_type = infer_media_type({"duration": 5}, "https://cdn/file")
    assert ext == ".mp4"
    assert content_type == "video/mp4"


def test_blob_streaming_response_has_expected_headers():
    response = blob_streaming_response(task_id="task-1", data=b"abc", content_type="video/mp4", file_size=3)
    assert response.media_type == "video/mp4"
    assert response.headers["content-length"] == "3"
    assert "final-task-1.mp4" in response.headers["content-disposition"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/video.mp4",
        "http://127.0.0.1/video.mp4",
        "http://10.0.0.1/video.mp4",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/video.mp4",
    ],
)
def test_validate_public_media_url_rejects_ssrf_targets(url):
    with pytest.raises(HTTPException):
        validate_public_media_url(url)


def test_validate_public_media_url_accepts_public_ip_url():
    validate_public_media_url("https://93.184.216.34/video.mp4")
