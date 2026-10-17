#!/usr/bin/env bash
# bash-guard lite — PreToolUse (Bash|PowerShell). Bash builtins only: spawns no subprocess (~50 ms).
# (a) background wait loop with sleep -> deny (zombie)
# (b) find on a broad root, no -maxdepth or > 3 -> deny (handle leak)
# Matches on the raw JSON; the command text arrives JSON-escaped (\" and \\).

IFS= read -r -d '' input
shopt -s nocasematch

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"bash-guard-lite: %s"}}\n' "$1"
  exit 0
}

# --- (a) zombie: background + loop + sleep ---
loop_re='(^|[^a-z_-])(while|until|for|do)([^a-z_-]|$)'
sleep_re='(^|[^a-z_-])(sleep|start-sleep)([^a-z_-]|$)'
bg_re='"run_in_background"[[:space:]]*:[[:space:]]*true|nohup|start-job|start-process|[^&]&[[:space:]]*(\\n|"|;|$)|&[[:space:]]+[a-z]'
if [[ $input =~ $loop_re && $input =~ $sleep_re && $input =~ $bg_re ]]; then
  deny "background wait loop with sleep (zombie risk). To wait, use Monitor or a single run_in_background command."
fi

# --- (b) find on a broad root ---
q='(\\\"|\\\\\"|'"'"')?'
root="(/|/[a-z]/?|[a-z]:(\\\\\\\\|/)*|~/?|\\\$home/?|\\\$env:userprofile|/c/users/[^/ \"]+/?|[a-z]:(\\\\\\\\|/)+users(\\\\\\\\|/)+[^\\\\/ \"]+(\\\\\\\\|/)?|[^ \"]*appdata[^ \"]*)"
find_re="(^|[;&|( \"])find[[:space:]]+${q}${root}${q}([[:space:]]|\"|\\\\n|$)"
if [[ $input =~ $find_re ]]; then
  depth_re='-maxdepth[[:space:]]+([0-9]+)'
  if ! [[ $input =~ $depth_re ]] || (( BASH_REMATCH[1] > 3 )); then
    deny "find on a broad root (/, drive root, profile, AppData) without -maxdepth <= 3. Use a narrow folder or -maxdepth 3."
  fi
fi

exit 0
