"""
CoachAI — Standalone local-server entrypoint.

This is what PyInstaller compiles into `coachai-server(.exe)` and what the
Electron app spawns. It runs the FastAPI app with uvicorn programmatically,
reading the port the desktop app assigned via COACHAI_PORT.

In local mode (COACHAI_LOCAL_MODE=1) the app uses SQLite, local-disk storage,
and the local upload/Discord routes — no Postgres, S3, or Stripe required.
"""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("COACHAI_PORT", "8745"))
    # Bind to loopback only — this server is private to the user's machine.
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        # reload must be False in a frozen binary
        reload=False,
    )


if __name__ == "__main__":
    main()
