# Run on PowerShell 7 on any OS; this does NOT install software or require admin.
#Requires -Version 5.1
param([string]$Script = (Join-Path $PSScriptRoot 'setup-windows-research.ps1'))
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
[Management.Automation.Language.Parser]::ParseFile($Script, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
. $Script
function Assert-SetupTest([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
$root = Join-Path ([IO.Path]::GetTempPath()) ('studio setup test ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    # Generated settings and launchers preserve paths containing spaces and Unicode.
    $repo = Join-Path $root 'project with spaces'
    $python = Join-Path $root 'venv with spaces/Scripts/python.exe'
    $workspacePath = New-WorkspaceFiles $root $repo $python 'research-session-1' 'code.cmd'
    $workspace = Get-Content -LiteralPath $workspacePath -Raw | ConvertFrom-Json
    Assert-SetupTest ($workspace.settings.'manimStudio.studioExecutable' -eq (Join-Path (Split-Path $python -Parent) 'studio.exe')) 'Absolute studio path is incorrect'
    Assert-SetupTest ($workspace.settings.'manimStudio.processEnv'.MANIM_STUDIO_RESEARCH_SESSION -eq 'research-session-1') 'RPC session environment missing'
    Assert-SetupTest ($workspace.settings.'terminal.integrated.env.windows'.MANIM_STUDIO_RESEARCH_SESSION -eq 'research-session-1') 'Terminal session environment missing'
    $mcp = Get-Content -LiteralPath (Join-Path $root 'mcp-client.json') -Raw | ConvertFrom-Json
    Assert-SetupTest ($mcp.mcpServers.'manim-studio'.cwd -eq $repo) 'MCP working directory mismatch'
    $toml = Get-Content -LiteralPath (Join-Path $repo '.codex/config.toml') -Raw
    Assert-SetupTest ($toml.Contains("MANIM_STUDIO_RESEARCH_SESSION = 'research-session-1'")) 'Codex session environment missing'
    $launcherTokens = $null
    $launcherErrors = $null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'Open-Manim-Research.ps1'), [ref]$launcherTokens, [ref]$launcherErrors) | Out-Null
    Assert-SetupTest ($launcherErrors.Count -eq 0) 'Generated launcher does not parse'
    # Repeat is a no-op; a different generated value keeps the previous version.
    Set-GeneratedFile (Join-Path $root 'retained.txt') 'original'
    Set-GeneratedFile (Join-Path $root 'retained.txt') 'original'
    Assert-SetupTest (@(Get-ChildItem $root -Filter 'retained.txt.backup-*').Count -eq 0) 'Unchanged file was backed up unnecessarily'
    Set-GeneratedFile (Join-Path $root 'retained.txt') 'updated'
    $backup = @(Get-ChildItem $root -Filter 'retained.txt.backup-*')
    Assert-SetupTest ($backup.Count -eq 1 -and (Get-Content -LiteralPath $backup[0].FullName -Raw) -eq 'original') 'Previous generated file was lost'
    function Fake-RebootInstaller { $global:LASTEXITCODE = 3010 }
    $reboot = $false
    try { Invoke-Checked 'Fake-RebootInstaller' @() @(0, 3010) }
    catch [OperationCanceledException] { $reboot = $true }
    Assert-SetupTest $reboot 'Reboot-required installer result was ignored'
    function Fake-WinGetReboot { $global:LASTEXITCODE = -1978334967 }
    $reboot = $false
    try { Invoke-Checked 'Fake-WinGetReboot' }
    catch [OperationCanceledException] { $reboot = $true }
    Assert-SetupTest $reboot 'WinGet reboot HRESULT was ignored'
    function Fake-FailedInstaller { $global:LASTEXITCODE = 7 }
    $failed = $false
    try { Invoke-Checked 'Fake-FailedInstaller' }
    catch { $failed = $true }
    Assert-SetupTest $failed 'Nonzero installer result was ignored'
    # Refuse to overwrite a destination that is not a checkout.
    $failed = $false
    try { Initialize-Checkout 'git' $root 'research/prompt-logging' }
    catch { $failed = $true }
    Assert-SetupTest $failed 'Non-Git destination was accepted'
    # MiKTeX rejects installing an already-installed package; reruns must skip it.
    $global:SetupTestTeXFiles = @{}
    $global:SetupTestTeXInstalls = @()
    function Fake-TeXLookup([string]$File) {
        if ($global:SetupTestTeXFiles.ContainsKey($File)) { $global:LASTEXITCODE = 0; return "C:/tex/$File" }
        $global:LASTEXITCODE = 1
    }
    function Fake-TeXInstall {
        $id = $args[2]
        $global:SetupTestTeXInstalls += $id
        $file = $(if ($id -eq 'standalone') { 'standalone.cls' } elseif ($id -eq 'amsfonts') { 'amssymb.sty' } else { "$id.sty" })
        $global:SetupTestTeXFiles[$file] = $true
        $global:LASTEXITCODE = 0
    }
    Ensure-TeXPackages 'Fake-TeXInstall' 'Fake-TeXLookup'
    $count = $global:SetupTestTeXInstalls.Count
    Ensure-TeXPackages 'Fake-TeXInstall' 'Fake-TeXLookup'
    Assert-SetupTest ($count -eq 8 -and $global:SetupTestTeXInstalls.Count -eq 8) 'TeX rerun attempted duplicate package installs'
    Write-Host 'Windows setup parser, generated configuration, backup, reboot and error tests passed.'
    # The deliberately failed fake installer must not leak a nonzero CI process exit.
    $global:LASTEXITCODE = 0
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
