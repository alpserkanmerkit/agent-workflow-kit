# agent-workflow-kit — a working setup for building software with AI coding agents

## Quick start

```bash
bash demo.sh
```

Requirements: `bash` (tested with 5.x), `python3` (3.12+; tested with 3.13), `git` (tested with 2.43). No network and no new
dependencies; the demo runs in a temporary directory, leaves the repository untouched and takes ~1 second. What it shows: the template
being installed into an empty project, `bash-guard-lite` and the WAIT hook really denying dangerous input and letting harmless input
through, and the `.gitignore` secret patterns keeping a fake `.env` out of git.

End of the expected output:

```text
== (b1) bash-guard-lite: dangerous input is BLOCKED, harmless input is ALLOWED ==
  find / ...  -> exit=0  "permissionDecision":"deny"
  OK   'find /' denied (deny)
  npm test    -> exit=0  output=''
  OK   'npm test' allowed (empty output = allow)
...
== (d) summary ==
8 checks passed. DEMO COMPLETE
```

(If `gitleaks` is installed, the demo also scans a fake token; if not, it marks that step as "SKIPPED".)

This repository is the **cleaned-up showcase** of the working setup built to produce software from a weak Windows PC with
Claude Code and worker models (Qwen, Gemini, DeepSeek, NVIDIA). There is no product code here; it holds the rules, the hooks and the project template.

## What?

| Folder | Contents |
|---|---|
| [`rules/AGENTS.md`](rules/AGENTS.md) | The general working rules the agent reads every session (W1): safety core, modes, conversation, how work is done, quality |
| [`docs/workflow.md`](docs/workflow.md) | One-page summary of the setup: requests distilled from 3,319 of the user's messages |
| [`docs/architecture.md`](docs/architecture.md) | Rules → hooks → template → CI layers; what changed since the old "merkez" system and why |
| [`hooks/`](hooks/) | Claude Code hooks: WAIT mode, CI wait, bash guard, night watch + their tests + an example wiring (`settings.example.json`) |
| [`template/`](template/) | A template installed into every new project in ~1 minute: single CI, pre-commit, `.gitignore`, the `ci-fix` skill |

## Why?

The first system ("merkez"), built between May and October 2026, grew layer by layer to stop the agent from making mistakes:
8 hooks, 6 git hooks, 4 workflows, 27 self-test scripts and ~2,900 evidence files. The result: many rules, little product;
every commit went through local gates that took minutes, and the weak computer could not carry that.

In October 2026 the system was shut down and its **lessons** were distilled into this small setup:

- **Rules are tools; the goal is finished work.** No custom gates or watchdogs; standard tools (pytest, ruff, gitleaks, shellcheck, flutter analyze) are enough.
- **Heavy work runs in the cloud.** Tests and gates run on GitHub Actions (Linux); locally only second-long secret scanning and formatting.
- **No fake green.** 0 tests = red; "done" = the expected behaviour was seen in real use.
- **Work does not stop while the user is away.** Once a plan is approved its permissions are written to a list; the night watch passes what is on the list and denies the rest with a reason.

Measured effect (a sample TypeScript + Python project, the same 95 tests):
CI **127 s → 64 s** — parallel jobs, browser/pip caching, cancelling old runs, no CI on md-only changes.

## How?

```bash
# 1) Install the template into a new project (does not overwrite existing files)
bash template/install.sh <repo-path>

# 2) Wire up the hooks: copy the hooks/ files to <HOME>/.claude/hooks/,
#    and add the "hooks" block from hooks/settings.example.json to <HOME>/.claude/settings.json.

# 3) Hook tests (Python 3.12 + pytest)
python -m pytest hooks/tests -q
python hooks/bash-guard-lite-test.py
```

Flow: the user gives the definition of "done" → the agent writes a short plan and asks every permission question at once → "I approve" →
the agent works on a branch (`gece/<name>`), red test first, then code → push → CI (if red, `ci-fix` for at most 3 rounds) →
if CI is green, main is updated by fast-forward only → one report (commit hash, run-id, test count).

## Note

Personal information was removed: paths were replaced with placeholders such as `<HOME>` and `<NOTES>`, account names with `example-user`.
The code is here to show the behaviour; for real use, adjust the paths and the repository name to your own environment.
Some identifiers, file names the hooks read (for example `gece-modu.on`, `plan-izinleri.txt`) and the WAIT-mode phrases are Turkish,
because the setup was built for a Turkish-speaking user; comments, messages and documentation are in English.
