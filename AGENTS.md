# Manim Studio agent instructions

Work within the existing Manim Studio architecture and inspect documentation and CLI help before making assumptions. Prefer small, testable changes. Do not claim tests or renders ran unless verified.

For educational scene/deck creation, follow `.agents/skills/manim-studio-creator/SKILL.md` and select Guided or Flexible mode based on user intent.

At the start of each new Manim Studio deck-creation task, follow the research opt-in workflow in the creator skill. Never assume research capture is enabled or verified; do not claim a run is being recorded unless the research status confirms it. If the user declines, continue normally without repeated prompts for that task. Offer to finish an active research run at the end, but do not close it without approval.

Keep narrative planning distinct from visual design and implementation. Respect Hebrew RTL rendering needs. Do not overwrite existing scenes or modify installation/release workflows without checking their impact.
