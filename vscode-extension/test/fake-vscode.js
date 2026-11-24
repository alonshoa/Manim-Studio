const Module = require("module");

function installFakeVscode(overrides = {}) {
  const originalLoad = Module._load;
  const fake = createFakeVscode(overrides);
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") {
      return fake;
    }
    return originalLoad.apply(this, arguments);
  };
  return {
    vscode: fake,
    restore() {
      Module._load = originalLoad;
    },
  };
}

function createFakeVscode(overrides) {
  const posted = [];
  const receivedHandlers = [];
  const panel = {
    webview: {
      options: {},
      html: "",
      cspSource: "vscode-resource:",
      asWebviewUri(uri) {
        return { toString: () => `webview://${uri.fsPath}` };
      },
      postMessage(message) {
        posted.push(message);
        return Promise.resolve(true);
      },
      onDidReceiveMessage(handler) {
        receivedHandlers.push(handler);
        return { dispose() {} };
      },
    },
    revealCalls: [],
    reveal(column, preserveFocus) {
      this.revealCalls.push({ column, preserveFocus });
    },
    onDidDispose() {
      return { dispose() {} };
    },
  };
  const fake = {
    ViewColumn: { Beside: 2 },
    StatusBarAlignment: { Left: 1 },
    ProgressLocation: { Notification: 15 },
    ThemeColor: class ThemeColor {
      constructor(id) {
        this.id = id;
      }
    },
    Uri: {
      file(fsPath) {
        return { fsPath };
      },
    },
    RelativePattern: class RelativePattern {
      constructor(base, pattern) {
        this.base = base;
        this.pattern = pattern;
      }
    },
    window: {
      panel,
      posted,
      receivedHandlers,
      createWebviewPanel() {
        return panel;
      },
      createTerminal(options) {
        const terminal = {
          options,
          showCalls: 0,
          disposed: false,
          show() {
            this.showCalls += 1;
          },
          dispose() {
            this.disposed = true;
          },
        };
        fake.window.terminals.push(terminal);
        return terminal;
      },
      terminals: [],
      showErrorMessage(message) {
        fake.window.errors.push(message);
        return Promise.resolve(undefined);
      },
      showInformationMessage(message, ...actions) {
        fake.window.information.push({ message, actions });
        return Promise.resolve(undefined);
      },
      showWarningMessage() {
        return Promise.resolve(undefined);
      },
      showInputBox() {
        return Promise.resolve(undefined);
      },
      withProgress(_options, task) {
        return Promise.resolve(task());
      },
      createOutputChannel() {
        return { appendLine() {}, show() {}, dispose() {} };
      },
      createStatusBarItem() {
        return { text: "", show() {}, dispose() {} };
      },
      registerWebviewViewProvider() {
        return { dispose() {} };
      },
      errors: [],
      information: [],
      openTextDocument() {
        return Promise.resolve({});
      },
      showTextDocument() {
        return Promise.resolve(undefined);
      },
    },
    workspace: {
      isTrusted: true,
      workspaceFolders: [{ uri: { fsPath: "C:/repo" } }],
      getConfiguration() {
        return { get: (_key, defaultValue) => defaultValue };
      },
      createFileSystemWatcher(pattern) {
        fake.workspace.watchers.push(pattern);
        return {
          onDidCreate(handler) {
            fake.workspace.createHandlers.push(handler);
          },
          onDidChange(handler) {
            fake.workspace.changeHandlers.push(handler);
          },
          dispose() {},
        };
      },
      watchers: [],
      createHandlers: [],
      changeHandlers: [],
      openTextDocument() {
        return Promise.resolve({});
      },
    },
    commands: {
      registerCommand(command, handler) {
        fake.commands.registered.push({ command, handler });
        return { dispose() {} };
      },
      registered: [],
    },
  };
  return Object.assign(fake, overrides);
}

module.exports = { installFakeVscode };
