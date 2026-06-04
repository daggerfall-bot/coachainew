/**
 * CoachAI Desktop — Bundled local server manager.
 */

const { spawn } = require("child_process");
const { EventEmitter } = require("events");
const net = require("net");
const path = require("path");
const http = require("http");
const fs = require("fs");

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

    this.emit("status", {
      state: "starting",
      port: this.port,
    });

    const env = {
      ...process.env,

      COACHAI_LOCAL_MODE: "1",
      COACHAI_PORT: String(this.port),

      // Use SQLite for the bundled local desktop app.
      DATABASE_URL: "sqlite+aiosqlite:///./coachai_local.db",

      // IMPORTANT:
      // Your bundled requirements intentionally do not include torch/torchvision.
      // Do not force self_hosted until you actually ship the trained model and
      // bundle the torch dependencies.
      VISION_BACKEND: "api",
    };

    if (this.isDev) {
      const backendDir = path.join(__dirname, "..", "..", "..", "backend");

      this.proc = spawn(
        "uvicorn",
        ["app.main:app", "--host", "127.0.0.1", "--port", String(this.port)],
        {
          cwd: backendDir,
          env,
        }
      );
    } else {
      const { app } = require("electron");
      const exeName = process.platform === "win32"
        ? "coachai-server.exe"
        : "coachai-server";

      const serverBin = path.join(process.resourcesPath, "server", exeName);

      if (!fs.existsSync(serverBin)) {
        throw new Error(`Bundled server missing: ${serverBin}`);
      }

      this.proc = spawn(serverBin, [], {
        cwd: path.dirname(serverBin),
        env,
        windowsHide: true,
      });
    }

    this.proc.stdout.on("data", (d) => {
      this.emit("log", d.toString().trim());
    });

    this.proc.stderr.on("data", (d) => {
      this.emit("log", d.toString().trim());
    });

    this.proc.on("error", (err) => {
      this.isReady = false;
      this.emit("error", err);
      this.emit("status", {
        state: "error",
        message: String(err && err.message ? err.message : err),
      });
    });

    this.proc.on("exit", (code) => {
      this.isReady = false;
      this.emit("status", {
        state: "stopped",
        code,
      });
    });

    await this._waitForHealth();

    this.isReady = true;

    this.emit("status", {
      state: "ready",
      port: this.port,
    });

    return this.baseUrl;
  }

  _waitForHealth(timeoutMs = 60_000) {
    const deadline = Date.now() + timeoutMs;
    const url = `${this.baseUrl}/health`;

    return new Promise((resolve, reject) => {
      const tryOnce = () => {
        const req = http.get(url, (res) => {
          res.resume();

          if (res.statusCode === 200) {
            return resolve();
          }

          retry();
        });

        req.on("error", retry);

        req.setTimeout(2000, () => {
          req.destroy();
        });
      };

      const retry = () => {
        if (Date.now() > deadline) {
          return reject(new Error("Local server failed to start in time"));
        }

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
