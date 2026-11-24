#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Vsix,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../dist/windows'),
    [string]$SourceBranch = 'main'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$vsixPath = (Resolve-Path -LiteralPath $Vsix).Path
if ($SourceBranch -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or $SourceBranch.Contains('..')) { throw 'Invalid source branch.' }
$commit = (& git -C $repo rev-parse HEAD | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine source revision.' }
$dirty = (& git -C $repo status --porcelain --untracked-files=no | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Commit tracked changes before packaging; package source must match the build commit.' }
$out = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $out -Force | Out-Null
$metadata = [IO.File]::ReadAllText((Join-Path $repo 'pyproject.toml'))
if ($metadata -notmatch '(?m)^version = "([^"]+)"') { throw 'Missing package version.' }
$version = $Matches[1]
$name = 'Manim-Studio-Windows-x64-' + $version + '-' + $commit.Substring(0, 12)
$zip = Join-Path $out "$name.zip"
if (Test-Path -LiteralPath $zip) { throw "Package already exists: $zip" }
$stage = Join-Path ([IO.Path]::GetTempPath()) ('studio-package-' + [guid]::NewGuid().ToString('N'))
$bare = Join-Path $stage 'source.git'
$payload = Join-Path $stage $name
New-Item -ItemType Directory -Path $payload -Force | Out-Null
try {
    # A bare staging clone makes an exact branch bundle even on a detached CI checkout.
    & git clone --bare --no-hardlinks $repo $bare
    if ($LASTEXITCODE -ne 0) { throw 'Cannot stage source repository.' }
    & git -C $bare update-ref "refs/heads/$SourceBranch" $commit
    if ($LASTEXITCODE -ne 0) { throw 'Cannot set package source ref.' }
    & git -C $bare bundle create (Join-Path $payload 'source.bundle') "refs/heads/$SourceBranch"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create source bundle.' }
    Copy-Item -LiteralPath (Join-Path $repo 'scripts/setup-windows-research.ps1') -Destination $payload
    Copy-Item -LiteralPath (Join-Path $repo 'scripts/verify-windows-package.ps1') -Destination $payload
    Copy-Item -LiteralPath (Join-Path $repo 'docs/getting-started/windows-research-setup.md') -Destination $payload
    Copy-Item -LiteralPath (Join-Path $repo 'LICENSE') -Destination $payload
    Copy-Item -LiteralPath $vsixPath -Destination (Join-Path $payload 'manim-studio-authoring.vsix')
    $cmd = @'
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows-research.ps1" %*
set "setup_code=%errorlevel%"
if "%setup_code%"=="3010" echo Restart Windows and run Start-Setup.cmd again.
if not "%setup_code%"=="0" echo Setup stopped with exit code %setup_code%. See the message and setup logs.
exit /b %setup_code%
'@
    [IO.File]::WriteAllText((Join-Path $payload 'Start-Setup.cmd'), ($cmd -replace "`r?`n", "`r`n"), [Text.ASCIIEncoding]::new())
    $readme = @"
MANIM STUDIO $version - WINDOWS x64 ONLINE SETUP
Source commit: $commit
Branch: $SourceBranch

1. Extract the entire ZIP to a local folder.
2. Right-click Start-Setup.cmd and select Run as administrator under your normal account.
   Or run setup-windows-research.ps1 from an elevated 64-bit Windows PowerShell.
3. Restart and rerun if setup exits with code 3010. No automatic reboot is requested.
4. After success, close the administrator window and open Manim Studio from the desktop or Start menu.
5. Trust the project in VS Code. Python and pip use the project's .venv without manual activation.
   Codex sign-in is optional and separate from local editing/rendering.

This bundle includes an exact Git source snapshot and a prebuilt VS Code extension.
Internet is still required for Windows tools, Python packages, MiKTeX and Codex.
Local SHA-256 checks detect damaged payloads; they are not a code-signing certificate.
Run verify-windows-package.ps1 to check payload integrity, or setup-windows-research.ps1 -Plan.
Research is disabled by default. Opt in explicitly from the agent workflow.
Full chat logging requires a verified supported capture adapter.
See windows-research-setup.md for installation details and limitations.
"@
    [IO.File]::WriteAllText((Join-Path $payload 'README.txt'), $readme, [Text.UTF8Encoding]::new($false))
    $files = @(Get-ChildItem -LiteralPath $payload -File | Sort-Object Name | ForEach-Object {
        [ordered]@{ path = $_.Name; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    $extension = [IO.File]::ReadAllText((Join-Path $repo 'vscode-extension/package.json')) | ConvertFrom-Json
    if ($extension.version -ne $version) { throw 'Python and extension versions differ.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($vsixPath)
    try {
        $reader = [IO.StreamReader]::new($archive.GetEntry('extension/package.json').Open())
        try { $packagedExtension = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($packagedExtension.version -ne $version) { throw 'VSIX version differs from source.' }
    } finally { $archive.Dispose() }
    $manifest = [ordered]@{
        schema_version = 1; version = $version; source_commit = $commit; source_branch = $SourceBranch
        package_kind = 'online-bootstrap'; target = 'windows-x64'; extension_version = $extension.version
        built_at_utc = [DateTime]::UtcNow.ToString('o'); files = $files
    }
    [IO.File]::WriteAllText((Join-Path $payload 'package-manifest.json'), ($manifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Compress-Archive -LiteralPath $payload -DestinationPath $zip -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$zip.sha256", "$hash  $name.zip`n", [Text.ASCIIEncoding]::new())
    Write-Output $zip
} finally { Remove-Item -LiteralPath $stage -Recurse -Force }
