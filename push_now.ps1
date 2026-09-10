$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RemoteUrl = "https://github.com/sxd55/astrbot_plugin_tiancai.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"
$CommitMsg = "feat(v1.7.0): public library manage tab (list/edit/delete/import)"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Fail([string]$Message) {
    Write-Log "FAILED: $Message"
    Write-Host $Message
    Write-Host ""
    Write-Host "Network resets are common. Retry later or use VPN, then rerun."
    Write-Host "Manual: git pull --rebase origin main && git push -u origin main"
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
Write-Log "Push v1.7.0 start"

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

if (Test-Path ".git/rebase-merge") {
    Write-Log "abort stuck rebase"
    git rebase --abort 2>$null
}

$pullOk = Invoke-GitRetry "git pull --rebase" { git pull --rebase origin main }
if (-not $pullOk) { Fail "git pull --rebase failed after retries" }

$pushOk = Invoke-GitRetry "git push" { git push -u origin main }
if (-not $pushOk) { Fail "git push failed after retries" }

Write-Log "SUCCESS"
Write-Host "Done: $RemoteUrl"
Write-Host "Version: v1.7.0"
Read-Host "Press Enter to exit"
exit 0
