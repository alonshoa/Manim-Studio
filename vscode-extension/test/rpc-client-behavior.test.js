const assert = require("assert");
const { EventEmitter } = require("events");
const { PassThrough } = require("stream");
const Module = require("module");

let observedSpawnOptions;
let observedSpawnArgs;
const payloads = [];
const originalLoad = Module._load;
Module._load = function patchedLoad(request, parent, isMain) {
  if (request === "child_process") {
    return { spawn: fakeSpawn };
  }
  return originalLoad.apply(this, arguments);
};

main()
  .then(() => {
    console.log("rpc client timeout behavior ok");
    Module._load = originalLoad;
  })
  .catch((error) => {
    Module._load = originalLoad;
    throw error;
  });

async function main() {
  const { StudioRpcClient } = require("../out/studioClient");
  const client = new StudioRpcClient("C:/repo", "studio", "catalog/scenes.yaml", () => undefined, 30000, { MANIM_STUDIO_RESEARCH_SESSION: "research-test", PATH: "C:/venv/Scripts;C:/tools" });
  await assert.rejects(
    () => client.request("render_authoring_preview", { session_id: "s1" }, 5),
    /timed out after 5ms: render_authoring_preview/,
  );
  assert.strictEqual(observedSpawnOptions.env.MANIM_STUDIO_RESEARCH_SESSION, "research-test");
  assert.strictEqual(observedSpawnOptions.env.PATH, "C:/venv/Scripts;C:/tools");
  assert.strictEqual(observedSpawnOptions.cwd, "C:/repo");
  client.setResearchContext({session_id: "A", client_id: "client-A"});
  const first = client.request("list_sessions", {}, 5).catch(() => undefined);
  client.setResearchContext({session_id: "B", client_id: "client-B"});
  const second = client.request("list_sessions", {}, 5).catch(() => undefined);
  const management = client.request("research.list", {}, 5).catch(() => undefined);
  client.setResearchContext(undefined);
  const detached = client.request("list_sessions", {}, 5).catch(() => undefined);
  await Promise.all([first, second, management, detached]);
  assert.strictEqual(payloads.at(-4).params._research.session_id, "A");
  assert.strictEqual(payloads.at(-3).params._research.session_id, "B");
  assert.strictEqual(payloads.at(-2).params._research, undefined);
  assert.deepStrictEqual(payloads.at(-1).params._research, {});
  client.dispose();
  const annotations = new StudioRpcClient("C:/repo", "studio", "catalog/scenes.yaml", () => undefined, 30000, {}, "classification");
  await annotations.request("classification.schema", {}, 5).catch(() => undefined);
  assert.deepStrictEqual(observedSpawnArgs, ["research", "rpc", "--repo-root", "C:/repo"]);
  annotations.dispose();
}

function fakeSpawn(_command, _args, options) {
  observedSpawnArgs = _args;
  observedSpawnOptions = options;
  const process = new EventEmitter();
  process.stdout = new PassThrough();
  process.stderr = new EventEmitter();
  process.stdin = {
    write(_payload, callback) {
      payloads.push(JSON.parse(_payload));
      callback();
    },
  };
  process.kill = () => undefined;
  return process;
}
