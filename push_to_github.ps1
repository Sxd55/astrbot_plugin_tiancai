$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$RepoName = "astrbot_plugin_tiancai"
$Owner = "sxd55"
$RemoteUrl = "https://github.com/$Owner/$RepoName.git"
$LogFile = Join-Path $PSScriptRoot "push_log.txt"
$GitName = "sxd55"
$GitEmail = "sxd55@users.noreply.github.com"

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

function Ensure-Origin {
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
}

"" | Set-Content -LiteralPath $LogFile -Encoding UTF8
Write-Log "Start push for $Owner/$RepoName"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git not found"
}

$hasGh = [bool](Get-Command "gh" -ErrorAction SilentlyContinue)
if ($hasGh) {
    Write-Log ("gh: " + ((gh --version | Select-Object -First 1) -join " "))
} else {
    Write-Log "gh not installed, will use pure git"
}

if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".git"))) {
    Write-Log "git init"
    git init | Out-Host
}

$name = (git config --get user.name 2>$null)
$email = (git config --get user.email 2>$null)
if (-not $name) {
    git config user.name $GitName | Out-Null
    Write-Log "set local user.name=$GitName"
} else {
    Write-Log "user.name=$name"
}
if (-not $email) {
    git config user.email $GitEmail | Out-Null
    Write-Log "set local user.email=$GitEmail"
} else {
    Write-Log "user.email=$email"
}

git add . 2>&1 | Out-Host

$hasHead = $false
git rev-parse --verify HEAD 1>$null 2>$null
if ($LASTEXITCODE -eq 0) { $hasHead = $true }

$status = git status --porcelain
if (($status) -or (-not $hasHead)) {
    Write-Log "commit changes"
    git commit -m "feat: initial astrbot_plugin_tiancai"
    if ($LASTEXITCODE -ne 0) { Fail "git commit failed" }
} else {
    Write-Log "no new changes to commit"
}

git branch -M main

if ($hasGh) {
    gh auth status 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Log "try: gh repo create + push"
        gh repo create $RepoName --public --source=. --remote=origin --push --description "AstrBot plugin: tiancai videos"
        if ($LASTEXITCODE -eq 0) {
            Write-Log "SUCCESS via gh"
            Write-Host "Done: $RemoteUrl"
            Read-Host "Press Enter to exit"
            exit 0
        }
        Write-Log "gh repo create failed, fallback to git push"
    } else {
        Write-Log "gh is not logged in, fallback to git push"
    }
}

Write-Host ""
Write-Host "Pure Git mode"
Write-Host "1) Open https://github.com/new"
Write-Host "2) Repository name: $RepoName"
Write-Host "3) Public, create EMPTY repo (no README / gitignore / license)"
Write-Host "4) Come back and press Enter"
Write-Host ""
Read-Host "Press Enter after the empty repo exists"

Ensure-Origin

Write-Host ""
Write-Host "Pushing to $RemoteUrl"
Write-Host "Username: sxd55"
Write-Host "Password: GitHub Personal Access Token (repo scope)"
Write-Host ""

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Fail "git push failed. Check token / empty repo exists."
}

Write-Log "SUCCESS via git"
Write-Host "Done: $RemoteUrl"
Read-Host "Press Enter to exit"
exit 0
