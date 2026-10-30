#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap a native Manim Studio research workstation from Windows 10/11 x64.
.DESCRIPTION
    Run as Administrator under your normal Windows account. No prior Git, Python,
    Node, VS Code, TeX, FFmpeg or WinGet setup is required. -Plan makes no changes.
    Installers may require a reboot (exit 3010); rerun the same command afterward.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = '',
    [string]$Branch = 'research/prompt-logging',
    [switch]$Plan,
    [switch]$SkipCodex,
    [switch]$SkipRenderCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-SetupPackages {
    @(
        @{ Id = 'Microsoft.VCRedist.2015+.x64'; Label = 'Microsoft Visual C++ runtime (x64)' },
        @{ Id = 'Git.Git'; Label = 'Git' },
        @{ Id = 'Python.Python.3.12'; Label = 'Python 3.12 (64-bit)' },
        @{ Id = 'OpenJS.NodeJS.LTS'; Label = 'Node.js LTS and npm' },
        @{ Id = 'Microsoft.VisualStudioCode'; Label = 'Visual Studio Code' },
        @{ Id = 'Gyan.FFmpeg'; Label = 'FFmpeg' },
        @{ Id = 'MiKTeX.MiKTeX'; Label = 'MiKTeX (LaTeX, XeLaTeX, dvisvgm)' }
    )
}

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments = @(), [int[]]$SuccessCodes = @(0))
    & $File @Arguments | Out-Host
    $code = $LASTEXITCODE
    # MSI codes and WinGet HRESULTs (0x8A150109 through 0x8A15010B).
    if ($code -in @(3010, 1641, -1978334967, -1978334966, -1978334965)) {
        throw [System.OperationCanceledException]::new('REBOOT_REQUIRED: Restart Windows and rerun this script. No automatic restart was requested.')
    }
    if ($code -notin $SuccessCodes) {
        throw "Command failed (exit $code): $File $($Arguments -join ' ')"
    }
}

function Update-ProcessPath {
    $paths = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        $env:Path,
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'),
        (Join-Path $env:APPDATA 'npm'),
        (Join-Path $env:ProgramFiles 'Git\cmd'),
        (Join-Path $env:ProgramFiles 'nodejs'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin'),
        (Join-Path $env:ProgramFiles 'Microsoft VS Code\bin'),
        (Join-Path $env:LOCALAPPDATA 'Programs\MiKTeX\miktex\bin\x64'),
        (Join-Path $env:ProgramFiles 'MiKTeX\miktex\bin\x64')
    )
    $env:Path = (($paths | Where-Object { $_ }) -join ';')
}

function Resolve-Tool {
    param([string]$Name, [string[]]$Candidates = @())
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $Candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw "Required tool is missing after installation: $Name. Restart Windows, rerun setup, and inspect the setup log."
}

function Ensure-WinGet {
    Update-ProcessPath
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host 'Bootstrapping Microsoft WinGet...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null
        Install-Module -Name Microsoft.WinGet.Client -Repository PSGallery -Scope CurrentUser -Force -AllowClobber
        Import-Module Microsoft.WinGet.Client
        Repair-WinGetPackageManager -AllUsers -Force -Latest | Out-Host
        Update-ProcessPath
    }
    Resolve-Tool 'winget.exe'
}

function Install-SetupPackage {
    param([string]$Winget, [hashtable]$Package)
    Write-Host "Preparing $($Package.Label)..."
    & $Winget list --id $Package.Id --exact --source winget --accept-source-agreements --disable-interactivity 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) { return }
    Invoke-Checked $Winget @('install', '--id', $Package.Id, '--exact', '--source', 'winget',
        '--architecture', 'x64', '--silent', '--accept-package-agreements',
        '--accept-source-agreements', '--disable-interactivity') @(0, 3010, 1641, -1978335189)
    Update-ProcessPath
}

