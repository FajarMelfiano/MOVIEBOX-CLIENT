$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Write-Step {
    param([string]$Message)
    Write-Host "[step] $Message" -ForegroundColor Blue
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[ok] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Throw-InstallError {
    param([string]$Message)
    Write-Host "[error] $Message" -ForegroundColor Red
    throw $Message
}

function Add-ShellIntegration {
    if ($env:MOVIEBOX_SKIP_SHELL_SETUP -eq "1") {
        Write-Warn "Skipping shell integration because MOVIEBOX_SKIP_SHELL_SETUP=1"
        return
    }

    $profileDir = Split-Path -Parent $PROFILE
    if (-not (Test-Path $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }
    if (-not (Test-Path $PROFILE)) {
        New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    }

    $marker = "# >>> moviebox shell setup >>>"
    $content = Get-Content -Path $PROFILE -Raw
    if ($content -like "*$marker*") {
        Write-Ok "Shell integration already exists in $PROFILE"
        return
    }

    $escapedRoot = $ProjectRoot.Replace("'", "''")
    $blockTemplate = @'
# >>> moviebox shell setup >>>
$env:MOVIEBOX_PROJECT_ROOT = '__MOVIEBOX_PROJECT_ROOT__'
if (-not (Get-Variable -Name MovieboxOriginalPrompt -Scope Global -ErrorAction SilentlyContinue)) {
    $global:MovieboxOriginalPrompt = $function:prompt
    function global:prompt {
        $repo = $env:MOVIEBOX_PROJECT_ROOT
        if ($repo -and $pwd.Path.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
            $activateScript = Join-Path $repo ".venv\Scripts\Activate.ps1"
            if (-not $env:VIRTUAL_ENV -and (Test-Path $activateScript)) {
                & $activateScript | Out-Null
                $global:MovieboxAutoVenvActive = $true
            }
        }
        elseif ($global:MovieboxAutoVenvActive -and $env:VIRTUAL_ENV) {
            if (Get-Command deactivate -ErrorAction SilentlyContinue) {
                deactivate
            }
            $global:MovieboxAutoVenvActive = $false
        }
        & $global:MovieboxOriginalPrompt
    }
}
$movieboxBinary = Join-Path $env:MOVIEBOX_PROJECT_ROOT ".venv\Scripts\moviebox.exe"
if (Test-Path $movieboxBinary) {
    (& {
        $env:_MOVIEBOX_COMPLETE = "powershell_source"
        & $movieboxBinary
    }) | Out-String | Invoke-Expression
    Remove-Item Env:_MOVIEBOX_COMPLETE -ErrorAction SilentlyContinue
}
# <<< moviebox shell setup <<<
'@
    $block = $blockTemplate.Replace('__MOVIEBOX_PROJECT_ROOT__', $escapedRoot)

    Add-Content -Path $PROFILE -Value "`r`n$block`r`n"
    Write-Ok "Added auto-venv and completion to $PROFILE"
}

Write-Host "Moviebox installer (Windows PowerShell)" -ForegroundColor Cyan
Write-Host ""

Write-Step "Checking Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Throw-InstallError "Python 3.10+ is required. Install from https://www.python.org/downloads/"
}

$pythonVersionRaw = (& python --version) 2>&1
$match = [regex]::Match($pythonVersionRaw, "(\d+)\.(\d+)")
if (-not $match.Success) {
    Throw-InstallError "Unable to parse Python version: $pythonVersionRaw"
}

$major = [int]$match.Groups[1].Value
$minor = [int]$match.Groups[2].Value
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
    Throw-InstallError "Python 3.10+ is required (detected: $pythonVersionRaw)"
}
Write-Ok "Using $pythonVersionRaw"

Write-Step "Creating virtual environment"
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Ok "Reusing existing .venv"
}
else {
    & python -m venv .venv
    Write-Ok "Created .venv"
}

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$movieboxBinary = Join-Path $ProjectRoot ".venv\Scripts\moviebox.exe"

Write-Step "Upgrading pip"
& $venvPython -m pip install --upgrade pip
Write-Ok "pip upgraded"

Write-Step "Installing moviebox with CLI extras"
& $venvPython -m pip install -e ".[cli]"
Write-Ok "moviebox installed"

Write-Step "Configuring shell integration"
Add-ShellIntegration

Write-Step "Verifying CLI entrypoint"
& $movieboxBinary --help | Out-Null
Write-Ok "moviebox CLI is ready"

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "- Open a new PowerShell window to enable auto-venv + completion."
Write-Host "- Run now: .\.venv\Scripts\Activate.ps1; moviebox interactive-tui" -ForegroundColor Cyan
Write-Host "- Legacy menu is still available: moviebox interactive" -ForegroundColor Cyan
Write-Host "- Disable shell setup on rerun with: `$env:MOVIEBOX_SKIP_SHELL_SETUP='1'; .\install.ps1" -ForegroundColor Cyan
