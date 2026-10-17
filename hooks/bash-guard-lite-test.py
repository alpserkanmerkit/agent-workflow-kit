# 10-command test list for bash-guard-lite: 5 must be blocked, 5 must pass + latency measurement.
import json
import shutil
import subprocess
import time
from pathlib import Path

HOOK = str(Path(__file__).resolve().parent / "bash-guard-lite.sh")
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"

CASES = [
    ("deny", "Bash", "until [ -f done.txt ]; do sleep 5; done", True),
    ("deny", "Bash", "while true; do gh run list -L 1; sleep 30; done &", False),
    ("deny", "PowerShell", "Start-Job { while ($true) { Start-Sleep 10; git status } }", False),
    ("deny", "Bash", "find / -name '*.log'", False),
    ("deny", "PowerShell", 'find "C:\\Users\\example" -maxdepth 6 -name x.txt', False),
    ("allow", "Bash", 'for f in *.py; do ruff check "$f"; done', False),
    ("allow", "Bash", "sleep 2 && echo ok", False),
    ("allow", "Bash", "find . -name '*.py' -newer setup.cfg", False),
    ("allow", "Bash", "find /c/Users/example -maxdepth 2 -name '*.md'", False),
    ("allow", "Bash", "npm test", True),
]


def run(tool, command, background):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command, "run_in_background": background},
    }
    start = time.perf_counter()
    out = subprocess.run([BASH, HOOK], input=json.dumps(payload), capture_output=True, text=True, check=False, timeout=10)
    ms = (time.perf_counter() - start) * 1000
    decision = "deny" if '"permissionDecision":"deny"' in out.stdout else "allow"
    return decision, ms, out.returncode


def main():
    ok = 0
    for expected, tool, command, background in CASES:
        decision, ms, rc = run(tool, command, background)
        verdict = "PASS" if decision == expected and rc == 0 else "FAIL"
        ok += verdict == "PASS"
        print(f"{verdict} | expected={expected:5} | result={decision:5} | {ms:5.0f} ms | {tool}: {command}")
    times = [run("Bash", "npm test", False)[1] for _ in range(5)]
    print(f"SUMMARY {ok}/{len(CASES)} | latency 5 runs (ms): {', '.join(f'{t:.0f}' for t in times)} | avg {sum(times) / 5:.0f}")


if __name__ == "__main__":
    main()
