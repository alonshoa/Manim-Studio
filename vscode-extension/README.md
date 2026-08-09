# Manim Studio Authoring Extension

This is a thin local desktop VS Code client for the Python authoring-session controller.

It starts `studio authoring rpc` as a local subprocess and sends JSON-lines requests over stdio. It does not use a webview, hidden integrated terminal, or network port.

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
