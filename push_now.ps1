$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RemoteUrl = "https://github.com/sxd55/astrbot_plugin_tiancai.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

Add-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
Write-Log "Direct push start"

function Fail([string]$Message) {
    Write-Log "FAILED: $Message"
    Write-Host $Message
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git not found"
}

if (-not (Test-Path ".git")) {
    Fail ".git not found. Run push_to_github.bat first."
}

$name = (git config --get user.name 2>$null)
$email = (git config --get user.email 2>$null)
if (-not $name) {
    git config user.name "sxd55" | Out-Null
    Write-Log "set user.name=sxd55"
}
if (-not $email) {
    git config user.email "sxd55@users.noreply.github.com" | Out-Null
    Write-Log "set user.email=sxd55@users.noreply.github.com"
}

git add . 2>&1 | Out-Host

$hasHead = $false
git rev-parse --verify HEAD 1>$null 2>$null
if ($LASTEXITCODE -eq 0) { $hasHead = $true }

$status = git status --porcelain
if (($status) -or (-not $hasHead)) {
    Write-Log "creating commit"
    git commit -m "chore: update push scripts"
    if ($LASTEXITCODE -ne 0) {
        Fail "git commit failed"
    }
} else {
    Write-Log "nothing to commit"
}

git branch -M main 2>&1 | Out-Host

$remoteNames = @()
$remoteOut = git remote 2>$null
if ($remoteOut) {
    $remoteNames = @($remoteOut | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
}
Write-Log ("current remotes: " + (($remoteNames -join ",") -replace "^$", "(none)"))

if ($remoteNames -contains "origin") {
    Write-Log "set-url origin -> $RemoteUrl"
    git remote set-url origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) { Fail "git remote set-url failed" }
} else {
    Write-Log "add origin -> $RemoteUrl"
    git remote add origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) { Fail "git remote add failed" }
}

Write-Host ""
Write-Host "Pushing to $RemoteUrl"
Write-Host "If asked for credentials:"
Write-Host "  Username: sxd55"
Write-Host "  Password: GitHub Personal Access Token (repo scope)"
Write-Host ""

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Fail "git push failed. Check login token / empty repo exists at $RemoteUrl"
}

Write-Log "SUCCESS"
Write-Host ""
Write-Host "Done: $RemoteUrl"
Read-Host "Press Enter to exit"
exit 0
