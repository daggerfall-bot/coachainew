/**
 * CoachAI Desktop — IPC bridge (main side).
 *
 * The renderer owns the actual screen capture (MediaRecorder + getUserMedia via
 * desktopCapturer) because capture is a renderer-only API in Electron. Main
 * owns everything else: the local server URL, the overlay window, and OS
 * integration. This module is the contract between them.
 *
 * Channels:
 *   invoke  get-server-info      → { baseUrl, ready }
 *   invoke  get-capture-sources  → [{ id, name, thumbnail }]
 *   on      coach-tip            → forward a live tip to the overlay + show it
 *   on      recording-state      → reflect in tray/overlay
 *   on      open-external        → open OAuth / billing URLs in the real browser
 */
const { ipcMain, desktopCapturer, shell, BrowserWindow } = require("electron");

function registerIpc({ getServer, getWatcher, windows, mainWin }) {
  // Renderer asks where the local backend is listening.
  ipcMain.handle("get-server-info", () => {
    const s = getServer();
    return { baseUrl: s?.baseUrl ?? null, ready: s?.isReady ?? false };
  });

  // Renderer asks for screen/window capture sources (to record the game).
  ipcMain.handle("get-capture-sources", async () => {
    const sources = await desktopCapturer.getSources({
      types: ["window", "screen"],
      thumbnailSize: { width: 320, height: 180 },
    });
    return sources.map((s) => ({
      id: s.id,
      name: s.name,
      thumbnail: s.thumbnail.toDataURL(),
    }));
  });

  // Auto-pick the Overwatch window if present, else the primary screen.
  ipcMain.handle("get-best-capture-source", async () => {
    const sources = await desktopCapturer.getSources({
      types: ["window", "screen"],
    });
    const game = sources.find((s) => s.name.toLowerCase().includes("overwatch"));
    const screen = sources.find((s) => s.id.startsWith("screen"));
    const chosen = game || screen || sources[0];
    return chosen ? { id: chosen.id, name: chosen.name } : null;
  });

  // Live tip from the renderer's WebSocket → show on overlay + speak handled
  // in the overlay renderer.
  ipcMain.on("coach-tip", (_e, tip) => {
    windows.showOverlay();
    windows.sendToOverlay("tip", tip);
  });

  ipcMain.on("hide-overlay", () => windows.hideOverlay());

  // Recording state changes update tray tooltip + let main coordinate.
  ipcMain.on("recording-state", (_e, state) => {
    windows.sendToMain("recording-state-echo", state);
  });

  // OAuth (Discord) and Stripe must open in the user's real browser, not an
  // Electron window (security + cookie continuity).
  ipcMain.on("open-external", (_e, url) => {
    if (typeof url === "string" && /^https?:\/\//.test(url)) shell.openExternal(url);
  });

  // The renderer finished an upload+analyze cycle; surface a desktop note.
  ipcMain.on("notify", (_e, { title, body }) => {
    const { Notification } = require("electron");
    if (Notification.isSupported()) new Notification({ title, body }).show();
  });
}

module.exports = { registerIpc };
