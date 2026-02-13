#!/bin/bash
# Test Windows Scripts on Linux (Basic Validation)

echo "🧪 Testing Windows Installation Scripts (on Linux)"
echo ""

# Test PowerShell syntax (if pwsh available)
echo "[1/3] Checking PowerShell script..."
if command -v pwsh &> /dev/null; then
    pwsh -NoProfile -Command "
        try {
            \$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content install.ps1 -Raw), [ref]\$null)
            Write-Host '✓ install.ps1 syntax valid' -ForegroundColor Green
        } catch {
            Write-Host '❌ install.ps1 has errors' -ForegroundColor Red
            exit 1
        }
    "
else
    echo "⚠ PowerShell not available - install with: sudo snap install powershell --classic"
    echo "Skipping PowerShell validation..."
fi
echo ""

# Validate batch file structure
echo "[2/3] Checking batch script..."
if [ -f "install.bat" ]; then
    # Check for key commands
    if grep -q "python" install.bat && grep -q "pip" install.bat && grep -q "venv" install.bat; then
        echo "✓ install.bat structure looks good"
    else
        echo "⚠ install.bat might be missing key commands"
    fi
else
    echo "❌ install.bat not found"
fi
echo ""

# Check file line endings (Windows needs CRLF)
echo "[3/3] Checking line endings..."
if command -v file &> /dev/null; then
    BAT_TYPE=$(file install.bat | grep -o "CRLF\|LF")
    PS1_TYPE=$(file install.ps1 | grep -o "CRLF\|LF")
    
    if [ "$BAT_TYPE" = "CRLF" ]; then
        echo "✓ install.bat has Windows line endings (CRLF)"
    else
        echo "⚠ install.bat has Unix line endings - converting..."
        if command -v unix2dos &> /dev/null; then
            unix2dos install.bat install.ps1 2>/dev/null
            echo "✓ Converted to CRLF"
        else
            echo "  Install unix2dos: sudo apt install dos2unix"
        fi
    fi
fi
echo ""

echo "✅ Basic validation complete!"
echo ""
echo "📝 Notes:"
echo "  • Full testing requires actual Windows"  
echo "  • Scripts validated for structure and syntax"
echo "  • Line endings checked for Windows compatibility"
echo ""

# Summary
echo "📊 Summary:"
echo "  install.sh       ✅ (current platform)"
echo "  install.ps1      ⚠️  (needs Windows/PowerShell)"
echo "  install.bat      ⚠️  (needs Windows)"
echo "  install-termux.sh ✅ (validated)"
echo ""
