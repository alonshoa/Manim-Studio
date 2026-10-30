# Windows research workstation: clean-machine setup

`setup-windows-research.ps1` bootstraps a **native Windows** workstation for the
`research/prompt-logging` branch. It does not require Python, Git, npm, VS Code,
FFmpeg, TeX, Docker or WSL beforehand. It runs with built-in Windows PowerShell 5.1.
An Internet connection and administrator credentials are required.

## Run from a clean machine

Download [setup-windows-research.ps1](https://github.com/alonshoa/Manim-Studio/blob/research/prompt-logging/scripts/setup-windows-research.ps1)
using **Download raw file**, or run the following in **64-bit Windows PowerShell,
Run as Administrator**, under the account that will use the workstation:

```powershell
$setup = Join-Path $env:USERPROFILE 'Downloads\setup-windows-research.ps1'
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/alonshoa/Manim-Studio/research/prompt-logging/scripts/setup-windows-research.ps1' -OutFile $setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup
```

Read the downloaded script before running it if you want to inspect the changes.
The command accepts software package/source agreements through WinGet. It changes
execution policy for this process only, without changing the machine/user policy.
Do not use a different administrator account: per-user installation, extensions,
research data and later Codex login belong to the intended Windows user.

Default destination: `%USERPROFILE%\Manim-Research`. To select another destination:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup -InstallRoot 'D:\Manim Research'
```

To see the plan without installing anything or requiring elevation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup -Plan
```

If an installer requests a reboot, setup exits with code **3010**. Restart Windows
and rerun exactly the same command. Setup never restarts Windows automatically and
does not install an automatic logon task. A non-reboot failure exits with code 1.

## What is installed and configured

| Item | Behavior |
|---|---|
| Windows support | Windows 10 22H2 / Windows 11 on x64; reject ARM64 and 32-bit PowerShell |
| WinGet | Bootstrap/repair using Microsoft's PowerShell module if not present |
| Visual C++ runtime | Microsoft's x64 2015+ redistributable for native libraries |
| Tools | Git, Python 3.12 x64, Node.js LTS, VS Code and FFmpeg from exact WinGet package IDs |
| TeX | MiKTeX, package database/update, initial formula/Hebrew packages and automatic package installation |
| Fonts | DejaVu 2.37 archive from the official download, verified with published SHA-256, installed in Windows |
| Source | Clone the specified research branch; safely fast-forward an existing clean checkout |
| Python | Separate `venv` outside the checkout; install the project's pinned runtime dependencies and dev extra |
| Native wheels | Require binary wheels for PyCairo/ManimPango on Python 3.12 x64; no ad-hoc C toolchain compilation |
| Local extension | `npm ci`, compile TypeScript, package VSIX and install in desktop VS Code |
| AI client | Codex CLI and official Codex VS Code extension; Python extension installed too |
| Research | Enable local SQLite logging and create/reuse a bootstrap research session |
| Configuration | `.code-workspace`, JSON MCP example, project-scoped Codex MCP TOML, and a normal-user launcher |
| Checks | `studio doctor`, research tests, and a short Cairo-rendered video with Hebrew text and a LaTeX formula |

The native path is chosen because the current interactive authoring extension is
supported locally on Windows; its WSL/devcontainer path is not yet the supported
GUI workflow. Docker, WSL, CUDA and NVIDIA drivers are not dependencies of this
Cairo/embedded-preview setup. External OpenGL preview remains an optional separate
hardware/driver check and is not marked as verified.

Host tools are the versions currently supplied by WinGet, npm and the extension
marketplace. Project runtime pins are in `pyproject.toml`; transitive Python
requirements are not a complete frozen lockfile. Setup does not claim an identical
bit-for-bit environment on every future date. MiKTeX may download further packages
for later scenes and needs Internet access unless those packages are cached.

## Open the workstation

Close the administrator setup window. In **normal** PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Manim-Research\Open-Manim-Research.ps1"
```

Use your custom destination in this command if you chose one. Trust the project
when VS Code asks. The generated workspace configures the exact virtual environment,
Studio executable, RPC process environment and terminal environment. Explicit RPC
environment settings also work if VS Code was already open before the launcher ran.

Sign in to Codex from the extension (or run `codex login` in the configured terminal).
Setup does not sign in for you, save credentials or choose a model. Project-local
Codex MCP settings are loaded only after project trust. In Codex, check `/mcp` or
`codex mcp list` for `manim-studio`, then test `list_decks`.
The generic `mcp-client.json` is a configuration example for other compatible hosts;
it is not automatically imported into every client.

**The workstation is prepared, but complete prompt/response capture is still not
implemented.** This setup enables tool-action logging and exposes the existing
research bridge. It does not add the external host adapter discussed in
[research logging v1](../concepts/research-logging.md). Use a new research session
for each actual study workflow, and pass its IDs explicitly or update the workspace
RPC/terminal/MCP session settings together. No prompt ID is guessed or set globally.

## Files and reruns

The destination contains:

- `Manim-Studio\`: research checkout; local research database is inside its
  gitignored `.manim-studio\research\` directory.
- `venv\`: dedicated Python environment.
- `downloads\`: verified font archive, built VSIX and initialization helper.
- `setup-logs\`: installation transcripts, including the command that failed.
- `research-session.json`: bootstrap session ID, reused on a setup rerun.
- `Manim-Research.code-workspace` and `Open-Manim-Research.ps1`.
- `mcp-client.json` and `setup-report.json`.

The project-local `.codex\config.toml` is gitignored and contains machine paths,
not credentials. Existing generated files are backed up before replacement. The
script does not rewrite the global Codex configuration or a PowerShell profile.
Reruns refuse a checkout with local changes, another origin or another branch;
no reset, stash or forced branch switch is performed. They may still update Python
packages, MiKTeX packages and the installed local extension.

Software installers may modify system/user PATH. Setup refreshes PATH in the running
process, and the generated workspace records the paths needed by its processes.
Prefer a simple local path; apostrophes in generated TOML paths are currently rejected.
Do not place this workstation inside another Git checkout or a cloud-synchronized
folder if it would interfere with installers, the virtual environment or SQLite.

`-SkipCodex` omits Codex CLI/extension installation, but still generates MCP examples.
`-SkipRenderCheck` omits the real video smoke test and records the result explicitly
as `configured-render-not-verified`. Neither switch is necessary for a full install.

## Verification and practical limits

The setup development checks include PowerShell parsing/plan execution, generated
settings/launcher validation, backup preservation, error/reboot behavior, native
Windows font detection, extension RPC environment propagation and VSIX packaging.
PowerShell tests run without installing software:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-windows-setup.ps1
```

**A clean Windows VM or physical machine installation has not been executed in the
authoring environment.** The script must pass its on-machine doctor, Python tests
and video smoke test before that workstation can be considered verified. A final
manual preview/accept/reject flow, Codex authentication and visual inspection of
Hebrew are still needed. Files under `smoke\media` contain the rendered test video.
The existing Python suite also has a separate Linux failure around a Windows-only
`manim.exe` fixture; setup runs the research tests, not that unrelated failing test.

Reference documentation used for the bootstrap:

- [Microsoft WinGet bootstrap](https://learn.microsoft.com/en-us/windows/package-manager/winget/)
- [Manim installation](https://docs.manim.community/en/stable/installation/)
- [MiKTeX packages](https://docs.miktex.org/manual/miktex-packages.html)
- [DejaVu official downloads and checksum](https://dejavu-fonts.github.io/Download.html)
- [VS Code extension packaging](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
