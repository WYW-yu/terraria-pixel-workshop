@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not installed or not found in PATH.
  echo Please install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" during installation, then run this again.
  pause
  exit /b 1
)
echo Installing application and build dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
echo Building exe (folder mode, runs anywhere)...
python -m PyInstaller --noconfirm --clean --distpath "dist-v5.2" --workpath "build-v5.2" TerrariaPixelArt.spec
if errorlevel 1 (
  echo Build failed. Please check the error messages above.
  pause
  exit /b 1
)
copy /y "使用说明.txt" "dist-v5.2\TerrariaPixelArt\使用说明.txt" >nul
if errorlevel 1 exit /b 1
echo Creating distributable zip...
python tools\package_portable.py
if errorlevel 1 exit /b 1
echo.
echo Done!
echo   - Program folder : dist-v5.2\TerrariaPixelArt\  (double-click TerrariaPixelArt.exe)
echo   - Share this zip : dist-v5.2\泰拉瑞拉像素工坊-v5.2.zip
echo Send the zip to your friends - they can run it without installing Python.
pause
