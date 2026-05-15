@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  AccGenie / Aiccounting — Windows packaging build
REM
REM  Phase A pipeline:
REM    1. Nuitka --standalone compiles main.py + all packages to a real
REM       Windows binary in build\output\main.dist\
REM    2. Inno Setup wraps that folder into a single Setup.exe installer.
REM
REM  Prerequisites:
REM    • pip install -r requirements-build.txt
REM    • Inno Setup 6 (https://jrsoftware.org/isdl.php) — installs ISCC.exe
REM    • A C compiler. Nuitka will offer to download MinGW-w64 on first run
REM      if none is present (--assume-yes-for-downloads accepts it).
REM
REM  Run from repository root:
REM      build\build.bat
REM ──────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

set APP_NAME=AccGenie
set VERSION=1.0.7
set OUTPUT_DIR=build\output
set DIST_DIR=build\dist

echo.
echo === [1/2]  Compiling with Nuitka  (this takes 5-15 minutes) ===
echo.

python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=ui ^
    --include-package=ai ^
    --include-package=core.migration ^
    --include-data-files="ui/AccGenie final logo.png=ui/AccGenie final logo.png" ^
    --windows-console-mode=disable ^
    --output-dir=%OUTPUT_DIR% ^
    --output-filename=%APP_NAME%.exe ^
    --remove-output ^
    --assume-yes-for-downloads ^
    --product-name=%APP_NAME% ^
    --product-version=%VERSION% ^
    --file-version=%VERSION% ^
    --file-description="AccGenie - Indian Accounting Software" ^
    --copyright="(c) 2026 Aiccounting" ^
    main.py

if errorlevel 1 (
    echo.
    echo *** Nuitka build failed. See output above. ***
    exit /b 1
)

echo.
echo === [2/2]  Building installer with Inno Setup ===
echo.

REM Try standard Inno Setup install paths
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"      set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if "!ISCC!"=="" (
    where iscc.exe >nul 2>&1
    if not errorlevel 1 set ISCC=iscc.exe
)

if "!ISCC!"=="" (
    echo *** ISCC.exe not found. Install Inno Setup 6 from
    echo     https://jrsoftware.org/isdl.php  and re-run.
    exit /b 1
)

if not exist %DIST_DIR% mkdir %DIST_DIR%

!ISCC! /Qp ^
    "/DAppName=%APP_NAME%" ^
    "/DAppVersion=%VERSION%" ^
    build\installer.iss

if errorlevel 1 (
    echo *** Inno Setup build failed. ***
    exit /b 1
)

echo.
echo === Done. Installer at:  %DIST_DIR%\%APP_NAME%-Setup-%VERSION%.exe ===
echo.
endlocal