function Write-Utf8 {
    param([string]$Path, [string]$Text)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Set-GeneratedFile {
    param([string]$Path, [string]$Text)
    if (Test-Path -LiteralPath $Path) {
        if ([IO.File]::ReadAllText($Path) -eq $Text) { return }
        $backup = "$Path.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
        Copy-Item -LiteralPath $Path -Destination $backup
        Write-Host "Previous generated file backed up: $backup"
    }
    Write-Utf8 $Path $Text
}

function Install-StudioFonts {
    param([string]$Cache)
    $archive = Join-Path $Cache 'dejavu-fonts-ttf-2.37.zip'
    $expected = '7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a'
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://downloads.sourceforge.net/project/dejavu/dejavu/2.37/dejavu-fonts-ttf-2.37.zip' -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw "DejaVu font archive checksum mismatch. Remove $archive and rerun."
    }
    $expanded = Join-Path $Cache 'dejavu-2.37'
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class StudioFontInstaller {
    [DllImport("gdi32.dll", CharSet=CharSet.Unicode)]
    public static extern int AddFontResource(string file);
    [DllImport("user32.dll", CharSet=CharSet.Auto)]
    public static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, UIntPtr w, IntPtr l, uint flags, uint timeout, out UIntPtr result);
}
'@
    foreach ($font in Get-ChildItem -LiteralPath $expanded -Filter '*.ttf' -Recurse) {
        $destination = Join-Path (Join-Path $env:WINDIR 'Fonts') $font.Name
        if (-not (Test-Path -LiteralPath $destination)) { Copy-Item -LiteralPath $font.FullName -Destination $destination }
        New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts' -Name "$($font.BaseName) (TrueType)" -Value $font.Name -PropertyType String -Force | Out-Null
        [StudioFontInstaller]::AddFontResource($destination) | Out-Null
    }
    $result = [UIntPtr]::Zero
    [StudioFontInstaller]::SendMessageTimeout([IntPtr]0xffff, 0x001d, [UIntPtr]::Zero, [IntPtr]::Zero, 2, 5000, [ref]$result) | Out-Null
}

function Initialize-Checkout {
    param([string]$Git, [string]$Repository, [string]$BranchName)
    $remote = 'https://github.com/alonshoa/Manim-Studio.git'
    if (-not (Test-Path -LiteralPath $Repository)) {
        Invoke-Checked $Git @('clone', '--branch', $BranchName, '--single-branch', $remote, $Repository)
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Repository '.git'))) {
        throw "Destination already exists and is not a Git checkout: $Repository. Use another -InstallRoot."
    }
    $origin = (& $Git -C $Repository remote get-url origin | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $origin -notin @($remote, $remote.Substring(0, $remote.Length - 4))) {
        throw 'The existing checkout has another origin; it will not be modified.'
    }
    $status = (& $Git -C $Repository status --porcelain --untracked-files=normal | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $status) { throw 'The existing checkout has local changes. Commit/stash them or choose another -InstallRoot.' }
    $current = (& $Git -C $Repository branch --show-current | Out-String).Trim()
    if ($current -ne $BranchName) { throw "Existing checkout is on $current; expected $BranchName. No automatic branch switch was performed." }
    Invoke-Checked $Git @('-C', $Repository, 'pull', '--ff-only', 'origin', $BranchName)
}

function New-WorkspaceFiles {
    param([string]$Root, [string]$Repository, [string]$Python, [string]$ResearchSession, [string]$Code)
    $scriptsPath = Split-Path -Parent $Python
    $toolPath = "$scriptsPath;$env:Path"
    $studio = Join-Path $scriptsPath 'studio.exe'
    $mcp = Join-Path $scriptsPath 'manim-mcp.exe'
    $workspace = [ordered]@{
        folders = @(@{ path = $Repository })
        settings = [ordered]@{
            'python.defaultInterpreterPath' = $Python
            'manimStudio.studioExecutable' = $studio
            'manimStudio.previewMode' = 'embedded'
            'manimStudio.processEnv' = @{
                PATH = $toolPath; MANIM_STUDIO_REPO_ROOT = $Repository
                MANIM_STUDIO_RESEARCH_SESSION = $ResearchSession; PYTHONUTF8 = '1'
            }
            'terminal.integrated.env.windows' = @{
                PATH = $toolPath; MANIM_STUDIO_REPO_ROOT = $Repository
                MANIM_STUDIO_RESEARCH_SESSION = $ResearchSession; PYTHONUTF8 = '1'
            }
        }
        extensions = @{ recommendations = @('ms-python.python', 'openai.chatgpt', 'manim-studio.manim-studio-authoring') }
    }
    $workspaceFile = Join-Path $Root 'Manim-Research.code-workspace'
    Set-GeneratedFile $workspaceFile ($workspace | ConvertTo-Json -Depth 12)
    $mcpConfig = @{ mcpServers = @{ 'manim-studio' = @{
        command = $mcp; cwd = $Repository
        env = @{ PATH = $toolPath; MANIM_STUDIO_REPO_ROOT = $Repository; MANIM_STUDIO_RESEARCH_SESSION = $ResearchSession; PYTHONUTF8 = '1' }
    } } }
    Set-GeneratedFile (Join-Path $Root 'mcp-client.json') ($mcpConfig | ConvertTo-Json -Depth 12)
    # TOML literal strings preserve Windows backslashes without JSON-style escaping.
    foreach ($value in @($mcp, $Repository, $toolPath)) {
        if ($value.Contains("'")) { throw 'Workspace paths containing apostrophes are not supported by the generated TOML. Choose another -InstallRoot/user path.' }
    }
    $config = @"
[mcp_servers.manim-studio]
command = '$mcp'
cwd = '$Repository'
startup_timeout_sec = 30
tool_timeout_sec = 300
[mcp_servers.manim-studio.env]
PATH = '$toolPath'
MANIM_STUDIO_REPO_ROOT = '$Repository'
MANIM_STUDIO_RESEARCH_SESSION = '$ResearchSession'
PYTHONUTF8 = '1'
"@
    Set-GeneratedFile (Join-Path $Repository '.codex\config.toml') $config
    $escapedRepo = $Repository.Replace("'", "''")
    $escapedCode = $Code.Replace("'", "''")
    $escapedPath = $toolPath.Replace("'", "''")
    $escapedWorkspace = $workspaceFile.Replace("'", "''")
    $launcher = @"
# Run this launcher in a NORMAL, non-administrator PowerShell after setup.
`$env:PATH = '$escapedPath'
`$env:PYTHONUTF8 = '1'
`$env:MANIM_STUDIO_REPO_ROOT = '$escapedRepo'
`$env:MANIM_STUDIO_RESEARCH_SESSION = '$ResearchSession'
Set-Location -LiteralPath '$escapedRepo'
& '$escapedCode' --new-window '$escapedWorkspace'
Write-Host 'Trust this project in VS Code, then sign in to Codex. Complete-chat capture still needs the host adapter.'
"@
    Set-GeneratedFile (Join-Path $Root 'Open-Manim-Research.ps1') $launcher
    return $workspaceFile
}

