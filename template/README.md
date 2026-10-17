# Project template (07.10)

## Project start checklist

In every new project, before writing code, in this order:

1. **Definition of "done".** One sentence + a deadline. Then write 3-5 acceptance scenarios in the user's own words:
   "When I open the book on my phone, it continues from the page where I stopped." A scenario is behaviour the user sees; no technical terms.
2. **Turn the scenarios into tests.**
   - Unit test = logic (calculations, rules, transformations).
   - Integration test = flow (screens, saving, service calls together).
   - Acceptance on a real device / in real use = "done". Green unit tests alone are not "done".
   Helper skill: `engineering:testing-strategy`.
3. **Install the template:** `bash <this-repo>/template/install.sh <repo-path>`. Language blocks (Python / Node / Flutter / shell) switch on by themselves in CI.
4. **Debugging flow:** a **red test** that catches the bug → fix → **green** → push → CI (if red, the `ci-fix` skill) →
   show it in real use. Helper skill: `engineering:debug`.

## Installation

Installs into a new project in ~1 minute:

```bash
bash <this-repo>/template/install.sh <repo-path>
```

| File | What it does |
|---|---|
| `.pre-commit-config.yaml` | Local hook, seconds: whitespace/end of file, YAML, large files, **gitleaks** (staged only), ruff (.py only) |
| `.github/workflows/ci.yml` | Single CI (ubuntu-latest): gitleaks (the branch's whole history) + Python / Node / Flutter / shellcheck jobs that switch on by language; `main` and `gece/**`, md-only changes do not run CI, old runs are cancelled, caching |
| `.gitignore` | `.env`, `.env.*`, `*.key`, `*.pem`, service account / credential files + language clutter (only missing lines are added to an existing one) |
| `.claude/skills/ci-fix/SKILL.md` | Self-repair loop when CI is red (at most 3 rounds) |
| `PROJECT_TEMPLATE.md` | This file: the start checklist also lives in the project |

## Secret scanning — 3 layers
1. **Global git template** (`git config --global init.templateDir <HOME>/.git-template`): every new `git init` / `git clone` gets a `pre-commit` hook automatically; the hook scans staged changes with `gitleaks` (`~/.local/bin/gitleaks.exe`) and, if the repository has a `.pre-commit-config.yaml`, runs that too.
2. **Repository hook**: `pre-commit install` (install.sh does it). An existing hook becomes `pre-commit.legacy` and still runs.
3. **CI**: the gitleaks binary scans the whole history of the pushed branch (for pushes from places without the hook; a leak on another branch turns that branch's own CI red).

To add the global hook to an existing repository (the repository's own hook is left alone; if there is none, it is copied):

```bash
git -C <repo-path> init
```

False positive: add the `Fingerprint` line from the gitleaks output to `.gitleaksignore` at the repository root.
