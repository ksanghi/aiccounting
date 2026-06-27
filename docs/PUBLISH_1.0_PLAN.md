# Publish Accounts HQ 1.0 — ready-to-execute plan

**Status: NOT executed — awaiting your OK** (it touches the live site, so it
waits for you per the no-unilateral-deploy rule). On your "go" I run all of it
in one pass.

The built installer is verified and waiting:
`build/dist/Accounts HQ-Setup-1.0.31.exe` (icon embedded, smoke-tested).
Public release version is **“1.0”** (build 1.0.31); the installer is hosted
under a *stable* name so the URL never changes between builds.

## The change set (5 steps)

1. **Host the installer** — copy the built exe into the site's downloads folder
   under a stable name:
   `build/dist/Accounts HQ-Setup-1.0.31.exe`  →  `marketing-aic/downloads/AccountsHQ-Setup.exe`
   (Today that folder holds only `RWAHQ-Setup.exe`.)

2. **Add a Download button** on `marketing-aic/accountshq.html`.
   Today the CTAs point to `#pricing` / `pricing.html` (“Start free”, “Try
   free”) — there is **no download link yet**. Add a *“Download for Windows”*
   button in the hero `cta-row` (line ~489) and the final CTA, pointing at
   `https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe`.

3. **Resolve the self-update TODO** — `license_server/main.py:421-427`,
   `LATEST_RELEASE["accgenie"]`: set
   `"url": "https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe"`
   (currently a placeholder `https://apps.ai-consultants.in/`). `latest` stays
   `"1.0"` — matches the baked release, so no false update prompt.

4. **Wire license-email installer link** — `license_server/services/email_service.py:100`,
   add to `_INSTALLER_URL`:
   `"accgenie": "https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe"`
   so purchase/license emails carry the download link (today AHQ falls through
   to a “write to info@” nudge).

5. **Deploy** the license server (it serves marketing pages + downloads):
   ```
   fly deploy --config license_server/fly.toml --dockerfile license_server/Dockerfile .
   ```
   (run from the `Aiccounting/` dir — the parent build context is required).

## After deploy — verify
- `https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe` downloads.
- `https://aic.ai-consultants.in/accountshq.html` shows the Download button.
- `GET https://license.ai-consultants.in/api/v1/app-version?product=accgenie`
  returns the real installer URL.

## Open question for you
- Should the public **Download button** give the installer directly (free tier,
  upgrade in-app) — or route through **pricing/checkout** first? The page is
  currently built around “Start free → pricing”. I’ll wire it whichever way you
  want; my default is a direct **Download for Windows** button *plus* keeping
  the existing “See pricing” CTA next to it.
