# Changelog

All notable changes to GmailBridge (formerly MailBridge). Dates are YYYY-MM-DD.

## [3.0.0] - 2026-11-02 · "Sunrise" 🌅

MailBridge grows up: it gets a new name, a whole new face and a handful of new tricks.

### ✨ New name, new look
- **MailBridge is now GmailBridge.** Same app, same job, a name that says where your mail ends up.
- **A real logo**: a suspension bridge at sunrise. The towers and the cable draw the "M" of Gmail (and an
  envelope flap), and the rising sun is your mail arriving. Crisp at every size, down to the tiny 16 px
  tray icon, which gets its own bolder drawing.
- **A wordmark** set in Sora, where the dot on the "i" of *Bridge* is the same rising sun.
- **A redesigned window**: night-sky and sunrise palette, automatic light and dark themes, status lights
  shaped like little suns on the horizon, a countdown where your mail crosses a bridge, a main button
  where the sun rises on hover, dashed "Add" slots, and a bridge silhouette in the background.
- **Hand-made icon set**, with a little coral sun on the key icons.
- **Better readability**: every text and colour pair meets WCAG AA contrast (the old purple theme had two
  that didn't).
- **Brand kit** in `assets/brand/`: logo, wordmark, lockups (light and dark), banner, brand sheet and
  icons, all SVG, all generated from code.

### 🧭 Google Calendar, the easy way
- A **guided wizard**: each step opens the exact Google Cloud page and tells you what to click.
- The downloaded `client_secret_….json` is **spotted in your Downloads folder and imported automatically**.
- Sign-in follows straight away and the access is **really checked** ("connected and verified · N calendars").
- Google errors are translated into plain words, with a **Fix** button that opens the right page.
- Sign-in can be cancelled, and "Web application" clients are refused up front with an explanation.

### 🔔 Tray icon
- A **persistent notification-area icon** shows that GmailBridge is alive between runs: active, paused or
  needs a look, plus the time of the last run. Click it to open the app; right-click to **Sync now**.

### 🛠️ Under the hood
- `mailbridge/icon.py` is the single source of the logo: it writes the SVGs and renders the multi-size
  `.ico` in pure Python (no image library), checked against Chrome's SVG rendering.
- New developer tools: `tools/build_brand.py`, `tools/make_screenshots.py`, `tools/build_release.py`.
- 60 offline tests (new: icon tests).

### ⚠️ Upgrading from MailBridge
- Run the installer again (or `Install-GmailBridge.cmd`): it replaces the old shortcuts with GmailBridge ones.
- **Nothing to migrate**: settings, saved passwords, Google access and background tasks keep working as is
  (their internal names did not change on purpose).
- Existing Google calendars keep their names; new ones are called "GmailBridge · …".

## [2.0.0] - 2026-10-30

- Several accounts in one Gmail, each with its own label: IMAP providers and Outlook mode
  (Microsoft 365 through the local Outlook, no password).
- Duplicate protection (message ID, then sender + subject + time).
- Outlook calendars mirrored into Google Calendar (desktop OAuth with PKCE, standard library only).
- Animated HTML interface (pywebview + WebView2), demo mode, one-click installer.

[3.0.0]: https://github.com/Andrianarivelo/MailBridge/releases/tag/v3.0.0
