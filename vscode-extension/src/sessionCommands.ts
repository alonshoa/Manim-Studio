import * as vscode from "vscode";
import { ManimPreviewPanel, PreviewAction, logPathsFromError } from "./previewPanel";
import { RpcResponse, StudioRpcClient } from "./studioClient";
import { TerminalManager } from "./terminalManager";

const ACTIVE_SESSION_KEY = "manimStudio.activeSessionId";
const NOTIFIED_PROPOSALS_KEY = "manimStudio.notifiedProposalIds";

type RenderRequestIdentity = {
  sessionId: string;
  proposalId: string | null;
  revision: number | undefined;
  beat: string | undefined;
};

export class SessionCommandController {
  private proposalWatcher: vscode.FileSystemWatcher | undefined;
  private discoveryTimer: NodeJS.Timeout | undefined;
  private discoveryInFlight = false;
  private renderInFlight = false;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly output: vscode.OutputChannel,
    private readonly statusBar: vscode.StatusBarItem,
    private readonly rpc: StudioRpcClient,
    private readonly preview: ManimPreviewPanel,
    private readonly terminal: TerminalManager,
  ) {}

  register(context: vscode.ExtensionContext): void {
    const register = (command: string, handler: () => Promise<void>) => {
      context.subscriptions.push(vscode.commands.registerCommand(command, () => this.runSafely(handler)));
    };
    register("manimStudio.startAuthoringSession", () => this.startAuthoringSession());
    register("manimStudio.resumeLastSession", () => this.resumeLastSession());
    register("manimStudio.switchActiveSession", () => this.switchActiveSession());
    register("manimStudio.pauseSession", () => this.pauseSession());
    register("manimStudio.finishSession", () => this.finishSession());
    register("manimStudio.continueAuthoring", () => this.continueAuthoring());
    register("manimStudio.startLivePreview", () => this.sessionCommand("start_live"));
    register("manimStudio.previewActiveProposal", () => this.previewActiveProposal());
    register("manimStudio.acceptActiveProposal", () => this.acceptActiveProposal());
    register("manimStudio.rejectActiveProposal", () => this.rejectActiveProposal());
    register("manimStudio.reviseActiveProposal", () => this.reviseActiveProposal());
    register("manimStudio.restartLivePreview", () => this.sessionCommand("reload_live"));
    register("manimStudio.stopLivePreview", () => this.sessionCommand("stop_live"));
    register("manimStudio.showSessionStatus", () => this.showSessionStatus());
    register("manimStudio.openWorkspace", () => this.openWorkspace());
    register("manimStudio.openTerminal", () => this.openTerminal());
    register("manimStudio.refreshPreview", () => this.renderActivePreview());
  }

  startProposalDiscovery(workspace: vscode.WorkspaceFolder): void {
    this.proposalWatcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(workspace, "builds/staged/*/proposal.json"),
    );
    const onChange = () => void this.discoverAndNotify();
    this.proposalWatcher.onDidCreate(onChange);
    this.proposalWatcher.onDidChange(onChange);
    this.context.subscriptions.push(this.proposalWatcher);
    this.discoveryTimer = setInterval(onChange, 5000);
    this.context.subscriptions.push({ dispose: () => this.discoveryTimer && clearInterval(this.discoveryTimer) });
  }

  async refreshActiveStatus(): Promise<void> {
    const sessionId = await this.activeSessionId();
    if (!sessionId || !vscode.workspace.isTrusted) {
      return;
    }
    await this.statusFor(sessionId);
  }

  async handlePreviewAction(action: PreviewAction): Promise<void> {
    await this.runSafely(async () => {
      switch (action) {
        case "render":
          await this.renderActivePreview();
          break;
        case "accept":
          await this.acceptActiveProposal();
          break;
        case "revise":
          await this.reviseActiveProposal();
          break;
        case "reject":
          await this.rejectActiveProposal();
          break;
        case "pause":
          await this.pauseSession();
          break;
        case "resume":
          await this.resumeLastSession();
          break;
        case "finish":
          await this.finishSession();
          break;
        case "terminal":
          await this.openTerminal();
          break;
        case "logs":
          await this.openLogs();
          break;
      }
    });
  }

  dispose(): void {
    this.proposalWatcher?.dispose();
    if (this.discoveryTimer) {
      clearInterval(this.discoveryTimer);
      this.discoveryTimer = undefined;
    }
  }

  private async startAuthoringSession(): Promise<void> {
    if (!(await this.ensureTrusted())) {
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
    const response = await this.rpc.request("start_session", { title, deck_id: deckId });
    await this.handleResponse(response);
    if (response.ok) {
      if (this.previewMode() === "externalOpenGL" && response.data?.session_id) {
        await this.handleResponse(await this.rpc.request("start_live", { session_id: response.data.session_id }));
      }
      await this.openWorkspace();
      await this.afterStateChange(response.data ?? {});
    }
  }

  private async resumeLastSession(): Promise<void> {
    const sessionId = await this.activeSessionId();
    if (!sessionId) {
      await this.switchActiveSession();
      return;
    }
    const response = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Resuming Manim Studio session", cancellable: false },
      () => this.rpc.request("resume_session", { session_id: sessionId, start_live: this.previewMode() === "externalOpenGL" }),
    );
    await this.handleResponse(response);
    if (response.ok) {
      await this.openWorkspace();
      await this.afterStateChange(response.data ?? {});
    }
  }

  private async switchActiveSession(): Promise<void> {
    if (!(await this.ensureTrusted())) {
      return;
    }
    const response = await this.rpc.request("list_sessions");
    if (!response.ok) {
      await this.handleResponse(response);
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
    await this.setActiveSession(picked.sessionId);
    await this.refreshActiveStatus();
  }

  private async pauseSession(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const status = await this.statusFor(sessionId);
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
    await this.handleResponse(await this.rpc.request("pause_session", { session_id: sessionId, proposal_policy: proposalPolicy }));
  }

  private async finishSession(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const status = await this.statusFor(sessionId);
    if (!status) {
      return;
    }
    if (status.active_proposal_id) {
      vscode.window.showWarningMessage("Resolve the active Manim proposal before finishing.");
      return;
    }
    const response = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Finishing Manim Studio session", cancellable: false },
      () => this.rpc.request("finish_session", { session_id: sessionId }, this.renderTimeoutMs()),
    );
    await this.handleResponse(response);
  }

  private async continueAuthoring(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const status = await this.statusFor(sessionId);
    if (!status) {
      return;
    }
    switch (String(status.next_action ?? "")) {
      case "PREVIEW_PROPOSAL":
        await this.previewActiveProposal();
        break;
      case "ACCEPT_REVISE_OR_REJECT":
        await this.preview.show();
        break;
      case "RESUME_SESSION":
        await this.resumeLastSession();
        break;
      case "RETRY":
        await this.showSessionStatus();
        break;
      case "NONE":
        vscode.window.showInformationMessage("Manim Studio session is complete.");
        break;
      default:
        await this.showSessionStatus();
        break;
    }
  }

  private async previewActiveProposal(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const response = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Previewing Manim proposal", cancellable: false },
      () => this.rpc.request("preview_proposal", { session_id: sessionId }),
    );
    await this.handleResponse(response);
    if (!response.ok) {
      return;
    }
    if (this.previewMode() === "externalOpenGL" && response.data?.live_status === "STOPPED") {
      await this.handleResponse(await this.rpc.request("start_live", { session_id: sessionId }));
      return;
    }
    await this.renderActivePreview();
  }

  private async acceptActiveProposal(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const confirmed = await vscode.window.showWarningMessage("Accept this Manim proposal?", { modal: true }, "Accept");
    if (confirmed !== "Accept") {
      return;
    }
    const response = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Accepting Manim proposal", cancellable: false },
      () => this.rpc.request("accept_proposal", { session_id: sessionId, confirm: "accept" }, this.renderTimeoutMs()),
    );
    await this.handleResponse(response);
    if (response.ok) {
      await this.afterStateChange(response.data ?? {});
    }
  }

  private async rejectActiveProposal(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const response = await this.rpc.request("reject_proposal", { session_id: sessionId });
    await this.handleResponse(response);
    if (response.ok) {
      await this.afterStateChange(response.data ?? {});
    }
  }

  private async reviseActiveProposal(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const feedback = await vscode.window.showInputBox({ prompt: "Revision feedback" });
    if (!feedback) {
      return;
    }
    const response = await this.rpc.request("revise_proposal", { session_id: sessionId, feedback });
    await this.handleResponse(response);
  }

  private async showSessionStatus(): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    await this.handleResponse(await this.rpc.request("get_status", { session_id: sessionId }));
    this.output.show(true);
  }

  private async openWorkspace(): Promise<void> {
    if (!(await this.ensureTrusted())) {
      return;
    }
    this.preview.show();
    this.terminal.showOnce(this.autoOpenTerminal(), this.powerShellExecutable());
  }

  private async openTerminal(): Promise<void> {
    this.terminal.show(this.powerShellExecutable());
  }

  private async openLogs(): Promise<void> {
    for (const filePath of logPathsFromError(this.preview.currentState().renderError)) {
      try {
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        await vscode.window.showTextDocument(document, { preview: true });
        return;
      } catch {
        // Try the next log path.
      }
    }
    vscode.window.showInformationMessage("No preview render logs are available yet.");
  }

  private async renderActivePreview(): Promise<void> {
    if (this.renderInFlight) {
      return;
    }
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    const status = await this.statusFor(sessionId);
    if (!status) {
      return;
    }
    const expected = identityFromStatus(status);
    const researchContext = this.rpc.getResearchContext?.();
    this.renderInFlight = true;
    this.preview.show();
    this.preview.setRendering(status);
    try {
      const response = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Rendering Manim preview", cancellable: false },
        () => this.rpc.request("render_authoring_preview", { session_id: sessionId }, this.renderTimeoutMs()),
      );
      if (!response.ok) {
        await this.handleResponse(response);
        this.preview.setError(response.error?.message ?? "Preview render failed", response.error?.detail);
        return;
      }
      if (shouldApplyRenderResult(expected, response.data ?? {}, await this.activeSessionId())) {
        this.preview.updateRender({...response.data, research_session_id: researchContext?.session_id});
        this.output.appendLine(JSON.stringify(response.data));
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.preview.setError(message);
      vscode.window.showErrorMessage(`${message}. See Manim Studio output for details.`);
      this.output.appendLine(`Preview render failed: ${message}`);
    } finally {
      this.renderInFlight = false;
    }
  }

  private async afterStateChange(data: Record<string, unknown>): Promise<void> {
    if (this.previewMode() === "embedded" && data.authoring_status !== "PAUSED" && data.authoring_status !== "COMPLETED") {
      await this.renderActivePreview();
    }
  }

  private async sessionCommand(method: string): Promise<void> {
    const sessionId = await this.requireActiveSession();
    if (!sessionId) {
      return;
    }
    await this.handleResponse(await this.rpc.request(method, { session_id: sessionId }));
  }

  private async discoverAndNotify(): Promise<void> {
    if (this.discoveryInFlight) {
      return;
    }
    this.discoveryInFlight = true;
    try {
      const sessionId = await this.activeSessionId();
      if (!sessionId || !vscode.workspace.isTrusted) {
        return;
      }
      const response = await this.rpc.request("discover_active_proposal", { session_id: sessionId });
      if (!response.ok) {
        this.output.appendLine(JSON.stringify(response.error));
        return;
      }
      await this.handleResponse(response);
      const proposalId = String(response.data?.active_proposal_id ?? "");
      if (!proposalId || response.data?.proposal_status !== "PROPOSED") {
        return;
      }
      this.preview.show();
      const notified = new Set(this.context.workspaceState.get<string[]>(NOTIFIED_PROPOSALS_KEY, []));
      if (notified.has(proposalId)) {
        return;
      }
      notified.add(proposalId);
      await this.context.workspaceState.update(NOTIFIED_PROPOSALS_KEY, Array.from(notified).slice(-100));
      const title = String(response.data?.title ?? "New proposal");
      const action = await vscode.window.showInformationMessage(`New Manim proposal: ${title}`, "Preview", "Inspect", "Reject");
      if (action === "Preview") {
        await this.previewActiveProposal();
      } else if (action === "Inspect") {
        await this.showSessionStatus();
      } else if (action === "Reject") {
        await this.rejectActiveProposal();
      }
    } finally {
      this.discoveryInFlight = false;
    }
  }

  private async statusFor(sessionId: string): Promise<Record<string, unknown> | undefined> {
    const response = await this.rpc.request("get_status", { session_id: sessionId });
    await this.handleResponse(response);
    return response.ok ? response.data : undefined;
  }

  private async handleResponse(response: RpcResponse): Promise<void> {
    if (!response.ok) {
      const message = response.error?.message ?? "Studio command failed";
      vscode.window.showErrorMessage(`${message}. See Manim Studio output for details.`);
      this.output.appendLine(JSON.stringify(response.error));
      return;
    }
    const data = response.data ?? {};
    const sessionId = String(data.session_id ?? "");
    if (sessionId) {
      await this.setActiveSession(sessionId);
    }
    this.updateStatus(data);
    this.preview.updateSession(data);
    this.output.appendLine(JSON.stringify(data));
  }

  private updateStatus(data: Record<string, unknown>): void {
    this.statusBar.text = statusText(data);
    this.statusBar.color =
      data.authoring_status === "ERROR" || data.live_status === "FAILED"
        ? new vscode.ThemeColor("errorForeground")
        : undefined;
  }

  private async requireActiveSession(): Promise<string | undefined> {
    if (!(await this.ensureTrusted())) {
      return undefined;
    }
    const sessionId = await this.activeSessionId();
    if (sessionId) {
      return sessionId;
    }
    await this.switchActiveSession();
    return this.activeSessionId();
  }

  private async activeSessionId(): Promise<string | undefined> {
    return this.context.workspaceState.get<string>(ACTIVE_SESSION_KEY);
  }

  private async setActiveSession(sessionId: string): Promise<void> {
    await this.context.workspaceState.update(ACTIVE_SESSION_KEY, sessionId);
  }

  private async ensureTrusted(): Promise<boolean> {
    if (vscode.workspace.isTrusted) {
      return true;
    }
    vscode.window.showErrorMessage("Trust this workspace before running local Manim Studio authoring commands.");
    return false;
  }

  private async runSafely(handler: () => Promise<void>): Promise<void> {
    try {
      await handler();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.output.appendLine(`Command failed: ${message}`);
      vscode.window.showErrorMessage(`${message}. See Manim Studio output for details.`);
    }
  }

  private previewMode(): string {
    return vscode.workspace.getConfiguration("manimStudio").get<string>("previewMode") || "embedded";
  }

  private renderTimeoutMs(): number {
    return vscode.workspace.getConfiguration("manimStudio").get<number>("renderRequestTimeoutMs") || 180000;
  }

  private powerShellExecutable(): string {
    return vscode.workspace.getConfiguration("manimStudio").get<string>("powerShellExecutable") || "";
  }

  private autoOpenTerminal(): boolean {
    return vscode.workspace.getConfiguration("manimStudio").get<boolean>("openTerminalOnSessionStart") ?? true;
  }
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

export function shouldApplyRenderResult(
  expected: RenderRequestIdentity,
  result: Record<string, unknown>,
  activeSessionId: string | undefined,
): boolean {
  if (!activeSessionId || result.session_id !== activeSessionId || result.session_id !== expected.sessionId) {
    return false;
  }
  const resultProposal = result.proposal_id === null || result.proposal_id === undefined ? null : String(result.proposal_id);
  if (resultProposal !== expected.proposalId) {
    return false;
  }
  if (typeof result.revision === "number" && expected.revision !== undefined && result.revision !== expected.revision) {
    return false;
  }
  if (typeof result.beat === "string" && expected.beat && result.beat !== expected.beat) {
    return false;
  }
  return true;
}

function identityFromStatus(status: Record<string, unknown>): RenderRequestIdentity {
  const proposalId =
    status.proposal_status === "PREVIEWED" && (status.active_proposal_id || status.proposal_id)
      ? String(status.active_proposal_id ?? status.proposal_id)
      : null;
  return {
    sessionId: String(status.session_id ?? ""),
    proposalId,
    revision: typeof status.revision === "number" ? status.revision : undefined,
    beat: typeof status.beat === "string" ? status.beat : undefined,
  };
}
