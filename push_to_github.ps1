$ErrorActionPreference = "Stop"
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

"" | Set-Content -LiteralPath $LogFile -Encoding UTF8
Write-Log "Start push for $Owner/$RepoName"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command not found: $Name"
    }
}

function Ensure-GitIdentity {
    $name = ""
    $email = ""
    try { $name = (git config --get user.name 2>$null) } catch {}
    try { $email = (git config --get user.email 2>$null) } catch {}

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
}

try {
    Assert-Command "git"
    Write-Log ("git: " + (git --version))

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

    Ensure-GitIdentity

    git add .
    $status = git status --porcelain
    $headExists = $true
    try {
        git rev-parse --verify HEAD | Out-Null
    } catch {
        $headExists = $false
    }

    if ($status -or (-not $headExists)) {
        Write-Log "commit changes"
        git commit -m "feat: initial astrbot_plugin_tiancai" | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "git commit failed with exit code $LASTEXITCODE"
        }
    } else {
        Write-Log "no new changes to commit"
    }

    git branch -M main
    if ($LASTEXITCODE -ne 0) {
        throw "git branch -M main failed"
    }

    if ($hasGh) {
        $authOk = $false
        try {
            gh auth status | Out-Host
            if ($LASTEXITCODE -eq 0) { $authOk = $true }
        } catch {
            $authOk = $false
        }

        if ($authOk) {
            Write-Log "try: gh repo create + push"
            try {
                gh repo create $RepoName --public --source=. --remote=origin --push --description "AstrBot plugin: tiancai videos"
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "SUCCESS via gh"
                    Write-Host ""
                    Write-Host "Done: $RemoteUrl"
                    Read-Host "Press Enter to exit"
                    exit 0
                }
            } catch {
                Write-Log ("gh repo create failed: " + $_.Exception.Message)
            }
            Write-Log "fallback to git push"
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

    git remote remove origin 2>$null
    git remote add origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) {
        throw "git remote add failed"
    }

    Write-Log "git push -u origin main"
    git push -u origin main
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed with exit code $LASTEXITCODE"
    }

    Write-Log "SUCCESS via git"
    Write-Host ""
    Write-Host "Done: $RemoteUrl"
    Read-Host "Press Enter to exit"
    exit 0
}
catch {
    Write-Log ("FAILED: " + $_.Exception.Message)
    Write-Host ""
    Write-Host "Push failed. See push_log.txt for details."
    Write-Host $_.Exception.Message
    Read-Host "Press Enter to exit"
    exit 1
}
