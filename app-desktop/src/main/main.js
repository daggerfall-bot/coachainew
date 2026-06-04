/**
 * CoachAI Desktop — Electron main process.
 *
 * This is the heart of the "just works" experience. On launch it:
 *   1. Spawns the bundled local backend (Python mini-server) as a child process
 *      so analysis + vision run on the user's own machine, offline.
 *   2. Creates the main window (login → dashboard) and a frameless overlay.
 *   3. Installs a system-tray icon so the app lives in the background.
 *   4. Starts the game watcher, which auto-detects Overwatch 2 and triggers
 *      recording with no user action.
 *
 * Nothing here requires the user to touch a terminal, OBS, or a config file.
 */
const { app, BrowserWindow, Tray, Menu, ipcMain, shell, nativeImage } =
  require("electron");
const path = require("path");

const { LocalServer } = require("./localServer");
const { GameWatcher } = require("./gameWatcher");
const { createTray } = require("./tray");
const { registerIpc } = require("./ipc");
const {
  registerProtocol,
  installDeepLinkHandlers,
} = require("./auth");

// Single-instance lock: launching again just focuses the existing window
// (gamers double-click the icon repeatedly; don't spawn duplicates).
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

let mainWin = null;
let overlayWin = null;
let tray = null;
let server = null;
let watcher = null;

const isDev = !app.isPackaged;

// Register the coachai:// scheme for Discord OAuth deep-links (must happen
// early, before app is ready on some platforms).
registerProtocol();

function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 940,
    minHeight: 640,
    title: "CoachAI",
    backgroundColor: "#080C10",
    show: false,
    frame: true,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWin.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
  mainWin.once("ready-to-show", () => mainWin.show());

  // Closing the window doesn't quit — the app keeps running in the tray so it
  // can keep auto-detecting the game. Quit is explicit (tray menu).
  mainWin.on("close", (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWin.hide();
    }
  });
}

function createOverlayWindow() {
  const { screen } = require("electron");
  const { width } = screen.getPrimaryDisplay().workAreaSize;
  overlayWin = new BrowserWindow({
    width: 420,
    height: 110,
    x: Math.round(width / 2 - 210),
    y: 28,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: false,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.js"),
      contextIsolation: true,
    },
  });
  overlayWin.setIgnoreMouseEvents(true);
  overlayWin.setAlwaysOnTop(true, "screen-saver"); // float above fullscreen games
  overlayWin.loadFile(path.join(__dirname, "..", "renderer", "overlay.html"));
  overlayWin.hide();
}

// ── Status helpers exposed to other modules ──
function sendToMain(channel, payload) {
  if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send(channel, payload);
}
function sendToOverlay(channel, payload) {
  if (overlayWin && !overlayWin.isDestroyed())
    overlayWin.webContents.send(channel, payload);
}
function showOverlay() {
  overlayWin && overlayWin.showInactive();
}
function hideOverlay() {
  overlayWin && overlayWin.hide();
}

app.whenReady().then(async () => {
  createMainWindow();
  createOverlayWindow();

  // Deliver Discord OAuth deep-links (coachai://auth?token=...) to the renderer.
  installDeepLinkHandlers(sendToMain, () => mainWin);

  // 1. Boot the bundled local backend and wait until it's healthy.
  server = new LocalServer({ isDev });
  server.on("status", (s) => sendToMain("server-status", s));
  server.on("log", (line) => isDev && console.log("[server]", line));
  try {
    await server.start();
    sendToMain("server-status", { state: "ready", port: server.port });
  } catch (err) {
    sendToMain("server-status", { state: "error", message: String(err) });
  }

  // 2. Wire all IPC (recording control, auth, settings) — see ipc.js.
  registerIpc({
    getServer: () => server,
    getWatcher: () => watcher,
    windows: { sendToMain, sendToOverlay, showOverlay, hideOverlay },
    mainWin: () => mainWin,
  });

  // 3. Start watching for Overwatch 2; auto-record on launch.
  watcher = new GameWatcher();
  watcher.on("game-started", () => {
    sendToMain("game-detected", { running: true });
    // Tell the renderer to begin capture (the renderer owns the MediaRecorder).
    sendToMain("auto-record", { action: "start" });
  });
  watcher.on("game-stopped", () => {
    sendToMain("game-detected", { running: false });
    sendToMain("auto-record", { action: "stop" });
    hideOverlay();
  });
  watcher.start();

  // 4. Tray icon keeps the app alive in the background.
  tray = createTray({
    onOpen: () => {
      mainWin.show();
      mainWin.focus();
    },
    onToggleRecord: () => sendToMain("tray-toggle-record", {}),
    onQuit: () => {
      app.isQuitting = true;
      app.quit();
    },
    getState: () => ({
      gameRunning: watcher?.isRunning ?? false,
      serverReady: server?.isReady ?? false,
    }),
  });
});

app.on("before-quit", async () => {
  app.isQuitting = true;
  watcher?.stop();
  await server?.stop(); // graceful child-process shutdown
});

// Don't quit when all windows are closed — we live in the tray.
app.on("window-all-closed", (e) => {
  // no-op on purpose
});

module.exports = { sendToMain, sendToOverlay, showOverlay, hideOverlay };
