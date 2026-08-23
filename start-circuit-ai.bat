@echo off
setlocal
chcp 65001 >nul
title Circuit Design AI - Development

cd /d "%~dp0frontend\desktop" || goto :startup_failed

rem Electron can be present in node_modules while its platform binary is
rem missing. Requiring the pinned package completes that one-time install.
node -e "require('electron')" || goto :startup_failed

call npm.cmd run dev
if errorlevel 1 goto :startup_failed
exit /b 0

:startup_failed
set "STARTUP_EXIT_CODE=%ERRORLEVEL%"
if "%STARTUP_EXIT_CODE%"=="0" set "STARTUP_EXIT_CODE=1"
echo.
echo Circuit Design AI failed to start ^(exit code %STARTUP_EXIT_CODE%^).
echo Review the error above. If dependencies are missing, run npm install in:
echo %~dp0frontend\desktop
echo.
pause
exit /b %STARTUP_EXIT_CODE%
