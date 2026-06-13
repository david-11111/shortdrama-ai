import shutil
import uuid
from pathlib import Path

from app.services import shot_revision


def test_prompt_revision_lifecycle(monkeypatch):
    storage = Path("storage") / "test-shot-revisions" / uuid.uuid4().hex
    monkeypatch.setattr(shot_revision, "STORAGE", storage)
    try:
        revision = shot_revision.build_prompt_revision(
            shot_index=2,
            original_prompt="wide shot with crowd",
            rewritten_prompt="medium shot, at most two people",
            preflight={"risk_level": "blocked"},
        )

        saved = shot_revision.append_prompt_revision("../project/one", revision)

        assert saved["revision_id"] == revision["revision_id"]
        assert (storage / "project_one" / "shot_prompt_revisions.json").exists()
        latest = shot_revision.latest_prompt_revision("../project/one", 2)
        assert latest["rewritten_prompt"] == "medium shot, at most two people"

        payload = shot_revision.revision_public_payload("../project/one", 2)
        assert payload["count"] == 1
        assert payload["latest"]["revision_id"] == revision["revision_id"]

        rolled_back = shot_revision.mark_prompt_revision_rolled_back("../project/one", 2, revision["revision_id"])

        assert rolled_back["revision_id"] == revision["revision_id"]
        assert rolled_back["rolled_back_at"]
        assert shot_revision.latest_prompt_revision("../project/one", 2) is None
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)
