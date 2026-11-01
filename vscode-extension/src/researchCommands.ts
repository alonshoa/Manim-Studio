import * as vscode from "vscode";
import { randomUUID } from "crypto";
import { StudioRpcClient } from "./studioClient";
import { TerminalManager } from "./terminalManager";

const SELECTED = "manimStudio.selectedResearchSession";
const PENDING = "manimStudio.pendingResearchRequests";
type Session = {
  session_id: string; title: string; topic: string; state: string; revision: number;
  sources: Array<{ source_id: string; thread_id: string; connected: number; last_hook_at: string }>;
  capture: Array<{ capture_status: string; gap_count: number; last_hook_at: string }>;
  counts: Record<string, number>; incomplete_actions: number; collection_enabled: boolean;
  clients?: Array<{client_id: string; client_type: string}>;
  observed_at: string; unassigned_failure_count?: number;
};
type Pending = { method: string; params: Record<string, unknown> };

export class ResearchCommandController {
  private selected: string | undefined;
  private status: Session | undefined;
  private refreshing = false;
  private busy = false;
  private panel: vscode.WebviewPanel | undefined;
  private timer: NodeJS.Timeout | undefined;
  private readonly clients = new Map<string, string>();
  private readonly terminalClients = new Map<string, string>();
  private warnedParallel = false;
  private disposed = false;
  private selectionGeneration = 0;

  constructor(private readonly context: vscode.ExtensionContext,
    private readonly rpc: StudioRpcClient, private readonly terminal: TerminalManager,
    private readonly bar: vscode.StatusBarItem, private readonly output: vscode.OutputChannel) {
    this.selected = context.workspaceState.get<string>(SELECTED);
  }

  register(): void {
    const handlers: Record<string, () => Promise<void>> = {
      startSession: () => this.startSession(), selectSession: () => this.selectSession(),
      attachSource: () => this.attachSource(), pauseSession: () => this.transition("pause"),
      resumeSession: () => this.transition("resume"), finishSession: () => this.transition("finish"),
      showStatus: () => this.showStatus(), openTerminal: () => this.openTerminal(),
      retryPending: () => this.retryPending(), menu: () => this.menu(),
    };
    for (const [name, handler] of Object.entries(handlers)) {
      this.context.subscriptions.push(vscode.commands.registerCommand(`manimStudio.research.${name}`,
        () => this.run(handler)));
    }
    this.bar.command = "manimStudio.research.menu";
    this.bar.text = "Research: No session";
    this.bar.show();
    this.timer = setInterval(() => {
      if (!vscode.window.state || vscode.window.state.focused) { void this.refresh(); }
    }, 5000);
    this.context.subscriptions.push({ dispose: () => this.dispose() });
    void this.restore();
  }

  private async run(handler: () => Promise<void>): Promise<void> {
    if (!vscode.workspace.isTrusted || this.busy || this.disposed) { return; }
    this.busy = true;
    try { await handler(); }
    catch (error) {
      if (this.disposed) { return; }
      this.markStale();
      this.output.appendLine(`Research: ${String(error)}`);
      void vscode.window.showErrorMessage(`Research: ${String(error)}. Refresh status or retry a pending action.`);
    } finally { this.busy = false; }
  }

