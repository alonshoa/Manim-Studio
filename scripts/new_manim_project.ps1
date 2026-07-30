$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..")
$SrcPath = Join-Path $RepoRoot "src"

$pythonCommand = $null
$pythonArgs = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
}
elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCommand = "python3"
}
else {
    Write-Error "Python was not found on PATH. Install Python 3.11+ or run from the Manim Studio devcontainer."
    exit 1
}

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$SrcPath;$env:PYTHONPATH"
}
else {
    $env:PYTHONPATH = "$SrcPath"
}

& $pythonCommand @pythonArgs -m manim_studio.cli project init @args
exit $LASTEXITCODE
