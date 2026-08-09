const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const commands = manifest.contributes.commands.map((command) => command.command);

assert.deepStrictEqual(commands.sort(), [
  "manimStudio.acceptActiveProposal",
  "manimStudio.previewActiveProposal",
  "manimStudio.rejectActiveProposal",
  "manimStudio.restartLivePreview",
  "manimStudio.showSessionStatus",
  "manimStudio.startAuthoringSession",
  "manimStudio.startLivePreview",
  "manimStudio.stopLivePreview",
].sort());

assert(manifest.activationEvents.every((event) => event.startsWith("onCommand:manimStudio.")));
console.log("extension manifest ok");
