const assert = require("assert");
const { installFakeVscode } = require("./fake-vscode");

const installed = installFakeVscode();
main()
  .then(() => {
    console.log("preview panel behavior ok");
    installed.restore();
  })
  .catch((error) => {
    installed.restore();
    throw error;
  });

async function main() {
  const { ManimPreviewPanel, controlsForState } = require("../out/previewPanel");

  assert.strictEqual(
    controlsForState({
      sessionId: "s1",
      activeProposalId: "p1",
      proposalStatus: "PREVIEWED",
      authoringStatus: "DECISION_REQUIRED",
      updatedAt: "now",
    }).accept,
    true,
  );
  assert.strictEqual(
    controlsForState({
      sessionId: "s1",
      proposalStatus: "NONE",
      authoringStatus: "READY",
      updatedAt: "now",
    }).finish,
    true,
  );

  const actions = [];
  const panel = new ManimPreviewPanel({ subscriptions: [] }, "C:/repo", async (action) => actions.push(action));
  panel.show();
  panel.updateRender({
    session_id: "s1",
    title: "Story",
    beat: "step_001",
    revision: 1,
    source_kind: "candidate",
    render_status: "success",
    artifact_path: "C:/repo/builds/video.mp4",
    build_id: "b1",
  });

  const lastMessage = installed.vscode.window.posted.at(-1);
  assert.strictEqual(lastMessage.state.sourceKind, "candidate");
  assert.strictEqual(lastMessage.state.renderStatus, "success");
  assert(lastMessage.mediaUri.includes("build=b1"));

  await installed.vscode.window.receivedHandlers[0]({ action: "accept" });
  assert.deepStrictEqual(actions, ["accept"]);
}
