# Building the AccGenie installer (Windows)

Phase A pipeline — produces a real Windows binary + Inno Setup `.exe`
installer that runs on Windows 10 / 11 with no Python required on
the target machine.

## One-time setup

1. **Build dependencies**:
   ```
   pip install -r requirements-build.txt
   ```
   This installs Nuitka, zstandard (for compression), ordered-set
   (faster analysis), and the runtime dependencies.

2. **Inno Setup 6** — installer-builder. Free, Windows only.
   Download from <https://jrsoftware.org/isdl.php> and install.
   The build script auto-detects standard install paths.

3. **C compiler** — Nuitka needs one. On first run it offers to
   download MinGW-w64 automatically; the build script accepts via
   `--assume-yes-for-downloads`. If you already have Visual Studio
   Build Tools, Nuitka will pick those up.

## Operator config (Excel → baked Python)

Per-version operator parameters — AI feature routing, plan tiers,
features-per-plan, country pricing — live in two Excel files:

```
config\ai_features.xlsx    Which AI features are byok vs ag_key
config\pricing.xlsx        Tiers, plan-feature matrix, country pricing
```

Edit these by hand in Excel. After editing, run the baker to compile
the values into Python modules that ship inside the binary:

```
python build\bake_config.py
```

The baker writes:

- `core\_baked_config.py` — consumed by the desktop app
  (`core\ai_features.py`, `core\pricing.py`, `core\license_manager.py`).
- `license_server\_baked_config.py` — consumed by the license-server
  (`license_server\plans.py`).

Both generated files are committed to git so a diff at review time shows
exactly what changed in the operator config between releases. The
running app never reads the .xlsx at runtime; values are frozen at bake
time.

If you ever need to reset the .xlsx templates back to seed defaults
(careful — overwrites your edits), run:

```
python build\make_config_xlsx.py
```

## Build

From the repository root:

```
build\build.bat
```

> **Note:** `build.bat` does not currently auto-run the baker. After
> editing the .xlsx files, run `python build\bake_config.py` yourself
> before kicking off `build.bat`. The baker writes generated .py files
> that the Nuitka step then picks up.


What it does (5–15 minutes total):

1. **Nuitka `--standalone`** compiles `main.py` and every package
   (core, ui, ai, core.migration) to a real Windows binary, bundling
   the Python interpreter and all PyQt6 / pdfplumber / openpyxl /
   python-docx DLLs. Output: `build\output\main.dist\AccGenie.exe`.

2. **Inno Setup** wraps that folder into
   `build\dist\AccGenie-Setup-1.0.0.exe` — a single double-click
   installer with Start Menu / optional desktop shortcuts and an
   uninstaller. Per-user install (no admin required); lands in
   `%LOCALAPPDATA%\AccGenie`.

## Where data lives

The packaged build separates code (read-only, install dir) from
user data (writable, per-user):

| What | Path |
|------|------|
| Binaries / Qt DLLs | `%LOCALAPPDATA%\AccGenie\` |
| Company `.db` files | `%APPDATA%\AccGenie\companies\` |
| `license.json` | `%APPDATA%\AccGenie\license.json` |
| `credits.json` | `%APPDATA%\AccGenie\credits.json` |
| API key / config | `%APPDATA%\AccGenie\config\` |

Path resolution lives in `core/paths.py`. In dev mode (running
from source), data still lands in `<repo>/data/` so existing dev
workflows aren't affected.

## Source protection

Nuitka compiles Python to native machine code. There is no `.pyc`
bytecode in the install folder; reverse-engineering requires
disassembling actual x86_64 machine code — a much higher bar than
PyArmor or plain PyInstaller bundles. Trade-offs:

- Build time: 5–15 minutes (vs ~30 seconds with PyInstaller).
- Binary size: larger than PyInstaller (~120 MB vs ~80 MB).
- Compatibility: Nuitka generally tracks PyQt6 well. If a runtime
  ImportError appears for a package you use dynamically, add
  `--include-package=foo` or `--include-module=foo.bar` to
  `build\build.bat`.

## Code signing (later)

Once you have a code-signing certificate, add a `signtool sign`
step to `build.bat` after the Inno Setup line:

```
signtool sign /f mycert.pfx /p PASSWORD /tr http://timestamp.sectigo.com ^
  /td sha256 /fd sha256 build\dist\AccGenie-Setup-%VERSION%.exe
```

## Troubleshooting

- **"Nuitka is not recognized"**: `pip install nuitka` (or
  `pip install -r requirements-build.txt`).
- **"ISCC.exe not found"**: install Inno Setup 6 from the link
  above. Default install path is auto-detected.
- **Nuitka asks to download MinGW or ccache**: accept (it answers
  yes automatically with `--assume-yes-for-downloads`).
- **First run on the target machine fails** with a missing-DLL
  error: ensure the user has the **Microsoft Visual C++
  Redistributable** installed (most Windows 10/11 boxes already do).
