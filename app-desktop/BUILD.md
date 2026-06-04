# CoachAI Desktop — Build & Ship Guide

This turns the source into a **double-click installer** — `CoachAI-Setup.exe`
on Windows, `CoachAI.dmg` on Mac. A gamer downloads it, runs it, signs in with
Discord once, and never touches anything else: the app sits in the tray, detects
Overwatch, and records + coaches automatically.

## What the user experiences

1. Download `CoachAI-Setup.exe`, double-click.
2. It installs and launches itself (one-click NSIS installer).
3. Click **Sign in with Discord** once. Done.
4. The window can be closed — the app keeps running in the system tray.
5. Launch Overwatch 2 → CoachAI auto-starts recording, shows live tips on an
   overlay, and generates a report when the match ends.

No OBS. No terminal. No Python install. No separate web dashboard to open.

## What's inside the installer

- The Electron app (this `app-desktop/`).
- The **entire Python backend compiled to a single binary** by PyInstaller,
  bundled in `resources/server/`. The app spawns it on launch on a random
  loopback port. This is why it works offline with no per-user cloud cost.
- The vision model file (`ow2_state_detector.pt`) — ships in the binary or
  alongside it (see note below).

## One-time setup on YOUR build machine

You build on each target OS (Windows builds the `.exe`, a Mac builds the
`.dmg` — electron-builder can't cross-compile native installers).

```bash
# Prereqs (once):
#   - Node 18+ and npm
#   - Python 3.11 + pip install pyinstaller
#   - The trained vision model at backend/models/ow2_state_detector.pt
#     (or set VISION_BACKEND=api in the bundled env to skip the model — see below)

cd app-desktop
npm install
```

## Build it

```bash
# This single command does everything:
#   1. PyInstaller compiles backend → server-dist/coachai-server(.exe)
#   2. electron-builder packages the app + server into an installer
npm run build          # builds for your current OS
# or explicitly:
npm run build:win      # → dist/CoachAI-Setup-1.0.0.exe
npm run build:mac      # → dist/CoachAI-1.0.0.dmg
```

Output lands in `app-desktop/dist/`. That file is what you give to users.

## Configuration the bundled server needs

The compiled server reads a few values. Bake them into the PyInstaller build by
committing a `backend/.env.local` (loaded when `COACHAI_LOCAL_MODE=1`) **without
secrets you don't want shipped**:

| Var | For | Ship it? |
|---|---|---|
| `DISCORD_CLIENT_ID` | OAuth | yes (public) |
| `DISCORD_CLIENT_SECRET` | OAuth token exchange | **risky to ship** — see below |
| `ANTHROPIC_API_KEY` | coaching LLM | **do NOT ship** — see below |
| `VISION_BACKEND` | `self_hosted` (uses the bundled model) | yes |

### The two things you can't just bake in

**1. The LLM key.** If you bundle your Anthropic key in the binary, every user
shares it and anyone can extract it. Two clean options:
- Route only the LLM calls through a thin cloud proxy that authenticates the
  user's JWT (everything else stays local). This is the recommended hybrid.
- Or ship a small local LLM (e.g. an 8B model via llama.cpp) for fully offline
  coaching — bigger download, no key. Wire it as a third `vision_backend`-style
  option in `analysis/coach.py`.

**2. The Discord secret.** Same problem. The clean fix is the same proxy: the
desktop app hits `your-cloud.com/auth/discord/start`, the exchange happens
server-side, and the cloud 302s the token to `coachai://auth`. The
`discord_callback_url` then points at your cloud, not loopback. The code already
supports this — just set `DISCORD_CALLBACK_URL` to your cloud endpoint.

So the honest architecture for a real launch is **mostly-local**: vision,
recording, clip-cutting, reports, and the database all run on the user's
machine; only OAuth and the LLM call touch a tiny cloud shim you run. That keeps
your per-user cost to near-zero (just LLM tokens) while preserving the offline,
no-setup feel for everything heavy.

## Code signing (do this before public release)

Unsigned apps trigger scary warnings (Windows SmartScreen, Mac Gatekeeper).
- **Windows:** buy an OV/EV code-signing cert; set `CSC_LINK` + `CSC_KEY_PASSWORD`
  env vars and electron-builder signs automatically.
- **Mac:** enrol in the Apple Developer Program; set `APPLE_ID`,
  `APPLE_APP_SPECIFIC_PASSWORD`, `CSC_NAME`; electron-builder notarises.

## Model file size note

The vision model + Python runtime make the installer large (~150–400MB depending
on torch build). To shrink it: ship the CPU-only torch wheel if you're okay with
slower inference, or download the model on first run instead of bundling it
(add a one-time fetch in `localServer.js` before the health check).
