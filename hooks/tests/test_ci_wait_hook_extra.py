"""ADDED: small, deterministic tests that close the coverage.py gap (ci_wait_hook.py 83% -> target >95%).

Rules: no real sleep (time runs on a fake clock), no network (gh is fake), fixed clock. Each test notes which line/branch it was added for.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

import ci_wait_hook as bk  # noqa: E402


SIMDI = 1_790_000_000.0  # fixed instant (2026-09)
SHA = "c" * 40


@pytest.fixture(autouse=True)
def durum(tmp_path, monkeypatch):
    yol = tmp_path / "durum" / "bekleme.json"
    monkeypatch.setenv("BEKLEME_DURUM", str(yol))
    monkeypatch.setattr(bk, "simdi", lambda: SIMDI)
    return yol


_GERCEK = time


class SahteSaat:
    """Stands in for bk.time: sleep does not really wait, it advances monotonic."""

    def __init__(self, baslangic=0.0):
        self.t = baslangic
        self.uyunan = []

    def monotonic(self):
        return self.t

    def sleep(self, sn):
        self.uyunan.append(sn)
        self.t += sn

    time = staticmethod(_GERCEK.time)
    strftime = staticmethod(_GERCEK.strftime)
    gmtime = staticmethod(_GERCEK.gmtime)


# ---------------- pure helpers (small) ----------------


@pytest.mark.small
def test_simdi_real_clock(monkeypatch):
    monkeypatch.undo()  # undo the autouse patch
    assert abs(bk.simdi() - time.time()) < 5


@pytest.mark.small
@pytest.mark.parametrize(
    "girdi,beklenen",
    [
        ("c:/x", "C:/x"),  # line 150: lowercase drive letter
        ("d:\\a\\b\\", "D:/a/b"),
        ("/c/x/", "C:/x"),
        ("/d", "D:/"),
        ("D:/", "D:/"),
        ("a\\b", "a/b"),
    ],
)
def test_yol_normal(girdi, beklenen):
    assert bk.yol_normal(girdi) == beklenen


@pytest.mark.small
def test_coz_relative_and_absolute_path():
    assert bk._coz("D:/r", "sub") == "D:/r/sub"  # line 159
    assert bk._coz("D:/r", "E:/other") == "E:/other"
    assert bk._coz("D:/r", "/tmp/x") == "/tmp/x"


@pytest.mark.small
def test_push_request_repr():
    assert repr(bk.PushIstegi("D:/r", "origin", ["x"])) == "PushIstegi('D:/r', 'origin', ['x'])"  # line 141


@pytest.mark.small
@pytest.mark.parametrize(
    "komut,arac,dizin,remote,refspecler",
    [
        ('git push origin "x', "Bash", "D:/r", "origin", ['"x']),  # shlex ValueError -> split fallback (172-173)
        ("git --no-pager push origin x", "Bash", "D:/r", "origin", ["x"]),  # unknown leading option (202)
        ("git --git-dir /g push origin x", "Bash", "D:/r", "origin", ["x"]),  # leading option with a value
        ("git push -o ci.skip origin x", "Bash", "D:/r", "origin", ["x"]),  # VALUELI_SECENEK (212-213)
        ("cd && git push origin x", "Bash", "D:/r", "origin", ["x"]),  # cd without a target (241->243)
        ("; git push origin x", "Bash", "D:/r", "origin", ["x"]),  # empty part (177->179)
        ("git push origin +x", "Bash", "D:/r", "origin", ["+x"]),
        ("git.exe push origin x", "Bash", "D:/r", "origin", ["x"]),  # git.exe name (244)
        ("git --work-tree /w push origin x", "Bash", "D:/r", "origin", ["x"]),  # leading options with a value (199)
        ("git --namespace ns push origin x", "Bash", "D:/r", "origin", ["x"]),
        ("git -c a=b -C D:/z push origin x", "Bash", "D:/z", "origin", ["x"]),
        ("git push origin gece/X1", "Bash", "D:/r", "origin", ["gece/X1"]),  # uppercase X is not counted as a separator (167/176)
        ("git push origin X", "Bash", "D:/r", "origin", ["X"]),  # a token that is only 'X' is not counted as a separator (176)
        ("cd -P D:/other && git push origin x", "Bash", "D:/other", "origin", ["x"]),  # cd option is skipped (240)
    ],
)
def test_push_parsing_edge_cases(komut, arac, dizin, remote, refspecler):
    istekler = bk.push_istekleri(komut, arac, "D:/r")
    assert len(istekler) == 1
    assert (bk.yol_normal(istekler[0].dizin), istekler[0].remote, istekler[0].refspecler) == (dizin, remote, refspecler)


@pytest.mark.small
@pytest.mark.parametrize(
    "komut",
    [
        "FOO=bar",
        "timeout 60",
        "git",
        "git -C",
        "git push --mirror origin",
        "git push --all",
        "git push -d origin x",
        "git push --branches origin",
    ],
)
def test_non_push_edge_commands(komut):
    assert bk.push_istekleri(komut, "Bash", "D:/r") == []  # 194->205, 237, delete/mirror/all


@pytest.mark.small
@pytest.mark.parametrize("sarmalayici", ["time", "nice", "nohup", "env", "command", "builtin", "timeout 60", "FOO=1"])
def test_push_found_inside_wrapper_commands(sarmalayici):
    istekler = bk.push_istekleri(f"{sarmalayici} git push origin x", "Bash", "D:/r")
    assert [(i.remote, i.refspecler) for i in istekler] == [("origin", ["x"])]


@pytest.mark.small
@pytest.mark.parametrize("cd", ["cd", "Set-Location", "sl", "pushd", "chdir"])
def test_directory_change_aliases_are_followed(cd):
    istekler = bk.push_istekleri(f"{cd} D:/other && git push origin x", "Bash", "D:/r")
    assert [bk.yol_normal(i.dizin) for i in istekler] == ["D:/other"]


@pytest.mark.small
@pytest.mark.parametrize("secenek", ["-o", "--push-option", "--repo", "--receive-pack", "--exec"])
def test_option_value_is_not_mistaken_for_remote(secenek):
    istekler = bk.push_istekleri(f"git push {secenek} VALUE origin x", "Bash", "D:/r")
    assert [(i.remote, i.refspecler) for i in istekler] == [("origin", ["x"])]


@pytest.mark.small
def test_yol_normal_strips_trailing_slash():
    assert bk.yol_normal("a/b/") == "a/b" and bk.yol_normal("D:/") == "D:/"  # 151: len > 3 limit


@pytest.mark.small
def test_metinler_nested_list_and_dict():
    assert list(bk._metinler({"a": ["x", {"b": "y"}], "c": 3, "d": "z"})) == ["x", "y", "z"]  # 277-278


@pytest.mark.small
def test_epoch_fractional_and_plus_offset_format_and_dk():
    assert bk._epoch("2026-10-07T13:58:00.123+00:00") == bk._epoch("2026-10-07T13:58:00Z")
    assert bk.dk(-5) == "0.0" and bk.dk(90) == "1.5"


@pytest.mark.small
def test_blok_sayisi_other_prompt_resets():
    kayit = {"bloklar": {"a": {"prompt_id": "p1", "sayi": 3}}}
    assert bk._blok_sayisi(kayit, "a", "p1") == 3
    assert bk._blok_sayisi(kayit, "a", "p2") == 0
    assert bk._blok_sayisi({}, "a", "p1") == 0


# ---------------- state file and lock (medium: temp file, fake clock) ----------------


def test_durum_oku_broken_or_wrong_schema_returns_empty(durum):
    durum.parent.mkdir(parents=True)
    for icerik in ("{broken", '{"kayitlar": 5}', "[]", ""):
        durum.write_text(icerik, encoding="utf-8")
        assert bk.durum_oku() == {"kayitlar": []}  # 48->52


def test_lock_is_acquired_and_released(durum):
    with bk._Kilit() as k:
        assert k.alindi and os.path.exists(k.yol)
    assert not os.path.exists(k.yol)


def test_stale_lock_is_removed_and_acquired(durum, monkeypatch):
    saat = SahteSaat()
    monkeypatch.setattr(bk, "time", saat)
    durum.parent.mkdir(parents=True)
    kilit = Path(str(durum) + ".kilit")
    kilit.write_text("", encoding="utf-8")
    eski = time.time() - 60  # > 15 s: stale
    os.utime(kilit, (eski, eski))
    with bk._Kilit() as k:
        assert k.alindi
    assert saat.uyunan == []  # acquired without waiting (70-73)


def test_lock_not_acquired_continues_unlocked_after_3_s_and_foreign_lock_not_removed(durum, monkeypatch):
    saat = SahteSaat()
    monkeypatch.setattr(bk, "time", saat)
    durum.parent.mkdir(parents=True)
    kilit = Path(str(durum) + ".kilit")
    kilit.write_text("", encoding="utf-8")  # fresh lock of another process
    with bk._Kilit() as k:
        assert not k.alindi
    assert 3 <= saat.t < 3.2 and len(saat.uyunan) >= 50  # "waited" 3 s in 0.05 s steps (no real waiting)
    assert kilit.exists()  # a lock that was not acquired is not removed on release (81->exit)


def test_lock_remove_error_on_exit_is_swallowed(durum, monkeypatch):
    with bk._Kilit() as k:
        monkeypatch.setattr(bk.os, "remove", lambda _y: (_ for _ in ()).throw(OSError("missing")))
    assert k.alindi  # 84-85: the error did not leak out
    monkeypatch.undo()
    os.remove(k.yol)


def test_kayitlari_ekle_does_not_repeat_same_id_and_prunes_old(durum):
    taze = bk.yeni_kayit("s1", "o/r", "d", SHA, SIMDI - 10)
    eski = bk.yeni_kayit("s1", "o/r", "old", SHA, SIMDI - 24 * 3600 - 1)
    bk.kayitlari_ekle([taze, eski])
    bk.kayitlari_ekle([taze])
    assert [k["dal"] for k in bk.durum_oku()["kayitlar"]] == ["d"]


# ---------------- git subprocess ----------------


def test_git_calistir_returns_none_without_git_or_outside_repo(tmp_path, monkeypatch):
    assert (
        bk.git_calistir(str(tmp_path), "rev-parse", "HEAD") == bk.git_calistir(str(tmp_path), "rev-parse", "HEAD") is None
    )  # rc != 0
    monkeypatch.setenv("PATH", "")
    assert bk.git_calistir(str(tmp_path), "status") is None  # OSError (265-266)


def test_git_calistir_timeout_none(monkeypatch):
    def tasi(*_a, **_k):
        raise subprocess.TimeoutExpired("git", 5)

    monkeypatch.setattr(subprocess, "run", tasi)
    assert bk.git_calistir(".", "status") is None


def _git(d, *args):
    return subprocess.run(
        ["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()


def olay(komut, cwd, yanit=None, **ek):
    o = {
        "session_id": "s1",
        "tool_name": "Bash",
        "cwd": str(cwd),
        "tool_input": {"command": komut},
        "tool_response": {"stdout": "", "stderr": "", "interrupted": False} if yanit is None else yanit,
    }
    o.update(ek)
    return o


def test_remote_sec_config_precedence(depo):
    assert bk._remote_sec(str(depo), "gece/x") == "origin"
    _git(depo, "config", "branch.gece/x.remote", "upstream")
    assert bk._remote_sec(str(depo), "gece/x") == "upstream"
    _git(depo, "config", "remote.pushDefault", "default")
    assert bk._remote_sec(str(depo), "gece/x") == "default"
    _git(depo, "config", "branch.gece/x.pushRemote", "custom")
    assert bk._remote_sec(str(depo), "gece/x") == "custom"  # 283->282, 286
    assert bk._remote_sec(str(depo), "") == "default"  # no branch -> branch-specific keys are skipped


def test_head_refspec_resolves_to_current_branch_and_return_value(depo):
    sha = _git(depo, "rev-parse", "HEAD")
    _git(depo, "update-ref", "refs/remotes/origin/gece/x", sha)
    cikti = bk.post_isle(olay("git push origin HEAD", depo))  # 306
    assert cikti["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "push recorded (example/test gece/x @ " + sha[:7] in cikti["hookSpecificOutput"]["additionalContext"]
    assert bk.durum_oku()["kayitlar"][0]["dal"] == "gece/x"


@pytest.mark.parametrize("refspec", ["HEAD:refs/tags/v1", "missing-branch"])
def test_tag_target_and_missing_source_produce_no_record(depo, refspec):
    assert bk.post_isle(olay(f"git push origin {refspec}", depo)) is None  # 309, 312
    assert bk.durum_oku()["kayitlar"] == []


def test_push_by_direct_url_is_recorded_but_not_when_rejected(depo):
    url = "https://github.com/example/test.git"
    ret = {"stdout": "", "stderr": " ! [rejected] gece/x -> gece/x", "interrupted": False}
    assert bk.post_isle(olay(f"git push {url} gece/x", depo, ret)) is None  # 317-318
    assert bk.durum_oku()["kayitlar"] == []
    cikti = bk.post_isle(olay(f"git push {url} gece/x", depo))
    assert cikti is not None
    k = bk.durum_oku()["kayitlar"][0]
    assert (k["repo"], k["dal"], k["remote_url"]) == ("example/test", "gece/x", url)


def test_non_github_remote_produces_no_record(depo):
    _git(depo, "remote", "add", "gitlab", "https://gitlab.com/o/r.git")
    assert bk.post_isle(olay("git push gitlab gece/x", depo)) is None  # 298
    assert bk.durum_oku()["kayitlar"] == []


@pytest.mark.parametrize(
    "yanit,ek",
    [
        ({"exit_code": 1}, {}),
        ({"interrupted": True}, {}),
        (None, {"tool_input": {"command": "git push origin gece/x", "run_in_background": True}}),
    ],
)
def test_failed_interrupted_or_background_push_produces_no_record(depo, yanit, ek):
    # tracking ref is current: without these conditions the push WOULD BE RECORDED (this is what makes the test discriminating)
    _git(depo, "update-ref", "refs/remotes/origin/gece/x", _git(depo, "rev-parse", "HEAD"))
    o = olay("git push origin gece/x", depo, yanit)
    o.update(ek)
    assert bk.post_isle(o) is None  # 330 and early exit
    assert bk.durum_oku()["kayitlar"] == []
    assert (
        bk.post_isle(olay("git push origin gece/x", depo)) is not None
    )  # control: the same event is recorded without these conditions


@pytest.mark.parametrize(
    "isaret",
    ["! [rejected]", "! [remote rejected]", "error: failed to push", "fatal: unable to access"],
)
def test_every_rejection_marker_blocks_direct_url_push_record(depo, isaret):
    """On a named remote the tracking ref decides; on a push by URL the only evidence is the output text (317-318)."""
    url = "https://github.com/example/test.git"
    yanit = {"stdout": "", "stderr": f"... {isaret} ...", "interrupted": False}
    assert bk.post_isle(olay(f"git push {url} gece/x", depo, yanit)) is None
    assert bk.durum_oku()["kayitlar"] == []
    assert bk.post_isle(olay(f"git push {url} gece/x", depo)) is not None  # control: recorded without the rejection text


def test_plus_and_full_ref_targets_and_multi_refspec_summary(depo):
    sha = _git(depo, "rev-parse", "HEAD")
    for dal in ("a", "b"):
        _git(depo, "update-ref", f"refs/remotes/origin/{dal}", sha)
    cikti = bk.post_isle(olay("git push origin +HEAD:refs/heads/a HEAD:b", depo))  # '+' and 'refs/heads/' are stripped (302, 307)
    assert [k["dal"] for k in bk.durum_oku()["kayitlar"]] == ["a", "b"]
    assert cikti["hookSpecificOutput"]["additionalContext"].count(" @ ") == 2
    assert (
        f"example/test a @ {sha[:7]}, example/test b @ {sha[:7]}" in cikti["hookSpecificOutput"]["additionalContext"]
    )  # ', ' (338)


def test_yeni_kayit_schema_and_id_format():
    k = bk.yeni_kayit("s1", "o/r", "gece/x", SHA, SIMDI, "https://github.com/o/r", "D:/r")
    assert k == {
        "kimlik": f"s1|o/r|gece/x|{SHA}",
        "session_id": "s1",
        "repo": "o/r",
        "dal": "gece/x",
        "sha": SHA,
        "ts": SIMDI,
        "zaman": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(SIMDI)),
        "remote_url": "https://github.com/o/r",
        "dizin": "D:/r",
        "islendi": False,
        "bloklar": {},
        "beklenen": {},
    }


# ---------------- gh wrapper ----------------


@pytest.mark.skipif(os.name == "nt", reason="the fake gh is a sh script")
def test_gh_calistir_runs_BEKLEME_GH_script(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\necho "$@"\necho error >&2\nexit 3\n', encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("BEKLEME_GH", str(gh))
    assert bk.gh_calistir(["run", "list"], 5) == (3, "run list\n", "error\n")  # 351-356


@pytest.mark.small
@pytest.mark.parametrize(
    "tepki,mesaj",
    [
        (OSError("missing"), "gh failed to run: missing"),  # 381-382
        (subprocess.TimeoutExpired("gh", 15), "gh did not respond within 15 s"),
        ((1, "", ""), "gh exit 1"),
        ((0, "{not json", ""), "gh output is not JSON"),  # 387-388
        ((1, "output", ""), "output"),
        ((1, "", "x" * 300), "x" * 200),  # the error text is cut to 200 characters
        ((1, "", "  padded  \n"), "padded"),
    ],
)
def test_gh_json_error_classes_exact_message(monkeypatch, tepki, mesaj):
    def sahte(_a, _z):
        if isinstance(tepki, Exception):
            raise tepki
        return tepki

    monkeypatch.setattr(bk, "gh_calistir", sahte)
    with pytest.raises(bk.GhHatasi) as hata:
        bk._gh_json(["run", "list"])
    assert str(hata.value) == mesaj


@pytest.mark.small
def test_gh_json_empty_output_empty_list(monkeypatch):
    monkeypatch.setattr(bk, "gh_calistir", lambda _a, _z: (0, "", ""))
    assert bk._gh_json(["x"]) == []


@pytest.mark.small
@pytest.mark.parametrize(
    "gecmis,beklenen",
    [
        ([{"createdAt": "broken", "updatedAt": "x"}], 600),  # 411-412 (ValueError -> default)
        ([{"missing": 1}], 600),  # KeyError
        (None, 600),  # gh error
        (
            [{"createdAt": "2026-10-07T10:00:00Z", "updatedAt": f"2026-10-07T10:0{m}:00Z"} for m in (1, 2, 3, 4)],
            150 + 60,
        ),  # even count: mean of the middle two
    ],
)
def test_beklenen_sure_default_and_even_count_median(monkeypatch, gecmis, beklenen):
    def sahte(_a, _z):
        return (1, "", "bad") if gecmis is None else (0, json.dumps(gecmis), "")

    monkeypatch.setattr(bk, "gh_calistir", sahte)
    assert bk.beklenen_sure("o/r", "CI") == beklenen


# ---------------- Stop: multiple records, budget ----------------


def _kayit(dal):
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", dal, SHA, SIMDI - 30)])


def _kosu(id_, status="in_progress", conclusion=""):
    return {
        "databaseId": id_,
        "status": status,
        "conclusion": conclusion,
        "createdAt": "2026-10-07T13:58:00Z",
        "updatedAt": "2026-10-07T13:58:00Z",
        "workflowName": "CI",
        "headSha": SHA,
    }


def test_two_records_one_blocked_one_gh_error_reason_and_systemmessage_together(monkeypatch):
    _kayit("gece/a")
    _kayit("gece/b")

    def gh(args, _z):
        if "--workflow" in args:
            return 0, "[]", ""
        if args[args.index("--branch") + 1] == "gece/b":
            return 1, "", "HTTP 500"
        return 0, json.dumps([_kosu(11)]), ""

    monkeypatch.setattr(bk, "gh_calistir", gh)
    cikti = bk.stop_isle({"session_id": "s1", "prompt_id": "p"})
    assert cikti["decision"] == "block" and "CI 11 running" in cikti["reason"]
    assert "gece/b" in cikti["systemMessage"] and "NOT VERIFIED" in cikti["systemMessage"]
    kayitlar = {k["dal"]: k for k in bk.durum_oku()["kayitlar"]}
    assert kayitlar["gece/a"]["bloklar"]  # the change was applied only to the blocked record (515)
    assert not kayitlar["gece/b"]["bloklar"] and not kayitlar["gece/b"]["islendi"]


def test_stop_budget_exhausted_remaining_records_not_verified_message(monkeypatch):
    _kayit("gece/a")
    _kayit("gece/b")
    saat = SahteSaat()
    monkeypatch.setattr(bk, "time", saat)
    cagrilar = []

    def gh(args, _z):
        cagrilar.append(args)
        saat.t += 41  # the first query uses up the 40 s budget
        return 0, json.dumps([_kosu(5, "completed", "success")]), ""

    monkeypatch.setattr(bk, "gh_calistir", gh)
    cikti = bk.stop_isle({"session_id": "s1", "prompt_id": "p"})
    assert len(cagrilar) == 1  # gh was not called for the second record (499-500)
    assert "time budget exhausted" in cikti["systemMessage"]
    assert "CI 5 finished: success" in cikti["reason"]


@pytest.mark.parametrize(
    "durum_adi", ["queued", "in_progress", "waiting", "requested", "pending"]
)  # fixed list: must NOT be derived from the module
def test_every_active_status_counts_as_block(monkeypatch, durum_adi):
    _kayit("gece/a")
    monkeypatch.setattr(
        bk, "gh_calistir", lambda a, z: (0, "[]" if "--workflow" in a else json.dumps([_kosu(31, durum_adi)]), "")
    )
    cikti = bk.stop_isle({"session_id": "s1", "prompt_id": "p"})
    assert cikti["decision"] == "block" and "CI 31 running" in cikti["reason"]


@pytest.mark.parametrize("durum_adi", ["completed", "cancelled", "skipped"])
def test_inactive_status_does_not_count_as_block(monkeypatch, durum_adi):
    _kayit("gece/a")
    monkeypatch.setattr(bk, "gh_calistir", lambda a, z: (0, json.dumps([_kosu(32, durum_adi, "success")]), ""))
    cikti = bk.stop_isle({"session_id": "s1", "prompt_id": "p"})
    assert cikti == {
        "decision": "block",
        "reason": "CI 32 finished: success. Handle the result and report it.",
    }  # finished-report once


def test_multiple_finished_runs_joined_with_semicolon(monkeypatch):
    _kayit("gece/a")
    kosular = [_kosu(41, "completed", "success"), _kosu(42, "completed", "")]
    monkeypatch.setattr(bk, "gh_calistir", lambda a, z: (0, json.dumps(kosular), ""))
    cikti = bk.stop_isle({"session_id": "s1", "prompt_id": "p"})
    assert cikti["reason"] == "CI 41 finished: success; CI 42 finished: unknown. Handle the result and report it."  # 480


def test_three_hour_limit_inclusive_one_second_beyond_excluded(monkeypatch):
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "exact", SHA, SIMDI - 3 * 3600)])
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "over", SHA, SIMDI - 3 * 3600 - 1)])
    dallar = []

    def gh(a, z):
        dallar.append(a[a.index("--branch") + 1] if "--branch" in a else None)
        return 0, "[]", ""

    monkeypatch.setattr(bk, "gh_calistir", gh)
    bk.stop_isle({"session_id": "s1", "prompt_id": "p"})
    assert dallar == ["exact"]


def test_record_lifetime_limit_inclusive_one_second_beyond_pruned():
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "exact", SHA, SIMDI - 24 * 3600)])
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "over", SHA, SIMDI - 24 * 3600 - 1)])
    assert [k["dal"] for k in bk.durum_oku()["kayitlar"]] == ["exact"]


def test_run_visibility_grace_limit(monkeypatch):
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "gece/a", SHA, SIMDI - 120 + 1)])
    monkeypatch.setattr(bk, "gh_calistir", lambda a, z: (0, "[]", ""))
    assert bk.stop_isle({"session_id": "s1", "prompt_id": "p"})["decision"] == "block"  # 119 s: still wait
    monkeypatch.setattr(bk, "simdi", lambda: SIMDI + 1)  # 120 s: grace period over
    assert bk.stop_isle({"session_id": "s1", "prompt_id": "p2"}) is None


@pytest.mark.small
def test_timeout_and_budget_constants_contract():
    """The constants are a documented contract (module docstring + settings.example.json: Stop timeout 90 s > budget 40 + gh 15)."""
    assert (bk.GH_ZAMAN_ASIMI, bk.STOP_BUTCESI, bk.GIT_ZAMAN_ASIMI, bk.BLOK_SINIRI) == (15, 40, 5, 8)
    assert bk.STOP_BUTCESI + bk.GH_ZAMAN_ASIMI < 90


@pytest.mark.skipif(os.name == "nt", reason="the fake gh is a sh script")
def test_gh_calistir_invalid_utf8_does_not_crash(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nprintf 'a\\377b'\nprintf 'c\\377d' >&2\n", encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("BEKLEME_GH", str(gh))
    rc, cikti, hata = bk.gh_calistir([], 5)
    assert (rc, cikti, hata) == (0, "a\ufffdb", "c\ufffdd")  # stdout and stderr: errors="replace" (356)


def test_durum_yolu_default_under_home_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("BEKLEME_DURUM")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path(bk.durum_yolu()) == tmp_path / ".claude" / "agent-state" / "bekleme.json"


# ---------------- main() (stdin/stdout contract, in-process) ----------------


class _Girdi:
    def __init__(self, metin):
        self.buffer = SimpleNamespace(read=lambda: metin.encode("utf-8"))


@pytest.mark.parametrize("mod", ["post", "stop"])
def test_main_valid_event_returns_zero_and_silent(monkeypatch, capsys, mod):
    monkeypatch.setattr(sys, "stdin", _Girdi(json.dumps({"session_id": "s1", "tool_input": {"command": "ls"}})))
    assert bk.main(["ci_wait_hook.py", mod]) == 0  # 534-542
    assert capsys.readouterr().out == ""


def test_main_stop_block_json_written_as_ascii(monkeypatch, capsys):
    _kayit("gece/a")
    monkeypatch.setattr(bk, "gh_calistir", lambda a, z: (0, json.dumps([_kosu(21)]) if "--workflow" not in a else "[]", ""))
    monkeypatch.setattr(sys, "stdin", _Girdi(json.dumps({"session_id": "s1", "prompt_id": "p"})))
    assert bk.main(["ci_wait_hook.py", "stop"]) == 0
    ham = capsys.readouterr().out
    assert ham.isascii()  # ensure_ascii=True: independent of the Windows console code page
    assert json.loads(ham)["decision"] == "block"


@pytest.mark.small
@pytest.mark.parametrize("argv", [["x"], ["x", "unknown"]])
def test_main_invalid_mode_fail_open_stderr(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "stdin", _Girdi("{}"))
    assert bk.main(argv) == 0
    gorulen = capsys.readouterr()
    assert gorulen.out == "" and "ci_wait_hook:" in gorulen.err


# ---------------- gaps found by mutation testing: full text, fixed literals, cache, limits ----------------


class IzliGh:
    """Fake gh that records its arguments: the `--workflow` history query and `run list` are counted separately."""

    def __init__(self, kosular=None, gecmis=None, dal_hata=None):
        self.kosular, self.gecmis, self.dal_hata = kosular or [], gecmis or [], dal_hata or {}
        self.cagrilar = []

    def __call__(self, args, _zaman_asimi):
        self.cagrilar.append(list(args))
        if "--workflow" in args:
            return 0, json.dumps(self.gecmis), ""
        dal = args[args.index("--branch") + 1]
        if dal in self.dal_hata:
            return 1, "", self.dal_hata[dal]
        return 0, json.dumps(self.kosular.get(dal, []) if isinstance(self.kosular, dict) else self.kosular), ""


def stop_et(monkeypatch, gh, prompt_id="p1", simdi=None):
    monkeypatch.setattr(bk, "gh_calistir", gh)
    if simdi is not None:
        monkeypatch.setattr(bk, "simdi", lambda: simdi)
    return bk.stop_isle({"session_id": "s1", "prompt_id": prompt_id})


def kayit_yas(dal, yas_sn=30):
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", dal, SHA, SIMDI - yas_sn)])


def test_gh_argument_lists_exact(monkeypatch):
    kayit_yas("gece/a")
    gh = IzliGh([_kosu(7)])
    stop_et(monkeypatch, gh)
    assert gh.cagrilar[0] == [
        "run", "list", "-R", "o/r", "--branch", "gece/a", "--json", "databaseId,status,conclusion,createdAt,updatedAt,workflowName,headSha", "-L", "20",
    ]  # fmt: skip
    assert gh.cagrilar[1] == [
        "run",
        "list",
        "-R",
        "o/r",
        "--workflow",
        "CI",
        "--status",
        "completed",
        "-L",
        "5",
        "--json",
        "createdAt,updatedAt",
    ]


def test_beklenen_sure_cached_on_record_history_queried_once(monkeypatch):
    kayit_yas("gece/a")
    gh = IzliGh([_kosu(7)])
    ilk = stop_et(monkeypatch, gh)
    ikinci = stop_et(monkeypatch, gh)
    assert "expected 10.0 min" in ilk["reason"] and "expected 10.0 min" in ikinci["reason"]
    assert sum("--workflow" in c for c in gh.cagrilar) == 1  # not asked again on the second turn (467)
    kayit = bk.durum_oku()["kayitlar"][0]
    assert kayit["beklenen"] == {"CI": 600} and kayit["bloklar"] == {"CI 7": {"prompt_id": "p1", "sayi": 2}}


def test_oldest_of_multiple_active_runs_is_chosen(monkeypatch):
    kayit_yas("gece/a")
    yeni, eski = _kosu(1), _kosu(2)
    yeni["createdAt"], eski["createdAt"] = "2026-10-07T13:59:00Z", "2026-10-07T13:50:00Z"
    cikti = stop_et(monkeypatch, IzliGh([yeni, eski]))
    assert "CI 2 running" in cikti["reason"] and "CI 1" not in cikti["reason"]  # 463


def test_timeout_text_exact(monkeypatch):
    simdi = bk._epoch("2026-10-07T14:00:00Z")
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "gece/x", SHA, simdi - 700)])
    kosu = _kosu(77)
    kosu["createdAt"] = "2026-10-07T13:50:00Z"
    gecmis = [
        {"createdAt": "2026-10-06T10:00:00Z", "updatedAt": f"2026-10-06T10:{m:02d}:00Z"} for m in (5, 5, 5, 5, 5)
    ]  # median 300 + 60 s
    cikti = stop_et(monkeypatch, IzliGh([kosu], gecmis), simdi=simdi)
    assert cikti == {
        "decision": "block",
        "reason": (
            "TIME EXCEEDED — CI 77 running (elapsed 10.0 min, expected 6.0 min). Do not end the turn: wait with `gh run watch 77 --exit-status`, then handle the result. "
            "Send the user a PushNotification: 'CI CI (o/r gece/x) exceeded the estimate by 4.0 min: <reason>'"
        ),
    }


def test_gh_error_system_message_exact(monkeypatch):
    kayit_yas("gece/a")
    cikti = stop_et(monkeypatch, IzliGh(dal_hata={"gece/a": "HTTP 502"}))
    assert cikti == {
        "systemMessage": "wait hook: could not read gh (o/r gece/a: HTTP 502) — CI status NOT VERIFIED, turn end allowed."
    }


def test_block_limit_message_exact_and_counter_key(monkeypatch):
    kayit_yas("gece/a")
    gh = IzliGh([_kosu(7)])
    for _ in range(8):
        assert stop_et(monkeypatch, gh)["decision"] == "block"
    assert stop_et(monkeypatch, gh) == {
        "systemMessage": "wait hook: CI 7 reached the limit of 8 consecutive blocks — turn end allowed; handle the CI result later."
    }
    assert bk.durum_oku()["kayitlar"][0]["bloklar"]["CI 7"] == {"prompt_id": "p1", "sayi": 8}


def test_run_not_visible_text_exact_then_no_ci_marker(monkeypatch):
    kayit_yas("gece/a", 30)
    ilk = stop_et(monkeypatch, IzliGh([]))
    assert ilk == {
        "decision": "block",
        "reason": (
            "CI run not visible yet (o/r gece/a @ ccccccc, pushed 30 s ago). Do not end the turn: "
            "find the run with `gh run list -R o/r --branch gece/a -L 5`, wait with `gh run watch <id> --exit-status`, then handle the result."
        ),
    }
    assert "waiting ccccccc" in bk.durum_oku()["kayitlar"][0]["bloklar"]
    assert stop_et(monkeypatch, IzliGh([]), simdi=SIMDI + 200) is None
    kayit = bk.durum_oku()["kayitlar"][0]
    assert kayit["islendi"] is True and kayit["ci_yok"] is True  # 461


def test_multiple_records_reason_lines_and_messages_with_separate_separators(monkeypatch):
    for dal in ("gece/a", "gece/b", "gece/c", "gece/d"):
        kayit_yas(dal)
    kosular = {"gece/a": [_kosu(1)], "gece/b": [_kosu(2)]}
    gh = IzliGh(kosular, dal_hata={"gece/c": "E1", "gece/d": "E2"})
    cikti = stop_et(monkeypatch, gh)
    nedenler = cikti["reason"].split("\n")
    assert len(nedenler) == 2 and nedenler[0].startswith("CI 1 running") and nedenler[1].startswith("CI 2 running")  # 527
    assert cikti["systemMessage"] == (
        "wait hook: could not read gh (o/r gece/c: E1) — CI status NOT VERIFIED, turn end allowed."
        " | wait hook: could not read gh (o/r gece/d: E2) — CI status NOT VERIFIED, turn end allowed."
    )  # 529


def test_budget_message_exact(monkeypatch):
    kayit_yas("gece/a")
    kayit_yas("gece/b")
    saat = SahteSaat()
    monkeypatch.setattr(bk, "time", saat)

    def gh(args, _z):
        saat.t += 41
        return 0, json.dumps([_kosu(5, "completed", "success")]), ""

    cikti = stop_et(monkeypatch, gh)
    assert cikti["systemMessage"] == "wait hook: time budget exhausted (o/r gece/b) — CI status NOT VERIFIED."  # 499


def test_post_additional_context_text_exact(depo):
    sha = _git(depo, "rev-parse", "HEAD")
    _git(depo, "update-ref", "refs/remotes/origin/gece/x", sha)
    assert bk.post_isle(olay("git push origin gece/x", depo)) == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"wait hook: push recorded (example/test gece/x @ {sha[:7]}). Do not end the turn before CI finishes.",
        }
    }


def test_url_target_tag_ref_produces_no_record(depo):
    url = "https://github.com/example/test.git"
    assert bk.post_isle(olay(f"git push {url} HEAD:refs/tags/v1", depo)) is None  # 308: a target starting with refs/ is skipped
    assert bk.durum_oku()["kayitlar"] == []


def test_state_file_format_utf8_and_indented(durum):
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "gece/é", SHA, SIMDI - 10)])
    metin = durum.read_text(encoding="utf-8")
    assert "gece/é" in metin and metin.startswith('{\n "kayitlar": [\n  {\n   "kimlik"')  # 92: ensure_ascii=False, indent=1


@pytest.mark.parametrize("yas,alinir", [(14.5, False), (15.5, True)])
def test_lock_staleness_limit_15_s(durum, monkeypatch, yas, alinir):
    saat = SahteSaat()
    monkeypatch.setattr(bk, "time", saat)
    durum.parent.mkdir(parents=True)
    kilit = Path(str(durum) + ".kilit")
    kilit.write_text("", encoding="utf-8")
    eski = time.time() - yas
    os.utime(kilit, (eski, eski))
    with bk._Kilit() as k:
        assert k.alindi is alinir  # 72


@pytest.mark.small
def test_main_reads_invalid_bytes_with_replacement_and_stderr_format(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=SimpleNamespace(read=lambda: b'{"x": "\xff", "session_id": "s1"}')))
    assert bk.main(["ci_wait_hook.py", "unknown"]) == 0
    gorulen = capsys.readouterr()
    assert (
        gorulen.err == "ci_wait_hook: KeyError('unknown')\n"
    )  # JSON was read (decode did not blow up), no such mode -> KeyError; 541
    assert gorulen.out == ""


@pytest.mark.parametrize("mod", ["post", "stop"])
def test_main_valid_mode_stderr_empty(monkeypatch, capsys, mod):
    monkeypatch.setattr(sys, "stdin", _Girdi(json.dumps({"session_id": "s1"})))
    assert bk.main(["ci_wait_hook.py", mod]) == 0
    assert capsys.readouterr().err == ""  # 537: valid mode names do not raise KeyError


def test_main_stop_prints_block_even_with_invalid_utf8_event(monkeypatch, capsys):
    kayit_yas("gece/a")
    monkeypatch.setattr(bk, "gh_calistir", IzliGh([_kosu(21)]))
    ham = b'{"junk": "\xff", "session_id": "s1", "prompt_id": "p"}'
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=SimpleNamespace(read=lambda: ham)))
    assert bk.main(["ci_wait_hook.py", "stop"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"  # 536: errors="replace"


@pytest.mark.skipif(os.name == "nt", reason="the fake gh is a sh script")
def test_subprocess_stop_prints_block_json(tmp_path, durum):
    """Real script path with python -I -S (__main__): the block JSON is written to stdout as ASCII (545)."""
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/bin/sh\ncase \"$*\" in\n *--workflow*) echo '[]';;\n"
        f' *) echo \'[{{"databaseId":9,"status":"in_progress","conclusion":"","createdAt":"2026-10-07T13:58:00Z","updatedAt":"2026-10-07T13:58:00Z","workflowName":"CI","headSha":"{SHA}"}}]\';;\nesac\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    bk.kayitlari_ekle([bk.yeni_kayit("s1", "o/r", "gece/a", SHA, time.time() - 30)])
    ortam = {"BEKLEME_DURUM": str(durum), "BEKLEME_GH": str(gh), "PATH": ""}
    cikti = subprocess.run(
        [sys.executable, "-I", "-S", str(HOOKS / "ci_wait_hook.py"), "stop"],
        input=json.dumps({"session_id": "s1", "prompt_id": "p"}).encode("utf-8"),
        env=ortam,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert cikti.returncode == 0 and cikti.stderr == b""
    karar = json.loads(cikti.stdout.decode("ascii"))
    assert karar["decision"] == "block" and "CI 9 running" in karar["reason"]


@pytest.mark.small
def test_git_calistir_invalid_utf8_output_read_with_replacement(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"branch-\xff\n"))
    assert bk.git_calistir(".", "branch") == "branch-\ufffd"  # 267: errors="replace" + strip


@pytest.mark.small
@pytest.mark.parametrize("olay_alani,beklenen", [({"tool_name": "PowerShell"}, "PowerShell"), ({}, "Bash")])
def test_post_isle_passes_tool_name_to_push_parser(monkeypatch, olay_alani, beklenen):
    gorulen = []
    monkeypatch.setattr(bk, "push_istekleri", lambda komut, arac, cwd: gorulen.append((komut, arac, cwd)) or [])
    olay = {"session_id": "s1", "cwd": "D:/r", "tool_input": {"command": "git push origin x"}, **olay_alani}
    assert bk.post_isle(olay) is None
    assert gorulen == [("git push origin x", beklenen, "D:/r")]  # 333