  private async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const response = await this.rpc.request(`research.${method}`, params);
    if (!response.ok) { throw new Error(`${response.error?.code ?? "request_failed"}: ${response.error?.message ?? "Research request failed"}`); }
    return response.data as T;
  }

  private async mutate(method: string, params: Record<string, unknown>, requestId: string = randomUUID()): Promise<Session> {
    const pending = { ...(this.context.workspaceState.get<Record<string, Pending>>(PENDING) ?? {}) };
    const argumentsWithId = { ...params, request_id: requestId };
    pending[requestId] = { method, params: argumentsWithId };
    await this.context.workspaceState.update(PENDING, pending);
    // A transport failure leaves this exact request durable for safe retry.
    const response = await this.rpc.request(`research.${method}`, argumentsWithId);
    const remaining = { ...(this.context.workspaceState.get<Record<string, Pending>>(PENDING) ?? {}) };
    delete remaining[requestId];
    await this.context.workspaceState.update(PENDING, remaining);
    if (!response.ok) { throw new Error(`${response.error?.code}: ${response.error?.message}`); }
    return response.data as unknown as Session;
  }

  async restore(): Promise<void> {
    if (!vscode.workspace.isTrusted || !this.selected || this.disposed) { return; }
    const selected = this.selected, generation = this.selectionGeneration;
    try {
      const status = await this.request<Session>("get", { session_id: selected });
      if (this.selected === selected && generation === this.selectionGeneration && !this.disposed) {
        await this.select(status);
      }
    }
    catch (error) {
      if (this.selected !== selected || generation !== this.selectionGeneration || this.disposed) { return; }
      this.rpc.setResearchContext(undefined);
      if (String(error).includes("session_not_found")) {
        this.selected = undefined;
        await this.context.workspaceState.update(SELECTED, undefined);
      }
      // Do not erase a durable selection just because storage/transport is down.
      this.markStale();
      this.output.appendLine(`Research restore: ${String(error)}`);
    }
  }

  async refresh(): Promise<void> {
    if (this.refreshing || this.busy || this.disposed || !vscode.workspace.isTrusted || !this.selected) { return; }
    const selected = this.selected;
    this.refreshing = true;
    try {
      const status = await this.request<Session>("status", { session_id: selected });
      if (!this.disposed && selected === this.selected && (!this.status || status.revision >= this.status.revision)) {
        this.apply(status);
      }
    } catch { if (!this.disposed && selected === this.selected) { this.markStale(); } }
    finally { this.refreshing = false; }
  }

  private apply(status: Session): void {
    if (this.disposed) { return; }
    this.status = status;
    const hint = status.state === "finished" ? "" : !status.collection_enabled ? "collection off"
      : !status.sources.length ? "waiting for conversation" : "";
    this.bar.text = `Research: ${status.title} · ${status.state}${hint ? ` · ${hint}` : ""}`;
    this.bar.tooltip = `${status.topic} | ${status.state} | ${status.capture.map(s => s.capture_status).join(", ") || "Delivery unverified"}`;
    if (this.panel) { this.panel.webview.html = statusHtml(status); }
  }

  private markStale(): void {
    this.bar.text = "Research: Status not current";
    this.bar.tooltip = "The latest state could not be verified. Last displayed state is not proof of collection.";
    if (this.panel) { this.panel.webview.html = "<p>Research status is not current. Refresh after restoring the connection.</p>"; }
  }

  private async select(status: Session): Promise<void> {
    const generation = ++this.selectionGeneration;
    let clientId = this.clients.get(status.session_id);
    if (status.state !== "finished") {
      if (!clientId) {
        clientId = randomUUID();
        await this.mutate("bind_client", { session_id: status.session_id, client_id: clientId, client_type: "rpc" });
        this.clients.set(status.session_id, clientId);
      }
    }
    if (this.disposed || generation !== this.selectionGeneration) { return; }
    this.rpc.setResearchContext(status.state === "finished" ? undefined : { session_id: status.session_id, client_id: clientId! });
    this.selected = status.session_id;
    await this.context.workspaceState.update(SELECTED, this.selected);
    this.apply(status);
  }

  private async titleAndTopic(defaultTitle = "Research attempt"): Promise<{ title: string; topic: string } | undefined> {
    const title = await vscode.window.showInputBox({ prompt: "Research attempt name", value: defaultTitle });
    if (!title?.trim()) { return; }
    const existing = await this.request<{ sessions: Session[] }>("list");
    const topics = [...new Set(existing.sessions.map(s => s.topic))];
    let topic: string | undefined;
    if (topics.length) {
      const picked = await vscode.window.showQuickPick([
        ...topics.map(label => ({ label, newTopic: false })), { label: "New topic…", newTopic: true },
      ], { placeHolder: "Choose research topic" });
      if (!picked) { return; }
      topic = picked.newTopic ? await vscode.window.showInputBox({ prompt: "New research topic" }) : picked.label;
    } else { topic = await vscode.window.showInputBox({ prompt: "Research topic" }); }
    if (!topic?.trim()) { return; }
    return { title: title.trim(), topic: topic.trim() };
  }

  async startSession(): Promise<void> {
    const fields = await this.titleAndTopic();
    if (!fields) { return; }
    const listing = await this.request<{ sessions: Session[]; enabled: boolean }>("list");
    if (!listing.enabled) {
      const accepted = await vscode.window.showInformationMessage(
        "Start local research collection for this project? Conversation capture begins only after binding a source.", "Enable and start");
      if (accepted !== "Enable and start") { return; }
      await this.request("configure", { enabled: true });
    }
    if (!this.warnedParallel && listing.sessions.some(s => s.state === "active")) {
      this.warnedParallel = true;
      void vscode.window.showWarningMessage("Parallel research logs are separate. Use separate project folders or worktrees for concurrent edits of the same files.");
    }
    await this.select(await this.mutate("create", fields));
    await this.attachSource();
  }

  async selectSession(): Promise<void> {
    const listing = await this.request<{ sessions: Session[]; legacy_sessions: Array<{session_id: string; title: string}> }>("list");
    const choices = [...listing.sessions.map(s => ({ label: s.title, description: `${s.topic} · ${s.state}`, id: s.session_id, legacy: false })),
      ...listing.legacy_sessions.map(s => ({ label: s.title, description: "Existing capture · adopt to manage", id: s.session_id, legacy: true }))];
    const picked = await vscode.window.showQuickPick(choices, { placeHolder: "Select research session" });
    if (!picked) { return; }
    if (picked.legacy) {
      const fields = await this.titleAndTopic(picked.label);
      if (!fields) { return; }
      await this.select(await this.mutate("adopt_legacy", { session_id: picked.id, ...fields }));
    } else { await this.select(await this.request<Session>("get", { session_id: picked.id })); }
  }

  async attachSource(): Promise<void> {
    if (!this.selected) { return; }
    const selected = this.selected;
    const status = await this.request<Session>("get", { session_id: selected });
    const result = await this.request<{ sources: Array<{source_id: string; thread_id: string; session_id?: string; last_hook_at: string}> }>("sources");
    const sources = result.sources.filter(s => !s.session_id || s.session_id === selected);
    if (!sources.length) {
      void vscode.window.showInformationMessage("Open a Codex conversation in this project, then use Research: Attach Conversation. Send the first research prompt after attaching. Existing conversations can be selected through Research: Select Session.");
      return;
    }
    const picked = await vscode.window.showQuickPick(sources.map(s => ({ label: s.thread_id,
      description: `Observed ${s.last_hook_at}`, sourceId: s.source_id })), { placeHolder: "Attach an observed Codex conversation; previous text will not be imported" });
    if (!picked) { return; }
    this.apply(await this.mutate("attach_source", { session_id: selected, source_id: picked.sourceId, expected_revision: status.revision }));
  }

  async transition(action: "pause" | "resume" | "finish"): Promise<void> {
    if (!this.selected) { return; }
    const status = await this.request<Session>("get", { session_id: this.selected });
    const updated = await this.mutate(action, { session_id: status.session_id, expected_revision: status.revision });
    this.apply(updated);
    if (action === "finish") {
      this.rpc.setResearchContext(undefined);
      void vscode.window.showInformationMessage(`Research finished: ${updated.title}. ${updated.counts["prompt.recorded"] ?? 0} prompts; ${updated.incomplete_actions} actions with unverified completion.`);
    }
  }

  async openTerminal(): Promise<void> {
    if (!this.selected) { return; }
    const status = await this.request<Session>("get", { session_id: this.selected });
    let clientId = this.terminalClients.get(status.session_id);
    if (!clientId) {
      clientId = randomUUID();
      await this.mutate("bind_client", { session_id: status.session_id, client_id: clientId, client_type: "terminal" });
      this.terminalClients.set(status.session_id, clientId);
    }
    if (status.state === "finished") { throw new Error("Research session is finished"); }
    const shell = vscode.workspace.getConfiguration("manimStudio").get<string>("powerShellExecutable") || "";
    this.terminal.showResearch(status.session_id, status.title, clientId, shell);
  }

  async retryPending(): Promise<void> {
    const pending = this.context.workspaceState.get<Record<string, Pending>>(PENDING) ?? {};
    const picked = await vscode.window.showQuickPick(Object.entries(pending).map(([id, p]) => ({ label: p.method, description: id, id })), { placeHolder: "Retry an uncertain research action using its original request ID" });
    if (!picked) { return; }
    const request = pending[picked.id];
    const status = await this.mutate(request.method, request.params, picked.id);
    await this.select(await this.request<Session>("get", { session_id: status.session_id }));
  }

  async showStatus(): Promise<void> {
    if (!this.selected) { await this.selectSession(); }
    if (!this.selected) { return; }
    const status = await this.request<Session>("status", { session_id: this.selected });
    this.panel?.dispose();
    this.panel = vscode.window.createWebviewPanel("manimStudio.researchStatus", "Research status", vscode.ViewColumn.Beside, { enableScripts: false });
    const panel = this.panel;
    panel.onDidDispose(() => { if (this.panel === panel) { this.panel = undefined; } });
    this.apply(status);
  }

  private async menu(): Promise<void> {
    const picked = await vscode.window.showQuickPick([
      { label: "Start research", action: () => this.startSession() },
      { label: "Select or adopt research", action: () => this.selectSession() },
      { label: "Attach conversation", action: () => this.attachSource() },
      { label: "Pause", action: () => this.transition("pause") },
      { label: "Resume", action: () => this.transition("resume") },
      { label: "Finish", action: () => this.transition("finish") },
      { label: "Open research terminal", action: () => this.openTerminal() },
      { label: "Show status", action: () => this.showStatus() },
      { label: "Integrity, recovery and export", action: () => vscode.commands.executeCommand("manimStudio.research.showIntegrity") },
      { label: "Human time and run metadata", action: () => vscode.commands.executeCommand("manimStudio.research.showTime") },
      { label: "Artifacts and decisions", action: () => vscode.commands.executeCommand("manimStudio.research.showArtifacts") },
      { label: "Classify prompts", action: async () => {await vscode.commands.executeCommand("manimStudio.research.classifyPrompts");} },
      { label: "Retry pending action", action: () => this.retryPending() },
    ], { placeHolder: "Research session" });
    if (picked) { await picked.action(); }
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer) { clearInterval(this.timer); }
    this.panel?.dispose();
    this.bar.dispose();
  }
}

