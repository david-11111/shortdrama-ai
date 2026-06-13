from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_PAGE = ROOT / "frontend" / "src" / "pages" / "director" / "agent-run" / "[runId].vue"
RUN_STATUS_BAR = ROOT / "frontend" / "src" / "pages" / "director" / "agent-run" / "components" / "RunStatusBar.vue"
RUN_BANNER = ROOT / "frontend" / "src" / "pages" / "director" / "agent-run" / "components" / "RunBanner.vue"


def test_agent_run_sidebar_width_has_single_owner():
    page = RUN_PAGE.read_text(encoding="utf-8")
    status_bar = RUN_STATUS_BAR.read_text(encoding="utf-8")

    assert "--agent-run-sidebar-width" in page
    assert "grid-template-columns: var(--agent-run-sidebar-width)" in page
    assert "width: 200px" not in status_bar
    assert "width: 100%" in status_bar
    assert "box-sizing: border-box" in status_bar


def test_agent_run_banner_distinguishes_story_plan_from_video_completion():
    banner = RUN_BANNER.read_text(encoding="utf-8")

    assert "isStoryPlanComplete" in banner
    assert "需求理解完成，等待下一步" in banner
    assert "已生成分镜" in banner
    assert "Run 完成" in banner
