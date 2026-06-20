from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCH_PAGE = ROOT / "frontend" / "src" / "pages" / "director" / "agent-run" / "index.vue"


def test_agent_run_launch_defaults_to_clean_fresh_project():
    source = LAUNCH_PAGE.read_text(encoding="utf-8")

    assert "const createFreshProject = ref(true)" in source
    assert "project_id: createFreshProject.value ? '' : form.value.project_id" in source
    assert "clean_start: true" in source
    assert "video_provider: 'joy-echo'" in source
