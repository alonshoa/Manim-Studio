# Manim-Studio v0.1.0 release-readiness report

Assessment: **Requires manual verification**. Prepare a **draft** PR from
`research/prompt-logging` to `main`. Do not merge, tag or publish a release.

Date: 2026-11-24. Starting candidate: `4dad2f1b416dc77f78cfc1359c9ceaa4badcad30`.
Main baseline: `06af1981b368dca0eeacd92cde636ade4a62124e`.
The original branch contains 48 commits beyond main; history is preserved.

## Stage 1 — Repository cleanup

Reviewed the complete branch file inventory/diff and commit history, with focused
review of lifecycle consent, file/export boundaries, installation, packaging and
agent distribution. The original diff comprises 187 changed files and roughly
23,700 inserted lines. This release preparation is targeted; it is not a security
audit or a claim that every research result has been independently reproduced.

- Reviewed current GitHub Issues, including the November 23 dispositions. #17 owns
  actual installer/client acceptance; #31 owns complete practical documentation.
  No duplicate issues were created and no retired roadmap was reinstated.
- Archived `todo.md` and `feature_todo.md` under `docs/archive/`, retained their
  contents/history and repaired their relative documentation links.
- Added [an inventory](archive/README.md) classifying scratch decks, empty client
  smoke sessions, accepted-step ledgers, tests, baselines, design records and
  historical validation reports. All experiment files, catalog IDs and references
  remain intact. No research evidence was deleted or relocated.
- Expanded `.gitignore` for local research databases, SQLite journals, VSIX/private
  key output and Python build staging. Existing build/media/log/config exclusions
  remain in place. Generated packages and test environments were not committed.
- Pattern-scanned 192 candidate changed files and all new commit patches for common
  private keys, GitHub tokens, OpenAI keys and AWS keys: no matches. Current-file
  scans also checked credential assignments. Reviewed all six added screenshots;
  they show demo UI/research IDs, not observed credentials or personal contacts.
  Retained demo transcripts, synthetic fixture paths and historical result metadata
  are documented evidence. This scan cannot establish absence of every secret.

Files removed: **none**, other than the original paths of the two archived TODO
files. `catalog/scenes.yaml`, scratch sources/ledgers and `validation/` are preserved.

## Stage 2 — Agent instructions and skills

Updated `AGENTS.md`, `CLAUDE.md`, the Creator `SKILL.md` and Flexible reference:

- Creator is required for educational scenes/decks and revisions.
- Each new creation task requires an explicit Guided/Flexible choice unless already
  explicitly selected for that task; inference and silent switching are prohibited.
- The selected reference must be read before content creation.
- Research consent is optional and separate; refusal does not block authoring.
  Status/conversation binding must be verified; completion/export need approval.

`project_builder.py` now generates matching root instructions and canonical skill
files/references for `.agents` and `.claude`. Python wheel/sdist metadata includes
those resources; Docker retains them during packaging. A missing installed skill
fails project initialization with an actionable error instead of generating an
incomplete project. Regression tests compare generated files with canonical bytes.

Fixed a demonstrated CLI regression: `codex-prepare` had an implementation but was
missing from argparse choices. A real subprocess test verifies preparation without
enabling capture or creating `events.sqlite3`. No modes or lifecycle were redesigned.

## Stage 3 — Release preparation

- Python and extension/lockfile metadata already identify 0.1.0; retained those
  versions. Windows packaging now records the product version and checks it against
  both extension source metadata and the supplied VSIX manifest.
- Windows package names contain version and commit; source bundles remain pinned to
  the exact clean revision with checksums. Default ref is `main`, not the research
  branch. Normal setup requires the verified bundled payload. Mutable branch setup
  requires explicit `-DevelopmentSource`; it remains a development-only option.
- Ordinary new installation no longer enables logging. `-EnableResearchCapture`
  explicitly enables optional tool-action logging. Earlier data/settings are
  preserved; absence of that flag does not revoke previous consent.
- README, docs home, installation, quick start, Windows setup and skill contracts
  now lead with native Windows installation and explicit authoring modes. Added
  research/privacy navigation and this report; kept Docker and devcontainer support.
- Added `CHANGELOG.md` describing only implemented capabilities, with limitations.
- Privacy guidance covers collected text/state, local SQLite/artifacts, disabling
  capture, binding verification, metadata/full exports and archive sensitivity.
- No comprehensive tutorial rewrite: #31 remains separate. The dormant manual Docker
  trial-publish workflow is preserved; it is not the v0.1.0 Windows distribution
  path and was not executed. No GitHub Release automation was added or invoked.

Main changed file groups: root instructions/README/changelog/gitignore;
`.agents/skills/manim-studio-creator/`; `pyproject.toml` and `Dockerfile`;
`src/manim_studio/{project_builder,research_cli}.py`; Windows build/setup/test
scripts and package workflow; project/lifecycle/validation tests; documentation
entry pages, navigation, archive and report. The VS Code implementation did not
need changes during release preparation.

## Stage 4 — Executed verification

Environment: Linux, Python 3.12, isolated test environments, PowerShell 7.4.13.
Python suite/build and extension checks cover the implementation in `60c2fdd`;
PowerShell package checks cover `3373f79` (same implementation plus the corrected
setup-test variable). Later changes are documentation/report corrections only.

