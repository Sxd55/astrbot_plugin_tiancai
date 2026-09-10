$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RemoteUrl = "https://github.com/sxd55/astrbot_plugin_tiancai.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"
$CommitMsg = "feat(v1.1.0): Batch1 index v2, permissions, cooldown, soft-delete"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Fail([string]$Message) {
    Write-Log "FAILED: $Message"
    Write-Host $Message
    Read-Host "Press Enter to exit"
    exit 1
}

Add-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
Write-Log "Push Batch1 start"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git not found"
}
if (-not (Test-Path ".git")) {
    Fail ".git missing"
}

$name = (git config --get user.name 2>$null)
$email = (git config --get user.email 2>$null)
if (-not $name) { git config user.name "sxd55" | Out-Null }
if (-not $email) { git config user.email "sxd55@users.noreply.github.com" | Out-Null }

# ignore noisy files if still tracked
git rm --cached -f push_log.txt 2>$null | Out-Null

git add -A 2>&1 | Out-Host
$status = git status --porcelain
if ($status) {
    Write-Log "committing changes"
    Write-Host $status
    git commit -m $CommitMsg
    if ($LASTEXITCODE -ne 0) { Fail "git commit failed" }
} else {
    Write-Log "nothing new to commit"
}

git branch -M main

$remoteNames = @()
$remoteOut = git remote 2>$null
if ($remoteOut) {
    $remoteNames = @($remoteOut | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
}
if ($remoteNames -contains "origin") {
    git remote set-url origin $RemoteUrl
} else {
    git remote add origin $RemoteUrl
}
if ($LASTEXITCODE -ne 0) { Fail "configure origin failed" }

Write-Log "git push -u origin main"
git push -u origin main
if ($LASTEXITCODE -ne 0) { Fail "git push failed" }

Write-Log "SUCCESS"
Write-Host ""
Write-Host "Done: $RemoteUrl"
Write-Host "Version: v1.1.0 Batch1"
Read-Host "Press Enter to exit"
exit 0
