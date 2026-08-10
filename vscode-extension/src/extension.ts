import * as path from "path";
import * as vscode from "vscode";
import { StudioRpcClient, RpcResponse } from "./studioClient";

const ACTIVE_SESSION_KEY = "manimStudio.activeSessionId";
const NOTIFIED_PROPOSALS_KEY = "manimStudio.notifiedProposalIds";

let client: StudioRpcClient | undefined;
let output: vscode.OutputChannel;
let statusBar: vscode.StatusBarItem;
let extensionContext: vscode.ExtensionContext;
let proposalWatcher: vscode.FileSystemWatcher | undefined;
let discoveryTimer: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext): void {
  extensionContext = context;
  output = vscode.window.createOutputChannel("Manim Studio");
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.text = "Manim Studio: Ready";
  statusBar.command = "manimStudio.continueAuthoring";
  statusBar.show();

  const register = (command: string, handler: () => Promise<void>) => {
    context.subscriptions.push(vscode.commands.registerCommand(command, () => runSafely(handler)));
  };

  register("manimStudio.startAuthoringSession", startAuthoringSession);
  register("manimStudio.resumeLastSession", resumeLastSession);
  register("manimStudio.switchActiveSession", switchActiveSession);
  register("manimStudio.pauseSession", pauseSession);
  register("manimStudio.finishSession", finishSession);
  register("manimStudio.continueAuthoring", continueAuthoring);
  register("manimStudio.startLivePreview", () => sessionCommand("start_live"));
  register("manimStudio.previewActiveProposal", previewActiveProposal);
  register("manimStudio.acceptActiveProposal", acceptActiveProposal);
  register("manimStudio.rejectActiveProposal", rejectActiveProposal);
  register("manimStudio.reviseActiveProposal", reviseActiveProposal);
  register("manimStudio.restartLivePreview", () => sessionCommand("reload_live"));
  register("manimStudio.stopLivePreview", pauseSession);
  register("manimStudio.showSessionStatus", showSessionStatus);

  context.subscriptions.push(statusBar, output, { dispose: () => disposeClient() });
  startProposalDiscovery(context);
  void refreshActiveStatus();
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
  disposeClient();
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
    await setActiveSession(String(response.data.session_id));
    await handleResponse(await rpc().request("start_live", { session_id: response.data.session_id }));
  }
}

async function resumeLastSession(): Promise<void> {
  const sessionId = await activeSessionId();
  if (!sessionId) {
    await switchActiveSession();
    return;
  }
  await withProgress("Resuming Manim Studio session", () =>
    rpc().request("resume_session", { session_id: sessionId }).then(handleResponse),
  );
}

async function switchActiveSession(): Promise<void> {
  if (!(await ensureTrusted())) {
    return;
  }
  const response = await rpc().request("list_sessions");
  if (!response.ok) {
    await handleResponse(response);
    return;
  }
  const sessions = Array.isArray(response.data?.sessions) ? response.data.sessions : [];
  const picked = await vscode.window.showQuickPick(
    sessions.map((session) => {
      const item = session as Record<string, unknown>;
      return {
        label: String(item.title ?? item.session_id ?? ""),
        description: String(item.target ?? ""),
        detail: `${String(item.authoring_status ?? "")} | ${String(item.beat ?? "")} | ${String(item.updated_at ?? "")}`,
        sessionId: String(item.session_id ?? ""),
      };
    }),
    { placeHolder: "Switch active Manim Studio session" },
  );
  if (!picked?.sessionId) {
    return;
  }
  await setActiveSession(picked.sessionId);
  await refreshActiveStatus();
}

async function pauseSession(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  const status = await statusFor(sessionId);
  if (!status) {
    return;
  }
  let proposalPolicy = "keep";
  if (status.active_proposal_id) {
    const picked = await vscode.window.showQuickPick(
      [
        { label: "Keep proposal as draft and pause", policy: "keep" },
        { label: "Reject proposal and pause", policy: "reject" },
      ],
      { placeHolder: "Pause with active proposal" },
    );
    if (!picked) {
      return;
    }
    proposalPolicy = picked.policy;
  }
  await handleResponse(await rpc().request("pause_session", { session_id: sessionId, proposal_policy: proposalPolicy }));
}

