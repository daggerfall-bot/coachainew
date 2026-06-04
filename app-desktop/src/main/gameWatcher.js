/**
 * CoachAI Desktop — Game watcher.
 *
 * Polls the OS process list for Overwatch 2 and emits 'game-started' /
 * 'game-stopped'. This is what powers the "auto-detect and start recording"
 * default the user chose — they never click anything; launching the game is
 * the trigger.
 *
 * Cross-platform process names for OW2:
 *   Windows: Overwatch.exe
 *   macOS:   Overwatch (rare, but handled)
 * We match loosely (case-insensitive contains) to survive launcher variations.
 *
 * Polling (every 4s) is deliberately simple and dependency-free. A native
 * hook would be lower-latency but adds per-OS native code; 4s is plenty since
 * a match takes minutes and recording a few seconds late costs nothing.
 */
const { EventEmitter } = require("events");
const { exec } = require("child_process");

const GAME_PROCESS_HINTS = ["overwatch"];
const POLL_MS = 4000;

function listProcesses() {
  return new Promise((resolve) => {
    const cmd =
      process.platform === "win32"
        ? "tasklist /fo csv /nh"
        : "ps -axco command"; // macOS/Linux: just command names
    exec(cmd, { windowsHide: true, maxBuffer: 4 * 1024 * 1024 }, (err, stdout) => {
      if (err || !stdout) return resolve("");
      resolve(stdout.toLowerCase());
    });
  });
}

class GameWatcher extends EventEmitter {
  constructor() {
    super();
    this.isRunning = false; // is the GAME running
    this._timer = null;
  }

  start() {
    if (this._timer) return;
    this._tick(); // immediate first check
    this._timer = setInterval(() => this._tick(), POLL_MS);
  }

  async _tick() {
    const procList = await listProcesses();
    const detected = GAME_PROCESS_HINTS.some((h) => procList.includes(h));
    if (detected && !this.isRunning) {
      this.isRunning = true;
      this.emit("game-started");
    } else if (!detected && this.isRunning) {
      this.isRunning = false;
      this.emit("game-stopped");
    }
  }

  stop() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }
}

module.exports = { GameWatcher };
