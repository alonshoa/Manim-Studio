import { spawnSync } from "child_process";
import * as vscode from "vscode";

export type CommandExists = (command: string) => boolean;

export class TerminalManager {
  private terminal: vscode.Terminal | undefined;
  private shownOnce = false;

  constructor(
    private readonly workspaceRoot: string,
    private readonly commandExists: CommandExists = defaultCommandExists,
  ) {}

  show(configuredShellPath = ""): void {
    if (!this.terminal) {
      this.terminal = vscode.window.createTerminal({
        name: "Manim Studio",
        cwd: this.workspaceRoot,
        shellPath: resolvePowerShellExecutable(configuredShellPath, process.platform, this.commandExists),
      });
    }
    this.terminal.show(false);
    this.shownOnce = true;
  }

  showOnce(enabled: boolean, configuredShellPath = ""): void {
    if (!enabled || this.shownOnce) {
      return;
    }
    this.show(configuredShellPath);
  }

  dispose(): void {
    this.terminal?.dispose();
    this.terminal = undefined;
    this.shownOnce = false;
  }
}

export function resolvePowerShellExecutable(
  configuredShellPath: string | undefined,
  platform: NodeJS.Platform,
  commandExists: CommandExists,
): string {
  if (configuredShellPath?.trim()) {
    return configuredShellPath.trim();
  }
  if (platform === "win32") {
    return commandExists("pwsh.exe") ? "pwsh.exe" : "powershell.exe";
  }
  return commandExists("pwsh") ? "pwsh" : "powershell";
}

function defaultCommandExists(command: string): boolean {
  const probe = process.platform === "win32" ? "where.exe" : "which";
  const result = spawnSync(probe, [command], { stdio: "ignore" });
  return result.status === 0;
}
