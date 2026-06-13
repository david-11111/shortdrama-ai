from __future__ import annotations

import subprocess
import sys
from shutil import which
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CHECKS = [
    ("python compile", [sys.executable, "-m", "compileall", "-q", "app", "scripts", "alembic"]),
    (
        "unit smoke",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_auth_hardening.py",
            "tests/unit/test_task_dispatcher.py",
            "tests/unit/test_task_submission.py",
            "tests/unit/test_agent_runs_route_contract.py",
            "tests/unit/test_agent_worker_events.py",
            "tests/unit/test_project_brain.py",
            "tests/unit/test_visual_planner.py",
            "tests/unit/test_visual_quality_rules.py",
            "-o",
            "cache_dir=E:/tmp/saas_pytest_cache",
            "-q",
        ],
    ),
    ("frontend build", [which("npm.cmd") or which("npm") or "npm", "run", "build"], ROOT / "frontend"),
]


def main() -> int:
    for name, command, *cwd_override in CHECKS:
        cwd = cwd_override[0] if cwd_override else ROOT
        print(f"==> {name}")
        result = subprocess.run(command, cwd=cwd)
        if result.returncode != 0:
            print(f"FAILED: {name}", file=sys.stderr)
            return result.returncode
    print("quality gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
