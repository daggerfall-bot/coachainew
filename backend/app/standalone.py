"""
CoachAI — Standalone local-server entrypoint.

This is what PyInstaller compiles into `coachai-server(.exe)` and what the
Electron app spawns. It runs the FastAPI app with uvicorn.

IMPORTANT (PyInstaller): we import the FastAPI `app` OBJECT and pass it to
uvicorn directly. Passing the import STRING "app.main:app" makes uvicorn try to
re-import the module by name at runtime, which fails inside a frozen binary
(there's no importable `app` package on disk). Passing the object avoids that.
For the same reason, reload/workers must stay off.
"""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn
    from app.main import app  # import the object, not a module string

    port = int(os.environ.get("COACHAI_PORT", "8745"))
    # Bind to loopback only — this server is private to the user's machine.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
