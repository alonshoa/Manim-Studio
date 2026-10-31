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

  const actions = [], presentations=[];
  const panel = new ManimPreviewPanel({ subscriptions: [] }, "C:/repo", async (action) => actions.push(action), async state=>presentations.push(state));
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
    research_session_id: "research-A",
  });

  const lastMessage = installed.vscode.window.posted.at(-1);
  assert.strictEqual(lastMessage.state.sourceKind, "candidate");
  assert.strictEqual(lastMessage.state.renderStatus, "success");
  assert(lastMessage.mediaUri.includes("build=b1"));

  await installed.vscode.window.receivedHandlers[0]({action:"mediaLoaded",buildId:"stale-build"});
  assert.strictEqual(presentations.length,0);
  await installed.vscode.window.receivedHandlers[0]({action:"mediaLoaded",buildId:"b1"});
  assert.strictEqual(presentations[0].researchSessionId,"research-A");
  panel.updateSession({finish_artifact_path:"C:/repo/builds/other.mp4"});
  await installed.vscode.window.receivedHandlers[0]({action:"mediaLoaded",buildId:"b1"});
  assert.strictEqual(presentations.length,1,"a changed video must not inherit the previous build identity");
  await installed.vscode.window.receivedHandlers[0]({ action: "accept" });
  assert.deepStrictEqual(actions, ["accept"]);
}
