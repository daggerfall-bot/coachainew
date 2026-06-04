# CoachAI Desktop

The "just works" version: one app, double-click, sign in with Discord once,
play Overwatch. It records, coaches you live, and reports — no OBS, no terminal,
no Python install, no separate dashboard.

## How it works

```
┌─────────────────────────── CoachAI.exe ───────────────────────────┐
│                                                                     │
│  Electron main ──spawns──▶ Bundled Python server (loopback:random) │
│      │                          │  vision model on user's GPU      │
│      │  tray + game watcher     │  analysis + reports local        │
│      │                          │  SQLite, local-disk clips        │
│      ▼                          ▲                                   │
│  Renderer (capture) ──frames───┘                                   │
│      │  records screen like OBS (built in)                          │
│      │  streams 5fps → live coach socket → overlay tips             │
│      ▼                                                              │
│  Transparent always-on-top overlay (speaks + shows tips)            │
└─────────────────────────────────────────────────────────────────┘
       only OAuth + the LLM call optionally touch a tiny cloud shim
```

## Run in dev

```bash
# Terminal 1 — backend (auto-spawned in prod; run manually in dev)
cd ../backend && COACHAI_LOCAL_MODE=1 uvicorn app.main:app --port 8745

cd app-desktop && npm install && npm start
```

In dev, `localServer.js` runs uvicorn from source. In a built app it runs the
PyInstaller binary instead — see BUILD.md.

## Build the installer

```bash
npm run build      # → dist/CoachAI-Setup-1.0.0.exe (or .dmg / .AppImage)
```

Full details, the LLM-key / Discord-secret caveats, and code-signing: **BUILD.md**.

## Files

| Path | Role |
|---|---|
| `src/main/main.js` | app lifecycle, windows, orchestration |
| `src/main/localServer.js` | spawns + supervises the bundled Python server |
| `src/main/gameWatcher.js` | auto-detects Overwatch 2 |
| `src/main/auth.js` | Discord OAuth via coachai:// deep-link |
| `src/main/tray.js` | background tray icon + status |
| `src/main/ipc.js` | secure main↔renderer bridge |
| `src/preload/preload.js` | exposed `window.desktop` API |
| `src/renderer/capture.js` | the built-in screen recorder + frame streamer |
| `src/renderer/app.js` | login + status UI controller |
| `src/renderer/overlay.html` | live tip overlay (shows + speaks) |
| `scripts/build-server.js` | PyInstaller bundling step |
