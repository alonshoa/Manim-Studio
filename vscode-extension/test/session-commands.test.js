const assert = require("assert");
const { installFakeVscode } = require("./fake-vscode");

const installed = installFakeVscode();
main()
  .then(() => {
    console.log("session command behavior ok");
    installed.restore();
  })
  .catch((error) => {
    installed.restore();
    throw error;
  });

async function main() {
  const { SessionCommandController, shouldApplyRenderResult } = require("../out/sessionCommands");

  assert.strictEqual(
    shouldApplyRenderResult(
      { sessionId: "s1", proposalId: "p1", revision: 1, beat: "step_001" },
      { session_id: "s1", proposal_id: "p2", revision: 1, beat: "step_001" },
      "s1",
    ),
    false,
  );
  assert.strictEqual(
    shouldApplyRenderResult(
      { sessionId: "s1", proposalId: null, revision: 1, beat: "step_001" },
      { session_id: "s1", proposal_id: null, revision: 1, beat: "step_001" },
      "s1",
    ),
    true,
  );

  let requestCount = 0;
  const rpc = {
    request(method) {
      requestCount += 1;
      assert.strictEqual(method, "discover_active_proposal");
      return new Promise(() => undefined);
    },
  };
  const context = {
    subscriptions: [],
    workspaceState: {
      get() {
        return "s1";
      },
      update() {
        return Promise.resolve();
      },
    },
  };
  const controller = new SessionCommandController(
    context,
    { appendLine() {}, show() {} },
    { text: "", color: undefined },
    rpc,
    { updateSession() {}, show() {}, setRendering() {}, updateRender() {}, setError() {}, currentState() { return {}; } },
    { show() {}, showOnce() {} },
  );

  controller.startProposalDiscovery({ uri: { fsPath: "C:/repo" } });
  installed.vscode.workspace.createHandlers[0]();
  installed.vscode.workspace.createHandlers[0]();
  await Promise.resolve();
  assert.strictEqual(requestCount, 1);
  assert.strictEqual(installed.vscode.workspace.watchers[0].pattern, "builds/staged/*/proposal.json");
  controller.dispose();
}
