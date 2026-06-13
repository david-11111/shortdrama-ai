import shutil
import uuid
from pathlib import Path

from app.services import project_workspace


def test_project_workspace_initializes_required_files(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        result = project_workspace.init_project_workspace("../project/one", name="精品短剧项目")

        assert result["ready"] is True
        assert result["workspace_version"] == "shortdrama_workspace_v1"
        assert "PROJECT.md" in result["created"]
        assert "memory/failures.md" in result["created"]
        assert (storage / "project_one" / "PROJECT.md").exists()
        assert (storage / "project_one" / "story" / "characters.md").exists()
        assert (storage / "project_one" / "shots" / "episode-01-scene-01.json").exists()

        project_doc = (storage / "project_one" / "PROJECT.md").read_text(encoding="utf-8")
        assert "Agent 启动规则" in project_doc
        assert "精品短剧" in project_doc
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_project_workspace_keeps_existing_files_unless_forced(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.init_project_workspace("project-one", name="初版")
        project_doc = storage / "project-one" / "PROJECT.md"
        project_doc.write_text("# custom\n", encoding="utf-8")

        kept = project_workspace.init_project_workspace("project-one", name="新版")
        assert "PROJECT.md" in kept["kept"]
        assert project_doc.read_text(encoding="utf-8") == "# custom\n"

        forced = project_workspace.init_project_workspace("project-one", name="新版", force=True)
        assert "PROJECT.md" in forced["created"]
        assert "新版" in project_doc.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_read_project_workspace_returns_bootstrap_content(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        result = project_workspace.read_project_workspace("project-two", name="项目二")

        assert result["ready"] is True
        assert "PROJECT.md" in result["bootstrap"]
        assert "memory/decisions.md" in result["bootstrap"]
        assert result["bootstrap"]["shots/episode-01-scene-01.json"].strip().startswith("{")
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_write_project_workspace_appends_allowed_file_and_records_decision(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.init_project_workspace("project-three", name="project three")

        result = project_workspace.write_project_workspace_file(
            "project-three",
            relative_path="story/characters.md",
            content="## 主角\n- name: 林晚",
            mode="append",
            source="unit_test",
            reason="锁定主角",
        )

        characters = (storage / "project-three" / "story" / "characters.md").read_text(encoding="utf-8")
        decisions = (storage / "project-three" / "memory" / "decisions.md").read_text(encoding="utf-8")
        assert result["write"]["path"] == "story/characters.md"
        assert result["write"]["decision_recorded"] is True
        assert "林晚" in characters
        assert "path: story/characters.md" in decisions
        assert "reason: 锁定主角" in decisions
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_write_project_workspace_rejects_path_traversal(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.init_project_workspace("project-four", name="project four")

        try:
            project_workspace.write_project_workspace_file(
                "project-four",
                relative_path="../outside.md",
                content="bad",
            )
        except ValueError as exc:
            assert "Invalid workspace path" in str(exc)
        else:
            raise AssertionError("path traversal should be rejected")
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_write_project_workspace_rejects_disallowed_path(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.init_project_workspace("project-five", name="project five")

        try:
            project_workspace.write_project_workspace_file(
                "project-five",
                relative_path="exports/final.md",
                content="bad",
            )
        except ValueError as exc:
            assert "not writable" in str(exc)
        else:
            raise AssertionError("disallowed workspace path should be rejected")
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_write_project_workspace_replace_requires_force_and_validates_json(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.init_project_workspace("project-six", name="project six")

        try:
            project_workspace.write_project_workspace_file(
                "project-six",
                relative_path="shots/episode-01-scene-01.json",
                content='{"shots": []}',
                mode="replace",
            )
        except ValueError as exc:
            assert "requires force=true" in str(exc)
        else:
            raise AssertionError("replace should require force")

        result = project_workspace.write_project_workspace_file(
            "project-six",
            relative_path="shots/episode-01-scene-01.json",
            content='{"shots": [{"shot_index": 1}]}',
            mode="replace",
            force=True,
            reason="更新分镜规划",
        )

        written = (storage / "project-six" / "shots" / "episode-01-scene-01.json").read_text(encoding="utf-8")
        assert result["write"]["mode"] == "replace"
        assert '"shot_index": 1' in written

        try:
            project_workspace.write_project_workspace_file(
                "project-six",
                relative_path="shots/episode-01-scene-02.json",
                content="{bad json",
                mode="replace",
                force=True,
            )
        except ValueError as exc:
            assert "Invalid JSON" in str(exc)
        else:
            raise AssertionError("invalid JSON should be rejected")
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_persist_director_result_to_workspace_writes_plan_files(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        result = project_workspace.persist_director_result_to_workspace(
            "project-seven",
            {
                "reply": "第一场：女主在金店提出回购黄金。",
                "continuity": {
                    "character_continuity": "女主三十岁，职业装，表情克制。",
                    "scene_continuity": "现代金店柜台，暖色灯光。",
                    "prop_continuity": "黄金手镯和报价单。",
                },
                "execution_plan": {
                    "camera_plan": "先建立空间，再切特写和反应镜头。",
                },
                "shot_rows": [
                    {
                        "shot_index": 1,
                        "prompt": "金店柜台前，女主递出黄金手镯。",
                        "duration": 5,
                        "status": "pending",
                    }
                ],
                "quality_gate": {"allow_video_production": False, "reason": "先审关键帧"},
            },
            source="unit_director",
            reason="持久化导演规划",
        )

        assert len(result["writes"]) == 4
        characters = (storage / "project-seven" / "story" / "characters.md").read_text(encoding="utf-8")
        episodes = (storage / "project-seven" / "story" / "episodes.md").read_text(encoding="utf-8")
        scene = (storage / "project-seven" / "scenes" / "episode-01-scene-01.md").read_text(encoding="utf-8")
        shots = (storage / "project-seven" / "shots" / "episode-01-scene-01.json").read_text(encoding="utf-8")
        decisions = (storage / "project-seven" / "memory" / "decisions.md").read_text(encoding="utf-8")

        assert "女主三十岁" in characters
        assert "第一场" in episodes
        assert "金店柜台前" in scene
        assert "金店柜台前" in shots
        assert "path: shots/episode-01-scene-01.json" in decisions
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_persist_director_result_replaces_managed_plan_sections(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        base_result = {
            "reply": "第一版规划。",
            "continuity": {"character_continuity": "女主，白衬衫。"},
            "shot_rows": [{"shot_index": 1, "prompt": "第一版镜头。", "duration": 5}],
        }
        project_workspace.persist_director_result_to_workspace("project-replace", base_result)
        project_workspace.persist_director_result_to_workspace(
            "project-replace",
            {
                "reply": "第二版规划。",
                "continuity": {"character_continuity": "女主，黑西装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "第二版镜头。", "duration": 5}],
            },
        )

        episodes = (storage / "project-replace" / "story" / "episodes.md").read_text(encoding="utf-8")
        scene = (storage / "project-replace" / "scenes" / "episode-01-scene-01.md").read_text(encoding="utf-8")
        characters = (storage / "project-replace" / "story" / "characters.md").read_text(encoding="utf-8")

        assert "第一版规划" not in episodes
        assert "第二版规划" in episodes
        assert scene.count("## Director Scene Plan") == 1
        assert "第一版镜头" not in scene
        assert "第二版镜头" in scene
        assert characters.count("## Director Lock") == 1
        assert "黑西装" in characters
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_compact_project_workspace_keeps_latest_managed_section(monkeypatch):
    storage = Path("storage") / "test-project-workspace" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.init_project_workspace("project-compact", name="compact")
        episodes = storage / "project-compact" / "story" / "episodes.md"
        episodes.write_text(
            "# 剧集规划\n\n"
            "## Director Plan 2026-01-01\n\n旧版规划\n\n"
            "## Director Plan 2026-01-02\n\n新版规划\n",
            encoding="utf-8",
        )

        dry = project_workspace.compact_project_workspace("project-compact", dry_run=True)
        assert dry["planned"][0]["path"] == "story/episodes.md"
        assert "旧版规划" in episodes.read_text(encoding="utf-8")

        result = project_workspace.compact_project_workspace("project-compact")
        compacted = episodes.read_text(encoding="utf-8")
        decisions = (storage / "project-compact" / "memory" / "decisions.md").read_text(encoding="utf-8")

        assert result["writes"]
        assert "旧版规划" not in compacted
        assert "新版规划" in compacted
        assert "source: workspace_compactor" in decisions
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)
