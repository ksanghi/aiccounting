# Onboarding Wizard — Spec (F2)

All-tier, flexible, license-aware onboarding for **both Accounts HQ and RWA HQ**.
Locked 2026-06-10. Replaces the old behaviour where pages were hidden by tier.

## Goal
Make the setup wizard adapt to the licence the customer actually bought, show
them everything (including what they don't have yet, as upsell), turn the right
things on, and come back when they upgrade.

## Behaviours

1. **License-aware.** Reads the bought plan and asks only the questions/settings
   that matter for it. Plan comes from `lmgr` (`has_feature` / `plan`).

2. **Show, don't hide (the "not tier-gated tour" fix).** Every feature is shown
   to everyone. Features above the current tier are NOT hidden — they appear with
   a **"Unlocks with Standard/Pro"** badge, a one-line "what it does", and an
   **Upgrade** button. Free users see what they're missing.

3. **Re-runs on upgrade.** Today it runs once (`setup_wizard_done`) and never
   returns. New rule: store the plan it last ran for (`setup_wizard_plan`). On
   launch, if the current plan is higher than the stored one, re-open the wizard
   focused on the **newly unlocked** features so the upgrade actually gets turned
   on. (Hook RWA's existing `_on_plan_changed`; add the same for AHQ.)

4. **AI key choice drives the AI pipeline.** One page asks: use **our key**
   (wallet, pay-per-doc) or **your own key** (BYOK)?
   - Our key (wallet) → **AI Doc Reader** (`document_recognition`) is the active
     AI path; **Document Inbox** (`document_inbox`, BYOK bulk email/scan) stays off.
   - Own key (BYOK) → **Document Inbox** is activated (key saved via
     `core.ai_routing.routing.set_own_key`).
   Aligns with the AI-doc-routing decision (AI Doc Reader is always wallet;
   Document Inbox is always BYOK).

5. **Flexible, not a forced march.** Checklist-style: the user can do the items
   they want, skip the rest, and re-run any time from the sidebar/Settings.
   Each item shows done / not-done.

6. **Both products, different page sets.**
   - **AHQ pages:** Look & feel, GST, TDS, Bill-wise, AI key + Document Inbox,
     Email import, Scanner, Backup.
   - **RWA HQ pages:** Society profile (name/address/GSTIN/state), Billing setup
     (basis, schedules, waivers), payment-collection UPI, WhatsApp/Meta, Backup.
   Shared framework in `ui/setup_wizard.py`; RWA HQ contributes its page set via
   a subclass hook (mirrors how RWA adds settings cards via
   `_build_extra_settings_cards`).

7. **Captures ALL settings, persisted, after an informed decision.** The wizard
   is the single consolidated place settings are set — every choice is saved to
   durable storage (`user_prefs` / `core.config` / company row / `ai_routing`),
   nothing left transient. Each setting is presented with the existing
   **"Why this helps / What it takes"** block so the user makes an educated
   choice (set it up or skip), not a blind one. Re-running the wizard shows the
   current saved value so it doubles as the settings editor.

## Code shape
- `ui/setup_wizard.py` — EXTEND. Replace `if has(f): addPage` with always-add +
  per-page locked/unlocked state. Add the AI-key choice page. Add a
  product/page-set hook so RWA HQ injects its pages.
- `ui/main_window.py` — `_maybe_setup_wizard` re-runs on upgrade (compare current
  plan vs stored `setup_wizard_plan`); both AHQ and RWA paths.
- RWA subclass (`rwagenie/.../main_window` or wherever RWAMainWindow lives) —
  provide the RWA page set + reuse the upgrade re-run.

## Tier
The wizard itself is all-tier (free included). Feature *activation* still respects
`has_feature`; locked features are shown but their controls are replaced by the
upgrade teaser.