async function finishSession(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  const status = await statusFor(sessionId);
  if (!status) {
    return;
  }
  if (status.active_proposal_id) {
    vscode.window.showWarningMessage("Resolve the active Manim proposal before finishing.");
    return;
  }
  await withProgress("Finishing Manim Studio session", () =>
    rpc().request("finish_session", { session_id: sessionId }).then(handleResponse),
  );
}

async function continueAuthoring(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  const status = await statusFor(sessionId);
  if (!status) {
    return;
  }
  switch (String(status.next_action ?? "")) {
    case "PREVIEW_PROPOSAL":
      await previewActiveProposal();
      break;
    case "ACCEPT_REVISE_OR_REJECT":
      await showDecisionQuickPick();
      break;
    case "RESUME_SESSION":
      await resumeLastSession();
      break;
    case "RETRY":
      await showRecoveryQuickPick();
      break;
    case "NONE":
      vscode.window.showInformationMessage("Manim Studio session is complete.");
      break;
    case "WAIT_FOR_PROPOSAL":
    default:
      await showSessionStatus();
      break;
  }
}

async function previewActiveProposal(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  await withProgress("Previewing Manim proposal", async () => {
    const preview = await rpc().request("preview_proposal", { session_id: sessionId });
    await handleResponse(preview);
    if (!preview.ok || preview.data?.live_status !== "STOPPED") {
      return;
    }
    await handleResponse(await rpc().request("start_live", { session_id: sessionId }));
  });
}

async function acceptActiveProposal(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  const confirmed = await vscode.window.showWarningMessage("Accept this Manim proposal?", { modal: true }, "Accept");
  if (confirmed !== "Accept") {
    return;
  }
  await withProgress("Accepting Manim proposal", () =>
    rpc().request("accept_proposal", { session_id: sessionId, confirm: "accept" }).then(handleResponse),
  );
}

async function rejectActiveProposal(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  await handleResponse(await rpc().request("reject_proposal", { session_id: sessionId }));
}

async function reviseActiveProposal(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  const feedback = await vscode.window.showInputBox({ prompt: "Revision feedback" });
  if (!feedback) {
    return;
  }
  await handleResponse(await rpc().request("revise_proposal", { session_id: sessionId, feedback }));
}

async function showSessionStatus(): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  await handleResponse(await rpc().request("get_status", { session_id: sessionId }));
  output.show(true);
}

async function sessionCommand(method: string): Promise<void> {
  const sessionId = await requireActiveSession();
  if (!sessionId) {
    return;
  }
  await handleResponse(await rpc().request(method, { session_id: sessionId }));
}

async function showDecisionQuickPick(): Promise<void> {
  const picked = await vscode.window.showQuickPick(["Accept", "Revise", "Reject", "Inspect"], {
    placeHolder: "Decide on the active Manim proposal",
  });
  if (picked === "Accept") {
    await acceptActiveProposal();
  } else if (picked === "Revise") {
    await reviseActiveProposal();
  } else if (picked === "Reject") {
    await rejectActiveProposal();
  } else if (picked === "Inspect") {
    await showSessionStatus();
  }
}

async function showRecoveryQuickPick(): Promise<void> {
  const picked = await vscode.window.showQuickPick(["Show Status", "Restart Live Preview", "Stop Session"], {
    placeHolder: "Recover Manim Studio session",
  });
  if (picked === "Show Status") {
    await showSessionStatus();
  } else if (picked === "Restart Live Preview") {
    await sessionCommand("reload_live");
  } else if (picked === "Stop Session") {
    await pauseSession();
  }
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
    await setActiveSession(sessionId);
  }
  updateStatus(data);
  output.appendLine(JSON.stringify(data));
}

export function statusText(data: Record<string, unknown>): string {
  const authoringStatus = String(data.authoring_status ?? "READY");
  const proposalStatus = String(data.proposal_status ?? "NONE");
  const beat = String(data.beat ?? "empty");
  if (authoringStatus === "ERROR") {
    return "Manim Studio: Error";
  }
  if (authoringStatus === "PAUSED") {
    return "Manim Studio: Paused";
  }
  if (authoringStatus === "COMPLETED") {
    return "Manim Studio: Complete";
  }
  if (proposalStatus === "PROPOSED" || proposalStatus === "NEEDS_REVISION") {
    return "Manim Studio: Proposal waiting";
  }
  if (proposalStatus === "PREVIEWED") {
    return `Manim Studio: Decision required | ${beat}`;
  }
  return `Manim Studio: Ready | ${beat}`;
}

