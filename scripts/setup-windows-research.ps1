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
$script:SetupDirectory = $PSScriptRoot
$script:BranchSpecified = $PSBoundParameters.ContainsKey('Branch')

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
    param([string]$Path, [string]$Text, [switch]$Utf8Bom)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new([bool]$Utf8Bom))
}

function Set-GeneratedFile {
    param([string]$Path, [string]$Text, [switch]$Utf8Bom)
    if (Test-Path -LiteralPath $Path) {
        if ([IO.File]::ReadAllText($Path) -eq $Text) { return }
        $backup = "$Path.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
        Copy-Item -LiteralPath $Path -Destination $backup
        Write-Host "Previous generated file backed up: $backup"
    }
    Write-Utf8 $Path $Text -Utf8Bom:$Utf8Bom
}

function Ensure-TeXPackages {
    param([string]$Miktex, [string]$Lookup = 'kpsewhich.exe')
    $packages = @(
        @{ Id = 'standalone'; File = 'standalone.cls' }, @{ Id = 'preview'; File = 'preview.sty' },
        @{ Id = 'amsmath'; File = 'amsmath.sty' }, @{ Id = 'amsfonts'; File = 'amssymb.sty' },
        @{ Id = 'xcolor'; File = 'xcolor.sty' }, @{ Id = 'fontspec'; File = 'fontspec.sty' },
        @{ Id = 'polyglossia'; File = 'polyglossia.sty' }, @{ Id = 'bidi'; File = 'bidi.sty' }
    )
    foreach ($package in $packages) {
        $found = (& $Lookup $package.File | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $found) { continue }
        Invoke-Checked $Miktex @('packages', 'install', $package.Id)
        $found = (& $Lookup $package.File | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $found) { throw "TeX package is still unavailable: $($package.Id)" }
    }
}

