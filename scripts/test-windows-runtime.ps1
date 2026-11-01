#Requires -Version 5.1
# GitHub-hosted Windows runner smoke test, using installed Python, MiKTeX and FFmpeg.
[CmdletBinding()]
param([ValidateSet('all', 'prepare', 'test', 'render')][string]$Stage = 'all')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'setup-windows-research.ps1')
$cache = Join-Path $env:RUNNER_TEMP 'manim-runtime-smoke'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
Update-ProcessPath
$python = (Get-Command python.exe -ErrorAction Stop).Source
if ($Stage -in @('all', 'prepare')) {
$initexmf = Resolve-Tool 'initexmf.exe'
$miktex = Resolve-Tool 'miktex.exe'
Invoke-Checked $initexmf @('--set-config-value', '[MPM]AutoInstall=1')
Invoke-Checked $miktex @('packages', 'update-package-database')
Invoke-Checked $miktex @('packages', 'update')
Ensure-TeXPackages $miktex (Resolve-Tool 'kpsewhich.exe')
Invoke-Checked $initexmf @('--update-fndb')
Install-StudioFonts $cache
Invoke-Checked $python @('-m', 'pip', 'install', '--prefer-binary', '--only-binary=pycairo,manimpango', '-e', '.[dev]')
}
if ($Stage -in @('all', 'test')) {
Invoke-Checked $python @('-m', 'manim_studio.cli', 'doctor')
# Run the suites that cover research capture, service integration and native setup.
Invoke-Checked $python @('-m', 'pytest', 'tests/test_research.py', 'tests/test_research_capture.py', 'tests/test_research_capture_acceptance.py', 'tests/test_research_sessions.py', 'tests/test_prompt_classifications.py', 'tests/test_research_artifacts.py', 'tests/test_research_time.py', 'tests/test_research_integrity.py', 'tests/test_research_export.py', 'tests/test_windows_fonts.py',
    'tests/test_studio_cli.py', 'tests/test_manim_mcp_services.py', 'tests/test_authoring_sessions.py', '-q', '--junitxml=runtime-test-results.xml')
}
if ($Stage -in @('all', 'render')) {
$scene = @'
from manim import *
class PackageRuntimeSmoke(Scene):
    def construct(self):
        label=Text("\u05e9\u05dc\u05d5\u05dd",font="DejaVu Sans")
        formula=MathTex(r"a^2+b^2=c^2").next_to(label,DOWN)
        self.play(Write(label),Write(formula),run_time=0.5)
        self.wait(0.2)
'@
$scenePath = Join-Path $cache 'runtime_smoke.py'
Write-Utf8 $scenePath $scene
$media = Join-Path $cache 'media'
Invoke-Checked $python @('-m', 'manim', '-ql', '--renderer=cairo', '--media_dir', $media, $scenePath, 'PackageRuntimeSmoke')
$video = Get-ChildItem -LiteralPath $media -Recurse -Filter 'PackageRuntimeSmoke.mp4' | Select-Object -First 1
if (-not $video -or $video.Length -lt 100) { throw 'Runtime smoke produced no video.' }
# Decode the result as well as checking that a file exists.
Invoke-Checked (Resolve-Tool 'ffmpeg.exe') @('-v', 'error', '-i', $video.FullName, '-f', 'null', '-')
Write-Host 'Windows native Manim/TeX/Hebrew render and video decode passed.'

}
