$ErrorActionPreference = "Stop"
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

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git not found"
    }

    if (-not (Test-Path ".git")) {
        throw ".git not found. Run push_to_github.bat first."
    }

    $name = ""
    $email = ""
    try { $name = git config --get user.name } catch {}
    try { $email = git config --get user.email } catch {}
    if (-not $name) { git config user.name "sxd55" | Out-Null }
    if (-not $email) { git config user.email "sxd55@users.noreply.github.com" | Out-Null }

    git add .
    git rev-parse --verify HEAD 2>$null | Out-Null
    $hasHead = ($LASTEXITCODE -eq 0)
    $status = git status --porcelain
    if ($status -or (-not $hasHead)) {
        git commit -m "feat: initial astrbot_plugin_tiancai"
        if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
    }

    git branch -M main

    $existing = ""
    git remote get-url origin 2>$null | Tee-Object -Variable existing | Out-Null
    if ($LASTEXITCODE -eq 0 -and $existing) {
        git remote set-url origin $RemoteUrl
    } else {
        git remote add origin $RemoteUrl
    }
    if ($LASTEXITCODE -ne 0) { throw "failed to configure origin" }

    Write-Log "Pushing to $RemoteUrl ..."
    Write-Host "If asked for credentials:"
    Write-Host "  Username: sxd55"
    Write-Host "  Password: GitHub Personal Access Token (repo scope)"
    Write-Host ""

    git push -u origin main
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed. Check auth / whether empty repo exists."
    }

    Write-Log "SUCCESS"
    Write-Host ""
    Write-Host "Done: $RemoteUrl"
    Read-Host "Press Enter to exit"
}
catch {
    Write-Log ("FAILED: " + $_.Exception.Message)
    Write-Host $_.Exception.Message
    Read-Host "Press Enter to exit"
    exit 1
}
