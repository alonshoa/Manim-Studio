const assert = require("assert");
const { EventEmitter } = require("events");
const { PassThrough } = require("stream");
const Module = require("module");

let observedSpawnOptions;
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
  client.dispose();
}

function fakeSpawn(_command, _args, options) {
  observedSpawnOptions = options;
  const process = new EventEmitter();
  process.stdout = new PassThrough();
  process.stderr = new EventEmitter();
  process.stdin = {
    write(_payload, callback) {
      callback();
    },
  };
  process.kill = () => undefined;
  return process;
}
