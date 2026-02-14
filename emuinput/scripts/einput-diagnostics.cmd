@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0uinput-diagnostics.ps1" -AttemptFix -PythonCheck %*
exit /b %ERRORLEVEL%
