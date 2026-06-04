/**
 * CoachAI Desktop — Bundled local server manager.
 *
 * Ships the Python backend INSIDE the app and runs it as a child process so
 * everything (vision inference, analysis, report generation) happens on the
 * user's machine — offline, no per-user cloud cost. This is what the user
 * chose: "bundled local mini-server".
 *
 * How the Python gets there:
 *   - In production we ship a PyInstaller one-file executable of the backend
 *     (built by scripts/build-server.* — see docs). No Python install required
 *     on the user's machine. The binary lives in resources/server/.
 *   - In dev we just run `uvicorn` from the sibling backend/ source tree.
 *
 * Responsibilities: pick a free port, launch, health-poll until ready, expose
 * the base URL, stream logs, and terminate cleanly on quit (no orphan
 * processes — a classic Electron+child-process bug).
 */
const { spawn } = require("child_process");
const { EventEmitter } = require("events");
const net = require("net");
const path = require("path");
const http = require("http");

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

class LocalServer extends EventEmitter {
  constructor({ isDev }) {
    super();
    this.isDev = isDev;
    this.proc = null;
    this.port = null;
    this.isReady = false;
  }

  get baseUrl() {
    return this.port ? `http://127.0.0.1:${this.port}` : null;
  }

  async start() {
    this.port = await findFreePort();
    this.emit("status", { state: "starting", port: this.port });

    const env = {
      ...process.env,
      // The bundled server runs in single-user local mode: SQLite instead of
      // Postgres, local filesystem instead of S3, no Stripe. These flags are
      // read by the backend's config when present.
      COACHAI_LOCAL_MODE: "1",
      COACHAI_PORT: String(this.port),
      DATABASE_URL: "sqlite+aiosqlite:///./coachai_local.db",
      VISION_BACKEND: "self_hosted",
      // The one thing that may phone home: the coaching LLM. Key is injected
      // by the app after Discord login (the user's account authorises it),
      // so no secret ships in the binary.
    };

    if (this.isDev) {
      // Dev: run uvicorn against the source backend.
      const backendDir = path.join(__dirname, "..", "..", "..", "backend");
      this.proc = spawn(
        "uvicorn",
        ["app.main:app", "--host", "127.0.0.1", "--port", String(this.port)],
        { cwd: backendDir, env },
      );
    } else {
      // Prod: run the PyInstaller binary shipped in resources/server/.
      const { app } = require("electron");
      const exeName =
        process.platform === "win32" ? "coachai-server.exe" : "coachai-server";
      const serverBin = path.join(process.resourcesPath, "server", exeName);
      this.proc = spawn(serverBin, [], { env });
    }

    this.proc.stdout.on("data", (d) => this.emit("log", d.toString().trim()));
    this.proc.stderr.on("data", (d) => this.emit("log", d.toString().trim()));
    this.proc.on("exit", (code) => {
      this.isReady = false;
      this.emit("status", { state: "stopped", code });
    });

    await this._waitForHealth();
    this.isReady = true;
    this.emit("status", { state: "ready", port: this.port });
    return this.baseUrl;
  }

  _waitForHealth(timeoutMs = 60_000) {
    const deadline = Date.now() + timeoutMs;
    const url = `${this.baseUrl}/health`;
    return new Promise((resolve, reject) => {
      const tryOnce = () => {
        const req = http.get(url, (res) => {
          res.resume();
          if (res.statusCode === 200) return resolve();
          retry();
        });
        req.on("error", retry);
        req.setTimeout(2000, () => req.destroy());
      };
      const retry = () => {
        if (Date.now() > deadline)
          return reject(new Error("Local server failed to start in time"));
        setTimeout(tryOnce, 600);
      };
      tryOnce();
    });
  }

  async stop() {
    if (!this.proc) return;
    return new Promise((resolve) => {
      const done = () => resolve();
      this.proc.once("exit", done);
      // Graceful first, then force.
      try {
        if (process.platform === "win32") {
          spawn("taskkill", ["/pid", String(this.proc.pid), "/f", "/t"]);
        } else {
          this.proc.kill("SIGTERM");
          setTimeout(() => this.proc && this.proc.kill("SIGKILL"), 4000);
        }
      } catch {
        resolve();
      }
    });
  }
}

module.exports = { LocalServer };
