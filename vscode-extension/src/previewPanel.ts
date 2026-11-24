import * as vscode from "vscode";

export type PreviewAction =
  | "render"
  | "accept"
  | "revise"
  | "reject"
  | "pause"
  | "resume"
  | "finish"
  | "terminal"
  | "logs";

export type PreviewState = {
  sessionId?: string;
  title?: string;
  target?: string;
  beat?: string;
  revision?: number;
  authoringStatus?: string;
  proposalStatus?: string;
  liveStatus?: string;
  nextAction?: string;
  activeProposalId?: string | null;
  sourceKind?: "canonical" | "candidate";
  renderStatus?: "idle" | "rendering" | "success" | "failed";
  artifactPath?: string | null;
  buildId?: string | null;
  researchSessionId?: string;
  renderError?: { message?: string; detail?: unknown } | null;
  updatedAt: string;
};

export const PREVIEW_PANEL_TYPE = "manimStudio.preview";

export class ManimPreviewPanel {
  private panel: vscode.WebviewPanel | undefined;
  private presentationPath?: string | null;
  private state: PreviewState = { renderStatus: "idle", updatedAt: new Date().toISOString() };

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly workspaceRoot: string,
    private readonly onAction: (action: PreviewAction) => Promise<void>,
    private readonly onPresented: (state: PreviewState) => Promise<void> = async () => undefined,
  ) {}

  show(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside, false);
      this.postState();
      return;
    }
    this.panel = vscode.window.createWebviewPanel(
      PREVIEW_PANEL_TYPE,
      "Manim Studio Preview",
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.file(this.workspaceRoot)],
      },
    );
    this.panel.webview.html = this.html(this.panel.webview);
    this.panel.webview.onDidReceiveMessage(
      async (message: { action?: PreviewAction | "mediaLoaded"; buildId?: string }) => {
        if(message.action === "mediaLoaded") {
          if(message.buildId === this.state.buildId && this.state.renderStatus === "success" && this.state.artifactPath === this.presentationPath) await this.onPresented({...this.state});
          return;
        }
        if (message.action) {
          await this.onAction(message.action);
        }
      },
      undefined,
      this.context.subscriptions,
    );
    this.panel.onDidDispose(() => {
      this.panel = undefined;
    });
    this.postState();
  }

  updateSession(data: Record<string, unknown>): void {
    this.state = {
      ...this.state,
      sessionId: stringValue(data.session_id) ?? this.state.sessionId,
      title: stringValue(data.title) ?? this.state.title,
      target: stringValue(data.target) ?? this.state.target,
      beat: stringValue(data.beat) ?? this.state.beat,
      revision: numberValue(data.revision) ?? this.state.revision,
      authoringStatus: stringValue(data.authoring_status) ?? this.state.authoringStatus,
      proposalStatus: stringValue(data.proposal_status) ?? this.state.proposalStatus,
      liveStatus: stringValue(data.live_status) ?? this.state.liveStatus,
      nextAction: stringValue(data.next_action) ?? this.state.nextAction,
      activeProposalId: nullableString(data.active_proposal_id ?? data.proposal_id, this.state.activeProposalId),
      artifactPath: stringValue(data.finish_artifact_path) ?? this.state.artifactPath,
      updatedAt: new Date().toISOString(),
    };
    this.postState();
  }

  setRendering(data: Record<string, unknown>): void {
    this.updateSession(data);
    this.state = {
      ...this.state,
      renderStatus: "rendering",
      renderError: null,
      updatedAt: new Date().toISOString(),
    };
    this.postState();
  }

  updateRender(data: Record<string, unknown>): void {
    this.updateSession(data);
    this.state = {
      ...this.state,
      sourceKind: sourceKindValue(data.source_kind) ?? this.state.sourceKind,
      renderStatus: renderStatusValue(data.render_status) ?? this.state.renderStatus,
      artifactPath: stringValue(data.artifact_path) ?? null,
      buildId: stringValue(data.build_id) ?? null,
      researchSessionId: stringValue(data.research_session_id),
      renderError: errorValue(data.render_error ?? data.error),
      updatedAt: new Date().toISOString(),
    };
    this.presentationPath=this.state.artifactPath;
    this.postState();
  }

  setError(message: string, detail?: unknown): void {
    this.state = {
      ...this.state,
      renderStatus: "failed",
      renderError: { message, detail },
      updatedAt: new Date().toISOString(),
    };
    this.postState();
  }

  currentState(): PreviewState {
    return { ...this.state };
  }

  private postState(): void {
    if (!this.panel) {
      return;
    }
    const mediaUri = this.state.artifactPath
      ? `${this.panel.webview.asWebviewUri(vscode.Uri.file(this.state.artifactPath)).toString()}?build=${encodeURIComponent(
          this.state.buildId ?? this.state.updatedAt,
        )}`
      : undefined;
    void this.panel.webview.postMessage({
      type: "state",
      state: this.state,
      mediaUri,
      controls: controlsForState(this.state),
    });
  }

  private html(webview: vscode.Webview): string {
    const nonce = nonceValue();
    const csp = [
      "default-src 'none'",
      `media-src ${webview.cspSource}`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src 'nonce-${nonce}'`,
    ].join("; ");
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { margin: 0; padding: 14px; color: var(--vscode-foreground); background: var(--vscode-editor-background); font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); }
    .shell { display: grid; grid-template-rows: minmax(280px, 1fr) auto auto; gap: 12px; height: calc(100vh - 28px); min-width: 0; }
    .stage { display: grid; place-items: center; min-height: 280px; border: 1px solid color-mix(in srgb, var(--vscode-foreground) 18%, transparent); background: #000; overflow: hidden; }
    video { width: 100%; height: 100%; max-height: 68vh; object-fit: contain; background: #000; }
    .empty { color: var(--vscode-descriptionForeground); padding: 24px; text-align: center; background: var(--vscode-editor-background); }
    .toolbar { display: flex; flex-wrap: wrap; gap: 6px; }
    button { min-height: 28px; padding: 4px 10px; border: 0; color: var(--vscode-button-foreground); background: var(--vscode-button-background); cursor: pointer; font: inherit; }
    button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
    button:disabled { opacity: 0.45; cursor: default; }
    .meta { display: grid; grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr); gap: 5px 12px; }
    .label { color: var(--vscode-descriptionForeground); }
    .value { overflow-wrap: anywhere; }
    .error { color: var(--vscode-errorForeground); overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <div class="shell">
    <div class="stage" id="stage"><div class="empty">No preview rendered yet.</div></div>
    <div class="toolbar">
      <button data-action="render" id="renderButton">Render/Refresh</button>
      <button data-action="accept" id="acceptButton">Accept</button>
      <button data-action="revise" class="secondary" id="reviseButton">Revise</button>
      <button data-action="reject" class="secondary" id="rejectButton">Reject</button>
      <button data-action="pause" class="secondary" id="pauseButton">Pause</button>
      <button data-action="resume" class="secondary" id="resumeButton">Resume</button>
      <button data-action="finish" class="secondary" id="finishButton">Finish</button>
      <button data-action="terminal" class="secondary">Open terminal</button>
      <button data-action="logs" class="secondary" id="logsButton">Open logs</button>
    </div>
    <div>
      <div class="meta">
        <div class="label">Session</div><div class="value" id="session">-</div>
        <div class="label">Beat</div><div class="value" id="beat">-</div>
        <div class="label">Status</div><div class="value" id="status">-</div>
        <div class="label">Source</div><div class="value" id="source">-</div>
        <div class="label">Render</div><div class="value" id="render">-</div>
        <div class="label">Build</div><div class="value" id="build">-</div>
      </div>
      <div class="error" id="error"></div>
    </div>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    for (const button of document.querySelectorAll("button[data-action]")) {
      button.addEventListener("click", () => vscode.postMessage({ action: button.dataset.action }));
    }
    window.addEventListener("message", (event) => {
      if (event.data.type !== "state") return;
      const state = event.data.state || {};
      const controls = event.data.controls || {};
      const mediaUri = event.data.mediaUri;
      document.getElementById("session").textContent = state.title || state.sessionId || "-";
      document.getElementById("beat").textContent = state.beat || "-";
      document.getElementById("status").textContent = [state.authoringStatus, state.proposalStatus, state.liveStatus].filter(Boolean).join(" / ") || "-";
      document.getElementById("source").textContent = state.sourceKind || "-";
      document.getElementById("render").textContent = state.renderStatus || "-";
      document.getElementById("build").textContent = state.buildId || "-";
      document.getElementById("error").textContent = state.renderError?.message || "";
      for (const [action, enabled] of Object.entries(controls)) {
        const button = document.querySelector('button[data-action="' + action + '"]');
        if (button) button.disabled = !enabled;
      }
      const stage = document.getElementById("stage");
      if (state.renderStatus === "rendering") {
        stage.innerHTML = '<div class="empty">Rendering preview...</div>';
      } else if (mediaUri) {
        stage.innerHTML = '<video controls autoplay muted loop src="' + mediaUri + '"></video>';
        const renderedBuildId = state.buildId;
        stage.querySelector('video').addEventListener('loadedmetadata', () => vscode.postMessage({action:'mediaLoaded',buildId:renderedBuildId}), {once:true});
      } else {
        stage.innerHTML = '<div class="empty">No preview rendered yet.</div>';
      }
    });
  </script>
</body>
</html>`;
  }
}