| Check | Result and evidence |
| --- | --- |
| Full `python -m pytest tests -q -rs` | **352 passed, 11 skipped, 15 subtests passed**; 14.21 seconds. Includes CLI, MCP services, authoring/movie sessions, capture, sessions, artifacts, integrity, timing, exports, compatibility and project generation. |
| Initial Python run | **1 failed, 350 passed, 11 skipped**. Windows executable fixture lacked simulated `sys.platform`; test now explicitly selects Windows. Subsequent full run passed as above. |
| Native dependency installation | **Failed/environment limitation**: ManimPango requires absent `pangocairo` development files; system package installation unavailable to this user. Core dependencies installed separately. |
| Manim-dependent tests | **11 skipped**: two catalog/import checks and nine Manim Kit/RTL/slide checks. No native render success is claimed. |
| `studio catalog validate` | **Executed, failed in this environment**: all 11 catalog entries require unavailable `manim`. Structural/unit catalog checks passed; real import/render validation remains a merge requirement. |
| External initialization | **Passed**: CLI generated 23 files, including both client skills/references and instructions. Native rendering of that project remains unverified. Default external wrappers/MCP snippet still use Docker; native paths require configuration. |
| Installed wheel initialization | **Passed**: isolated wheel install outside the source checkout created the same 23-file project and discovered packaged skill resources. |
| Python distribution build | **Passed**: wheel and sdist built as `manim_studio-0.1.0`; skill resources included. |
| Actual local MCP stdio | **Passed**: SDK client initialized server and listed 33 tools and two static resources from the external project. This is a local protocol smoke check, not authenticated Codex/Claude integration or a rendering test. |
| Disabled research status | **Passed**: generated project reported `enabled: false`, `threads: []`; no capture was enabled for this readiness work. |
| `npm ci` and `npm test` | **Passed**: TypeScript compilation and all 11 extension test scripts. VS Code APIs are fakes in these tests; desktop acceptance is separate. |
| VSIX packaging/content | **Passed**: 37 archive members, version 0.1.0, expected compiled client/panel modules and webview assets, development sources excluded. |
| PowerShell 7 parser/setup checks | **Passed on Linux**: all scripts parse; environment/launcher/backup/reboot/error checks pass. Added a safe plan assertion for `main` and research disabled by default. |
| Windows ZIP generation | **Passed under PowerShell 7/Linux**: `Manim-Studio-Windows-x64-0.1.0-3373f79278de.zip`, exact source commit and product/extension versions recorded. This does not establish native installation. |
| Extracted package verification | **Passed under PowerShell 7/Linux**: SHA-256, extraction, installer plan, pinned Git restoration, safe rerun/dirty-checkout refusal, VSIX content and corruption rejection. |
| `mkdocs build --strict` | **Passed** after repairing archive/report links. Navigation and command syntax were checked against CLI/bridge help; corrected an invalid documented research-status command. |

The first new setup-plan regression also exposed a PowerShell variable collision
with the dot-sourced `-Plan` switch. It was corrected; subsequent setup and package
checks passed. Historical Markdown hard-break whitespace and an existing EOF blank
line are non-blocking `git diff --check` findings, not functional regressions.

Automated research tests exercise initial-prompt replay, opt-in/out, pause/resume,
conversation association, concurrent isolation, disabled-capture boundaries,
file scope, historical database compatibility, integrity and ZIP verification.
Synthetic hooks and mocks do **not** prove real-client message delivery or complete
coverage of an actual conversation.

## Remaining acceptance and merge requirements

Keep the PR draft until the required final-revision CI and manual acceptance are
recorded. No confirmed unresolved implementation regression remains from executed
checks; there are verification blockers:

1. Run Windows CI on the final PR revision: PowerShell 5.1 and 7, native runtime,
   Hebrew/math render/decode, extension and package verification. Local Linux
   PowerShell checks are not evidence of PowerShell 5.1 compatibility.
2. Run the full suite and catalog imports with installed Manim. Complete render,
   selected-beat and PPTX embedded-video export acceptance; open the PPTX in PowerPoint.
3. On clean Windows, install the package and perform existing-installation rerun and
   cross-version/new-root migration checks. Automatic in-place cross-version upgrade
   is not supported; a different bundled revision requires a new install root.
4. With authenticated supported clients, verify Guided and Flexible selection,
   research refusal, creation/revision/reopen, selective rendering and live preview.
   Visually inspect Hebrew RTL, glyphs, formulas and exported video playback.
5. Verify real hooks capture the initial user prompt and response, bind the correct
   conversation, pause/resume and isolate concurrent sessions. Explicitly approve
   finish/export, verify the ZIP, and compare it with the actual conversation.
6. Review PR changes and required checks, including the default-disabled installer
   behavior and packaged skill discovery. Mark ready only after these gaps are
   resolved or explicitly accepted by the maintainer with recorded limitations.

Non-blocking follow-ups: #31 practical documentation and complete real examples;
#17 consolidates the product acceptance evidence above. Old adaptive checkpoints,
automatic classification and research analysis proposals remain archived future work.
Signed/offline installation, external native wrapper convenience and broader live
preview/platform support are not new v0.1.0 commitments.

## Stage 5 — Review and PR handoff

Preparation commits, preserving existing history:

| Commit | Purpose |
| --- | --- |
| `b0c4918` | Archive planning; inventory preserved evidence and local-output exclusions. |
| `94ab889` | Explicit authoring modes and shared skills in external/installed projects. |
| `627fe4a` | Windows distribution, optional setup capture and v0.1.0 documentation. |
| `60c2fdd` | Hook-preparation CLI regression, workflow contracts and navigation. |
| `3373f79` | Correct the setup regression test variable collision. |
| This report commit | Final readiness evidence and documentation consistency. |

The branch is intended to be pushed normally and opened as a draft PR targeting
main, with this report and remaining requirements in the PR description. The PR URL
and final commit are supplied in the completion handoff. No squash, rebase,
force-push, merge, release tag or GitHub Release is part of this task.
