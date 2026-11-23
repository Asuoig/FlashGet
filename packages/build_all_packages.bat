@echo off
setlocal
cd /d "%~dp0"
title Build FlashGet Portable & Installer Packages

echo ========================================================================
echo   FlashGet 全版本发布包自动构建脚本 (Portable ^& Installer)
echo ========================================================================

set "PYTHON_EXE=..\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo.
echo [1/2] 正在生成便携绿色版 (Portable Edition)...
cd ..
"%PYTHON_EXE%" -c "
import os
import shutil
import zipfile

base_dir = os.getcwd()
port_dir = os.path.join(base_dir, 'packages', 'portable', 'FlashGet_Portable')
os.makedirs(port_dir, exist_ok=True)

shutil.copy2(os.path.join(base_dir, 'FlashGet.exe'), os.path.join(port_dir, 'FlashGet.exe'))
shutil.copy2(os.path.join(base_dir, 'app_icon.ico'), os.path.join(port_dir, 'app_icon.ico'))
shutil.copy2(os.path.join(base_dir, 'README.md'), os.path.join(port_dir, 'README.md'))
ext_dst = os.path.join(port_dir, 'browser_extension')
if os.path.exists(ext_dst):
    shutil.rmtree(ext_dst, ignore_errors=True)
shutil.copytree(os.path.join(base_dir, 'browser_extension'), ext_dst)

zip_p = os.path.join(base_dir, 'packages', 'portable', 'FlashGet_v2.5.0_Portable.zip')
if os.path.exists(zip_p):
    os.remove(zip_p)
with zipfile.ZipFile(zip_p, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(port_dir):
        for file in files:
            full_p = os.path.join(root, file)
            rel_p = os.path.relpath(full_p, os.path.dirname(port_dir))
            zf.write(full_p, rel_p)

print('Portable package ready!')
"

echo.
echo [2/2] 正在生成安装包 (Installer Edition)...
cd packages\installer
"%PYTHON_EXE%" build_installer.py

echo.
echo ========================================================================
echo   全部发布版本构建完毕！保存在 packages\ 目录下。
echo ========================================================================
pause
