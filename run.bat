@echo off
setlocal
cd /d "%~dp0"
title Multi-Thread Downloader

set "PY_EXE="

if exist "%USERPROFILE%\.local\bin\python3.11.exe" (
    set "PY_EXE=%USERPROFILE%\.local\bin\python3.11.exe"
    goto do_run
)

if exist "%USERPROFILE%\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe" (
    set "PY_EXE=%USERPROFILE%\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe"
    goto do_run
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PY_EXE=%%D\python.exe"
        goto do_run
    )
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_EXE=python"
    goto do_run
)

echo [ERROR] Python not found on this machine!
echo Please make sure Python is installed.
pause
exit /b 1

:do_run
"%PY_EXE%" main.py %*
if %errorlevel% neq 0 (
    pause
)
