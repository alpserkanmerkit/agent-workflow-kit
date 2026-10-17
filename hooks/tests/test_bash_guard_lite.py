"""Tests for bash-guard-lite.sh.

hooks/bash-guard-lite-test.py is NOT collected by pytest (its file name does not match the test_*.py / *_test.py patterns and it has no test_ function);
it keeps working as a script. Here its 10 scenarios (CASES) are imported directly and turned into a parametrized test; extra scenarios are ADDED.
Every call spawns a real `bash` subprocess -> medium (filesystem/subprocess, no network).
"""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

KANCALAR = Path(__file__).resolve().parent.parent
HOOK = str(KANCALAR / "bash-guard-lite.sh")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not found")


def _betik_modulu():
    spec = importlib.util.spec_from_file_location("bash_guard_lite_betigi", KANCALAR / "bash-guard-lite-test.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _betik_senaryolari():
    return _betik_modulu().CASES


def karar(arac, komut, arka_plan=False, girinti=None):
    olay = {
        "hook_event_name": "PreToolUse",
        "tool_name": arac,
        "tool_input": {"command": komut, "run_in_background": arka_plan},
    }
    cikti = subprocess.run(
        [BASH, HOOK], input=json.dumps(olay, indent=girinti), capture_output=True, text=True, check=False, timeout=10
    )
    assert cikti.returncode == 0, cikti.stderr  # the hook never returns an error code
    return "deny" if '"permissionDecision":"deny"' in cikti.stdout else "allow", cikti.stdout


@pytest.mark.parametrize(
    "beklenen,arac,komut,arka_plan",
    _betik_senaryolari(),
    ids=[f"{i}-{c[0]}-{c[1]}" for i, c in enumerate(_betik_senaryolari(), 1)],
)
def test_script_case(beklenen, arac, komut, arka_plan):
    """bash-guard-lite-test.py CASES: 5 must be blocked, 5 must pass."""
    sonuc, _ = karar(arac, komut, arka_plan)
    assert sonuc == beklenen


def test_deny_output_is_valid_json_with_reason():
    sonuc, cikti = karar("Bash", "find / -name x")
    assert sonuc == "deny"
    govde = json.loads(cikti)["hookSpecificOutput"]
    assert govde["hookEventName"] == "PreToolUse"
    assert govde["permissionDecision"] == "deny"
    assert govde["permissionDecisionReason"].startswith("bash-guard-lite: ")


def test_allow_output_is_empty():
    assert karar("Bash", "npm test") == ("allow", "")


@pytest.mark.parametrize(
    "komut,arka_plan,beklenen",
    [
        # (a) zombie: all three conditions (loop + sleep + background) must hold together
        ("until [ -f d ]; do sleep 5; done", False, "allow"),  # foreground: not blocked
        ("until [ -f d ]; do sleep 5; done", True, "deny"),  # run_in_background:true
        ("nohup sh -c 'while true; do sleep 1; done'", False, "deny"),  # nohup
        ("while true; do echo x; done", True, "allow"),  # no sleep
        ("sleep 5", True, "allow"),  # no loop
        ("for i in 1 2; do sleep 1; done &", False, "deny"),  # trailing &
        ("WHILE true; DO SLEEP 3; DONE &", False, "deny"),  # upper/lower case (nocasematch)
        # (b) find on a broad root: -maxdepth > 3 or missing
        ("find / -maxdepth 3 -name x", False, "allow"),
        ("find / -maxdepth 4 -name x", False, "deny"),
        ("find ~ -name x", False, "deny"),
        ("find ~/ -maxdepth 2 -name x", False, "allow"),
        ("find $HOME -name x", False, "deny"),
        ("find /c/Users/example -name x", False, "deny"),
        ("find ./src -name x", False, "allow"),  # narrow root
        # (a) each loop keyword alone is enough (mutation check: removing one must be noticed)
        ("while x; sleep 1", True, "deny"),
        ("until x; sleep 1", True, "deny"),
        ("for x in a; sleep 1", True, "deny"),
        ("do sleep 1", True, "deny"),
        # (b) root forms: drive root, Windows path, environment variable, AppData
        ("find /d -name x", False, "deny"),
        ("find /c/ -name x", False, "deny"),
        ("find C:/ -name x", False, "deny"),
        (r"find C:\ -name x", False, "deny"),
        ("find $env:USERPROFILE -name x", False, "deny"),
        ("find /c/Users/example/AppData/Local -name x", False, "deny"),
        (r"find C:\Users\example\AppData\Local -name x", False, "deny"),
        # (b) separators before find (including forms without spaces)
        ("ls && find / -name x", False, "deny"),
        ("ls;find / -name x", False, "deny"),
        ("ls&&find / -name x", False, "deny"),
        ("ls|find / -name x", False, "deny"),
        ("(find / -name x)", False, "deny"),
        ("find / \necho hi", False, "deny"),
        ("find /\necho hi", False, "deny"),
    ],
)
def test_extra_cases(komut, arka_plan, beklenen):
    sonuc, _ = karar("Bash", komut, arka_plan)
    assert sonuc == beklenen


def test_script_main_summary_10_10_passes(capsys):
    """bash-guard-lite-test.py also runs as a script: prints SUMMARY 10/10 and 5 latency measurements."""
    _betik_modulu().main()
    cikti = capsys.readouterr().out
    assert "SUMMARY 10/10" in cikti and "FAIL" not in cikti
    assert cikti.count("PASS") == 10


@pytest.mark.parametrize(
    "arac,komut,arka_plan,beklenen",
    [
        ("Bash", "find / -name x", False, "deny"),
        ("Bash", "until [ -f d ]; do sleep 5; done", True, "deny"),
        ("PowerShell", "Start-Process pwsh -ArgumentList 'while ($true) { Start-Sleep 5 }'", False, "deny"),
        ("Bash", "npm test", False, "allow"),
    ],
)
def test_multiline_json_input_is_also_read(arac, komut, arka_plan, beklenen):
    """read -d '' reads all of stdin: indented (multi-line) JSON gives the same verdict (reading only the first line would make everything 'allow')."""
    assert karar(arac, komut, arka_plan, girinti=2)[0] == beklenen
