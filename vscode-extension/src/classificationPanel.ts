import * as vscode from "vscode";
import { randomUUID } from "crypto";
import { readFileSync } from "fs";
import { join } from "path";
import { StudioRpcClient } from "./studioClient";

const STORE = "manimStudio.classifications.v1";
type Data = Record<string, any>;
type Stored = { sessionId?: string; promptId?: string; drafts: Record<string, Data>; pending?: Data };

export function classificationHtml(nonce = randomUUID()): string {
  const folder = join(__dirname, "..", "media");
  const css = readFileSync(join(folder, "classification.css"), "utf8");
  const script = readFileSync(join(folder, "classification.js"), "utf8");
  const body = readFileSync(join(folder, "classification.html"), "utf8");
  return `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'"><style nonce="${nonce}">${css}</style></head><body>${body}<script nonce="${nonce}">${script}</script></body></html>`;
}

export class ClassificationPanel {
  private panel: vscode.WebviewPanel | undefined;
  private sessionId: string | undefined;
  private promptId: string | undefined;
  private page: Data | undefined;
  private detail: Data | undefined;
  private filter = "unclassified";
  private offset = 0;
  private snapshot: number | undefined;
  private generation = 0;
  private refreshing = false;
  private saving = false;
  private timer: NodeJS.Timeout | undefined;
  private disposed = false;
  private reloadRequested = false;
  private persistence: Promise<void> = Promise.resolve();

  constructor(private readonly context: vscode.ExtensionContext, private readonly rpc: StudioRpcClient) {}

  register(): void {
    this.context.subscriptions.push(vscode.commands.registerCommand("manimStudio.research.classifyPrompts", () => this.open()));
    this.context.subscriptions.push({dispose: () => this.dispose()});
  }

  private stored(): Stored {
    const state = this.context.workspaceState.get<Stored>(STORE);
    return state ? structuredClone(state) : {drafts: {}};
  }

  private persist(update: (state: Stored) => void): Promise<void> {
    const next = this.persistence.catch(() => undefined).then(async () => {
      const state = this.stored(); update(state);
      await this.context.workspaceState.update(STORE, state);
    });
    this.persistence = next;
    return next;
  }

  private key(sessionId = this.sessionId, promptId = this.promptId): string { return `${sessionId}/${promptId}`; }
  private send(message: Data): void { if (!this.disposed) { void this.panel?.webview.postMessage(message); } }

  private async request(method: string, params: Data = {}): Promise<Data> {
    const response = await this.rpc.request(`classification.${method}`, params);
    if (!response.ok) { throw Object.assign(new Error(response.error?.message ?? "Annotation request failed"), {code: response.error?.code}); }
    return response.data!;
  }

  async open(): Promise<void> {
    if (!vscode.workspace.isTrusted || this.disposed) { return; }
    if (this.panel) { this.panel.reveal(vscode.ViewColumn.Beside); return; }
    const stored = this.stored();
    this.sessionId = stored.sessionId ?? this.context.workspaceState.get<string>("manimStudio.selectedResearchSession");
    this.promptId = stored.promptId;
    this.panel = vscode.window.createWebviewPanel("manimStudio.promptClassifications", "סיווג פרומפטים · מחקר", vscode.ViewColumn.Beside,
      {enableScripts: true, retainContextWhenHidden: true});
    const panel = this.panel;
    panel.webview.html = classificationHtml();
    panel.webview.onDidReceiveMessage(message => {
      void this.handle(message).catch(error => this.send({type: "error", message: String(error)}));
    });
    panel.onDidDispose(() => { if (this.panel === panel) { this.panel = undefined; this.generation++; if (this.timer) {clearInterval(this.timer);} } });
    this.timer = setInterval(() => {
      if (this.panel?.visible && !this.saving) { void this.load(true).catch(() => this.send({type: "stale"})); }
    }, 5000);
  }

  private async chooseSession(): Promise<void> {
    if (this.saving) { return; }
    if (this.stored().drafts[this.key()]?.dirty) {
      const choice = await vscode.window.showWarningMessage("הטיוטה תישמר מקומית במחקר הנוכחי. לעבור למחקר אחר?", "שמור טיוטה והמשך", "בטל");
      if (choice !== "שמור טיוטה והמשך") { return; }
      await this.persistence;
    }
    const response = await this.rpc.request("research.list", {});
    if (!response.ok) { throw new Error("לא ניתן לקרוא את רשימת המחקרים"); }
    const data = response.data as Data;
    const options = [...data.sessions.map((s: Data) => ({label: s.title, description: `${s.topic} · ${s.state}`, id: s.session_id})),
      ...data.legacy_sessions.map((s: Data) => ({label: s.title, description: "תיעוד קיים", id: s.session_id}))];
    const selected = await vscode.window.showQuickPick(options, {placeHolder: "בחירת מחקר לסיווג"});
    if (!selected) { return; }
    this.sessionId = selected.id; this.promptId = undefined; this.snapshot = undefined; this.offset = 0; this.generation++;
    await this.persist(state => {state.sessionId = this.sessionId; state.promptId = undefined;});
    await this.load(false);
  }

