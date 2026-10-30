#Requires -Version 5.1
[CmdletBinding()]
param([string]$PackageRoot = $PSScriptRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-StudioPackage {
    param([Parameter(Mandatory)][string]$Root)
    $rootPath = [IO.Path]::GetFullPath($Root)
    $manifestPath = Join-Path $rootPath 'package-manifest.json'
    $manifest = [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.source_commit -notmatch '^[0-9a-f]{40}$') {
        throw 'Invalid package schema or source commit.'
    }
    if ($manifest.source_branch -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or $manifest.source_branch.Contains('..')) {
        throw 'Invalid package source branch.'
    }
    $required = @('setup-windows-research.ps1', 'verify-windows-package.ps1', 'Start-Setup.cmd',
        'manim-studio-authoring.vsix', 'source.bundle', 'README.txt', 'LICENSE', 'windows-research-setup.md')
    $seen = @{}
    foreach ($entry in $manifest.files) {
        $name = [string]$entry.path
        if ($name -notin $required -or $seen.ContainsKey($name) -or $entry.sha256 -notmatch '^[0-9a-f]{64}$') {
            throw "Invalid or duplicate package member: $name"
        }
        $seen[$name] = $true
        $path = Join-Path $rootPath $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing package member: $name" }
        if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Package member is a link: $name" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw "Package checksum mismatch: $name. Extract a fresh download."
        }
    }
    if ($seen.Count -ne $required.Count) { throw 'Package manifest is incomplete.' }
    return $manifest
}

if ($MyInvocation.InvocationName -ne '.') {
    $manifest = Test-StudioPackage $PackageRoot
    Write-Host "Package verified: $($manifest.source_commit) ($($manifest.source_branch))"
}
