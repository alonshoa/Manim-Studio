---
name: manim-studio-creator
description: Plan, create, render and review educational Manim Studio scenes and decks in guided or flexible workflows.
---
# Manim Studio Creator

Use this skill when creating or revising educational animations or slide decks with Manim Studio.

First inspect the project, available `studio` commands and MCP capabilities. Never assume a command exists; use `studio --help` and relevant subcommand help.

## Research opt-in lifecycle

At the beginning of each new deck-creation task, check whether a research session is already active. If none is active, ask once whether the user wants research capture enabled. A refusal must not block normal authoring and must not be re-asked within the same task.

When approved, prefer the installed `studio research start` lifecycle command **only if it is present in CLI help**. Until available, use the documented existing research setup procedure; do not silently skip source attachment, live capture verification, or hook configuration. A configured or enabled flag is not evidence that the current Codex conversation is captured. If the current conversation cannot be bound and verified, explicitly report the limitation and ask whether to proceed unrecorded or fix the capture setup. Never assert READY without observed capture evidence.

At the end of an active research task, ask whether to finish. On approval prefer `studio research finish` **only if installed**; otherwise use the existing research finish, integrity, and export procedure. Report incomplete coverage and failed exports; never describe partial capture as complete. Treat research initialization and closing as system setup, not content-authoring interventions.

Ask whether to use **Guided** or **Flexible** mode if the user's preference is unclear. Follow the corresponding reference document.

Keep pedagogical narrative, visual storyboard and implementation separate. Preserve existing work and scene identifiers. Prefer targeted edits and draft renders, then inspect results before final export. Report commands, artifacts and unresolved issues accurately. Never claim a render succeeded without checking it.

For Hebrew material, check RTL layout, glyph rendering and mathematical notation explicitly.

Read `references/guided.md` or `references/flexible.md` for the selected workflow.