  async load(poll = false): Promise<void> {
    if (!this.sessionId || this.disposed) { return; }
    if (this.refreshing) { this.reloadRequested = true; return; }
    this.refreshing = true;
    const generation = this.generation, sessionId = this.sessionId;
    try {
      const page = await this.request("list", {session_id: sessionId, filter: this.filter, offset: this.offset,
        limit: 30, snapshot_seq: poll ? undefined : this.snapshot});
      if (generation !== this.generation || this.disposed) { return; }
      this.page = page; this.snapshot = page.snapshot_seq;
      this.promptId ??= page.prompts[0]?.prompt_id;
      const detail = this.promptId ? await this.request("get", {session_id: sessionId, prompt_id: this.promptId}) : undefined;
      if (generation !== this.generation || this.disposed) { return; }
      this.detail = detail;
      const promptId = this.promptId;
      await this.persist(state => {
        if (generation !== this.generation) {return;}
        state.sessionId = sessionId; state.promptId = promptId;
      });
      if (generation !== this.generation || this.disposed) {return;}
      this.send({type: "page", page, detail, draft: this.stored().drafts[this.key()], pending: this.stored().pending});
    } finally {
      this.refreshing = false;
      if (this.reloadRequested && !this.disposed) {
        this.reloadRequested = false;
        void this.load(true).catch(() => this.send({type: "stale"}));
      }
    }
  }

  private async handle(message: Data): Promise<void> {
    if (!message || !vscode.workspace.isTrusted || this.disposed) { return; }
    if (message.type === "ready") {
      this.send({type: "schema", schema: await this.request("schema")});
      if (!this.sessionId) { await this.chooseSession(); } else { await this.load(); }
      return;
    }
    if (message.type === "session") { await this.chooseSession(); return; }
    if (message.type === "retry") { await this.retry(); return; }
    if (message.session_id !== this.sessionId) { return; }
    if (message.type === "draft") {
      if (message.prompt_id !== this.promptId || !this.detail || typeof message.draft !== "object" || !message.draft) { return; }
      const key = this.key(), promptId = this.promptId, sessionId = this.sessionId;
      // Keep only annotation draft fields; never treat client payload as a stored label.
      const d = message.draft;
      const draft = {prompt_type: d.prompt_type, reasons: d.reasons, other: d.other, dirty: true,
        expected_human_head: d.expected_human_head, suggestion_id: d.suggestion_id};
      await this.persist(state => {state.drafts[key] = draft;});
      this.send({type: "draftSaved", session_id: sessionId, prompt_id: promptId});
      return;
    }
    if (this.saving) { return; }
    if (message.type === "select") {
      this.promptId = String(message.prompt_id); this.generation++;
      await this.load();
    } else if (message.type === "filter") {
      this.filter = message.filter; this.offset = 0; this.snapshot = undefined; this.promptId = undefined; this.generation++;
      await this.load();
    } else if (message.type === "page") {
      if (!Number.isInteger(message.offset) || message.offset < 0) { return; }
      this.offset = message.offset; this.promptId = undefined; this.generation++;
      await this.load();
    } else if (message.type === "refresh") {this.snapshot = undefined; await this.load(true);}
    else if (message.prompt_id === this.promptId && message.type === "history") {
      this.send({type: "history", data: await this.request("history", {session_id: this.sessionId, prompt_id: this.promptId})});
    } else if (message.prompt_id === this.promptId && message.type === "discard") {
      const key = this.key();
      await this.persist(state => {delete state.drafts[key];}); await this.load(true);
    } else if (message.prompt_id === this.promptId && message.type === "write") {
      await this.save(message);
    }
  }

  private async save(message: Data): Promise<void> {
    if (!this.detail || !["save", "skip", "clear"].includes(message.action)) { return; }
    if (this.saving) {return;}
    this.saving = true;
    try {
    await this.persistence;
    const params: Data = {project_id: this.detail.project_id, session_id: this.sessionId, prompt_id: this.promptId,
      request_id: randomUUID(), expected_human_head: message.expected_human_head};
    if (message.action === "save") {
      Object.assign(params, {prompt_type: message.prompt_type, reasons: message.reasons,
        other: message.other, taxonomy_version: 1, suggestion_id: message.suggestion_id});
    }
    const pending = {action: message.action, params, next: !!message.next};
    await this.persist(state => {state.pending = pending;});
    await this.submit(pending);
    } finally {this.saving = false; this.send({type: "idle"});}
  }

  private async retry(): Promise<void> {
    const pending = this.stored().pending;
    if (!pending || this.saving) {return;}
    await this.submit(pending);
  }

  private async submit(pending: Data): Promise<void> {
    this.saving = true;
    this.send({type: "saving"});
    const key = this.key(pending.params.session_id, pending.params.prompt_id);
    try {
      const result = await this.request(pending.action, pending.params);
      await this.persist(state => {delete state.pending; delete state.drafts[key];});
      if (this.sessionId === result.session_id && this.promptId === result.prompt_id) {
        if (pending.next) {this.promptId = undefined; this.generation++;}
        this.snapshot = undefined;
        this.send({type: "saved", result, action: pending.action});
        await this.load(true);
      }
    } catch (error: any) {
      if (error.code && error.code !== "storage_error") {
        await this.persist(state => {delete state.pending;});
      }
      let current;
      if (error.code === "classification_conflict") {
        current = await this.request("get", {session_id: pending.params.session_id, prompt_id: pending.params.prompt_id});
      }
      this.send({type: "writeError", session_id: pending.params.session_id, prompt_id: pending.params.prompt_id,
        code: error.code, current, message: String(error), pending: this.stored().pending});
    } finally {this.saving = false; this.send({type: "idle"});}
  }

  dispose(): void {
    this.disposed = true; this.generation++;
    if (this.timer) {clearInterval(this.timer);}
    this.panel?.dispose(); this.panel = undefined; this.rpc.dispose();
  }
}
