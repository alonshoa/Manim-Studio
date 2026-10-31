#Requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Package)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipPath = (Resolve-Path -LiteralPath $Package).Path
$expected = ([IO.File]::ReadAllText("$zipPath.sha256").Trim() -split '\s+')[0]
if ($expected -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'ZIP checksum mismatch.' }
$zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    foreach ($entry in $zip.Entries) {
        if ($entry.FullName -match '(^[/\\]|:|(^|[/\\])\.\.([/\\]|$))') { throw 'Unsafe archive member.' }
    }
} finally { $zip.Dispose() }
$root = Join-Path ([IO.Path]::GetTempPath()) ('studio package test ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    Expand-Archive -LiteralPath $zipPath -DestinationPath $root
    $payloads = @(Get-ChildItem -LiteralPath $root -Directory)
    if ($payloads.Count -ne 1) { throw 'Expected a single package directory.' }
    $payload = $payloads[0].FullName
    . (Join-Path $payload 'verify-windows-package.ps1')
    $manifest = Test-StudioPackage $payload
    $tokens = $null; $parseErrors = $null
    foreach ($file in @('setup-windows-research.ps1', 'verify-windows-package.ps1')) {
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $payload $file), [ref]$tokens, [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count) { throw "Invalid packaged PowerShell: $file" }
    }
    $engineName = $(if ($PSVersionTable.PSEdition -eq 'Desktop') { 'powershell.exe' }
        elseif ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { 'pwsh.exe' } else { 'pwsh' })
    $engine = Join-Path $PSHOME $engineName
    $planText = & $engine -NoProfile -File (Join-Path $payload 'setup-windows-research.ps1') -Plan | Out-String
    if ($LASTEXITCODE -ne 0) { throw 'Packaged installer plan failed.' }
    $plan = $planText | ConvertFrom-Json
    if (-not $plan.bundled -or $plan.source_commit -ne $manifest.source_commit) { throw 'Installer did not select packaged source.' }
    . (Join-Path $payload 'setup-windows-research.ps1')
    $checkout = Join-Path $root 'installed source with spaces'
    Initialize-Checkout 'git' $checkout $manifest.source_branch $manifest.source_commit (Join-Path $payload 'source.bundle')
    $actual = (& git -C $checkout rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $manifest.source_commit) { throw 'Installed source does not match packaged revision.' }
    Initialize-Checkout 'git' $checkout $manifest.source_branch $manifest.source_commit (Join-Path $payload 'source.bundle')
    $sourceInstaller = Join-Path $checkout 'scripts/setup-windows-research.ps1'
    if ((Get-FileHash $sourceInstaller).Hash -ne (Get-FileHash (Join-Path $payload 'setup-windows-research.ps1')).Hash) { throw 'Bootstrap does not match bundled source.' }
    # Existing work is preserved on rerun.
    [IO.File]::AppendAllText((Join-Path $checkout 'README.md'), "`nlocal work")
    $rejected = $false
    try { Initialize-Checkout 'git' $checkout $manifest.source_branch $manifest.source_commit (Join-Path $payload 'source.bundle') }
    catch { $rejected = $true }
    if (-not $rejected) { throw 'Package setup overwrote a dirty checkout.' }
    # Inspect the actual VSIX rather than accepting a file with the right suffix.
    $vsix = [IO.Compression.ZipFile]::OpenRead((Join-Path $payload 'manim-studio-authoring.vsix'))
    try {
        foreach ($name in @('extension/package.json', 'extension/out/extension.js', 'extension/out/studioClient.js', 'extension/out/artifactsPanel.js', 'extension/media/artifacts.html', 'extension/media/artifacts.css', 'extension/media/artifacts.js')) {
            if (-not $vsix.GetEntry($name)) { throw "Missing VSIX entry: $name" }
        }
        $reader = [IO.StreamReader]::new($vsix.GetEntry('extension/package.json').Open())
        try { $extension = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($extension.contributes.commands.command -notcontains 'manimStudio.research.showArtifacts') { throw 'Missing artifacts command in packaged extension.' }
        if ($extension.name -ne 'manim-studio-authoring' -or $extension.version -ne $manifest.extension_version) { throw 'Wrong packaged extension.' }
    } finally { $vsix.Dispose() }
    # Deliberate payload corruption must be caught before installation.
    $bootstrap = Join-Path $payload 'setup-windows-research.ps1'
    [IO.File]::AppendAllText($bootstrap, "`n# corruption")
    $rejected = $false
    try { Test-StudioPackage $payload | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Corrupted payload was accepted.' }
    Write-Host 'Package extraction, plan, pinned source, safe rerun, VSIX and corruption tests passed.'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
