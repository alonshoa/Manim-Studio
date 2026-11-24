const assert = require("assert");
const { installFakeVscode } = require("./fake-vscode");

const installed = installFakeVscode();
try {
  const { TerminalManager, resolvePowerShellExecutable } = require("../out/terminalManager");

  assert.strictEqual(resolvePowerShellExecutable("C:/Tools/pwsh.exe", "win32", () => false), "C:/Tools/pwsh.exe");
  assert.strictEqual(resolvePowerShellExecutable("", "win32", (command) => command === "pwsh.exe"), "pwsh.exe");
  assert.strictEqual(resolvePowerShellExecutable("", "win32", () => false), "powershell.exe");

  const manager = new TerminalManager("C:/repo", () => true);
  manager.show("");
  manager.show("");
  assert.strictEqual(installed.vscode.window.terminals.length, 1);
  assert.strictEqual(installed.vscode.window.terminals[0].options.name, "Manim Studio");
  assert.strictEqual(installed.vscode.window.terminals[0].showCalls, 2);

  console.log("terminal manager behavior ok");
} finally {
  installed.restore();
}