function escape(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

export function statusHtml(status: Session): string {
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'"></head><body>
    <h1>${escape(status.title)}</h1><p>Topic: ${escape(status.topic)}</p><p>State: ${escape(status.state)}</p>
    <p>Collection enabled: ${escape(status.collection_enabled)}. This is not proof of complete delivery.</p>
    <p>Conversation: ${status.sources.length ? status.sources.map(s => `${escape(s.thread_id)} · ${s.connected === 1 ? "source observed" : s.connected === 0 ? "source ended" : "delivery unknown"} · last event ${escape(s.last_hook_at)}`).join("<br>") : "Not attached"}</p>
    <p>Coverage: ${status.capture.map(s => `${escape(s.capture_status)} · ${s.gap_count} detected gaps`).join("<br>") || "Unverified"}</p>
    <p>Clients: ${(status.clients ?? []).map(c => `${escape(c.client_type)} · ${escape(c.client_id)}`).join("<br>") || "None bound"}</p>
    <p>Prompts: ${status.counts["prompt.recorded"] ?? 0}; action starts: ${status.counts["action.started"] ?? 0}; unverified completions: ${status.incomplete_actions}</p>
    <p>Project failures without attribution: ${status.unassigned_failure_count ?? "Refresh status to check"}</p>
    <p>Refreshed: ${escape(status.observed_at)}</p></body></html>`;
}
