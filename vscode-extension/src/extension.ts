import * as vscode from "vscode";
import { ManimPreviewPanel } from "./previewPanel";
import { SessionCommandController } from "./sessionCommands";
import { StudioRpcClient } from "./studioClient";
import { TerminalManager } from "./terminalManager";

let client: StudioRpcClient | undefined;
let controller: SessionCommandController | undefined;
let terminal: TerminalManager | undefined;
let output: vscode.OutputChannel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Manim Studio");
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.text = "Manim Studio: Ready";
  statusBar.command = "manimStudio.continueAuthoring";
  statusBar.show();

  const workspace = vscode.workspace.workspaceFolders?.[0];
  if (!workspace) {
    context.subscriptions.push(statusBar, output);
    return;
  }

  client = createClient(workspace.uri.fsPath, output);
  terminal = new TerminalManager(workspace.uri.fsPath);
  const preview = new ManimPreviewPanel(context, workspace.uri.fsPath, (action) => {
    if (!controller) {
      return Promise.resolve();
    }
    return controller.handlePreviewAction(action);
  });
  controller = new SessionCommandController(context, output, statusBar, client, preview, terminal);
  controller.register(context);
  controller.startProposalDiscovery(workspace);

  context.subscriptions.push(statusBar, output, { dispose: () => disposeAll() });
  void controller.refreshActiveStatus();
}

export function deactivate(): void {
  disposeAll();
}

function createClient(repoRoot: string, log: vscode.OutputChannel): StudioRpcClient {
  const config = vscode.workspace.getConfiguration("manimStudio");
  const executable = config.get<string>("studioExecutable") || "studio";
  const timeoutMs = config.get<number>("requestTimeoutMs") || 30000;
  return new StudioRpcClient(repoRoot, executable, "catalog/scenes.yaml", (message) => log.appendLine(message), timeoutMs);
}

function disposeAll(): void {
  controller?.dispose();
  controller = undefined;
  client?.dispose();
  client = undefined;
  terminal?.dispose();
  terminal = undefined;
}
