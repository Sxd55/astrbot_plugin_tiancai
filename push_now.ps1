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
    Write-Host ""
    Write-Host $Message
    Write-Host ""
    Write-Host "If you see Connection was reset / SSL / timed out:"
    Write-Host "  1) Retry this script later or with VPN/proxy on"
    Write-Host "  2) Or run manually:"
    Write-Host "       git push -u origin main"
    Write-Host "  3) Or switch to SSH remote (if you have SSH key on GitHub):"
    Write-Host "       git remote set-url origin git@github.com:sxd55/astrbot_plugin_tiancai.git"
    Write-Host "       git push -u origin main"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Add-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
Write-Log "Push Batch1 start (retry-friendly)"

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

# Help flaky HTTPS links a bit
git config http.version HTTP/1.1 2>$null | Out-Null
git config http.postBuffer 524288000 2>$null | Out-Null

git rm --cached -f push_log.txt 2>$null | Out-Null

# Avoid PowerShell treating git stderr warnings as terminating errors
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
git add -A 2>&1 | ForEach-Object { Write-Host $_ }
$ErrorActionPreference = $prevEap

$status = git status --porcelain
if ($status) {
    Write-Log "committing changes"
    Write-Host $status
    git commit -m $CommitMsg
    if ($LASTEXITCODE -ne 0) { Fail "git commit failed" }
} else {
    Write-Log "nothing new to commit (will just push existing commits)"
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

Write-Log "git push -u origin main (up to 3 tries)"
$ok = $false
for ($i = 1; $i -le 3; $i++) {
    Write-Host ""
    Write-Host "=== push attempt $i/3 ==="
    git push -u origin main
    if ($LASTEXITCODE -eq 0) {
        $ok = $true
        break
    }
    Write-Log "attempt $i failed, wait 3s..."
    Start-Sleep -Seconds 3
}

if (-not $ok) {
    Fail "git push failed after 3 tries (network to github.com). Local commit is safe."
}

Write-Log "SUCCESS"
Write-Host ""
Write-Host "Done: $RemoteUrl"
Write-Host "Version: v1.1.0 Batch1"
Read-Host "Press Enter to exit"
exit 0
