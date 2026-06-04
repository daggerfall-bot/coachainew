/**
 * CoachAI Desktop — Electron main process.
 */

const { app, BrowserWindow } = require("electron");
const path = require("path");

const { LocalServer } = require("./localServer");
const { GameWatcher } = require("./gameWatcher");
const { createTray } = require("./tray");
const { registerIpc } = require("./ipc");
const {
  registerProtocol,
  installDeepLinkHandlers,
} = require("./auth");

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
  overlayWin.setAlwaysOnTop(true, "screen-saver");
  overlayWin.loadFile(path.join(__dirname, "..", "renderer", "overlay.html"));
  overlayWin.hide();
}

function sendToMain(channel, payload) {
  if (mainWin && !mainWin.isDestroyed()) {
    mainWin.webContents.send(channel, payload);
  }
}

function sendToOverlay(channel, payload) {
  if (overlayWin && !overlayWin.isDestroyed()) {
    overlayWin.webContents.send(channel, payload);
  }
}

function showOverlay() {
  if (overlayWin && !overlayWin.isDestroyed()) {
    overlayWin.showInactive();
  }
}

function hideOverlay() {
  if (overlayWin && !overlayWin.isDestroyed()) {
    overlayWin.hide();
  }
}

app.whenReady().then(async () => {
  createMainWindow();
  createOverlayWindow();

  installDeepLinkHandlers(sendToMain, () => mainWin);

  server = new LocalServer({ isDev });

  server.on("status", (s) => {
    sendToMain("server-status", s);
  });

  server.on("log", (line) => {
    console.log("[server]", line);
  });

  server.on("error", (err) => {
    console.error("[server error]", err);
    sendToMain("server-status", {
      state: "error",
      message: String(err && err.message ? err.message : err),
    });
  });

  // IMPORTANT:
  // Register IPC before starting the server so the renderer can safely call
  // getServerInfo() as soon as it boots.
  registerIpc({
    getServer: () => server,
    getWatcher: () => watcher,
    windows: {
      sendToMain,
      sendToOverlay,
      showOverlay,
      hideOverlay,
    },
    mainWin: () => mainWin,
  });

  try {
    await server.start();
    sendToMain("server-status", {
      state: "ready",
      port: server.port,
    });
  } catch (err) {
    console.error("[server failed to start]", err);
    sendToMain("server-status", {
      state: "error",
      message: String(err && err.message ? err.message : err),
    });
  }

  watcher = new GameWatcher();

  watcher.on("game-started", () => {
    sendToMain("game-detected", { running: true });
    sendToMain("auto-record", { action: "start" });
  });

  watcher.on("game-stopped", () => {
    sendToMain("game-detected", { running: false });
    sendToMain("auto-record", { action: "stop" });
    hideOverlay();
  });

  watcher.start();

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
  await server?.stop();
});

app.on("window-all-closed", () => {
  // Keep running in tray.
});