function Install-StudioFonts {
    param([string]$Cache)
    $archive = Join-Path $Cache 'dejavu-fonts-ttf-2.37.zip'
    $expected = '7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a'
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip' -OutFile $archive
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
    param([string]$Git, [string]$Repository, [string]$BranchName, [string]$PinnedCommit = '', [string]$SourceBundle = '')
    $remote = 'https://github.com/alonshoa/Manim-Studio.git'
    if (-not (Test-Path -LiteralPath $Repository)) {
        $source = $(if ($SourceBundle) { $SourceBundle } else { $remote })
        Invoke-Checked $Git @('clone', '--branch', $BranchName, '--single-branch', $source, $Repository)
        if ($SourceBundle) { Invoke-Checked $Git @('-C', $Repository, 'remote', 'set-url', 'origin', $remote) }
        if ($PinnedCommit) {
            $actual = (& $Git -C $Repository rev-parse HEAD | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or $actual -ne $PinnedCommit) { throw 'Bundled source revision mismatch.' }
        }
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
    if ($PinnedCommit) {
        $actual = (& $Git -C $Repository rev-parse HEAD | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $actual -ne $PinnedCommit) {
            throw 'Existing checkout differs from the packaged commit. Choose a new -InstallRoot; no checkout was replaced.'
        }
    } else {
        Invoke-Checked $Git @('-C', $Repository, 'pull', '--ff-only', 'origin', $BranchName)
    }
}

function New-WorkspaceFiles {
    param([string]$Root, [string]$Repository, [string]$Python, [string]$ResearchSession, [string]$Code)
    $scriptsPath = Split-Path -Parent $Python
    $toolPath = "$scriptsPath;$env:Path"
    $studio = Join-Path $scriptsPath 'studio.exe'
    $mcp = Join-Path $scriptsPath 'manim-mcp.exe'
    $venv = Split-Path -Parent $scriptsPath
    $environment = @{
        PATH = $toolPath; VIRTUAL_ENV = $venv; PYTHONUTF8 = '1'
        MANIM_STUDIO_REPO_ROOT = $Repository; MANIM_STUDIO_RESEARCH_SESSION = $ResearchSession
    }
    $workspace = [ordered]@{
        folders = @(@{ path = $Repository })
        settings = [ordered]@{
            'python.defaultInterpreterPath' = $Python
            # Terminals use the environment directly, without Activate.ps1 or a policy change.
            'python.terminal.activateEnvironment' = $false
            'terminal.integrated.cwd' = $Repository
            'manimStudio.pythonExecutable' = $Python
            'manimStudio.studioExecutable' = $studio
            'manimStudio.previewMode' = 'embedded'
            'manimStudio.processEnv' = $environment
            'terminal.integrated.env.windows' = $environment
        }
        extensions = @{ recommendations = @('ms-python.python', 'openai.chatgpt', 'manim-studio.manim-studio-authoring') }
    }
    $workspaceFile = Join-Path $Root 'Manim-Research.code-workspace'
    Set-GeneratedFile $workspaceFile ($workspace | ConvertTo-Json -Depth 12)
    # Opening the project folder directly must select the same environment too.
    Set-GeneratedFile (Join-Path $Repository '.vscode/settings.json') ($workspace.settings | ConvertTo-Json -Depth 12)
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
    $escapedPython = $Python.Replace("'", "''")
    $escapedVenv = $venv.Replace("'", "''")
    $escapedStudio = $studio.Replace("'", "''")
    $launcher = @"
# Run this launcher in a NORMAL, non-administrator PowerShell after setup.
`$ErrorActionPreference = 'Stop'
foreach (`$required in @('$escapedPython', '$escapedStudio', '$escapedWorkspace', '$escapedCode')) {
    if (-not (Test-Path -LiteralPath `$required)) { throw "Installation file missing: `$required. Rerun setup to repair the environment." }
}
`$env:PATH = '$escapedPath'
`$env:VIRTUAL_ENV = '$escapedVenv'
`$env:PYTHONUTF8 = '1'
`$env:MANIM_STUDIO_REPO_ROOT = '$escapedRepo'
`$env:MANIM_STUDIO_RESEARCH_SESSION = '$ResearchSession'
Set-Location -LiteralPath '$escapedRepo'
& '$escapedCode' --new-window '$escapedWorkspace'
if (`$LASTEXITCODE -ne 0) { throw 'VS Code could not open the configured project.' }
Write-Host 'Trust this project in VS Code. Python, pip and Studio are ready; Codex sign-in is optional for local work.'
"@
    # Windows PowerShell 5.1 requires a BOM to preserve Hebrew user/project paths.
    Set-GeneratedFile (Join-Path $Root 'Open-Manim-Research.ps1') $launcher -Utf8Bom
    return $workspaceFile
}

function New-UnicodeShortcutShell {
    # WScript.Shell can round-trip shortcut fields through the system ANSI code page.
    # Use the Unicode shell-link interface for paths, arguments and persistence.
    if (-not ('StudioUnicodeShortcutShell' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
internal class StudioNativeShellLink { }

[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface StudioShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size, IntPtr data, uint flags);
    void GetIDList(out IntPtr value);
    void SetIDList(IntPtr value);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
    void GetHotkey(out short value);
    void SetHotkey(short value);
    void GetShowCmd(out int value);
    void SetShowCmd(int value);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string value, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string value, uint reserved);
    void Resolve(IntPtr window, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string value);
}

public sealed class StudioUnicodeShortcutFile {
    private readonly string path;
    public string TargetPath { get; set; }
    public string Arguments { get; set; }
    public string WorkingDirectory { get; set; }
    public string Description { get; set; }
    public string IconLocation { get; set; }
    public int WindowStyle { get; set; }
    public StudioUnicodeShortcutFile(string file) {
        path = file;
        TargetPath = Arguments = WorkingDirectory = Description = IconLocation = "";
        WindowStyle = 1;
        if (!File.Exists(file)) return;
        object instance = new StudioNativeShellLink();
        try {
            ((IPersistFile)instance).Load(file, 0);
            var link = (StudioShellLinkW)instance;
            var text = new StringBuilder(32768);
            link.GetPath(text, text.Capacity, IntPtr.Zero, 0); TargetPath = text.ToString();
            text.Clear(); link.GetArguments(text, text.Capacity); Arguments = text.ToString();
            text.Clear(); link.GetWorkingDirectory(text, text.Capacity); WorkingDirectory = text.ToString();
            text.Clear(); link.GetDescription(text, text.Capacity); Description = text.ToString();
            int show; link.GetShowCmd(out show); WindowStyle = show;
            int icon; text.Clear(); link.GetIconLocation(text, text.Capacity, out icon);
            if (text.Length > 0) IconLocation = text.ToString() + "," + icon;
        } finally { Marshal.FinalReleaseComObject(instance); }
    }
    public void Save() {
        object instance = new StudioNativeShellLink();
        try {
            var link = (StudioShellLinkW)instance;
            link.SetPath(TargetPath);
            link.SetArguments(Arguments);
            link.SetWorkingDirectory(WorkingDirectory);
            link.SetDescription(Description);
            link.SetShowCmd(WindowStyle);
            if (!String.IsNullOrEmpty(IconLocation)) {
                int comma = IconLocation.LastIndexOf(',');
                int index = 0;
                string icon = IconLocation;
                if (comma >= 0 && Int32.TryParse(IconLocation.Substring(comma + 1), out index)) icon = IconLocation.Substring(0, comma);
                link.SetIconLocation(icon, index);
            }
            // New objects do not inherit an old shortcut's RunAs flag.
            ((IPersistFile)instance).Save(path, true);
        } finally { Marshal.FinalReleaseComObject(instance); }
    }
}

public sealed class StudioUnicodeShortcutShell {
    public StudioUnicodeShortcutFile CreateShortcut(string path) { return new StudioUnicodeShortcutFile(path); }
}
'@
    }
    return New-Object StudioUnicodeShortcutShell
}

