"""WAIT hook tests (UserPromptSubmit + PreToolUse). No gh/ag; flag directory is temporary."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

import wait_mode  # noqa: E402


DENY_NEDENI = "WAIT mode: do not use tools until a task is given; reply in one line."


@pytest.fixture(autouse=True)
def bayrak_dizini(tmp_path, monkeypatch):
    monkeypatch.setenv("BEKLE_DIZIN", str(tmp_path / "bekle"))
    return tmp_path / "bekle"


@pytest.mark.small
@pytest.mark.parametrize(
    "mesaj",
    [
        "oturum açılıyor",
        "Oturum açılıyor.",
        "  SELAM  ",
        "Merhaba!",
        "bekle",
        "Hazır mısın?",
        "HAZIR MISIN",
        "hazır ol",
        "Selam, oturum açılıyor",
        "oturum aciliyor",
        "Oturum açıldı",
    ],
)
def test_opening_greeting_is_wait_mode(mesaj):
    assert wait_mode.bekle_mi(mesaj) is True


@pytest.mark.small
@pytest.mark.parametrize(
    "mesaj",
    [
        "başla",
        "devam",
        "devam et",
        "talimatı oku ve başla",
        "bekle, şunu yap",
        "selam, testleri koş",
        r"D:\SystemTemp içindeki bir dosyayı listele",
        "",
        "oturum açılıyor ve README'yi oku",
        "beklemeden başla",
        "selam claude, PR'ı incele",
    ],
)
def test_task_bearing_message_is_not_wait(mesaj):
    assert wait_mode.bekle_mi(mesaj) is False


def _calistir(mod, olay, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Girdi(json.dumps(olay)))
    rc = wait_mode.main(["wait_mode.py", mod])
    cikti = capsys.readouterr().out.strip()
    return rc, (json.loads(cikti) if cikti else None)


class _Girdi:
    def __init__(self, metin):
        self.buffer = _Bayt(metin.encode("utf-8"))


class _Bayt:
    def __init__(self, veri):
        self._veri = veri

    def read(self):
        return self._veri


def test_greeting_sets_flag_next_task_message_clears_it(monkeypatch, capsys, bayrak_dizini):
    rc, cikti = _calistir("prompt", {"session_id": "s1", "prompt": "oturum açılıyor"}, monkeypatch, capsys)
    assert rc == 0
    assert (bayrak_dizini / "s1").exists()
    assert "WAIT" in cikti["hookSpecificOutput"]["additionalContext"]
    assert cikti["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    rc, cikti = _calistir("prompt", {"session_id": "s1", "prompt": "devam"}, monkeypatch, capsys)
    assert rc == 0 and cikti is None
    assert not (bayrak_dizini / "s1").exists()


def test_every_tool_denied_while_flag_set(monkeypatch, capsys):
    _calistir("prompt", {"session_id": "s2", "prompt": "selam"}, monkeypatch, capsys)
    for arac in ("Bash", "Read", "ToolSearch", "mcp__x__y"):
        rc, cikti = _calistir("pre", {"session_id": "s2", "tool_name": arac, "tool_input": {}}, monkeypatch, capsys)
        assert rc == 0
        hso = cikti["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert hso["permissionDecision"] == "deny"
        assert hso["permissionDecisionReason"] == DENY_NEDENI


def test_allowed_without_flag_and_in_other_session(monkeypatch, capsys):
    _calistir("prompt", {"session_id": "s3", "prompt": "merhaba"}, monkeypatch, capsys)
    rc, cikti = _calistir("pre", {"session_id": "other", "tool_name": "Bash", "tool_input": {}}, monkeypatch, capsys)
    assert rc == 0 and cikti is None
    rc, cikti = _calistir("pre", {"session_id": "s4", "tool_name": "Bash", "tool_input": {}}, monkeypatch, capsys)
    assert rc == 0 and cikti is None


@pytest.mark.small
def test_malformed_input_fail_open(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Girdi("{bozuk"))
    assert wait_mode.main(["wait_mode.py", "pre"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_session_id_cannot_escape_path(monkeypatch, capsys, bayrak_dizini):
    _calistir("prompt", {"session_id": "../../escape", "prompt": "selam"}, monkeypatch, capsys)
    assert not (bayrak_dizini.parent.parent / "escape").exists()


def test_runs_as_subprocess_and_prints_deny(tmp_path):
    ortam = {"BEKLE_DIZIN": str(tmp_path / "b"), "SYSTEMROOT": "C:\\Windows", "PATH": ""}
    betik = str(HOOKS / "wait_mode.py")
    istem = json.dumps({"session_id": "e2e", "prompt": "hazır ol"}).encode("utf-8")
    subprocess.run([sys.executable, "-I", "-S", betik, "prompt"], input=istem, env=ortam, check=True, timeout=20)
    arac = json.dumps({"session_id": "e2e", "tool_name": "Bash", "tool_input": {"command": "ls"}}).encode("utf-8")
    out = subprocess.run(
        [sys.executable, "-I", "-S", betik, "pre"], input=arac, env=ortam, capture_output=True, check=False, timeout=20
    )
    assert out.returncode == 0
    karar = json.loads(out.stdout.decode("ascii"))
    assert karar["hookSpecificOutput"]["permissionDecisionReason"] == DENY_NEDENI
