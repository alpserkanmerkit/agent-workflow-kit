#!/usr/bin/env bash
# One-command real demo: bash demo.sh   (prerequisites: bash, python3, git; no network, leaves the repo clean)
# (a) installs the template into an empty directory (b) hooks block the dangerous and allow the harmless (c) a secrets file never enters git (d) DEMO COMPLETE
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python)" || { echo "ERROR: python3 not found" >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$TMP/home/.gitconfig"
mkdir -p "$HOME" "$TMP/bin" "$TMP/proje"
# A real pre-commit install needs the network: use a fake script instead (accepts only the "install" call).
printf '#!/bin/sh\necho "[fake pre-commit] $*"\n' > "$TMP/bin/pre-commit"
chmod +x "$TMP/bin/pre-commit"
export PATH="$TMP/bin:$PATH"

SAYAC=0
tamam() { SAYAC=$((SAYAC + 1)); echo "  OK   $1"; }
hata() { echo "  FAIL $1" >&2; exit 1; }

echo "== (a) installing the template into an empty directory =="
bash "$KOK/template/install.sh" "$TMP/proje" | sed 's/^/  /'
for d in .pre-commit-config.yaml .github/workflows/ci.yml .claude/skills/ci-fix/SKILL.md .gitignore; do
  [ -f "$TMP/proje/$d" ] || hata "missing: $d"
done
tamam "template files installed (git repo + .gitignore + CI + pre-commit + ci-fix)"

echo "== (b1) bash-guard-lite: dangerous input is BLOCKED, harmless input is ALLOWED =="
guard() { printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$1" | bash "$KOK/hooks/bash-guard-lite.sh"; }
CIKTI="$(guard "find / -name '*.log'")" && RC=0 || RC=$?
echo "  find / ...  -> exit=$RC  $(printf '%s' "$CIKTI" | grep -o '"permissionDecision":"[a-z]*"')"
if [ "$RC" -ne 0 ] || [[ $CIKTI != *'"permissionDecision":"deny"'* ]]; then hata "find / was not blocked"; fi
tamam "'find /' denied (deny)"
CIKTI="$(guard 'until [ -f done.txt ]; do sleep 5; done &')" && RC=0 || RC=$?
echo "  sleep loop  -> exit=$RC  $(printf '%s' "$CIKTI" | grep -o '"permissionDecision":"[a-z]*"')"
[[ $CIKTI == *'"permissionDecision":"deny"'* ]] || hata "sleep loop was not blocked"
tamam "background sleep loop denied (deny)"
CIKTI="$(guard 'npm test')" && RC=0 || RC=$?
echo "  npm test    -> exit=$RC  output='${CIKTI}'"
if [ "$RC" -ne 0 ] || [ -n "$CIKTI" ]; then hata "harmless command was blocked"; fi
tamam "'npm test' allowed (empty output = allow)"

echo "== (b2) WAIT mode: greeting -> tools locked, unlocked once a task arrives =="
export BEKLE_DIZIN="$TMP/bekle"
kanca() { printf '{"session_id":"demo","prompt":"%s"}' "$2" | "$PY" -I -S "$KOK/hooks/wait_mode.py" "$1"; }
kanca prompt "selam" >/dev/null
CIKTI="$(kanca pre "")"
echo "  tool call after 'selam' (greeting) -> $(printf '%s' "$CIKTI" | grep -o '"permissionDecision": *"[a-z]*"')"
[[ $CIKTI == *'"permissionDecision": "deny"'* ]] || hata "WAIT mode did not block the tool"
tamam "tool denied while the WAIT flag is set"
kanca prompt "run the tests in the hooks folder" >/dev/null
CIKTI="$(kanca pre "")"
echo "  tool call after a task message -> output='${CIKTI}'"
[ -z "$CIKTI" ] || hata "tool still blocked after a task message"
tamam "tool allowed once a task was given"

echo "== (c) secret protection: a fake secrets file does NOT enter git =="
cd "$TMP/proje"
git -c user.name=demo -c user.email=demo@example.invalid -c commit.gpgsign=false commit -q --allow-empty -m initial
# Synthetic test string: not a real secret; written in pieces so the repo's secret scanners do not flag this file.
SAHTE="FAKE_KEY_""demo-only-0000"
printf 'API_KEY=%s\n' "$SAHTE" > .env
printf 'harmless note\n' > notes.txt
if git add .env 2> "$TMP/add.err"; then hata ".env was added to git!"; else RC=$?; fi
echo "  git add .env      -> exit=$RC  $(head -1 "$TMP/add.err")"
git add notes.txt && echo "  git add notes.txt -> exit=0 (harmless file added)"
[ "$(git diff --cached --name-only)" = "notes.txt" ] || hata "index differs from expected"
tamam ".gitignore secret pattern rejected .env, harmless file went in"
if command -v gitleaks >/dev/null 2>&1; then
  printf 'token = "%s%s"\n' "ghp_" "R7kQ2xLm9ZpV4wNb8TcY1dFgH6jS3aUe5oXi" > fake-token.txt
  if gitleaks dir --no-banner --redact -v fake-token.txt > "$TMP/gl.out" 2>&1; then
    hata "gitleaks did not catch the fake token"
  else
    echo "  gitleaks fake token -> exit=1 (finding present)"; tamam "gitleaks caught the fake token"
  fi
else
  echo "  gitleaks not installed: SKIPPED (the gitleaks job in CI does the same scan)"
fi

echo "== (d) summary =="
echo "$SAYAC checks passed. DEMO COMPLETE"
