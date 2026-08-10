# Interactive Authoring In VS Code

This manual smoke test verifies the GUI path on Windows. Do not mark OpenGL
live preview as verified unless these steps were actually run on a desktop
machine with local Manim dependencies.

## Prerequisites

- Local desktop VS Code
- Workspace trust enabled
- `studio` available on `PATH`
- Project installed locally:

```powershell
python -m pip install -e ".[dev]"
```

- VS Code extension dependencies installed:

```powershell
cd vscode-extension
npm install
npm run compile
```

## Smoke Test

1. Open this repository in desktop VS Code.
2. Launch the extension development host for `vscode-extension`.
3. Ensure `manimStudio.previewMode` is `embedded`.
4. Run `Manim Studio: Start Authoring Session`; confirm it becomes the active
   workspace session, the `Manim Studio Preview` editor tab opens, and the
   dedicated `Manim Studio` integrated terminal is available in the bottom
   panel.
5. Confirm no external PowerShell console or OpenGL window opens in embedded
   mode.
6. Ask Codex through MCP to call `propose_next_movie_step` and append a title.
7. Confirm VS Code shows one proposal notification and opens the Preview tab.
8. Choose `Preview` in the Preview tab; do not enter a session ID or proposal
   ID.
9. Confirm the candidate draft video appears in the Preview tab and the
   canonical scene file is unchanged.
10. Choose `Reject` in the Preview tab and confirm the panel returns to the
    accepted canonical source.
11. Ask Codex for a revised title proposal.
12. Preview and accept it from the Preview tab.
13. Confirm the status bar returns to `Manim Studio: Ready | step_001` and the
    accepted draft video is displayed.
14. Run `Manim Studio: Pause Session`.
15. Restart VS Code.
16. Run `Manim Studio: Resume Last Session` and confirm the last accepted beat
    is restored.
17. Create a proposal, preview it, and run `Manim Studio: Revise Active
    Proposal` with Hebrew feedback.
18. Confirm the revision feedback appears in `get_authoring_session_status`.
19. Resolve the proposal.
20. Run `Manim Studio: Finish Session` and confirm the final artifact appears in
    the Preview tab and the session becomes `COMPLETED`.
21. Set `manimStudio.previewMode` to `externalOpenGL`, then run the live preview
    command and confirm the existing OpenGL workflow still works.
22. Optionally run:

```powershell
studio render <deck-id>/<scene-id> --profile draft --beat step_001
```

## Known Limits

- The extension owns the docked VS Code preview and terminal, but session state,
  proposal decisions, and preview renders still flow through `studio authoring
  rpc`.
- Embedded preview displays rendered draft video artifacts. It does not attempt
  to embed or reparent native OpenGL windows.
- External OpenGL remains available only as an explicit fallback mode.
- Extension shutdown stops the extension-owned RPC process. Live preview process
  state is refreshed from persisted PID status when a session is active.
- Remote workspaces, WSL, and devcontainers are not the supported path yet.
- Automated tests use fake live runners; they do not open a real OpenGL window.
