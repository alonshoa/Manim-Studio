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
    $repo = Join-Path $root ('project with spaces ' + [char]0x05D0)
    $python = Join-Path $repo '.venv/Scripts/python.exe'
    $code = Join-Path $root 'VS Code/bin/code.ps1'
    Write-Utf8 $python ''
    Write-Utf8 (Join-Path (Split-Path $python -Parent) 'studio.exe') ''
    # Exercise the generated launcher in a fresh process, without a real VS Code install.
    Write-Utf8 $code @'
[ordered]@{ arguments = @($args); path = $env:PATH; venv = $env:VIRTUAL_ENV; cwd = (Get-Location).Path; utf8 = $env:PYTHONUTF8 } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $env:MANIM_STUDIO_REPO_ROOT 'launched.json') -Encoding UTF8
$global:LASTEXITCODE = 0
'@
    $workspacePath = New-WorkspaceFiles $root $repo $python 'research-session-1' $code
    $workspace = Get-Content -LiteralPath $workspacePath -Raw | ConvertFrom-Json
    Assert-SetupTest ($workspace.settings.'manimStudio.studioExecutable' -eq (Join-Path (Split-Path $python -Parent) 'studio.exe')) 'Absolute studio path is incorrect'
    Assert-SetupTest ($workspace.settings.'manimStudio.processEnv'.MANIM_STUDIO_RESEARCH_SESSION -eq 'research-session-1') 'RPC session environment missing'
    Assert-SetupTest ($workspace.settings.'terminal.integrated.env.windows'.MANIM_STUDIO_RESEARCH_SESSION -eq 'research-session-1') 'Terminal session environment missing'
    $venv = Split-Path (Split-Path $python -Parent) -Parent
    Assert-SetupTest ($workspace.settings.'python.defaultInterpreterPath' -eq $python) 'Python interpreter mismatch'
    Assert-SetupTest ($workspace.settings.'manimStudio.pythonExecutable' -eq $python) 'Studio Python mismatch'
    Assert-SetupTest ($workspace.settings.'terminal.integrated.env.windows'.VIRTUAL_ENV -eq $venv) 'Terminal environment missing'
    Assert-SetupTest ($workspace.settings.'terminal.integrated.env.windows'.PATH.StartsWith((Split-Path $python -Parent) + ';')) 'Project Python is not first on terminal PATH'
    Assert-SetupTest ($workspace.settings.'terminal.integrated.cwd' -eq $repo) 'Terminal starts outside the project'
    Assert-SetupTest ($workspace.settings.'python.terminal.activateEnvironment' -eq $false) 'Terminal requires activation script'
    $folderSettings = Get-Content -LiteralPath (Join-Path $repo '.vscode/settings.json') -Raw | ConvertFrom-Json
    Assert-SetupTest ($folderSettings.'python.defaultInterpreterPath' -eq $python) 'Direct folder open loses the environment'
    $mcp = Get-Content -LiteralPath (Join-Path $root 'mcp-client.json') -Raw | ConvertFrom-Json
    Assert-SetupTest ($mcp.mcpServers.'manim-studio'.cwd -eq $repo) 'MCP working directory mismatch'
    $toml = Get-Content -LiteralPath (Join-Path $repo '.codex/config.toml') -Raw
    Assert-SetupTest ($toml.Contains("MANIM_STUDIO_RESEARCH_SESSION = 'research-session-1'")) 'Codex session environment missing'
    $launcherTokens = $null
    $launcherErrors = $null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'Open-Manim-Research.ps1'), [ref]$launcherTokens, [ref]$launcherErrors) | Out-Null
    Assert-SetupTest ($launcherErrors.Count -eq 0) 'Generated launcher does not parse'
    $launcherBytes = [IO.File]::ReadAllBytes((Join-Path $root 'Open-Manim-Research.ps1'))
    Assert-SetupTest ($launcherBytes[0] -eq 239 -and $launcherBytes[1] -eq 187 -and $launcherBytes[2] -eq 191) 'Launcher lacks PowerShell 5.1 Unicode encoding marker'
    $engineName = $(if ($PSVersionTable.PSEdition -eq 'Desktop') { 'powershell.exe' }
        elseif ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { 'pwsh.exe' } else { 'pwsh' })
    $engine = Join-Path $PSHOME $engineName
    & $engine -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Open-Manim-Research.ps1')
    Assert-SetupTest ($LASTEXITCODE -eq 0) 'Generated launcher failed'
    $launched = Get-Content -LiteralPath (Join-Path $repo 'launched.json') -Raw | ConvertFrom-Json
    Assert-SetupTest ($launched.arguments[0] -eq '--new-window' -and $launched.arguments[1] -eq $workspacePath) 'Launcher opened wrong workspace'
    Assert-SetupTest ($launched.cwd -eq $repo -and $launched.venv -eq $venv -and $launched.utf8 -eq '1') 'Launcher environment is incorrect'
    # Missing environment must fail instead of silently opening with global Python.
    Remove-Item -LiteralPath $python
    $ErrorActionPreference = 'Continue'
    try { & $engine -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Open-Manim-Research.ps1') 2>&1 | Out-Null }
    finally { $ErrorActionPreference = 'Stop' }
    Assert-SetupTest ($LASTEXITCODE -ne 0) 'Launcher accepted a missing project environment'
    Write-Utf8 $python ''
    $desktop = Join-Path $root 'redirected desktop'
    $programs = Join-Path $root 'user programs'
    # Cross-platform contract test; the Windows branch below also reads real .lnk files.
    $fakeShellFactory = {
        $shell = [pscustomobject]@{}
        $shell | Add-Member ScriptMethod CreateShortcut {
            param($Path)
            $link = [pscustomobject]@{ Path = $Path; TargetPath = ''; Arguments = ''; WorkingDirectory = ''; Description = ''; WindowStyle = 0; IconLocation = '' }
            $link | Add-Member ScriptMethod Save { Write-Utf8 $this.Path ($this | ConvertTo-Json) }
            return $link
        }
        return $shell
    }
    $savedSystemRoot = $env:SystemRoot
    if (-not $env:SystemRoot) { $env:SystemRoot = Join-Path $root 'Windows' }
    try {
        $mockLinks = @(New-WorkstationShortcuts $root $repo $code $desktop $programs $fakeShellFactory)
        Assert-SetupTest ($mockLinks.Count -eq 2) 'Desktop and Start menu shortcuts were not both created'
        foreach ($path in $mockLinks) {
            $link = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            Assert-SetupTest ($link.WorkingDirectory -eq $repo -and $link.TargetPath -like '*powershell.exe') 'Shortcut target or directory mismatch'
            Assert-SetupTest ($link.Arguments -eq ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $root 'Open-Manim-Research.ps1') + '"')) 'Shortcut arguments were not quoted'
        }
        New-WorkstationShortcuts $root $repo $code $desktop $programs $fakeShellFactory | Out-Null
        Assert-SetupTest (@(Get-ChildItem $desktop -Filter '*.lnk').Count -eq 1) 'Shortcut rerun duplicated desktop entries'
        foreach ($path in $mockLinks) { Remove-Item -LiteralPath $path }
    } finally { $env:SystemRoot = $savedSystemRoot }
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $shortcuts = @(New-WorkstationShortcuts $root $repo $code $desktop $programs)
        $shell = New-Object -ComObject WScript.Shell
        foreach ($path in $shortcuts) {
            $link = $shell.CreateShortcut($path)
            Assert-SetupTest ($link.WorkingDirectory -eq $repo) 'Shortcut working directory mismatch'
            Assert-SetupTest ($link.Arguments -eq ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $root 'Open-Manim-Research.ps1') + '"')) 'Shortcut launcher path was not quoted'
            Assert-SetupTest ($link.TargetPath -like '*powershell.exe') 'Shortcut target is not PowerShell'
            # SLDF_RUNAS_USER would reopen the editor as administrator.
            $bytes = [IO.File]::ReadAllBytes($path)
            Assert-SetupTest (([BitConverter]::ToUInt32($bytes,20) -band 0x2000) -eq 0) 'Shortcut requests elevation'
        }
        New-WorkstationShortcuts $root $repo $code $desktop $programs | Out-Null
        Assert-SetupTest ($shortcuts.Count -eq 2 -and @(Get-ChildItem $desktop -Filter '*.lnk').Count -eq 1) 'Shortcut rerun is not idempotent'
    }
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
    Write-Host 'Windows setup parser, project environment, launcher, shortcut, backup, reboot and error tests passed.'
    # The deliberately failed fake installer must not leak a nonzero CI process exit.
    $global:LASTEXITCODE = 0
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
