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
3. Run `Manim Studio: Start Authoring Session`.
4. Run `Manim Studio: Start Live Preview` and confirm the empty scene opens.
5. Create a Codex or MCP proposal that adds a red dot.
6. Run `Manim Studio: Preview Active Proposal` and enter the proposal ID.
7. Confirm the candidate result appears after live restart and the canonical
   scene file is unchanged.
8. Run `Manim Studio: Reject Active Proposal` and confirm live preview returns
   to `empty`.
9. Create a second proposal that adds a dot and a text label.
10. Preview and accept it.
11. Restart live preview and confirm the accepted `step_001` content remains
    visible.
12. Run:

```powershell
studio render <deck-id>/<scene-id> --profile draft --beat step_001
```

## Known Limits

- The extension is a command/status-bar MVP, not a webview or timeline UI.
- Live preview uses controlled process restart for this milestone.
- Remote workspaces, WSL, and devcontainers are not the supported path yet.
- Automated tests use fake live runners; they do not open a real OpenGL window.
