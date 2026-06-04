/**
 * CoachAI Desktop — System tray.
 *
 * Keeps the app alive in the background and gives a minimal control surface:
 * open the window, toggle recording, quit. The tray tooltip/menu reflects live
 * state (is the game running, is the local server ready) so the user can tell
 * at a glance that it's working without opening the window.
 */
const { Tray, Menu, nativeImage } = require("electron");
const path = require("path");

function createTray({ onOpen, onToggleRecord, onQuit, getState }) {
  // A tiny embedded 16x16 orange dot so the app needs no external icon file to
  // run in dev. Production replaces this with build/trayTemplate.png.
  const icon = nativeImage.createFromDataURL(
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAQUlEQVR42mNgGAWjYBSMghEH/0FxQzGGmIEhRoQxQzGGmIEhRoQxQzGGmIEhRoQxQzGGmIEhRoQxQzGGmIEhRgEA3hQHEUjxbtcAAAAASUVORK5CYII="
  );

  const tray = new Tray(icon);
  tray.setToolTip("CoachAI");

  const rebuild = () => {
    const s = getState();
    const menu = Menu.buildFromTemplate([
      {
        label: s.gameRunning ? "● Overwatch detected" : "○ Waiting for Overwatch",
        enabled: false,
      },
      {
        label: s.serverReady ? "● Coaching engine ready" : "○ Engine starting…",
        enabled: false,
      },
      { type: "separator" },
      { label: "Open CoachAI", click: onOpen },
      { label: "Start / Stop recording", click: onToggleRecord },
      { type: "separator" },
      { label: "Quit", click: onQuit },
    ]);
    tray.setContextMenu(menu);
  };

  rebuild();
  setInterval(rebuild, 3000); // keep the status labels fresh
  tray.on("click", onOpen);
  return tray;
}

module.exports = { createTray };
