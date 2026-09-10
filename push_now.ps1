$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RemoteUrl = "https://github.com/sxd55/astrbot_plugin_tiancai.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"
$CommitMsg = "fix: replace iframe confirm() with in-page dialog for publish"

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
Write-Log "Push Batch5 start"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git not found" }
if (-not (Test-Path ".git")) { Fail ".git missing" }

$name = (git config --get user.name 2>$null)
$email = (git config --get user.email 2>$null)
if (-not $name) { git config user.name "sxd55" | Out-Null }
if (-not $email) { git config user.email "sxd55@users.noreply.github.com" | Out-Null }

git config http.version HTTP/1.1 2>$null | Out-Null
git config http.postBuffer 524288000 2>$null | Out-Null
git rm --cached -f push_log.txt 2>$null | Out-Null

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

Write-Log "git push (up to 3 tries)"
$ok = $false
for ($i = 1; $i -le 3; $i++) {
    Write-Host "=== push attempt $i/3 ==="
    git push -u origin main
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $ok) { Fail "git push failed after 3 tries" }

Write-Log "SUCCESS"
Write-Host "Done: $RemoteUrl"
Write-Host "Version: v1.5.0 Batch5"
Read-Host "Press Enter to exit"
exit 0
