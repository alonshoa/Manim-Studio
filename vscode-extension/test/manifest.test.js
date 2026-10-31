const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const commands = manifest.contributes.commands.map((command) => command.command);

assert.deepStrictEqual(commands.sort(), [
  ...["startSession", "selectSession", "attachSource", "pauseSession", "resumeSession", "finishSession", "showStatus", "openTerminal", "retryPending", "menu", "classifyPrompts", "showArtifacts", "captureCheckpoint", "configureCaptureScope"].map(name => `manimStudio.research.${name}`),
  "manimStudio.acceptActiveProposal",
  "manimStudio.continueAuthoring",
  "manimStudio.finishSession",
  "manimStudio.openTerminal",
  "manimStudio.openWorkspace",
  "manimStudio.pauseSession",
  "manimStudio.previewActiveProposal",
  "manimStudio.refreshPreview",
  "manimStudio.rejectActiveProposal",
  "manimStudio.resumeLastSession",
  "manimStudio.reviseActiveProposal",
  "manimStudio.restartLivePreview",
  "manimStudio.showSessionStatus",
  "manimStudio.startAuthoringSession",
  "manimStudio.startLivePreview",
  "manimStudio.stopLivePreview",
  "manimStudio.switchActiveSession",
].sort());

assert(manifest.activationEvents.every((event) => event.startsWith("onCommand:manimStudio.")));
assert.strictEqual(manifest.contributes.configuration.properties["manimStudio.requestTimeoutMs"].default, 30000);
assert.strictEqual(manifest.contributes.configuration.properties["manimStudio.renderRequestTimeoutMs"].default, 180000);
assert.strictEqual(manifest.contributes.configuration.properties["manimStudio.previewMode"].default, "embedded");
assert.deepStrictEqual(manifest.contributes.configuration.properties["manimStudio.previewMode"].enum, [
  "embedded",
  "externalOpenGL",
]);
assert.strictEqual(manifest.contributes.configuration.properties["manimStudio.powerShellExecutable"].default, "");
assert.strictEqual(manifest.contributes.configuration.properties["manimStudio.openTerminalOnSessionStart"].default, true);
assert(!("views" in manifest.contributes));
assert(!("manimStudio.lastSessionId" in manifest.contributes.configuration.properties));
console.log("extension manifest ok");