function New-WorkstationShortcuts {
    param([string]$Root, [string]$Repository, [string]$Code,
        [string]$Desktop = [Environment]::GetFolderPath('DesktopDirectory'),
        [string]$Programs = [Environment]::GetFolderPath('Programs'),
        [scriptblock]$ShellFactory = { New-UnicodeShortcutShell })
    $launcher = Join-Path $Root 'Open-Manim-Research.ps1'
    if (-not (Test-Path -LiteralPath $launcher)) { throw 'Cannot create shortcuts before the workspace launcher exists.' }
    if (-not $Desktop -or -not $Programs) { throw 'The current user desktop or Start menu location is unavailable.' }
    $shell = & $ShellFactory
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $icon = Join-Path (Split-Path (Split-Path $Code -Parent) -Parent) 'Code.exe'
    $paths = @()
    foreach ($folder in @($Desktop, (Join-Path $Programs 'Manim Studio'))) {
        if (-not $folder) { throw 'The current user desktop or Start menu location is unavailable.' }
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        $path = Join-Path $folder 'Manim Studio.lnk'
        $shortcut = $shell.CreateShortcut($path)
        $shortcut.TargetPath = $powershell
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '"'
        $shortcut.WorkingDirectory = $Repository
        $shortcut.Description = 'Open Manim Studio with the project Python environment'
        $shortcut.WindowStyle = 7
        if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = "$icon,0" }
        $shortcut.Save()
        if (-not (Test-Path -LiteralPath $path)) { throw "Shortcut was not created: $path" }
        $paths += $path
    }
    return $paths
}

