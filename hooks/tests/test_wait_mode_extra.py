"""ADDED: wait_mode.py coverage gaps (old-flag cleanup, empty session id, Turkish letter folding). No real sleep; age is set via os.utime."""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

import wait_mode  # noqa: E402


@pytest.fixture(autouse=True)
def bayrak_dizini(tmp_path, monkeypatch):
    monkeypatch.setenv("BEKLE_DIZIN", str(tmp_path / "bekle"))
    return tmp_path / "bekle"


@pytest.mark.small
@pytest.mark.parametrize(
    "ham,beklenen",
    [
        ("Hazır MISIN İyi", "hazir misin iyi"),  # dotless i and capital dotted I
        ("  Selam,   dünya!! ", "selam dunya"),
        ("", ""),
        ("...", ""),
    ],
)
def test_normalize(ham, beklenen):
    assert wait_mode.normallestir(ham) == beklenen


@pytest.mark.small
def test_is_wait_none_is_false():
    assert wait_mode.bekle_mi(None) is False


@pytest.mark.small
@pytest.mark.parametrize("mesaj", ["selamselam", "beklebekle", "merhabaselam"])
def test_wait_phrases_run_together_are_not_wait(mesaj):
    # Boundary check: a phrase counts only if it ends at a space/end of string (kills the "kalan.startswith(ifade)" mutation).
    assert wait_mode.bekle_mi(mesaj) is False


@pytest.mark.small
@pytest.mark.parametrize("sid", ["", "../..", "///"])
def test_empty_session_id_gives_no_path(sid):
    assert wait_mode.bayrak_yolu(sid) is None  # 78: empty id / id that is still empty after cleaning


@pytest.mark.parametrize("sid", ["", "../.."])
def test_empty_id_prompt_and_pre_are_silent(bayrak_dizini, sid):
    assert wait_mode.prompt_isle({"session_id": sid, "prompt": "selam"}) is None
    assert wait_mode.pre_isle({"session_id": sid, "tool_name": "Bash"}) is None
    assert not bayrak_dizini.exists()


def test_task_message_without_flag_is_silent(bayrak_dizini):
    assert wait_mode.prompt_isle({"session_id": "new", "prompt": "devam"}) is None  # 80->82: no flag to clear


def test_old_flags_removed_fresh_kept(bayrak_dizini):
    bayrak_dizini.mkdir()
    eski, taze = bayrak_dizini / "old", bayrak_dizini / "fresh"
    for f in (eski, taze):
        f.write_text("1", encoding="ascii")
    gecmis = time.time() - 2 * 24 * 3600 - 10  # 2-day limit: fixed literal (not derived from the module constant)
    os.utime(eski, (gecmis, gecmis))
    assert wait_mode.prompt_isle({"session_id": "new", "prompt": "selam"}) is not None
    assert not eski.exists() and taze.exists() and (bayrak_dizini / "new").exists()  # 67-72


def test_cleanup_swallows_error_on_unremovable_file(bayrak_dizini, monkeypatch):
    bayrak_dizini.mkdir()
    (bayrak_dizini / "x").write_text("1", encoding="ascii")
    monkeypatch.setattr(wait_mode.os.path, "getmtime", lambda _y: (_ for _ in ()).throw(OSError("missing")))
    wait_mode._eski_bayraklari_temizle(str(bayrak_dizini), time.time())  # 71-72: OSError does not leak out
    assert (bayrak_dizini / "x").exists()


# ---------------- gaps revealed by the mutation run ----------------


@pytest.mark.small
@pytest.mark.parametrize("mesaj", ["selamlar", "Merhabalar!", "selamlar merhabalar hazır ol"])
def test_plural_greeting_phrases_are_wait_mode(mesaj):
    assert wait_mode.bekle_mi(mesaj) is True


@pytest.mark.small
def test_context_and_deny_texts_exact():
    assert (
        wait_mode.BAGLAM == "WAIT mode (hook): the message is only an opening/greeting/wait. Do not use tools; reply in one line."
    )
    assert wait_mode.prompt_isle({"session_id": "x"}) is None  # no prompt -> no flag set


def test_prompt_context_output_exact(bayrak_dizini):
    assert wait_mode.prompt_isle({"session_id": "s1", "prompt": "selam"}) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "WAIT mode (hook): the message is only an opening/greeting/wait. Do not use tools; reply in one line.",
        }
    }


@pytest.mark.small
@pytest.mark.parametrize("sid,temiz", [("a-b_c", "a-b_c"), ("a.b/c", "abc"), ("ŞÖ1", "ŞÖ1")])
def test_session_id_only_letters_digits_dash_underscore(bayrak_dizini, sid, temiz):
    assert Path(wait_mode.bayrak_yolu(sid)).name == temiz


def test_flag_dir_default_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("BEKLE_DIZIN")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path(wait_mode.bayrak_dizini()) == tmp_path / ".claude" / "agent-state" / "bekle"


def test_old_flag_limit_two_days(bayrak_dizini):
    bayrak_dizini.mkdir()
    simdi = time.time()
    for ad, yas in (("within_limit", 2 * 24 * 3600 - 100), ("beyond_limit", 2 * 24 * 3600 + 100)):
        yol = bayrak_dizini / ad
        yol.write_text("1", encoding="ascii")
        os.utime(yol, (simdi - yas, simdi - yas))
    wait_mode._eski_bayraklari_temizle(str(bayrak_dizini), simdi)
    assert (bayrak_dizini / "within_limit").exists() and not (bayrak_dizini / "beyond_limit").exists()


class _HamGirdi:
    def __init__(self, veri):
        self.buffer = SimpleNamespace(read=lambda: veri)


def test_main_replaces_invalid_utf8_bytes_and_error_format(monkeypatch, capsys, bayrak_dizini):
    monkeypatch.setattr(sys, "stdin", _HamGirdi(b'{"x": "\xff", "session_id": "s1", "prompt": "selam"}'))
    assert wait_mode.main(["wait_mode.py", "prompt"]) == 0
    assert (bayrak_dizini / "s1").exists()  # decode did not blow up: errors="replace"
    capsys.readouterr()
    monkeypatch.setattr(sys, "stdin", _HamGirdi(b"{}"))
    assert wait_mode.main(["wait_mode.py", "unknown"]) == 0
    gorulen = capsys.readouterr()
    assert gorulen.out == "" and gorulen.err == "wait_mode: KeyError('unknown')\n"
