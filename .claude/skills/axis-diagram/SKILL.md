---
name: axis-diagram
description: Create editable architecture diagrams (draw.io + Mermaid) from a description or the codebase. Writes to .axis/diagrams/. Read-only on source.
argument-hint: "<what to diagram — description or code area>"
disable-model-invocation: true
allowed-tools: Read Glob Grep Bash Write Agent
---


# /axis-diagram

Read `.axis/context/refs/prose-style.md` before your first reply. It governs every word you write in this conversation, including any front-half dialogue above and the summary you return below.

Delegate to the `axis-diagram` subagent via the Agent tool. Pass the user's input after `/axis-diagram` verbatim to the subagent.

Call the Agent tool with these fields:

- `subagent_type`: `"axis-diagram"`
- `description`: a 3-5 word label for **this specific task** (what the run is doing, e.g. "review pending auth changes"). Not this skill's own description.
- `prompt`: the user's input, unchanged.

Return the subagent's output unchanged.

If this platform has no Agent tool or no `axis-diagram` subagent, follow `.claude/agents/axis-diagram.md` — the same procedure, self-contained — instead. (A repo that also targets Codex, Copilot, or OpenCode carries an identical copy at `.agents/skills/axis-diagram/SKILL.md`.)
