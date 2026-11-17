---
name: axis-test
description: Write new unit tests for a target. Reads test framework from AGENTS.md. Reports pre-existing failures separately.
argument-hint: "<file, module, or symbol to test>"
disable-model-invocation: true
allowed-tools: Read Glob Grep Bash Write Edit
---


## Routing & the loop contract

Classify **how** this should run — one-shot, goal ("until tests pass"), parallel/large, or recurring — route it to your platform's matching primitive, and **announce the route in one line**. Confirm first for parallel/recurring/unattended; one-shot and in-session goals just proceed.

When you run as anything but one-shot, honor the **loop contract**:

- **Isolation** — each unit/iteration runs in its own git worktree; never share a working tree across parallel units.
- **Checker** — stop only on a **machine-checkable** condition (tests green · `tsc` clean · CI green · plan-done), verified **independently** (e.g. dispatch `/axis-review`) — never grade your own output. No deterministic check ⇒ stay attended + human-gated; don't loop unattended.
- **Spend cap** — an unattended loop carries a ceiling and a no-progress stop. Headless runs bill by the token, and a loop with neither burns budget for as long as nobody is watching.
- **Complete the loop** — hand the result off through your tools (open the PR, link the ticket, post the summary); don't just print a fix and stop.
- **State on disk** — record done/next in your `.axis` artifact + status index (artifact conventions above) so the next pass resumes, not restarts.
- **Context** — your conventions live in AGENTS.md + glossary + playbooks (above); re-read them each pass.

Recurring runs that must stay in this environment use a local loop or your own CI — a cloud schedule clones the repo elsewhere.


# /axis-test

Read `.axis/context/refs/prose-style.md` before your first reply. It governs every word you write in this conversation, including any front-half dialogue above and the summary you return below.

Delegate to the `axis-test` subagent via the Agent tool. Pass the user's input after `/axis-test` verbatim to the subagent.

Call the Agent tool with these fields:

- `subagent_type`: `"axis-test"`
- `description`: a 3-5 word label for **this specific task** (what the run is doing, e.g. "review pending auth changes"). Not this skill's own description.
- `prompt`: the user's input, unchanged.

Return the subagent's output unchanged.

If this platform has no Agent tool or no `axis-test` subagent, follow `.claude/agents/axis-test.md` — the same procedure, self-contained — instead. (A repo that also targets Codex, Copilot, or OpenCode carries an identical copy at `.agents/skills/axis-test/SKILL.md`.)
