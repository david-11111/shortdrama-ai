from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE_OVERRIDE = ROOT / "docker-compose.override.yml"


def test_api_image_prepares_writable_runtime_storage_for_non_root_user():
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "USER appuser" in source
    assert "/app/storage" in source
    assert "/app/storage/projects" in source
    assert "chown -R appuser:appuser /app" in source


def test_dev_compose_initializes_bind_mounted_storage_permissions():
    source = COMPOSE_OVERRIDE.read_text(encoding="utf-8")

    assert "init-storage:" in source
    assert "user: \"0:0\"" in source
    assert "chmod -R a+rwX" in source
    assert "condition: service_completed_successfully" in source
