#!/usr/bin/env bash
# Installs the project template into a repo: bash ~/.claude/proje-sablonu/install.sh <repo-path>
# Never overwrites an existing file (only appends missing lines to .gitignore).
set -euo pipefail

SABLON="$(cd "$(dirname "$0")" && pwd)"
HEDEF="${1:?usage: install.sh <repo-path>}"
cd "$HEDEF"
git rev-parse --git-dir >/dev/null 2>&1 || git init -q -b main

kopyala() {
  if [ -e "$1" ]; then echo "exists, skipped: $1"
  else mkdir -p "$(dirname "$1")"; cp "$SABLON/$1" "$1"; echo "added: $1"; fi
}
kopyala .pre-commit-config.yaml
kopyala .github/workflows/ci.yml
kopyala .claude/skills/ci-fix/SKILL.md

# Keep the starter checklist + template note in the project too.
if [ -e PROJECT_TEMPLATE.md ]; then echo "exists, skipped: PROJECT_TEMPLATE.md"
else cp "$SABLON/README.md" PROJECT_TEMPLATE.md; echo "added: PROJECT_TEMPLATE.md"; fi

touch .gitignore
while IFS= read -r satir; do
  grep -qxF -- "$satir" .gitignore || echo "$satir" >> .gitignore
done < "$SABLON/.gitignore"
echo "updated: .gitignore"

# The global template hook duplicates pre-commit's gitleaks: if it is the same file, it is not kept.
KANCA="$(git rev-parse --git-path hooks)/pre-commit"
GENEL="$(git config --global --get init.templateDir || true)/hooks/pre-commit"
if [ -f "$KANCA" ] && [ -f "$GENEL" ] && cmp -s "$KANCA" "$GENEL"; then rm "$KANCA"; fi

if command -v pre-commit >/dev/null 2>&1; then pre-commit install
else python -m pre_commit install; fi
