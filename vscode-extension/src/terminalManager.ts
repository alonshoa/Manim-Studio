import { spawnSync } from "child_process";
import * as vscode from "vscode";

export type CommandExists = (command: string) => boolean;

export class TerminalManager {
  private terminal: vscode.Terminal | undefined;
  private shownOnce = false;
  private readonly researchTerminals = new Map<string, vscode.Terminal>();

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
    for (const terminal of this.researchTerminals.values()) {
      terminal.dispose();
    }
    this.researchTerminals.clear();
  }

  showResearch(sessionId: string, title: string, clientId: string, configuredShellPath = ""): void {
    let terminal = this.researchTerminals.get(sessionId);
    if (!terminal || terminal.exitStatus !== undefined) {
      terminal = vscode.window.createTerminal({
        name: `Research: ${title}`,
        cwd: this.workspaceRoot,
        shellPath: resolvePowerShellExecutable(configuredShellPath, process.platform, this.commandExists),
        env: { MANIM_STUDIO_RESEARCH_SESSION: sessionId, MANIM_STUDIO_RESEARCH_CLIENT: clientId,
          MANIM_STUDIO_RESEARCH_PROMPT: "" },
      });
      this.researchTerminals.set(sessionId, terminal);
    }
    terminal.show(false);
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
