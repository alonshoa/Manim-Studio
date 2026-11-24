import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import { randomUUID } from "crypto";
import * as readline from "readline";

export type RpcResponse = {
  ok: boolean;
  data?: Record<string, unknown>;
  error?: { code: string; message: string; detail?: unknown };
};

type PendingRequest = {
  resolve: (value: RpcResponse) => void;
  reject: (reason?: unknown) => void;
  timer: NodeJS.Timeout;
};

export function buildRpcArgs(repoRoot: string, catalog = "catalog/scenes.yaml"): string[] {
  return ["authoring", "rpc", "--repo-root", repoRoot, "--catalog", catalog];
}

export class StudioRpcClient {
  private researchContext: Record<string, string> | undefined;
  private researchContextControlled = false;
  private process: ChildProcessWithoutNullStreams | undefined;
  private nextId = 1;
  private pending = new Map<number, PendingRequest>();

  constructor(
    private readonly repoRoot: string,
    private readonly studioExecutable: string,
    private readonly catalog = "catalog/scenes.yaml",
    private readonly log: (message: string) => void = () => undefined,
    private readonly requestTimeoutMs = 30000,
    private readonly environment: NodeJS.ProcessEnv = {},
    private readonly transport: "authoring" | "classification" = "authoring",
  ) {}

  start(): void {
    if (this.process) {
      return;
    }
    const args = this.transport === "classification" ? ["research", "rpc", "--repo-root", this.repoRoot]
      : buildRpcArgs(this.repoRoot, this.catalog);
    this.process = spawn(this.studioExecutable, args, { cwd: this.repoRoot, env: { ...process.env, ...this.environment } });
    this.log(`${this.studioExecutable} ${args.join(" ")}`);
    const reader = readline.createInterface({ input: this.process.stdout });
    reader.on("line", (line) => this.handleLine(line));
    this.process.stderr.on("data", (chunk) => this.log(String(chunk).trim()));
    this.process.on("error", (error) => {
      this.log(`studio authoring rpc failed to start: ${error.message}`);
      this.process = undefined;
      for (const request of this.pending.values()) {
        clearTimeout(request.timer);
        request.reject(error);
      }
      this.pending.clear();
    });
    this.process.on("exit", (code) => {
      this.log(`studio authoring rpc exited: ${code}`);
      this.process = undefined;
      for (const request of this.pending.values()) {
        clearTimeout(request.timer);
        request.reject(new Error("studio authoring rpc exited"));
      }
      this.pending.clear();
    });
  }

  async request(method: string, params: Record<string, unknown> = {}, timeoutMs = this.requestTimeoutMs): Promise<RpcResponse> {
    // Snapshot request-local context before any later UI selection change.
    if (!method.startsWith("research.") && !method.startsWith("classification.") && !method.startsWith("artifacts.") && !method.startsWith("timing.") && !method.startsWith("integrity.") && !method.startsWith("exports.") && this.researchContextControlled && !("_research" in params)) {
      params = { ...params, _research: { ...(this.researchContext ?? {}) } };
    }
    if (["accept_proposal", "reject_proposal", "revise_proposal", "pause_session"].includes(method) && params._research && typeof params._research === "object") {
      params = { ...params, _research: { ...(params._research as Record<string, unknown>), decision_origin: "human", origin_evidence: "vscode_explicit_command", request_id: (params._research as Record<string, unknown>).request_id || randomUUID() } };
    }
    this.start();
    if (!this.process) {
      throw new Error("studio authoring rpc did not start");
    }
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    const result = new Promise<RpcResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`studio authoring rpc timed out after ${timeoutMs}ms: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
    });
    this.process.stdin.write(`${payload}\n`, (error) => {
      if (!error) {
        return;
      }
      const pending = this.pending.get(id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pending.delete(id);
        pending.reject(error);
      }
    });
    return result;
  }

  dispose(): void {
    if (!this.process) {
      return;
    }
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error("studio authoring rpc disposed"));
    }
    this.pending.clear();
    this.process.kill();
    this.process = undefined;
  }

  getResearchContext(): Record<string, string> | undefined { return this.researchContext ? {...this.researchContext} : undefined; }

  setResearchContext(context: Record<string, string> | undefined): void {
    this.researchContextControlled = true;
    this.researchContext = context ? { ...context } : undefined;
  }

  private handleLine(line: string): void {
    this.log(line);
    let response: { id?: number; ok?: boolean; data?: Record<string, unknown>; error?: RpcResponse["error"] };
    try {
      response = JSON.parse(line);
    } catch (error) {
      this.log(`invalid Studio response: ${String(error)}`);
      this.rejectAll(new Error("studio authoring rpc returned malformed JSON"));
      return;
    }
    if (typeof response.id !== "number") {
      this.log("invalid Studio response: missing numeric id");
      return;
    }
    const pending = this.pending.get(response.id);
    if (!pending) {
      return;
    }
    this.pending.delete(response.id);
    clearTimeout(pending.timer);
    pending.resolve({ ok: Boolean(response.ok), data: response.data, error: response.error });
  }

  private rejectAll(error: Error): void {
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
  }
}
