@echo off
echo [1/4] Killing processes...
taskkill /F /IM backend.exe /T 2>nul
taskkill /F /IM RuCaptioner.exe /T 2>nul
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM node.exe /T 2>nul
taskkill /F /IM electron.exe /T 2>nul

echo [2/4] Waiting for release of locks...
timeout /t 3 /nobreak >nul

echo [3/4] Removing release folder...
if exist "release" (
    rmdir /s /q "release"
    if exist "release" (
        echo ERROR: Could not delete release folder. Please restart your computer.
        pause
        exit /b 1
    )
)
if exist "dist" (
    rmdir /s /q "dist"
)
if exist "build" (
    rmdir /s /q "build"
)

echo [4/4] Starting build...
call npm run dist

echo.
echo ==============================================
echo BUILD COMPLETE!
echo You can close this window.
echo ==============================================
pause
