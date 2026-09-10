$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RemoteUrl = "https://github.com/sxd55/astrbot_plugin_tiancai.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"
$CommitMsg = "feat(v1.6.1): settings UI with grouped descriptions, select mode, safer repo defaults"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Fail([string]$Message) {
    Write-Log "FAILED: $Message"
    Write-Host $Message
    Write-Host ""
    Write-Host "This is often a GitHub network reset in China."
    Write-Host "Try again later, or enable VPN/proxy, then rerun push_now.bat"
    Write-Host ""
    Write-Host "Manual commands:"
    Write-Host "  git pull --rebase origin main"
    Write-Host "  git push -u origin main"
    Read-Host "Press Enter to exit"
    exit 1
}

function Invoke-GitRetry([string]$Label, [scriptblock]$Action, [int]$Tries = 5) {
    for ($i = 1; $i -le $Tries; $i++) {
        Write-Host "=== $Label attempt $i/$Tries ==="
        & $Action
        if ($LASTEXITCODE -eq 0) { return $true }
        Write-Log "$Label attempt $i failed, wait $($i * 2)s..."
        Start-Sleep -Seconds ($i * 2)
    }
    return $false
}

Add-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
Write-Log "Push start (retry pull/push)"

$logoSrc = "C:\Users\24122\AppData\Local\Claude-3p\local-agent-mode-sessions\a1678ef5\00000000\a865ea4d\uploads\0ee926631c1b369d3bc3a340898b9012.png"
$logoDst = Join-Path $PSScriptRoot "logo.png"
if (-not (Test-Path $logoDst) -and (Test-Path $logoSrc)) {
    Copy-Item -LiteralPath $logoSrc -Destination $logoDst -Force
    Write-Log "copied logo.png"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git not found" }
if (-not (Test-Path ".git")) { Fail ".git missing" }

$name = (git config --get user.name 2>$null)
$email = (git config --get user.email 2>$null)
if (-not $name) { git config user.name "sxd55" | Out-Null }
if (-not $email) { git config user.email "sxd55@users.noreply.github.com" | Out-Null }

git config http.version HTTP/1.1 2>$null | Out-Null
git config http.postBuffer 524288000 2>$null | Out-Null
git rm --cached -f push_log.txt 2>$null | Out-Null
git rm --cached -f copy_logo.bat 2>$null | Out-Null

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
git add -A 2>&1 | ForEach-Object { Write-Host $_ }
$ErrorActionPreference = $prevEap

$status = git status --porcelain
if ($status) {
    Write-Log "committing local changes"
    Write-Host $status
    git commit -m $CommitMsg
} else {
    Write-Log "nothing new to commit (local commit may already exist)"
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

# If a previous rebase is in progress, abort only when stuck; otherwise continue carefully
if (Test-Path ".git/rebase-merge") {
    Write-Log "detected in-progress rebase; trying git rebase --abort then retry pull"
    git rebase --abort 2>$null
}

$pullOk = Invoke-GitRetry "git pull --rebase" { git pull --rebase origin main }
if (-not $pullOk) {
    Fail "git pull --rebase failed after retries (network). Local commits are kept."
}

$pushOk = Invoke-GitRetry "git push" { git push -u origin main }
if (-not $pushOk) {
    Fail "git push failed after retries (network). Local commits are kept."
}

Write-Log "SUCCESS"
Write-Host "Done: $RemoteUrl"
Write-Host "Version: v1.6.1"
Read-Host "Press Enter to exit"
exit 0