function Install-ResearchWorkstation {
    if ($Plan) {
        [ordered]@{
            platform = 'Windows 10 22H2 / Windows 11, x64; Administrator under the intended user'
            branch = $Branch
            packages = @(Get-SetupPackages)
            remaining = @('Verified DejaVu fonts', 'isolated Python venv outside checkout', 'pinned project dependencies',
                'compile and package local VS Code extension', 'Python/Codex extensions', 'research session and local logging',
                'workspace, launcher and MCP configuration', 'doctor, real Cairo/TeX/Hebrew video smoke test')
            codex = (-not $SkipCodex)
            renderCheck = (-not $SkipRenderCheck)
        } | ConvertTo-Json -Depth 8 | Write-Output
        return
    }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This installer requires Windows.' }
    if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Use 64-bit PowerShell on Windows x64 (ARM64 is not supported by this installer).' }
    $build = [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
    if ($build -lt 19045) { throw 'Windows 10 22H2 (build 19045) or Windows 11 is required.' }
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Open 64-bit Windows PowerShell as Administrator under your usual account and rerun. Do not use another administrator account.'
    }
    if (-not $InstallRoot) { $InstallRoot = Join-Path $env:USERPROFILE 'Manim-Research' }
    $root = [IO.Path]::GetFullPath($InstallRoot)
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    $cache = Join-Path $root 'downloads'
    $logs = Join-Path $root 'setup-logs'
    New-Item -ItemType Directory -Path $cache, $logs -Force | Out-Null
    $transcript = Join-Path $logs "setup-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
    Start-Transcript -Path $transcript | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $winget = Ensure-WinGet
        foreach ($package in Get-SetupPackages) { Install-SetupPackage $winget $package }
        Update-ProcessPath
        $git = Resolve-Tool 'git.exe'
        $npm = Resolve-Tool 'npm.cmd'
        $code = Resolve-Tool 'code.cmd'
        $pythonCandidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
            (Join-Path $env:ProgramFiles 'Python312\python.exe')
        )
        $python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $python) { throw 'Python 3.12 executable was not found in the expected installer locations.' }
        Invoke-Checked $python @('-c', 'import sys; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32, sys.version')
        $env:PYTHONUTF8 = '1'
        Resolve-Tool 'ffmpeg.exe' | Out-Null
        $initexmf = Resolve-Tool 'initexmf.exe'
        $miktex = Resolve-Tool 'miktex.exe'
        Invoke-Checked $initexmf @('--set-config-value', '[MPM]AutoInstall=1')
        Invoke-Checked $miktex @('packages', 'update-package-database')
        Invoke-Checked $miktex @('packages', 'update')
        Invoke-Checked $miktex @('packages', 'install', 'standalone', 'preview', 'amsmath', 'amsfonts', 'xcolor', 'fontspec', 'polyglossia', 'bidi')
        Invoke-Checked $initexmf @('--update-fndb')
        foreach ($tool in @('latex.exe', 'xelatex.exe', 'dvisvgm.exe')) { Resolve-Tool $tool | Out-Null }
        Install-StudioFonts $cache
        $repo = Join-Path $root 'Manim-Studio'
        Initialize-Checkout $git $repo $Branch
        $venv = Join-Path $root 'venv'
        if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) { Invoke-Checked $python @('-m', 'venv', $venv) }
        $venvPython = Join-Path $venv 'Scripts\python.exe'
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel')
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '--prefer-binary', '--only-binary=pycairo,manimpango', '-e', "$repo[dev]")
        $env:Path = "$(Join-Path $venv 'Scripts');$env:Path"
        $extension = Join-Path $repo 'vscode-extension'
        Push-Location -LiteralPath $extension
        try {
            Invoke-Checked $npm @('ci')
            Invoke-Checked $npm @('run', 'compile')
            $vsix = Join-Path $cache 'manim-studio-authoring.vsix'
            Invoke-Checked $npm @('exec', '--yes', '--package=@vscode/vsce@3', '--', 'vsce', 'package', '--no-dependencies', '--allow-missing-repository', '--out', $vsix)
        } finally { Pop-Location }
        Invoke-Checked $code @('--install-extension', $vsix, '--force')
        Invoke-Checked $code @('--install-extension', 'ms-python.python')
        if (-not $SkipCodex) {
            Invoke-Checked $npm @('install', '--global', '@openai/codex')
            Update-ProcessPath
            Invoke-Checked $code @('--install-extension', 'openai.chatgpt')
        }
        # Initialize logging via the Python API (no PowerShell 5.1 Unicode pipe loss).
        $sessionFile = Join-Path $root 'research-session.json'
        $sessionCode = @'
