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
3. Run `Manim Studio: Start Authoring Session`; confirm it becomes the active
   workspace session and live preview opens.
4. Ask Codex through MCP to call `propose_next_movie_step` and append a title.
5. Confirm VS Code shows one proposal notification.
6. Choose `Preview`; do not enter a session ID or proposal ID.
7. Confirm the candidate result appears after live restart and the canonical
   scene file is unchanged.
8. Choose `Reject` and confirm live preview returns to `empty`.
9. Ask Codex for a revised title proposal.
10. Preview and accept it.
11. Confirm the status bar returns to `Manim Studio: Ready | step_001`.
12. Create and accept a second visual step.
13. Run `Manim Studio: Pause Session`.
14. Restart VS Code.
15. Run `Manim Studio: Resume Last Session` and confirm the last accepted beat
    is restored.
16. Create a proposal, preview it, and run `Manim Studio: Revise Active
    Proposal` with Hebrew feedback.
17. Confirm the revision feedback appears in `get_authoring_session_status`.
18. Resolve the proposal.
19. Run `Manim Studio: Finish Session` and confirm the Cairo draft render
    succeeds and the session becomes `COMPLETED`.
20. Optionally run:

```powershell
studio render <deck-id>/<scene-id> --profile draft --beat step_001
```

## Known Limits

- The extension is a command/status-bar MVP, not a webview or timeline UI.
- Live preview uses controlled process restart for this milestone.
- Extension shutdown stops the extension-owned RPC process. Live preview process
  state is refreshed from persisted PID status when a session is active.
- Remote workspaces, WSL, and devcontainers are not the supported path yet.
- Automated tests use fake live runners; they do not open a real OpenGL window.