function Install-ResearchWorkstation {
    $package = $null
    $bundle = ''
    $pinnedCommit = ''
    $manifestPath = Join-Path $script:SetupDirectory 'package-manifest.json'
    if (Test-Path -LiteralPath $manifestPath) {
        . (Join-Path $script:SetupDirectory 'verify-windows-package.ps1')
        $package = Test-StudioPackage $script:SetupDirectory
        if ($script:BranchSpecified -and $Branch -ne $package.source_branch) { throw 'Explicit branch differs from packaged source branch.' }
        $script:Branch = $package.source_branch
        $bundle = Join-Path $script:SetupDirectory 'source.bundle'
        $pinnedCommit = $package.source_commit
    } elseif (Test-Path -LiteralPath (Join-Path $script:SetupDirectory 'source.bundle')) {
        throw 'Source bundle exists without its package manifest. Extract a fresh complete package.'
    }
    if ($Plan) {
        [ordered]@{
            platform = 'Windows 10 22H2 / Windows 11, x64; Administrator under the intended user'
            branch = $Branch
            source_commit = $pinnedCommit
            bundled = ($null -ne $package)
            packages = @(Get-SetupPackages)
            remaining = @('Verified DejaVu fonts', 'project-local .venv', 'pinned project dependencies and pip check',
                'compile and package local VS Code extension', 'Python/Codex extensions', 'research session and local logging',
                'workspace, launcher, desktop/Start menu shortcuts and MCP configuration', 'doctor, real Cairo/TeX/Hebrew video smoke test')
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
        Ensure-TeXPackages $miktex (Resolve-Tool 'kpsewhich.exe')
        Invoke-Checked $initexmf @('--update-fndb')
        foreach ($tool in @('latex.exe', 'xelatex.exe', 'dvisvgm.exe')) { Resolve-Tool $tool | Out-Null }
        Install-StudioFonts $cache
        $repo = Join-Path $root 'Manim-Studio'
        Initialize-Checkout $git $repo $Branch $pinnedCommit $bundle
        $venv = Join-Path $repo '.venv'
        if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) { Invoke-Checked $python @('-m', 'venv', $venv) }
        $venvPython = Join-Path $venv 'Scripts\python.exe'
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel')
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '--prefer-binary', '--only-binary=pycairo,manimpango', '-e', "$repo[dev]")
        Invoke-Checked $venvPython @('-m', 'pip', 'check')
        Invoke-Checked $venvPython @('-c', 'import sys,sysconfig,pathlib,manim,manim_slides,pptx,yaml,mcp,manim_studio; p=pathlib.Path(sys.argv[1]); assert pathlib.Path(sys.prefix).resolve()==p.resolve(); assert pathlib.Path(sysconfig.get_path("scripts"),"studio.exe").is_file()', $venv)
        $env:Path = "$(Join-Path $venv 'Scripts');$env:Path"
        if ($package) {
            $vsix = Join-Path $script:SetupDirectory 'manim-studio-authoring.vsix'
        } else {
            $extension = Join-Path $repo 'vscode-extension'
            Push-Location -LiteralPath $extension
            try {
                Invoke-Checked $npm @('ci')
                Invoke-Checked $npm @('run', 'compile')
                $vsix = Join-Path $cache 'manim-studio-authoring.vsix'
                Invoke-Checked $npm @('exec', '--yes', '--package=@vscode/vsce@3', '--', 'vsce', 'package', '--no-dependencies', '--allow-missing-repository', '--out', $vsix)
            } finally { Pop-Location }
        }
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
        # Publish launch shortcuts only after all required installation checks succeeded.
        $shortcuts = @(New-WorkstationShortcuts $root $repo $code)
        $report = [ordered]@{
            status = $(if ($SkipRenderCheck) { 'configured-render-not-verified' } else { 'configured-smoke-passed' })
            branch = $Branch; commit = ((& $git -C $repo rev-parse HEAD | Out-String).Trim())
            workspace = $workspace; session_id = $researchSession; log = $transcript
            project = $repo; python_executable = $venvPython; virtual_environment = $venv
            shortcuts = $shortcuts; codex_required_for_local_work = $false
            python = ((& $venvPython --version | Out-String).Trim())
            node = ((& node.exe --version | Out-String).Trim())
            complete_chat_capture = $false; interactive_desktop_verified = $false
        }
        Set-GeneratedFile (Join-Path $root 'setup-report.json') ($report | ConvertTo-Json -Depth 8)
        Write-Host 'Setup complete. Close this administrator window and open Manim Studio from your desktop or Start menu.'
        Write-Host 'Alternative normal-user launcher:'
        Write-Host "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $root 'Open-Manim-Research.ps1')`""
        Write-Host 'Trust the project in VS Code. Python, pip and Studio are ready without Codex sign-in.'
    } finally { Stop-Transcript | Out-Null }
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Install-ResearchWorkstation; exit 0 }
    catch [System.OperationCanceledException] { Write-Warning $_.Exception.Message; exit 3010 }
    catch { Write-Error $_; exit 1 }
}
