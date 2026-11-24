const assert = require("assert");
const { installFakeVscode } = require("./fake-vscode");
const installed = installFakeVscode();
main().then(() => { installed.restore(); console.log("research UI behavior ok"); })
  .catch(error => { installed.restore(); throw error; });

async function main() {
  const { ResearchCommandController, statusHtml } = require("../out/researchCommands");
  const { TerminalManager } = require("../out/terminalManager");
  const vscode = installed.vscode;
  const store = new Map();
  const context = { subscriptions: [], workspaceState: {
    get(key) { return store.get(key); },
    async update(key, value) { store.set(key, value); },
  }};
  const sessions = new Map();
  const requests = [], selectedContexts = [];
  const makeSession = id => ({session_id: id, title: id, topic: "Math", state: "active", revision: 1,
    sources: [], capture: [], counts: {}, incomplete_actions: 0, collection_enabled: true, observed_at: "now"});
  const a = makeSession("A"), b = makeSession("B");
  sessions.set("A", a); sessions.set("B", b);
  let delayedStatus, failMutation = false;
  const rpc = {
    setResearchContext(value) { selectedContexts.push(value); },
    async request(method, params = {}) {
      requests.push({ method, params: JSON.parse(JSON.stringify(params)) });
      if (method === "research.status" && delayedStatus) { return delayedStatus; }
      if (method === "research.get" || method === "research.status") {
        const status = sessions.get(params.session_id);
        return status ? {ok: true, data: {...status}} : {ok: false, error: {code: "session_not_found", message: "Missing"}};
      }
      if (method === "research.list") { return {ok: true, data: {sessions: [...sessions.values()], legacy_sessions: [], enabled: true}}; }
      if (method === "research.sources") { return {ok: true, data: {sources: []}}; }
      if (method === "research.create") {
        const status = {...makeSession("C"), title: params.title, topic: params.topic};
        sessions.set("C", status);
        return {ok: true, data: {...status}};
      }
      if (method === "research.bind_client") { return {ok: true, data: {...sessions.get(params.session_id)}}; }
      if (["research.pause", "research.resume", "research.finish"].includes(method)) {
        if (failMutation) { failMutation = false; throw new Error("Lost transport reply"); }
        const status = sessions.get(params.session_id);
        status.state = {"research.pause": "paused", "research.resume": "active", "research.finish": "finished"}[method];
        status.revision++;
        return {ok: true, data: {...status}};
      }
      throw new Error(`Unexpected request ${method}`);
    }
  };
  const bar = {text: "", show() {}, dispose() {}}, output = {appendLine() {}};
  const terminal = new TerminalManager("C:/repo", () => true);
  const controller = new ResearchCommandController(context, rpc, terminal, bar, output);
  const choose = async (items) => items[0];
  vscode.window.showQuickPick = choose;

  // Selecting a second research does not mutate the first terminal's environment.
  await controller.selectSession();
  await controller.openTerminal();
  const terminalA = vscode.window.terminals.at(-1);
  vscode.window.showQuickPick = async items => items.find(item => item.id === "B") || items[0];
  await controller.selectSession();
  await controller.openTerminal();
  const terminalB = vscode.window.terminals.at(-1);
  assert.notStrictEqual(terminalA, terminalB);
  assert.strictEqual(terminalA.options.env.MANIM_STUDIO_RESEARCH_SESSION, "A");
  assert.strictEqual(terminalB.options.env.MANIM_STUDIO_RESEARCH_SESSION, "B");
  assert.strictEqual(terminalA.options.env.MANIM_STUDIO_RESEARCH_PROMPT, "");
  assert.strictEqual(selectedContexts.at(-1).session_id, "B");

  // A stale status callback from A must not overwrite the current selection B.
  vscode.window.showQuickPick = choose;
  await controller.selectSession();
  let resolve;
  delayedStatus = new Promise(done => { resolve = done; });
  const refresh = controller.refresh();
  vscode.window.showQuickPick = async items => items.find(item => item.id === "B");
  await controller.selectSession();
  resolve({ok: true, data: {...a}});
  await refresh;
  delayedStatus = undefined;
  assert(bar.text.includes("B"), bar.text);

  // Timeout retains the exact request across controller recreation; retry is explicit.
  failMutation = true;
  await assert.rejects(() => controller.transition("pause"), /Lost transport reply/);
  const pending = store.get("manimStudio.pendingResearchRequests");
  assert.strictEqual(Object.keys(pending).length, 1);
  const original = requests.at(-1);
  const restored = new ResearchCommandController(context, rpc, terminal, bar, output);
  vscode.window.showQuickPick = choose;
  await restored.retryPending();
  const replay = requests.filter(r => r.method === "research.pause").at(-1);
  assert.deepStrictEqual(replay.params, original.params);
  assert.deepStrictEqual(store.get("manimStudio.pendingResearchRequests"), {});
  assert.strictEqual(sessions.get("B").state, "paused");

  delayedStatus = Promise.resolve({ok: false, error: {code: "storage_error", message: "Unavailable"}});
  await restored.refresh();
  assert(bar.text.includes("not current"), bar.text);
  delayedStatus = undefined;
  await restored.refresh();
  assert(bar.text.includes("B"), bar.text);

  // Canceling user input must not create research or enable collection.
  const before = requests.length;
  vscode.window.showInputBox = async () => undefined;
  await restored.startSession();
  assert.strictEqual(requests.length, before);

  // Finished research is inspectable but cannot open a new recording terminal.
  await restored.transition("finish");
  assert.strictEqual(selectedContexts.at(-1), undefined);
  await assert.rejects(() => restored.openTerminal(), /finished/);

  // Missing stored identity is cleared, never recreated under a fresh UUID.
  store.set("manimStudio.selectedResearchSession", "missing");
  const missing = new ResearchCommandController(context, rpc, terminal, bar, output);
  await missing.restore();
  assert.strictEqual(store.get("manimStudio.selectedResearchSession"), undefined);
  assert(bar.text.includes("not current"));

  // Status panel cannot execute research labels as HTML.
  assert(statusHtml({...a, title: "<script>alert(1)</script>"}).includes("&lt;script&gt;"));
  assert(!statusHtml({...a, title: "<script>alert(1)</script>"}).includes("<script>"));

  // Exercise the registered command entry point, not only direct helper calls.
  const registered = new ResearchCommandController(context, rpc, terminal, bar, output);
  registered.register();
  const commands = vscode.commands.registered.filter(c => c.command.startsWith("manimStudio.research."));
  assert.strictEqual(commands.length, 10);
  const inputs = ["New attempt", "New topic"];
  vscode.window.showQuickPick = async items => items.find(item => item.newTopic) || items[0];
  vscode.window.showInputBox = async () => inputs.shift();
  await commands.find(c => c.command === "manimStudio.research.startSession").handler();
  assert.strictEqual(store.get("manimStudio.selectedResearchSession"), "C");
  assert.strictEqual(sessions.get("C").topic, "New topic");
  assert(bar.text.includes("waiting for conversation"), bar.text);
  controller.dispose(); restored.dispose(); missing.dispose(); registered.dispose(); terminal.dispose();
  assert(terminalA.disposed && terminalB.disposed);
}
