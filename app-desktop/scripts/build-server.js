/**
 * CoachAI Desktop — Server bundling step (PyInstaller).
 *
 * Compiles backend/ into a single standalone executable in ./server-dist,
 * which electron-builder copies into resources/server/.
 *
 * Robustness notes (these prevent the "server starts then instantly dies"
 * class of bug): we --collect-all the packages PyInstaller most often
 * under-bundles for async/ASGI + pydantic stacks, and add explicit
 * hidden-imports for submodules it can't see through dynamic imports.
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

const cmd = [
  "pyinstaller",
  "--onefile",
  "--name coachai-server",
  `--distpath "${outDir}"`,
  "--clean",
  "--noconfirm",
  // --collect-all pulls in ALL submodules/data/dynamic libs for these packages,
  // which is the reliable way to stop runtime ImportErrors in a frozen binary.
  "--collect-all uvicorn",
  "--collect-all anthropic",
  "--collect-all pydantic",
  "--collect-all passlib",
  "--collect-all sqlalchemy",
  "--collect-all aiosqlite",
  "--collect-all httpx",
  // Explicit hidden imports for things even --collect-all can miss.
  "--hidden-import uvicorn.protocols.http.auto",
  "--hidden-import uvicorn.protocols.websockets.auto",
  "--hidden-import uvicorn.lifespan.on",
  "--hidden-import passlib.handlers.bcrypt",
  "--hidden-import sqlalchemy.dialects.sqlite.aiosqlite",
  // The whole app package, so frozen imports of app.* resolve.
  "--paths .",
  `"${path.join(backendDir, "app", "standalone.py")}"`,
].join(" ");

try {
  execSync(cmd, { cwd: backendDir, stdio: "inherit" });
  console.log("[build-server] done →", outDir);
} catch (e) {
  console.error("[build-server] PyInstaller failed. Is it installed? `pip install pyinstaller`");
  process.exit(1);
}
