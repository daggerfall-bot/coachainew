/**
 * CoachAI Desktop — Server bundling step.
 *
 * Runs before electron-builder. Uses PyInstaller to compile the Python backend
 * (../backend) into a single standalone executable placed in ./server-dist,
 * which electron-builder then copies into the app's resources/server/.
 *
 * Result: the shipped app contains a self-contained backend binary — the user
 * needs NO Python install. This is the price of the "bundled local server"
 * choice: a larger download, but a true double-click experience.
 *
 * Requires (on YOUR build machine, once): python3 + `pip install pyinstaller`.
 */
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const backendDir = path.join(__dirname, "..", "..", "backend");
const outDir = path.join(__dirname, "..", "server-dist");

console.log("[build-server] compiling backend with PyInstaller…");

if (!fs.existsSync(backendDir)) {
  console.error("[build-server] backend/ not found at", backendDir);
  process.exit(1);
}

// A spec-free one-file build. The entrypoint imports the FastAPI app and runs
// uvicorn programmatically (see backend/app/standalone.py).
const cmd = [
  "pyinstaller",
  "--onefile",
  "--name coachai-server",
  `--distpath "${outDir}"`,
  "--clean",
  "--noconfirm",
  // hidden imports PyInstaller can miss for async stacks:
  "--hidden-import uvicorn.logging",
  "--hidden-import uvicorn.protocols.http.auto",
  "--hidden-import uvicorn.protocols.websockets.auto",
  "--hidden-import uvicorn.lifespan.on",
  "--hidden-import aiosqlite",
  "--hidden-import anthropic",
  "--hidden-import sqlalchemy.dialects.sqlite",
  `"${path.join(backendDir, "app", "standalone.py")}"`,
].join(" ");

try {
  execSync(cmd, { cwd: backendDir, stdio: "inherit" });
  console.log("[build-server] done →", outDir);
} catch (e) {
  console.error("[build-server] PyInstaller failed. Is it installed? `pip install pyinstaller`");
  process.exit(1);
}
