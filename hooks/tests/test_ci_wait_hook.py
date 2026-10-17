"""Wait hook tests: PostToolUse push record + Stop CI wait. gh and the clock are fake; no network."""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

import ci_wait_hook as bk  # noqa: E402


def ts(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


SIMDI = ts("2026-10-07T14:00:00Z")
SHA = "a" * 40


@pytest.fixture(autouse=True)
def durum_dosyasi(tmp_path, monkeypatch):
    yol = tmp_path / "bekleme.json"
    monkeypatch.setenv("BEKLEME_DURUM", str(yol))
    monkeypatch.setattr(bk, "simdi", lambda: SIMDI)
    return yol


class SahteGh:
    """Imitates `gh run list` calls; records every call."""

    def __init__(self, kosular=None, gecmis=None, hata=None):
        self.kosular = kosular or []
        self.gecmis = gecmis if gecmis is not None else []
        self.hata = hata
        self.cagrilar = []

    def __call__(self, args, zaman_asimi):
        self.cagrilar.append(list(args))
        if self.hata == "timeout":
            raise subprocess.TimeoutExpired("gh", zaman_asimi)
        if self.hata:
            return 1, "", self.hata
        if "--workflow" in args:
            return 0, json.dumps(self.gecmis), ""
        return 0, json.dumps(self.kosular), ""


def kosu(id_, status="in_progress", conclusion="", sha=SHA, created="2026-10-07T13:58:00Z", wf="Center Gate"):
    return {
        "databaseId": id_,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created,
        "updatedAt": created,
        "workflowName": wf,
        "headSha": sha,
    }


def gecmis_kosu(sure_sn):
    bas = SIMDI - 86400
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return {
        "createdAt": datetime.fromtimestamp(bas, UTC).strftime(fmt),
        "updatedAt": datetime.fromtimestamp(bas + sure_sn, UTC).strftime(fmt),
    }


GECMIS_5 = [gecmis_kosu(s) for s in (300, 320, 280, 310, 900)]  # median 310 + 60 = 370 s = 6.2 min


def kayit_ekle(session_id="s1", repo="example/test", dal="gece/x", sha=SHA, yas_sn=60):
    bk.kayitlari_ekle([bk.yeni_kayit(session_id, repo, dal, sha, SIMDI - yas_sn)])


def stop(monkeypatch, gh, session_id="s1", prompt_id="p1"):
    monkeypatch.setattr(bk, "gh_calistir", gh)
    return bk.stop_isle({"session_id": session_id, "prompt_id": prompt_id, "hook_event_name": "Stop"})


# ---------------- parsing the push command ----------------


@pytest.mark.small
@pytest.mark.parametrize(
    "arac,komut,cwd,dizin,remote,refspecler",
    [
        ("Bash", "git push origin gece/x", "D:/r", "D:/r", "origin", ["gece/x"]),
        ("Bash", "git -C D:/repo push -u origin feature", "D:/x", "D:/repo", "origin", ["feature"]),
        ("Bash", "cd /d/repo && git push", "D:/x", "D:/repo", None, []),
        ("PowerShell", 'git -C "D:\\My Project" push origin main', "C:/", "D:\\My Project", "origin", ["main"]),
        ("PowerShell", "Set-Location D:\\x; git push origin HEAD:gece/y", "C:/", "D:\\x", "origin", ["HEAD:gece/y"]),
        ("Bash", "git -c http.x=y push origin x", "D:/r", "D:/r", "origin", ["x"]),
        ("Bash", "timeout 60 git push origin x", "D:/r", "D:/r", "origin", ["x"]),
        ("Bash", "git add -A && git commit -m 'm; x' && git push origin gece/z", "D:/r", "D:/r", "origin", ["gece/z"]),
    ],
)
def test_push_command_found(arac, komut, cwd, dizin, remote, refspecler):
    istekler = bk.push_istekleri(komut, arac, cwd)
    assert len(istekler) == 1
    ist = istekler[0]
    assert bk.yol_normal(ist.dizin) == bk.yol_normal(dizin)
    assert ist.remote == remote
    assert ist.refspecler == refspecler


@pytest.mark.small
@pytest.mark.parametrize(
    "komut",
    [
        "git status && git log -1",
        'echo "git push origin x"',
        "git push --dry-run origin x",
        "git push -n origin x",
        "git push origin --delete x",
        "git push origin :x",
        "grep push README.md",
    ],
)
def test_non_push_or_dry_run_command_produces_no_record(komut):
    assert bk.push_istekleri(komut, "Bash", "D:/r") == []


@pytest.mark.small
@pytest.mark.parametrize(
    "url,beklenen",
    [
        ("https://github.com/example-user/ci-demo.git", "example-user/ci-demo"),
        ("https://github.com/example-user/ci-demo", "example-user/ci-demo"),
        ("git@github.com:example-account/center.git", "example-account/center"),
        ("ssh://git@github.com/o/r.git/", "o/r"),
        ("https://x-access-token@github.com/o/r.git", "o/r"),
        ("https://gitlab.com/o/r.git", None),
        ("D:/local/bare.git", None),
    ],
)
def test_repo_name_from_remote_url(url, beklenen):
    assert bk.repo_adi(url) == beklenen


# ---------------- PostToolUse: record with a real git repo ----------------


def git(dizin, *args):
    return subprocess.run(
        ["git", "-C", str(dizin), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()


def post_olay(komut, cwd, stderr="", session_id="s1", arac="Bash"):
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": arac,
        "cwd": str(cwd),
        "tool_input": {"command": komut},
        "tool_response": {"stdout": "", "stderr": stderr, "interrupted": False},
    }


def test_successful_push_is_recorded(depo):
    sha = git(depo, "rev-parse", "HEAD")
    git(depo, "update-ref", "refs/remotes/origin/gece/x", sha)  # simulates a successful push
    bk.post_isle(post_olay("git push origin gece/x", depo, " * [new branch] gece/x -> gece/x"))
    kayitlar = bk.durum_oku()["kayitlar"]
    assert len(kayitlar) == 1
    k = kayitlar[0]
    assert (k["session_id"], k["repo"], k["dal"], k["sha"], k["islendi"]) == ("s1", "example/test", "gece/x", sha, False)
    assert k["zaman"].endswith("Z")


def test_git_c_and_refspec_target_branch(depo, tmp_path):
    sha = git(depo, "rev-parse", "HEAD")
    git(depo, "update-ref", "refs/remotes/origin/gece/hedef", sha)
    bk.post_isle(post_olay(f'git -C "{depo}" push origin HEAD:gece/hedef', tmp_path))
    k = bk.durum_oku()["kayitlar"][0]
    assert (k["dal"], k["sha"]) == ("gece/hedef", sha)


def test_rejected_push_is_not_recorded(depo):
    bk.post_isle(post_olay("git push origin gece/x", depo, " ! [rejected] gece/x -> gece/x (fetch first)\nerror: failed to push"))
    assert bk.durum_oku()["kayitlar"] == []


def test_same_push_twice_single_record(depo):
    sha = git(depo, "rev-parse", "HEAD")
    git(depo, "update-ref", "refs/remotes/origin/gece/x", sha)
    bk.post_isle(post_olay("git push origin gece/x", depo))
    bk.post_isle(post_olay("git push", depo))
    assert len(bk.durum_oku()["kayitlar"]) == 1


def test_non_push_command_does_not_touch_file(durum_dosyasi, tmp_path):
    bk.post_isle(post_olay("ls -la", tmp_path))
    assert not durum_dosyasi.exists()


# ---------------- Stop: CI wait ----------------


def test_no_push_no_network_call(monkeypatch):
    gh = SahteGh()
    assert stop(monkeypatch, gh) is None
    assert gh.cagrilar == []


def test_other_session_and_old_record_make_no_network_call(monkeypatch):
    kayit_ekle(session_id="other")
    kayit_ekle(yas_sn=3 * 3600 + 5)
    gh = SahteGh([kosu(1)])
    assert stop(monkeypatch, gh) is None
    assert gh.cagrilar == []


def test_running_run_blocks_and_expected_is_median_plus_60(monkeypatch):
    kayit_ekle()
    gh = SahteGh([kosu(123)], GECMIS_5)
    cikti = stop(monkeypatch, gh)
    assert cikti["decision"] == "block"
    assert cikti["reason"] == (
        "CI 123 running (elapsed 2.0 min, expected 6.2 min). Do not end the turn: wait with `gh run watch 123 --exit-status`, then handle the result."
    )
    ilk = gh.cagrilar[0]
    assert ilk[:4] == ["run", "list", "-R", "example/test"]
    assert ilk[ilk.index("--branch") + 1] == "gece/x"
    assert "databaseId,status,conclusion,createdAt,updatedAt,workflowName,headSha" in ilk


def test_only_runs_for_that_sha_are_counted(monkeypatch):
    kayit_ekle()
    gh = SahteGh([kosu(9, sha="b" * 40), kosu(10, status="completed", conclusion="success")], GECMIS_5)
    cikti = stop(monkeypatch, gh)
    assert cikti["reason"] == "CI 10 finished: success. Handle the result and report it."


def test_no_data_expected_10_min(monkeypatch):
    kayit_ekle()
    cikti = stop(monkeypatch, SahteGh([kosu(5)], []))
    assert "expected 10.0 min" in cikti["reason"]


def test_timeout_warning(monkeypatch):
    kayit_ekle(yas_sn=700)
    gh = SahteGh([kosu(77, created="2026-10-07T13:50:00Z")], GECMIS_5)
    cikti = stop(monkeypatch, gh)
    assert cikti["decision"] == "block"
    assert cikti["reason"].startswith("TIME EXCEEDED — CI 77 running (elapsed 10.0 min, expected 6.2 min).")
    assert (
        "Send the user a PushNotification: 'CI Center Gate (example/test gece/x) exceeded the estimate by 3.8 min: <reason>'"
        in cikti["reason"]
    )


def test_finished_run_blocks_once_then_allows(monkeypatch):
    kayit_ekle()
    gh = SahteGh([kosu(42, status="completed", conclusion="failure")])
    cikti = stop(monkeypatch, gh)
    assert cikti == {"decision": "block", "reason": "CI 42 finished: failure. Handle the result and report it."}
    assert stop(monkeypatch, gh) is None
    assert bk.durum_oku()["kayitlar"][0]["islendi"] is True


def test_eight_consecutive_blocks_then_allow_and_systemmessage(monkeypatch):
    kayit_ekle()
    gh = SahteGh([kosu(7)], GECMIS_5)
    for _ in range(8):
        assert stop(monkeypatch, gh)["decision"] == "block"
    cikti = stop(monkeypatch, gh)
    assert "decision" not in cikti
    assert "8" in cikti["systemMessage"] and "7" in cikti["systemMessage"]
    assert stop(monkeypatch, gh, prompt_id="p2")["decision"] == "block"  # a new turn resets the counter


@pytest.mark.parametrize("hata", ["HTTP 502: bad gateway", "timeout"])
def test_gh_error_fail_open(monkeypatch, hata):
    kayit_ekle()
    cikti = stop(monkeypatch, SahteGh(hata=hata))
    assert "decision" not in cikti
    assert "NOT VERIFIED" in cikti["systemMessage"]


def test_run_not_visible_yet_blocks_briefly_then_gives_up(monkeypatch):
    kayit_ekle(yas_sn=20)
    cikti = stop(monkeypatch, SahteGh([]))
    assert cikti["decision"] == "block" and "not visible yet" in cikti["reason"]
    bk.kayitlari_ekle([])  # the record is preserved even if the file is rewritten
    monkeypatch.setattr(bk, "simdi", lambda: SIMDI + 200)
    assert stop(monkeypatch, SahteGh([])) is None


# ---------------- subprocess: latency and fail-open ----------------


def _betik(mod, olay, ortam):
    return subprocess.run(
        [sys.executable, "-I", "-S", str(HOOKS / "ci_wait_hook.py"), mod],
        input=json.dumps(olay).encode("utf-8"),
        env=ortam,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_subprocess_no_push_fast_and_silent(tmp_path):
    ortam = {
        "BEKLEME_DURUM": str(tmp_path / "missing.json"),
        "BEKLEME_GH": str(tmp_path / "gh-missing.exe"),
        "SYSTEMROOT": "C:\\Windows",
        "PATH": "",
    }
    bas = time.perf_counter()
    out = _betik("stop", {"session_id": "s1", "hook_event_name": "Stop"}, ortam)
    assert out.returncode == 0 and out.stdout == b""
    assert time.perf_counter() - bas < 1.0


def test_subprocess_broken_input_fail_open(tmp_path):
    ortam = {"BEKLEME_DURUM": str(tmp_path / "d.json"), "SYSTEMROOT": "C:\\Windows", "PATH": ""}
    out = subprocess.run(
        [sys.executable, "-I", "-S", str(HOOKS / "ci_wait_hook.py"), "stop"],
        input=b"{broken",
        env=ortam,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert out.returncode == 0 and out.stdout == b""