import json,sys
from pathlib import Path
from manim_studio.research import ResearchLog
root,session_path=map(Path,sys.argv[1:])
log=ResearchLog(root)
log.configure(True)
if session_path.exists():
    data=json.loads(session_path.read_text(encoding="utf-8"))
    with log.connection() as db:
        assert db.execute("SELECT 1 FROM events WHERE id=? AND type='session.started'",(data["session_id"],)).fetchone(), "Saved session is missing from the ledger; inspect it before continuing"
else:
    data={"session_id":log.start_session("Windows research workspace",run_settings={"capture":"tool-actions; external chat adapter required"})}
    session_path.write_text(json.dumps(data,indent=2),encoding="utf-8")
print(data["session_id"])
'@
        $sessionInitializer = Join-Path $cache 'initialize-research-session.py'
        Write-Utf8 $sessionInitializer $sessionCode
        $researchSession = (& $venvPython $sessionInitializer $repo $sessionFile | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Research session initialization failed.' }
        $env:MANIM_STUDIO_REPO_ROOT = $repo
        $env:MANIM_STUDIO_RESEARCH_SESSION = $researchSession
        $workspace = New-WorkspaceFiles $root $repo $venvPython $researchSession $code
        Push-Location -LiteralPath $repo
        try {
            Invoke-Checked $venvPython @('-m', 'manim_studio.cli', 'doctor')
            Invoke-Checked $venvPython @('-m', 'pytest', 'tests/test_research.py', '-q')
            if (-not $SkipRenderCheck) {
                $smoke = Join-Path $root 'smoke'
                New-Item -ItemType Directory -Path $smoke -Force | Out-Null
                $scenePath = Join-Path $smoke 'setup_smoke.py'
                # Keep the bootstrap source ASCII so it runs in both PowerShell 5.1 and 7.
                $scene = @'
from manim import *
class SetupSmoke(Scene):
    def construct(self):
        title=Text("\u05e9\u05dc\u05d5\u05dd",font="DejaVu Sans")
        formula=MathTex(r"a^2+b^2=c^2").next_to(title,DOWN)
        self.play(Write(title),Write(formula),run_time=0.5)
        self.wait(0.2)
'@
                Write-Utf8 $scenePath $scene
                Invoke-Checked $venvPython @('-m', 'manim', '-ql', '--renderer=cairo', '--media_dir', (Join-Path $smoke 'media'), $scenePath, 'SetupSmoke')
            }
        } finally { Pop-Location }
        $report = [ordered]@{
            status = $(if ($SkipRenderCheck) { 'configured-render-not-verified' } else { 'configured-smoke-passed' })
            branch = $Branch; commit = ((& $git -C $repo rev-parse HEAD | Out-String).Trim())
            workspace = $workspace; session_id = $researchSession; log = $transcript
            python = ((& $venvPython --version | Out-String).Trim())
            node = ((& node.exe --version | Out-String).Trim())
            complete_chat_capture = $false; interactive_desktop_verified = $false
        }
        Set-GeneratedFile (Join-Path $root 'setup-report.json') ($report | ConvertTo-Json -Depth 8)
        Write-Host "Setup complete. Close this administrator window. In a normal PowerShell, run:"
        Write-Host "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $root 'Open-Manim-Research.ps1')`""
        Write-Host 'Sign in to Codex and trust the project. Complete prompt/response capture needs the external host adapter.'
    } finally { Stop-Transcript | Out-Null }
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Install-ResearchWorkstation }
    catch [System.OperationCanceledException] { Write-Warning $_.Exception.Message; exit 3010 }
    catch { Write-Error $_; exit 1 }
}
