import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import * as readline from "readline";

export type RpcResponse = {
  ok: boolean;
  data?: Record<string, unknown>;
  error?: { code: string; message: string; detail?: unknown };
};

type PendingRequest = {
  resolve: (value: RpcResponse) => void;
  reject: (reason?: unknown) => void;
};

export function buildRpcArgs(repoRoot: string, catalog = "catalog/scenes.yaml"): string[] {
  return ["authoring", "rpc", "--repo-root", repoRoot, "--catalog", catalog];
}

export class StudioRpcClient {
  private process: ChildProcessWithoutNullStreams | undefined;
  private nextId = 1;
  private pending = new Map<number, PendingRequest>();

  constructor(
    private readonly repoRoot: string,
    private readonly studioExecutable: string,
    private readonly catalog = "catalog/scenes.yaml",
    private readonly log: (message: string) => void = () => undefined,
  ) {}

  start(): void {
    if (this.process) {
      return;
    }
    const args = buildRpcArgs(this.repoRoot, this.catalog);
    this.process = spawn(this.studioExecutable, args, { cwd: this.repoRoot });
    this.log(`${this.studioExecutable} ${args.join(" ")}`);
    const reader = readline.createInterface({ input: this.process.stdout });
    reader.on("line", (line) => this.handleLine(line));
    this.process.stderr.on("data", (chunk) => this.log(String(chunk).trim()));
    this.process.on("error", (error) => {
      this.log(`studio authoring rpc failed to start: ${error.message}`);
      this.process = undefined;
      for (const request of this.pending.values()) {
        request.reject(error);
      }
      this.pending.clear();
    });
    this.process.on("exit", (code) => {
      this.log(`studio authoring rpc exited: ${code}`);
      this.process = undefined;
      for (const request of this.pending.values()) {
        request.reject(new Error("studio authoring rpc exited"));
      }
      this.pending.clear();
    });
  }

  async request(method: string, params: Record<string, unknown> = {}): Promise<RpcResponse> {
    this.start();
    if (!this.process) {
      throw new Error("studio authoring rpc did not start");
    }
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    const result = new Promise<RpcResponse>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.process.stdin.write(`${payload}\n`);
    return result;
  }

  dispose(): void {
    if (!this.process) {
      return;
    }
    this.process.kill();
    this.process = undefined;
  }

  private handleLine(line: string): void {
    this.log(line);
    let response: { id?: number; ok?: boolean; data?: Record<string, unknown>; error?: RpcResponse["error"] };
    try {
      response = JSON.parse(line);
    } catch (error) {
      this.log(`invalid Studio response: ${String(error)}`);
      return;
    }
    if (typeof response.id !== "number") {
      return;
    }
    const pending = this.pending.get(response.id);
    if (!pending) {
      return;
    }
    this.pending.delete(response.id);
    pending.resolve({ ok: Boolean(response.ok), data: response.data, error: response.error });
  }
}
