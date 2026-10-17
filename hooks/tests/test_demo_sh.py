"""demo.sh smoke test: the one-command demo runs with real bash + git + python subprocesses, no network -> medium."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or os.name == "nt", reason="bash/POSIX required")


def test_demo_exits_0_prints_demo_complete_and_leaves_repo_clean():
    once = subprocess.run(["git", "status", "--porcelain"], cwd=KOK, capture_output=True, text=True, check=True).stdout
    s = subprocess.run([BASH, str(KOK / "demo.sh")], capture_output=True, text=True, check=False, timeout=120)
    assert s.returncode == 0, s.stdout + s.stderr
    assert "DEMO COMPLETE" in s.stdout
    for beklenen in (
        '"permissionDecision":"deny"',
        "git add .env      -> exit=1",
        "SKIPPED" if not shutil.which("gitleaks") else "gitleaks fake",
    ):
        assert beklenen in s.stdout
    sonra = subprocess.run(["git", "status", "--porcelain"], cwd=KOK, capture_output=True, text=True, check=True).stdout
    assert sonra == once
