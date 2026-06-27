@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  Books HQ — preview build (US flavor of the shared Accounts HQ engine).
REM
REM  Same pipeline as build.bat, but:
REM    • bakes core/_flavor.py FORCE_COUNTRY="US" so the app runs as Books HQ
REM      regardless of the licence country (preview/testing build),
REM    • uses the Books HQ name + logo + icon,
REM    • outputs "Books HQ.exe".
REM  The flavor file is reset to None after compiling so normal builds stay clean.
REM
REM  Run from repository root:  build\build_bookshq.bat
REM ──────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

set APP_NAME=Books HQ
set VERSION=0.1.2
set OUTPUT_DIR=build\output
set DIST_DIR=build\dist

echo.
echo === Baking US flavor (Books HQ) ===
(echo FORCE_COUNTRY = "US")> core\_flavor.py

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
    --include-data-files="ui/bookshq-logo.png=ui/bookshq-logo.png" ^
    --include-data-files="ui/bookshq.ico=ui/bookshq.ico" ^
    --include-data-files="ui/accountshq-logo.png=ui/accountshq-logo.png" ^
    --include-data-files="ui/accountshq.ico=ui/accountshq.ico" ^
    --windows-icon-from-ico="ui\bookshq.ico" ^
    --windows-console-mode=disable ^
    --output-dir=%OUTPUT_DIR% ^
    --output-filename="%APP_NAME%.exe" ^
    --remove-output ^
    --assume-yes-for-downloads ^
    main.py

set NUITKA_ERR=%errorlevel%

echo.
echo === Resetting flavor to None (clean for normal builds) ===
(echo FORCE_COUNTRY = None)> core\_flavor.py

if not "%NUITKA_ERR%"=="0" (
    echo.
    echo *** Nuitka build failed. See output above. ***
    exit /b 1
)

echo.
echo === [2/2]  Building installer with Inno Setup ===
echo.

set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"      set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" (
    where iscc.exe >nul 2>&1
    if not errorlevel 1 set ISCC=iscc.exe
)
if "!ISCC!"=="" (
    echo *** ISCC.exe not found. Install Inno Setup 6 and re-run. ***
    exit /b 1
)

if not exist %DIST_DIR% mkdir %DIST_DIR%

!ISCC! /Qp ^
    "/DAppName=%APP_NAME%" ^
    "/DAppVersion=%VERSION%" ^
    "/DAppId={{A1CC5E22-1234-4E78-9ABC-AICCOUNTING002}" ^
    "/DSetupIcon=bookshq.ico" ^
    build\installer.iss

if errorlevel 1 (
    echo *** Inno Setup build failed. ***
    exit /b 1
)

echo.
echo === Done. Installer at:  %DIST_DIR%\%APP_NAME%-Setup-%VERSION%.exe ===
echo.

endlocal
