---
name: axis-plan
description: Design an implementation plan before writing code — add `--grill` to shape it through a one-question-at-a-time dialogue first. Writes .axis/plans/<slug>.md (and .html with --html). Read-only.
argument-hint: "[--grill] [--html] <task to plan>"
disable-model-invocation: true
allowed-tools: Read Glob Grep Bash Write Agent
---

## Grill mode (`--grill`) — shape the idea before planning

`--grill` runs an **interactive shaping dialogue _before_ the plan is written**. It is the skill's front-half: you (the skill, in this conversation) conduct it, then hand a converged decision to the plan-writer. If the user never gives the go, **nothing is written** — the conversation was the deliverable (the "just talk it through" path; no flag needed). Without `--grill`, skip all of this and dispatch directly (the default, and what `/axis-ship` always uses).

**The one rule that makes grill work: one question per turn.** Never stack two questions, even when they feel related — stacking lets the user pick the easy one. Pick the most important, ask it, wait. The dialogue _is_ the value: it front-loads disagreement to the cheapest point.

**The second rule: never write until explicitly told.** Default to _continuing the dialogue_. The plan is written **only** on an unambiguous go — "write it", "go", "do it", "make the plan". **Agreement is not a go:** "yes", "exactly", "right", "makes sense", a thumbs-up, enthusiasm, or simply answering your question all mean the conversation is _working_ — keep going. When unsure, **ask** ("write it up now, or keep shaping?"); never announce "writing now" on your own read.

**Depth tracks the effort level:**

- **quick** — one classifying question, then converge. Skip the pressure-test.
- **standard** — pressure-test the gaps that matter; surface **2** approaches.
- **deep** — all four lenses; surface **3** approaches (one non-obvious).

**The loop:**

1. **Discover before you ask.** Anything answerable from the code or AGENTS.md, read it (spawn **Explore** for breadth) — never spend the user's turn on a fact you can find. Their turns are for what _only they_ know: intent, priorities, what they've watched users actually do.
2. **Pressure-test the gaps** — as prose, not multiple-choice (menus signal which answers "count" and let the user pick instead of produce). One probe per turn, in order of severity; skip lenses the opening already covered; stop when answers converge.

   | Lens               | Probe (one at a time)                                                              |
   | ------------------ | ---------------------------------------------------------------------------------- |
   | **Evidence**       | "What have you seen users actually _do_ — not say — that makes this matter?"       |
   | **Specificity**    | "Whose work changes after this ships? A name or role I can picture, not 'users.'"  |
   | **Counterfactual** | "What do they do today instead? What breaks (or stays annoying) if nothing ships?" |
   | **Attachment**     | "If the solution couldn't look like the shape you named, what would you propose?"  |

3. **Stay at mechanism, not implementation.** In the dialogue you decide _what_ and _why_ — no file layouts, schemas, libraries, or endpoints. Those are the plan-writer's job (the back-half). If the talk drifts into _how_, note it and pull back.
4. **Surface 2–3 approaches _before_ recommending** — anchoring early defeats the purpose. At least one **non-obvious**, drawn from: **inversion** (flip the default), **constraint removal** (drop an assumption — what opens up?), or **cross-domain analogy**. Mechanism / product-shape granularity.
5. **Converge slowly — never rush the synthesis.** When a thread resolves, probe the next gap or ask "what else should we pressure-test?" rather than reaching for the synthesis. Emit it **once**, when the idea has genuinely settled — then **wait**. Treat any further input as more dialogue (absorb it; re-emit only if it changed something), never as permission to write.

**Synthesis** (emit before handing off, then wait):

```
Synthesis:
  Problem       — <one line>
  Beneficiary   — <one line, concrete>
  Approaches    — <names>
  Recommended   — <one of them>
  Key tradeoff  — <one line>
  Out of scope  — <what's deferred>
  Slug          — <kebab-case>
Confirm and I'll write the plan, or correct any of the above.
```

**On an explicit go — the hinge (no re-invocation; this same flow continues):**

Writing needs an unambiguous go (see the second rule). Agreement, enthusiasm, or answering a question is **not** it — when in doubt, keep talking.

- **No go (the user ends the session, or only ever explored):** nothing is written — the dialogue was the deliverable (the "just talk" path, no flag required).
- **Explicit go:** hand the converged decision to the plan-writer (dispatch — see below) to produce `.axis/plans/<slug>.md`. The synthesis becomes the plan's **rationale header** (Problem · Approaches considered · Recommendation · Key tradeoff · Open questions), above the usual Objective / Steps / Risks. The user does **not** re-run anything.

**Mid-flight:** "enough, write it" → converge early and hand off. "Keep going" → more questions.

**Grill rationalizations — don't talk yourself into these:**

| Excuse                                                 | Rebuttal                                                                     |
| ------------------------------------------------------ | ---------------------------------------------------------------------------- |
| "I see the answer — I'll just write the plan now."     | The dialogue is the value. One question at a time; converge; confirm.        |
| "Both sub-questions are related, I'll ask together."   | No — stacking lets the user pick the easy one. Ask the most important; wait. |
| "I'll recommend the obvious approach and skip others." | Surface 2–3 (one non-obvious) **before** recommending.                       |
| "The codebase probably already does X."                | Don't fabricate. Didn't read it via Explore/Read? Don't claim it exists.     |

**Refuse:** "skip the questions, just plan it" → that's plain `/axis-plan` without `--grill`; point there. Offer the quick path (one classifying question + synthesis) if they're sure the scope is already clear.



# /axis-plan

Read `.axis/context/refs/prose-style.md` before your first reply. It governs every word you write in this conversation, including any front-half dialogue above and the summary you return below.

Delegate to the `axis-plan` subagent via the Agent tool. Pass the user's input after `/axis-plan` verbatim to the subagent.

Call the Agent tool with these fields:

- `subagent_type`: `"axis-plan"`
- `description`: a 3-5 word label for **this specific task** (what the run is doing, e.g. "review pending auth changes"). Not this skill's own description.
- `prompt`: the user's input, unchanged.

Return the subagent's output unchanged.

If this platform has no Agent tool or no `axis-plan` subagent, follow `.claude/agents/axis-plan.md` — the same procedure, self-contained — instead. (A repo that also targets Codex, Copilot, or OpenCode carries an identical copy at `.agents/skills/axis-plan/SKILL.md`.)
