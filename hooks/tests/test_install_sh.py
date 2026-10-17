"""ADDED: tests for template/install.sh (installing the template into a new project). Real bash + git subprocess, temp dir, no network -> medium.

`pre-commit` is replaced by a fake script (no real install/network); HOME is moved to a temp dir (the user's git config does not interfere).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[2]
KUR = KOK / "template" / "install.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or os.name == "nt", reason="bash/POSIX required")

DOSYALAR = [".pre-commit-config.yaml", ".github/workflows/ci.yml", ".claude/skills/ci-fix/SKILL.md", "PROJECT_TEMPLATE.md"]


@pytest.fixture
def ortam(tmp_path):
    ev = tmp_path / "home"
    ev.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gunluk = tmp_path / "pre-commit.log"
    sahte = bin_ / "pre-commit"
    sahte.write_text(f'#!/bin/sh\necho "$@" >> "{gunluk}"\n', encoding="utf-8")
    sahte.chmod(0o755)
    env = {"PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HOME": str(ev), "GIT_CONFIG_NOSYSTEM": "1"}
    return env, gunluk


def kur(hedef, env):
    return subprocess.run([BASH, str(KUR), str(hedef)], env=env, capture_output=True, text=True, check=False, timeout=60)


def test_installs_into_empty_dir_inits_git_and_calls_pre_commit_install(tmp_path, ortam):
    env, gunluk = ortam
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    s = kur(hedef, env)
    assert s.returncode == 0, s.stderr
    for d in DOSYALAR:
        assert (hedef / d).is_file() and f"added: {d}" in s.stdout
    assert (hedef / ".git").is_dir()  # was not a git repo -> init
    assert gunluk.read_text(encoding="utf-8").strip() == "install"
    govde = (hedef / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in govde.splitlines() and "__pycache__/" in govde.splitlines()
    assert (hedef / ".github/workflows/ci.yml").read_text(encoding="utf-8") == (
        KOK / "template/.github/workflows/ci.yml"
    ).read_text(encoding="utf-8")


def test_second_run_overwrites_nothing_and_gitignore_does_not_grow(tmp_path, ortam):
    env, _ = ortam
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    assert kur(hedef, env).returncode == 0
    (hedef / ".pre-commit-config.yaml").write_text("# the user's own config\n", encoding="utf-8")
    once = (hedef / ".gitignore").read_text(encoding="utf-8")
    s = kur(hedef, env)
    assert s.returncode == 0, s.stderr
    for d in DOSYALAR:
        assert f"exists, skipped: {d}" in s.stdout
    assert (hedef / ".pre-commit-config.yaml").read_text(encoding="utf-8") == "# the user's own config\n"
    assert (hedef / ".gitignore").read_text(encoding="utf-8") == once


def test_gitignore_adds_only_missing_lines_and_keeps_existing(tmp_path, ortam):
    env, _ = ortam
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    (hedef / ".gitignore").write_text("my-line\n.env\n", encoding="utf-8")
    assert kur(hedef, env).returncode == 0
    satirlar = (hedef / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert satirlar[:2] == ["my-line", ".env"]
    assert satirlar.count(".env") == 1 and "*.pem" in satirlar


def test_missing_argument_gives_usage_error(ortam):
    env, _ = ortam
    s = subprocess.run([BASH, str(KUR)], env=env, capture_output=True, text=True, check=False, timeout=60)
    assert s.returncode != 0 and "usage: install.sh <repo-path>" in s.stderr


def test_without_pre_commit_falls_back_to_python_module(tmp_path):
    """No pre-commit on PATH -> the `python -m pre_commit install` path (with a fake python)."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gunluk = tmp_path / "py.log"
    py = bin_ / "python"
    py.write_text(f'#!/bin/sh\necho "$@" >> "{gunluk}"\n', encoding="utf-8")
    py.chmod(0o755)
    for ad in ("git", "bash", "cp", "mkdir", "dirname", "touch", "grep", "cat", "cmp", "rm", "env"):
        yol = shutil.which(ad)
        if yol:
            (bin_ / ad).symlink_to(yol)
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    ev = tmp_path / "home"
    ev.mkdir()
    s = subprocess.run(
        [str(bin_ / "bash"), str(KUR), str(hedef)],
        env={"PATH": str(bin_), "HOME": str(ev), "GIT_CONFIG_NOSYSTEM": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert s.returncode == 0, s.stderr
    assert gunluk.read_text(encoding="utf-8").strip() == "-m pre_commit install"


def test_gitignore_line_match_is_whole_line_not_substring(tmp_path, ortam):
    env, _ = ortam
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    (hedef / ".gitignore").write_text(".envrc-mine\n", encoding="utf-8")  # ".env" is a substring of it but not the same line
    assert kur(hedef, env).returncode == 0
    assert (hedef / ".gitignore").read_text(encoding="utf-8").splitlines().count(".env") == 1


@pytest.fixture
def genel_sablon(tmp_path, ortam):
    env, _ = ortam
    template = tmp_path / "tpl"
    (template / "hooks").mkdir(parents=True)
    (template / "hooks" / "pre-commit").write_text("#!/bin/sh\necho global\n", encoding="utf-8")
    Path(env["HOME"], ".gitconfig").write_text(f"[init]\n\ttemplateDir = {template}\n", encoding="utf-8")
    return template


def test_repo_hook_identical_to_global_template_hook_is_removed(tmp_path, ortam, genel_sablon):
    env, _ = ortam
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    s = kur(
        hedef, env
    )  # git init copies the hook from the template -> identical -> install.sh removes it (so gitleaks does not run twice)
    assert s.returncode == 0, s.stderr
    assert not (hedef / ".git" / "hooks" / "pre-commit").exists()


def test_repo_hook_differing_from_global_template_is_kept(tmp_path, ortam, genel_sablon):
    env, _ = ortam
    hedef = tmp_path / "yeni"
    hedef.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(hedef)], env=env, check=True, capture_output=True, timeout=30)
    kanca = hedef / ".git" / "hooks" / "pre-commit"
    kanca.write_text("#!/bin/sh\necho users-own\n", encoding="utf-8")
    assert kur(hedef, env).returncode == 0
    assert kanca.read_text(encoding="utf-8") == "#!/bin/sh\necho users-own\n"
