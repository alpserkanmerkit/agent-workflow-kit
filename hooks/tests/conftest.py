"""Test boyutu zorlamasi (Google Testing Blog, "Test Sizes": small / medium / large).

Rule (docs/test-temel-ajan6.md):
  small  : NO network, database, filesystem, sleep, subprocess -> pure function / in-memory
  medium : local filesystem and local subprocess (git, bash, python) allowed; no network
  large  : network / end-to-end (none in this repo)
An unmarked test counts as MEDIUM (marked automatically; safe default). Only a test explicitly marked @pytest.mark.small is small;
if a test carries two different size markers, collection fails. So `-m small` and `-m medium` never overlap.
If a size's time limit (Google table: 60 / 300 / 900 s) is exceeded, the test fails.
"""

import shutil
import subprocess
import time

import pytest

SINIRLAR = {"small": 60, "medium": 300, "large": 900}


def _boyutlar(item):
    return {isaret.name for isaret in item.iter_markers() if isaret.name in SINIRLAR}


def _boyut(item):
    boyutlar = _boyutlar(item)
    return next(iter(boyutlar)) if len(boyutlar) == 1 else None


def pytest_collection_modifyitems(items):
    for item in items:
        boyutlar = _boyutlar(item)
        if not boyutlar:
            item.add_marker(pytest.mark.medium)
        elif len(boyutlar) > 1:
            raise pytest.UsageError(f"{item.nodeid}: more than one test size marker: {sorted(boyutlar)}")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    bas = time.perf_counter()
    try:
        return (yield)
    finally:
        sure = time.perf_counter() - bas
        boyut = _boyut(item)
        if boyut and sure > SINIRLAR[boyut]:
            pytest.fail(f"{boyut} test took {sure:.1f} s (limit {SINIRLAR[boyut]} s)", pytrace=False)


@pytest.fixture(scope="session")
def depo_sablonu(tmp_path_factory):
    """SPEEDUP: the git repo is built ONCE per session (5 git subprocesses, ~0.25 s); tests take a copy (~ms)."""
    d = tmp_path_factory.mktemp("template") / "depo"
    d.mkdir()

    def git(*args):
        # commit.gpgsign=false: the user's global git setting (signed commits) must not break the template install.
        subprocess.run(
            ["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
            capture_output=True,
            check=True,
            timeout=30,
        )

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "first")
    git("remote", "add", "origin", "https://github.com/example/test.git")
    git("checkout", "-q", "-b", "gece/x")
    git("commit", "-q", "--allow-empty", "-m", "second")
    return d


@pytest.fixture
def depo(depo_sablonu, tmp_path):
    hedef = tmp_path / "depo"
    shutil.copytree(depo_sablonu, hedef)
    return hedef
