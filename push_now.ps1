$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RemoteUrl = "https://github.com/sxd55/astrbot_plugin_tiancai.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"
$CommitMsg = "feat(v1.6.0): default public source, UI settings, cmd aliases, auto-import, open publish"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Fail([string]$Message) {
    Write-Log "FAILED: $Message"
    Write-Host $Message
    Write-Host ""
    Write-Host "If rebase conflict happened, open the conflicting files, fix them, then:"
    Write-Host "  git add ."
    Write-Host "  git rebase --continue"
    Write-Host "  git push -u origin main"
    Read-Host "Press Enter to exit"
    exit 1
}

Add-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
Write-Log "Push Batch6 start (with pull --rebase)"

# ensure logo
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
    if ($LASTEXITCODE -ne 0) {
        # maybe nothing staged after all
        Write-Log "commit returned $LASTEXITCODE (may be ok if empty)"
    }
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

Write-Log "git pull --rebase origin main"
git pull --rebase origin main
if ($LASTEXITCODE -ne 0) {
    Fail "git pull --rebase failed. Resolve conflicts then continue rebase."
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
Write-Host "Version: v1.6.0 Batch6"
Read-Host "Press Enter to exit"
exit 0
