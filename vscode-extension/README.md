# Manim Studio Authoring Extension

This is a local desktop VS Code client for the Python authoring-session controller.

It starts `studio authoring rpc` as a local subprocess and sends JSON-lines requests over stdio. The extension keeps the controller and RPC protocol as the source of truth while providing a unified VS Code authoring workspace:

- Singleton `Manim Studio Preview` editor tab backed by rendered draft video artifacts
- Proposal controls in the preview panel: Preview, Accept, Revise, Reject
- Pause, Resume, Finish, render refresh, log, and terminal actions in the panel
- Dedicated `Manim Studio` integrated PowerShell terminal rooted at the workspace
- Embedded preview mode by default, with external OpenGL kept as an explicit fallback

Supported for this milestone:

- Local desktop VS Code
- Local Python environment with `studio` on `PATH`
- Workspace trust enabled

Unsupported or experimental:

- WSL workspaces
- Devcontainers
- Remote SSH/Codespaces
- Marketplace packaging

Run locally:

```powershell
cd vscode-extension
npm install
npm run compile
```

Then launch the extension from VS Code's extension development host.

Start with `Manim Studio: Open Authoring Workspace` or `Manim Studio: Start Authoring Session`. In the default `embedded` mode, normal authoring commands render a draft video and show it inside VS Code without opening an external OpenGL window. Set `manimStudio.previewMode` to `externalOpenGL` to use the legacy live preview workflow.

Research integrity, safe recovery and scoped ZIP export: **Manim Studio Research: Integrity, Recovery and Export**. See [Windows test guide](../docs/concepts/research-integrity.md).
