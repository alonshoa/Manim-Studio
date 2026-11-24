# Changelog

## 0.1.0 — release candidate

Prepared for main; no release tag or publication is implied.

- Interactive authoring sessions: staged proposals, validation, draft previews,
  accept/reject/revise and durable session state; existing-scene editing remains available.
- Experimental local OpenGL live preview with beat selection, diagnostics and headless
  render fallback. Final output continues through the build/render pipeline.
- Movie sessions with incremental accepted steps and source/step ledgers.
- VS Code commands and embedded preview, session switching, terminal context,
  and research classification/artifact/time/integrity panels.
- Native Windows online setup ZIP with pinned Git bundle, prebuilt VSIX, payload
  hashes, PowerShell 5.1/7 checks, environment launchers and native render smoke checks.
  Default installation requires the verified bundle; mutable source setup is explicit.
- Required Creator skill with explicitly selected Guided/Flexible modes; shared
  references distributed in Python packages and newly initialized Codex/Claude projects.
- Optional local research logging and Codex capture adapter; preparation of hooks is
  separate from consent. Start verifies conversation binding and reports action required
  or incomplete coverage rather than assuming capture is ready.
- Research session management: explicit source association, pause/resume, concurrent
  session isolation and conservative recovery without rewriting historical events.
- Human prompt classification, intervention reasons, suggestions and correction history.
- Research artifact scope, candidate/build retention, quotas, provenance and coverage gaps.
- Explicit time tracking, reported/corrected time and overlap/recovery metadata; human
  working time is not inferred from gaps between messages.
- Integrity reports, durable jobs, scoped atomic ZIP export and independent verification;
  old database compatibility remains covered by regression tests.
- CLI/MCP/RPC additions reuse project services for authoring and research lifecycle;
  staged editing and selective beat rendering remain supported. PPTX export supports
  all-slide decks and embedded videos through the existing export path.

### Limitations

- Windows clean installation/upgrade, authenticated Codex/Claude behavior, real-client
  hook delivery and interactive VS Code acceptance need verification on the final revision.
  Mocked client tests do not establish real-client compatibility.
- Full capture depends on the supported adapter, hook trust and correct conversation
  association. Other clients require an explicit bridge; coverage gaps are reported.
- ZIP hashes detect corruption, not publisher identity. The installer is an online
  bootstrap, not a signed EXE/MSI or offline dependency bundle. Third-party tools and
  transitive dependency resolution still require Internet and can change over time.
- Packaged reruns preserve a clean identical revision. Cross-version upgrades require
  a new install root; automatic in-place upgrade is not supported.
- Live preview requires a usable graphical OpenGL environment. Cairo remains the
  normal final-render route. Visual Hebrew/RTL and math acceptance remains manual.
- HTML/PDF/mixed-deck export, cloud rendering and automatic/adaptive intervention
  classification are not advertised as complete. Research ZIP export is separate
  from educational deck export. Full practical documentation is tracked in #31.
