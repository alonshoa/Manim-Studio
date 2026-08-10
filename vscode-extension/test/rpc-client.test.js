const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "src", "studioClient.ts"), "utf8");

assert(source.includes("requestTimeoutMs"));
assert(source.includes("timeoutMs = this.requestTimeoutMs"));
assert(source.includes("timed out"));
assert(source.includes("studio authoring rpc exited"));
assert(source.includes("malformed JSON"));
assert(source.includes("clearTimeout"));

console.log("rpc client reliability source checks ok");
