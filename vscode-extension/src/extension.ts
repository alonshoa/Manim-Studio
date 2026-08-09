import * as vscode from "vscode";
import { StudioRpcClient, RpcResponse } from "./studioClient";

let client: StudioRpcClient | undefined;
let output: vscode.OutputChannel;
let statusBar: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Manim Studio");
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.text = "Manim Studio: stopped";
  statusBar.command = "manimStudio.showSessionStatus";
  statusBar.show();

  const register = (command: string, handler: () => Promise<void>) => {
    context.subscriptions.push(vscode.commands.registerCommand(command, () => runSafely(handler)));
  };

  register("manimStudio.startAuthoringSession", startAuthoringSession);
  register("manimStudio.startLivePreview", () => sessionCommand("start_live"));
  register("manimStudio.previewActiveProposal", previewActiveProposal);
  register("manimStudio.acceptActiveProposal", acceptActiveProposal);
  register("manimStudio.rejectActiveProposal", rejectActiveProposal);
  register("manimStudio.restartLivePreview", () => sessionCommand("reload_live"));
  register("manimStudio.stopLivePreview", () => sessionCommand("stop_live"));
  register("manimStudio.showSessionStatus", showSessionStatus);
  context.subscriptions.push(statusBar, output, { dispose: () => client?.dispose() });
}

async function runSafely(handler: () => Promise<void>): Promise<void> {
  try {
    await handler();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`Command failed: ${message}`);
    vscode.window.showErrorMessage(`${message}. See Manim Studio output for details.`);
  }
}

export function deactivate(): void {
  client?.dispose();
}

async function startAuthoringSession(): Promise<void> {
  if (!(await ensureTrusted())) {
    return;
  }
  const title = await vscode.window.showInputBox({ prompt: "Session title", value: "Interactive Movie" });
  if (!title) {
    return;
  }
  const deckId = await vscode.window.showInputBox({ prompt: "Deck ID", value: "interactive" });
  if (!deckId) {
    return;
  }
  const response = await rpc().request("start_session", { title, deck_id: deckId });
  await handleResponse(response);
  if (response.ok && response.data?.session_id) {
    await handleResponse(await rpc().request("start_live", { session_id: response.data.session_id }));
  }
}

async function previewActiveProposal(): Promise<void> {
  const sessionId = await requireSessionId();
  const proposalId = sessionId ? await pickProposalId(sessionId, "Proposal to preview") : undefined;
  if (!sessionId || !proposalId) {
    return;
  }
  await handleResponse(await rpc().request("preview_proposal", { session_id: sessionId, proposal_id: proposalId }));
}

async function acceptActiveProposal(): Promise<void> {
  const sessionId = await requireSessionId();
  const proposalId = sessionId ? await activeOrPickedProposalId(sessionId, "Proposal to accept") : undefined;
  if (!sessionId || !proposalId) {
    return;
  }
  await handleResponse(
    await rpc().request("accept_proposal", { session_id: sessionId, proposal_id: proposalId, confirm: "accept" }),
  );
}

async function rejectActiveProposal(): Promise<void> {
  const sessionId = await requireSessionId();
  if (!sessionId) {
    return;
  }
  await handleResponse(await rpc().request("reject_proposal", { session_id: sessionId }));
}

async function showSessionStatus(): Promise<void> {
  const sessionId = await requireSessionId();
  if (!sessionId) {
    return;
  }
  await handleResponse(await rpc().request("get_status", { session_id: sessionId }));
  output.show(true);
}

async function sessionCommand(method: string): Promise<void> {
  const sessionId = await requireSessionId();
  if (!sessionId) {
    return;
  }
  await handleResponse(await rpc().request(method, { session_id: sessionId }));
}

async function handleResponse(response: RpcResponse): Promise<void> {
  if (!response.ok) {
    const message = response.error?.message ?? "Studio command failed";
    vscode.window.showErrorMessage(`${message}. See Manim Studio output for details.`);
    output.appendLine(JSON.stringify(response.error));
    return;
  }
  const data = response.data ?? {};
  const sessionId = String(data.session_id ?? "");
  if (sessionId) {
    await vscode.workspace.getConfiguration("manimStudio").update("lastSessionId", sessionId, vscode.ConfigurationTarget.Workspace);
  }
  updateStatus(data);
  output.appendLine(JSON.stringify(data));
}

function updateStatus(data: Record<string, unknown>): void {
  const liveStatus = String(data.live_status ?? data.status ?? "stopped");
  const beat = String(data.beat ?? "empty");
  const liveStates = new Set(["running", "starting", "reloading"]);
  const isLive = liveStates.has(liveStatus);

  statusBar.text = isLive
    ? `$(primitive-dot) Manim Studio: ${liveStatus} ${beat}`
    : `Manim Studio: ${liveStatus} ${beat}`;
  statusBar.color = liveStatus === "failed" ? new vscode.ThemeColor("errorForeground") : undefined;
}

async function requireSessionId(): Promise<string | undefined> {
  if (!(await ensureTrusted())) {
    return undefined;
  }
  const config = vscode.workspace.getConfiguration("manimStudio");
  const existing = config.get<string>("lastSessionId") ?? "";
  return vscode.window.showInputBox({ prompt: "Authoring session ID", value: existing });
}

async function activeOrPickedProposalId(sessionId: string, placeHolder: string): Promise<string | undefined> {
  const status = await rpc().request("get_status", { session_id: sessionId });
  if (status.ok && typeof status.data?.proposal_id === "string" && status.data.proposal_id) {
    return status.data.proposal_id;
  }
  return pickProposalId(sessionId, placeHolder);
}

async function pickProposalId(sessionId: string, placeHolder: string): Promise<string | undefined> {
  const response = await rpc().request("list_proposals", { session_id: sessionId });
  if (!response.ok) {
    await handleResponse(response);
    return undefined;
  }
  const proposals = Array.isArray(response.data?.proposals) ? response.data.proposals : [];
  if (proposals.length === 0) {
    return vscode.window.showInputBox({ prompt: `${placeHolder} ID` });
  }
  const picked = await vscode.window.showQuickPick(
    proposals.map((proposal) => {
      const item = proposal as Record<string, unknown>;
      const proposalId = String(item.proposal_id ?? "");
      const detailParts = [
        String(item.changed_lines ?? ""),
        String(item.validation_status ?? ""),
        String(item.draft_render_status ?? ""),
      ].filter((part) => part.length > 0);
      return {
        label: proposalId,
        description: String(item.rationale ?? ""),
        detail: detailParts.join(" | "),
      };
    }),
    { placeHolder },
  );
  return picked?.label;
}

async function ensureTrusted(): Promise<boolean> {
  if (vscode.workspace.isTrusted) {
    return true;
  }
  vscode.window.showErrorMessage("Trust this workspace before running local Manim Studio authoring commands.");
  return false;
}

function rpc(): StudioRpcClient {
  if (client) {
    return client;
  }
  const workspace = vscode.workspace.workspaceFolders?.[0];
  if (!workspace) {
    throw new Error("Open a Manim Studio workspace first");
  }
  const config = vscode.workspace.getConfiguration("manimStudio");
  const executable = config.get<string>("studioExecutable") || "studio";
  client = new StudioRpcClient(workspace.uri.fsPath, executable, "catalog/scenes.yaml", (message) => output.appendLine(message));
  return client;
}
