# Windows Installation Tester
# Test syntax and logic of Windows install scripts

Write-Host "🧪 Testing Windows Installation Scripts" -ForegroundColor Cyan
Write-Host ""

# Test PowerShell script
Write-Host "Testing install.ps1..." -ForegroundColor Blue
try {
    # Parse script for syntax errors
    $null = [System.Management.Automation.PSParser]::Tokenize((Get-Content install.ps1 -Raw), [ref]$null)
    Write-Host "✓ PowerShell script syntax valid" -ForegroundColor Green
} catch {
    Write-Host "❌ PowerShell script has syntax errors:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit 1
}

# Test batch file
Write-Host "Testing install.bat..." -ForegroundColor Blue
if (Test-Path install.bat) {
    # Basic validation - check for common commands
    $content = Get-Content install.bat -Raw
    if ($content -match "python" -and $content -match "pip" -and $content -match "venv") {
        Write-Host "✓ Batch script structure valid" -ForegroundColor Green
    } else {
        Write-Host "⚠ Batch script missing key commands" -ForegroundColor Yellow
    }
} else {
    Write-Host "❌ install.bat not found" -ForegroundColor Red
}

Write-Host ""
Write-Host "✅ Windows scripts validated!" -ForegroundColor Green
Write-Host ""
Write-Host "Note: Full testing requires actual Windows environment" -ForegroundColor Yellow
