import * as vscode from "vscode";
import { ManimPreviewPanel } from "./previewPanel";
import { SessionCommandController } from "./sessionCommands";
import { StudioRpcClient } from "./studioClient";
import { TerminalManager } from "./terminalManager";
import { ResearchCommandController } from "./researchCommands";
import { ArtifactsPanel } from "./artifactsPanel";
import { ClassificationPanel } from "./classificationPanel";

let client: StudioRpcClient | undefined;
let controller: SessionCommandController | undefined;
let terminal: TerminalManager | undefined;
let output: vscode.OutputChannel | undefined;
let research: ResearchCommandController | undefined;
let classifications: ClassificationPanel | undefined;
let artifacts: ArtifactsPanel | undefined;

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
  const researchBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
  research = new ResearchCommandController(context, client, terminal, researchBar, output);
  research.register();
  const config = vscode.workspace.getConfiguration("manimStudio");
  const annotationClient = new StudioRpcClient(workspace.uri.fsPath, config.get<string>("studioExecutable") || "studio",
    "catalog/scenes.yaml", message => output?.appendLine(message), 5000,
    config.get<Record<string, string>>("processEnv") || {}, "classification");
  classifications = new ClassificationPanel(context, annotationClient);
  classifications.register();
  const artifactsClient = new StudioRpcClient(workspace.uri.fsPath, config.get<string>("studioExecutable") || "studio",
    "catalog/scenes.yaml", message => output?.appendLine(message), 15000,
    config.get<Record<string, string>>("processEnv") || {}, "classification");
  artifacts = new ArtifactsPanel(context, artifactsClient);
  artifacts.register();
  const preview = new ManimPreviewPanel(context, workspace.uri.fsPath, (action) => {
    if (!controller) {
      return Promise.resolve();
    }
    return controller.handlePreviewAction(action);
  }, async state => {
    if(state.researchSessionId && state.buildId) await artifacts?.recordPresentation(state.researchSessionId,state.buildId);
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
  const environment = config.get<Record<string, string>>("processEnv") || {};
  return new StudioRpcClient(repoRoot, executable, "catalog/scenes.yaml", (message) => log.appendLine(message), timeoutMs, environment);
}

function disposeAll(): void {
  artifacts?.dispose(); artifacts = undefined;
  classifications?.dispose(); classifications = undefined;
  research?.dispose();
  research = undefined;
  controller?.dispose();
  controller = undefined;
  client?.dispose();
  client = undefined;
  terminal?.dispose();
  terminal = undefined;
}
