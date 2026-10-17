# Workflow — one-page summary

Source: 3,319 of the user's messages and session notes from 28.05–07.10.2026; 168 sourced requests were extracted and distilled into this page.

## 1. Conversation
- Result first; short, plain language but complete. If a technical term is needed, explain it in two sentences.
- "What's the status?" gets a verified answer: every item with a commit hash, CI run-id or test count. Without evidence: "NOT VERIFIED".
- Give your opinion, criticise the decision, do not agree right away. If it did not work: finding + 2-3 options + a recommendation.

## 2. Decisions and autonomy
- Two modes: **WAIT** (no task → one line, no tools) and **TASK** (a task → all the way to the end, no questions).
- The only things to ask about are irreversible or outward-facing steps: money, deletion, critical settings, secrets, push to main.
- In a big job all questions are asked once, in the plan; after approval there are no pauses.

## 3. How work is done
- Product first; every product has a deadline and a one-sentence definition of "done".
- A slice of work is ≤ 1 hour; the time estimate is given up front.
- Independent work goes to parallel sub-agents; the number of agents depends on the job.
- The work ends inside the session: commit + push + main + clean-up; before a hand-off, a continuation file.

## 4. Speed — Linux and the cloud first
- Tests and gates run on GitHub Actions (ubuntu-latest). No full test run on the user's PC.
- The gate runs once when the work is done (at most 3 rounds if red). Speed it up without deleting tests; measure it ("gate X s").

## 5. Quality — five checks
1. Secret scanning (gitleaks, every commit + CI).
2. A red test first when behaviour changes.
3. One CI run at the end of the job.
4. A second pair of eyes on risky work (a model that has not seen the author's tests).
5. Done = the expected behaviour was seen in real use; green unit tests alone are not enough.

## 6. Code
Clean Code: meaningful names, small functions, single responsibility, DRY, KISS, YAGNI. Linters and formatters do the policing, not debates.

## 7. Night
While the user sleeps the agent works autonomously; no permission prompt opens (the watch denies it, or passes what is on the plan list).
If something blocks, it is noted and the agent moves on to independent work; one summary in the morning.

## 8. Don't list
Local Windows gates · a full gate on every commit · piling up rules/hooks · growing a factory when there is no product · constant approval questions ·
working on assumptions · fake green · long scattered answers · processes without a time limit · making the same mistake twice.
