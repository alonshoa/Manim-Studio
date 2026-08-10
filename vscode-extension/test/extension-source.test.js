const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "src", "extension.ts"), "utf8");

assert(source.includes('preview.data?.live_status !== "STOPPED"'));
assert(source.includes('request("start_live", { session_id: sessionId })'));
assert(source.includes('register("manimStudio.stopLivePreview", pauseSession)'));
assert(source.includes('"Stop Session"'));

console.log("extension preview source checks ok");
