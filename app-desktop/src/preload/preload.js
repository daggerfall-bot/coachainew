/**
 * CoachAI Desktop — preload bridge.
 *
 * Exposes a minimal, audited API to the renderer under window.desktop.
 * contextIsolation is ON and nodeIntegration is OFF, so the renderer can only
 * touch what we explicitly expose here — the secure Electron pattern.
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  // ── Local server ──
  getServerInfo: () => ipcRenderer.invoke("get-server-info"),
  onServerStatus: (cb) =>
    ipcRenderer.on("server-status", (_e, s) => cb(s)),

  // ── Screen capture sources ──
  getCaptureSources: () => ipcRenderer.invoke("get-capture-sources"),
  getBestCaptureSource: () => ipcRenderer.invoke("get-best-capture-source"),

  // ── Game auto-detect ──
  onGameDetected: (cb) =>
    ipcRenderer.on("game-detected", (_e, s) => cb(s)),
  onAutoRecord: (cb) =>
    ipcRenderer.on("auto-record", (_e, s) => cb(s)),
  onTrayToggleRecord: (cb) =>
    ipcRenderer.on("tray-toggle-record", () => cb()),

  // ── Overlay + tips ──
  sendTip: (tip) => ipcRenderer.send("coach-tip", tip),
  hideOverlay: () => ipcRenderer.send("hide-overlay"),
  onTip: (cb) => ipcRenderer.on("tip", (_e, tip) => cb(tip)),

  // ── Recording state ──
  setRecordingState: (state) => ipcRenderer.send("recording-state", state),

  // ── OS integration ──
  openExternal: (url) => ipcRenderer.send("open-external", url),
  notify: (title, body) => ipcRenderer.send("notify", { title, body }),

  // ── Discord OAuth deep-link callback ──
  onAuthCallback: (cb) =>
    ipcRenderer.on("auth-callback", (_e, data) => cb(data)),

  platform: process.platform,
});