function updateStatus(data: Record<string, unknown>): void {
  statusBar.text = statusText(data);
  statusBar.color =
    data.authoring_status === "ERROR" || data.live_status === "FAILED"
      ? new vscode.ThemeColor("errorForeground")
      : undefined;
}

async function statusFor(sessionId: string): Promise<Record<string, unknown> | undefined> {
  const response = await rpc().request("get_status", { session_id: sessionId });
  await handleResponse(response);
  return response.ok ? response.data : undefined;
}

async function refreshActiveStatus(): Promise<void> {
  const sessionId = await activeSessionId();
  if (!sessionId || !vscode.workspace.isTrusted) {
    return;
  }
  await statusFor(sessionId);
}

function startProposalDiscovery(context: vscode.ExtensionContext): void {
  const workspace = vscode.workspace.workspaceFolders?.[0];
  if (!workspace) {
    return;
  }
  const stagedPattern = new vscode.RelativePattern(workspace, path.join("builds", "staged", "*", "proposal.json"));
  proposalWatcher = vscode.workspace.createFileSystemWatcher(stagedPattern);
  const onChange = () => void discoverAndNotify();
  proposalWatcher.onDidCreate(onChange);
  proposalWatcher.onDidChange(onChange);
  context.subscriptions.push(proposalWatcher);
  discoveryTimer = setInterval(onChange, 5000);
  context.subscriptions.push({ dispose: () => discoveryTimer && clearInterval(discoveryTimer) });
}

async function discoverAndNotify(): Promise<void> {
  const sessionId = await activeSessionId();
  if (!sessionId || !vscode.workspace.isTrusted) {
    return;
  }
  const response = await rpc().request("discover_active_proposal", { session_id: sessionId });
  if (!response.ok) {
    output.appendLine(JSON.stringify(response.error));
    return;
  }
  await handleResponse(response);
  const proposalId = String(response.data?.active_proposal_id ?? "");
  if (!proposalId || response.data?.proposal_status !== "PROPOSED") {
    return;
  }
  const notified = new Set(extensionContext.workspaceState.get<string[]>(NOTIFIED_PROPOSALS_KEY, []));
  if (notified.has(proposalId)) {
    return;
  }
  notified.add(proposalId);
  await extensionContext.workspaceState.update(NOTIFIED_PROPOSALS_KEY, Array.from(notified).slice(-100));
  const title = String(response.data?.title ?? "New proposal");
  const action = await vscode.window.showInformationMessage(`New Manim proposal: ${title}`, "Preview", "Inspect", "Reject");
  if (action === "Preview") {
    await previewActiveProposal();
  } else if (action === "Inspect") {
    await showSessionStatus();
  } else if (action === "Reject") {
    await rejectActiveProposal();
  }
}

async function requireActiveSession(): Promise<string | undefined> {
  if (!(await ensureTrusted())) {
    return undefined;
  }
  const sessionId = await activeSessionId();
  if (sessionId) {
    return sessionId;
  }
  await switchActiveSession();
  return activeSessionId();
}

async function activeSessionId(): Promise<string | undefined> {
  return extensionContext.workspaceState.get<string>(ACTIVE_SESSION_KEY);
}

async function setActiveSession(sessionId: string): Promise<void> {
  await extensionContext.workspaceState.update(ACTIVE_SESSION_KEY, sessionId);
}

async function withProgress(title: string, task: () => Promise<void>): Promise<void> {
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title, cancellable: false },
    async () => task(),
  );
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
  const timeoutMs = config.get<number>("requestTimeoutMs") || 30000;
  client = new StudioRpcClient(
    workspace.uri.fsPath,
    executable,
    "catalog/scenes.yaml",
    (message) => output.appendLine(message),
    timeoutMs,
  );
  return client;
}

function disposeClient(): void {
  proposalWatcher?.dispose();
  if (discoveryTimer) {
    clearInterval(discoveryTimer);
    discoveryTimer = undefined;
  }
  client?.dispose();
  client = undefined;
}