export function controlsForState(state: PreviewState): Record<PreviewAction, boolean> {
  const hasSession = Boolean(state.sessionId);
  const hasProposal = Boolean(state.activeProposalId);
  const isPaused = state.authoringStatus === "PAUSED";
  const isComplete = state.authoringStatus === "COMPLETED";
  const decisionReady = hasProposal && ["PROPOSED", "PREVIEWED", "NEEDS_REVISION"].includes(state.proposalStatus ?? "");
  return {
    render: hasSession && !isPaused,
    accept: decisionReady,
    revise: decisionReady,
    reject: decisionReady,
    pause: hasSession && !isPaused && !isComplete,
    resume: hasSession && isPaused,
    finish: hasSession && !hasProposal && !isPaused && !isComplete,
    terminal: true,
    logs: Boolean(state.renderError),
  };
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function nullableString(value: unknown, fallback: string | null | undefined): string | null | undefined {
  if (value === null) {
    return null;
  }
  return stringValue(value) ?? fallback;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function sourceKindValue(value: unknown): "canonical" | "candidate" | undefined {
  return value === "canonical" || value === "candidate" ? value : undefined;
}

function renderStatusValue(value: unknown): "success" | "failed" | undefined {
  return value === "success" || value === "failed" ? value : undefined;
}

function errorValue(value: unknown): PreviewState["renderError"] {
  if (!value) {
    return null;
  }
  if (typeof value === "string") {
    return { message: value };
  }
  if (typeof value === "object") {
    const item = value as { message?: unknown; detail?: unknown };
    return {
      message: typeof item.message === "string" ? item.message : "Preview render failed",
      detail: item.detail,
    };
  }
  return { message: String(value) };
}

function nonceValue(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function logPathsFromError(error: PreviewState["renderError"]): string[] {
  const detail = error?.detail;
  if (!detail || typeof detail !== "object") {
    return [];
  }
  const item = detail as { stderr_log?: unknown; stdout_log?: unknown };
  return [item.stderr_log, item.stdout_log].filter((value): value is string => typeof value === "string");
}
