@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  wordCensor - Portable Build Script
::  Run this once from the project root to produce dist_portable\
::  Requires internet connection.
:: ============================================================

set PYTHON_VERSION=3.11.9
set PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
set FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip

set ROOT=%~dp0
set DIST=%ROOT%dist_portable
set PYDIR=%DIST%\python_embded

echo.
echo  =========================================
echo   wordCensor Portable Builder
echo  =========================================
echo.

:: Clean previous build
if exist "%DIST%" (
    echo [*] Removing previous build...
    rmdir /s /q "%DIST%"
)
mkdir "%DIST%"
mkdir "%PYDIR%"
mkdir "%DIST%\ffmpeg"
mkdir "%DIST%\app"

:: ----------------------------------------------------------
echo [1/5] Downloading Python %PYTHON_VERSION% embeddable...
:: ----------------------------------------------------------
powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%ROOT%python_embed.zip' -UseBasicParsing"
if errorlevel 1 ( echo ERROR: Failed to download Python. & exit /b 1 )

powershell -NoProfile -Command ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%ROOT%python_embed.zip', '%PYDIR%')"
if errorlevel 1 ( echo ERROR: Failed to extract Python. & exit /b 1 )
del "%ROOT%python_embed.zip"

:: ----------------------------------------------------------
echo [2/5] Configuring embedded Python...
:: ----------------------------------------------------------
powershell -NoProfile -Command ^
  "(Get-Content '%PYDIR%\python311._pth') -replace '#import site', 'import site' | Set-Content '%PYDIR%\python311._pth'"
echo ../app>> "%PYDIR%\python311._pth"

:: ----------------------------------------------------------
echo [3/5] Installing pip + dependencies...
:: ----------------------------------------------------------
powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%ROOT%get-pip.py' -UseBasicParsing"
if errorlevel 1 ( echo ERROR: Failed to download get-pip.py. & exit /b 1 )

"%PYDIR%\python.exe" "%ROOT%get-pip.py" --no-warn-script-location -q
del "%ROOT%get-pip.py"

"%PYDIR%\python.exe" -m pip install PyQt5 opencv-python numpy --no-warn-script-location -q
if errorlevel 1 ( echo ERROR: pip install failed. & exit /b 1 )

:: ----------------------------------------------------------
echo [4/5] Downloading FFmpeg...
:: ----------------------------------------------------------
powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri '%FFMPEG_URL%' -OutFile '%ROOT%ffmpeg_dl.zip' -UseBasicParsing"
if errorlevel 1 ( echo ERROR: Failed to download FFmpeg. & exit /b 1 )

powershell -NoProfile -Command ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%ROOT%ffmpeg_dl.zip', '%ROOT%ffmpeg_tmp')"
if errorlevel 1 ( echo ERROR: Failed to extract FFmpeg. & exit /b 1 )
del "%ROOT%ffmpeg_dl.zip"

for /r "%ROOT%ffmpeg_tmp" %%f in (ffmpeg.exe) do (
    copy /y "%%f" "%DIST%\ffmpeg\ffmpeg.exe" >nul
    goto :ffmpeg_done
)
:ffmpeg_done
rmdir /s /q "%ROOT%ffmpeg_tmp"

if not exist "%DIST%\ffmpeg\ffmpeg.exe" (
    echo ERROR: ffmpeg.exe not found in downloaded archive.
    exit /b 1
)

:: ----------------------------------------------------------
echo [5/5] Copying app files...
:: ----------------------------------------------------------
xcopy /s /e /y "%ROOT%app" "%DIST%\app\" >nul

:: ----------------------------------------------------------
echo [*] Creating launcher...
:: ----------------------------------------------------------
(
    echo @echo off
    echo cd /d "%%~dp0"
    echo start "" python_embded\pythonw.exe app\main.py
) > "%DIST%\wordCensor.bat"

echo.
echo  =========================================
echo   Build complete!  ^>  dist_portable\
echo  =========================================
echo.
echo   Zip the "dist_portable" folder and share it.
echo   End users double-click: wordCensor.bat
echo.
endlocal
