---
name: axis-prototype
description: Build a throwaway spike to de-risk an approach before committing — UI mock, data notebook, cloud sandbox, AI eval, or backend POC. Produces findings + reusable assets, not shippable code.
argument-hint: "<approach to de-risk>"
disable-model-invocation: true
allowed-tools: Read Glob Grep Bash Write Edit Agent
---


# /axis-prototype

Read `.axis/context/refs/prose-style.md` before your first reply. It governs every word you write in this conversation, including any front-half dialogue above and the summary you return below.

Delegate to the `axis-prototype` subagent via the Agent tool. Pass the user's input after `/axis-prototype` verbatim to the subagent.

Call the Agent tool with these fields:

- `subagent_type`: `"axis-prototype"`
- `description`: a 3-5 word label for **this specific task** (what the run is doing, e.g. "review pending auth changes"). Not this skill's own description.
- `prompt`: the user's input, unchanged.

Return the subagent's output unchanged.

If this platform has no Agent tool or no `axis-prototype` subagent, follow `.claude/agents/axis-prototype.md` — the same procedure, self-contained — instead. (A repo that also targets Codex, Copilot, or OpenCode carries an identical copy at `.agents/skills/axis-prototype/SKILL.md`.)
