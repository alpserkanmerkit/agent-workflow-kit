---
name: ci-fix
description: Self-repair loop for a red CI. LOAD after a branch is pushed, when the user says "watch CI", "CI is red", "make CI green", "ci-fix", or while a CI result is awaited after a push. At most 3 rounds; then BLOCKED with evidence.
---

# ci-fix — red CI -> root cause -> red test first -> fix -> push again (at most 3 rounds)

Rules: no push to main (only the working branch). No `--no-verify`. Tests are not deleted, thresholds are not loosened, tests are not skipped.
The author does not loosen a test; if the test is wrong, write that down with evidence and say BLOCKED.

## Loop (round = 1..3)
1. Find the latest run and wait for it to finish (do not write a separate wait loop; `gh run watch` waits by itself):
   ```bash
   RUN=$(gh run list --branch "$(git branch --show-current)" -L 1 --json databaseId -q '.[0].databaseId')
   timeout 1200 gh run watch "$RUN" --exit-status
   ```
   Exit 0 -> GREEN: write the run-id into the report, stop.
2. If red, read only the log of the failed steps:
   ```bash
   gh run view "$RUN" --log-failed | tail -n 150
   ```
3. Root cause (3 lines): which job/step, which file:line, why. Not a guess; quote the log.
4. If it is a behaviour bug, first write/find the test that catches it and run only that test locally -> see RED (quote the output).
   If it is a format/lint error, the tool's local output is enough instead of this step.
5. Fix; run only that test/tool again locally -> GREEN.
6. Commit (`fix(ci): <root cause>`), push to the same branch, go back to 1.

## Still red after 3 rounds
Stop. Write BLOCKED into RAPOR.md (or the session report): every round's run-id, root cause, the fix tried, the last error quote,
2-3 options + a recommendation. Move on to the next job.

## Report line
`ci-fix: <branch> | round=<n> | run-ids: <id1> (red) -> <id2> (green) | root cause: <one line>`
