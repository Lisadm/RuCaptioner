@echo off
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   RuCaptioner - Torch Compatibility Fix
echo ========================================
echo.

if not exist "venv" (
    echo [ERROR] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Current versions:
pip list | findstr "torch"

echo.
echo [INFO] Attempting to install nightly torchao to match torch 2.7.1+cu128...
echo.

:: We use the nightly index for torchao to get the version that matches torch 2.7 nightly
pip install --pre torchao --index-url https://download.pytorch.org/whl/nightly/cu128

if errorlevel 1 (
    echo.
    echo [WARNING] Nightly torchao for cu128 not found on PyTorch servers.
    echo [INFO] Falling back to standard pypi installation...
    pip install --upgrade torchao
)

echo.
echo [INFO] Verification:
pip list | findstr "torch"
python -c "import torch; import torchao; print('Torch:', torch.__version__); print('TorchAO:', torchao.__version__)"

echo.
echo ========================================
echo   Fix attempt complete!
echo ========================================
echo.
pause
