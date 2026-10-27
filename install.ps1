$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
if (-not (Test-Path (Join-Path $root "ses.py"))) {
    throw "Run this script from a clone of opencode-session-search."
}
if (-not (Test-Path (Join-Path $root "plugin\index.js"))) {
    throw "plugin/index.js is missing."
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
$pipx = Get-Command pipx -ErrorAction SilentlyContinue

if ($uv) {
    & $uv.Source tool install --force $root
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed." }
}
elseif ($pipx) {
    & $pipx.Source install --force $root
    if ($LASTEXITCODE -ne 0) { throw "pipx install failed." }
}
else {
    throw "uv or pipx is required. Install uv: https://docs.astral.sh/uv/"
}

$binDirs = @()
if ($uv) {
    $binDirs += (& $uv.Source tool dir --bin | Select-Object -First 1).Trim()
}
$binDirs += (Join-Path $env:USERPROFILE ".local\bin")

$ses = $null
foreach ($dir in $binDirs) {
    foreach ($name in @("ses.exe", "ses")) {
        $candidate = Join-Path $dir $name
        if (Test-Path $candidate) {
            $ses = $candidate
            break
        }
    }
    if ($ses) { break }
}
if (-not $ses) {
    $command = Get-Command ses -ErrorAction SilentlyContinue
    if ($command) { $ses = $command.Source }
}
if (-not $ses) { throw "ses binary not found after installation." }

$configHome = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { Join-Path $env:USERPROFILE ".config" }
$configDir = Join-Path $configHome "opencode"
$pluginDir = Join-Path $configDir "plugins\opencode-session-search"
$commandDir = Join-Path $configDir "commands"
New-Item -ItemType Directory -Force -Path $pluginDir, $commandDir | Out-Null

Copy-Item (Join-Path $root "plugin\index.js") (Join-Path $pluginDir "index.js") -Force
Copy-Item (Join-Path $root "plugin\package.json") (Join-Path $pluginDir "package.json") -Force
$json = @{ bin = $ses } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $pluginDir "config.json"), $json, [Text.UTF8Encoding]::new($false))
Copy-Item (Join-Path $root "command\ses.md") (Join-Path $commandDir "ses.md") -Force

Write-Host "CLI:     $ses"
Write-Host "Plugin:  $pluginDir"
Write-Host "Command: $(Join-Path $commandDir 'ses.md')"
Write-Host "Run 'opencode reload' or restart OpenCode."

$sesDir = Split-Path $ses
if (($env:PATH -split ';') -notcontains $sesDir) {
    Write-Host "Note: $sesDir is not on PATH. The plugin uses the absolute path; add it to call ses directly."
}
