---
name: axis-discover
description: Map a legacy system — code, schema, config-as-logic, and infra — into a structured inventory with flow diagrams. Read-only; feeds /axis-plan for migration.
argument-hint: "<system or subtree to map>"
disable-model-invocation: true
allowed-tools: Read Glob Grep Bash Write Agent
---


# /axis-discover

Read `.axis/context/refs/prose-style.md` before your first reply. It governs every word you write in this conversation, including any front-half dialogue above and the summary you return below.

Delegate to the `axis-discover` subagent via the Agent tool. Pass the user's input after `/axis-discover` verbatim to the subagent.

Call the Agent tool with these fields:

- `subagent_type`: `"axis-discover"`
- `description`: a 3-5 word label for **this specific task** (what the run is doing, e.g. "review pending auth changes"). Not this skill's own description.
- `prompt`: the user's input, unchanged.

Return the subagent's output unchanged.

If this platform has no Agent tool or no `axis-discover` subagent, follow `.claude/agents/axis-discover.md` — the same procedure, self-contained — instead. (A repo that also targets Codex, Copilot, or OpenCode carries an identical copy at `.agents/skills/axis-discover/SKILL.md`.)
