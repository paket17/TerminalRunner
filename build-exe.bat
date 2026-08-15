@echo off
setlocal
cd /d "%~dp0"

py -m pip install -e ".[dev]"
if errorlevel 1 exit /b %errorlevel%

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

py -m PyInstaller --noconfirm --clean TerminalRunner.spec
if errorlevel 1 exit /b %errorlevel%

copy /y "terminalrunner\commands.yaml" "dist\commands.yaml" >nul
if errorlevel 1 exit /b %errorlevel%

echo.
echo Built dist\TerminalRunner.exe and dist\commands.yaml
endlocal
