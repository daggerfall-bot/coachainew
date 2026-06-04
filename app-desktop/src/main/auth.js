/**
 * CoachAI Desktop — Discord OAuth via custom protocol deep-link.
 *
 * Desktop OAuth can't use a normal web redirect, so we register a custom URL
 * scheme (coachai://) as the OAuth redirect target. Flow:
 *
 *   1. App opens the Discord authorize URL in the user's real browser
 *      (shell.openExternal) — gamers are already logged into Discord there, so
 *      it's genuinely one click.
 *   2. Discord redirects to our backend callback, which exchanges the code and
 *      then 302-redirects to  coachai://auth?token=<jwt>
 *   3. The OS hands that deep-link back to this app; we parse the token and
 *      hand it to the renderer, which is now logged in.
 *
 * This keeps the OAuth client secret on the backend (never in the shipped app)
 * while still feeling like a single click to the user.
 */
const { app } = require("electron");
const path = require("path");

const PROTOCOL = "coachai";

function registerProtocol() {
  if (process.defaultApp && process.argv.length >= 2) {
    // dev: associate the scheme with this electron instance
    app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [
      path.resolve(process.argv[1]),
    ]);
  } else {
    app.setAsDefaultProtocolClient(PROTOCOL);
  }
}

/**
 * Parse a coachai://auth?token=... deep link and forward the token to the
 * renderer via the provided sender.
 */
function handleDeepLink(url, sendToMain) {
  try {
    const u = new URL(url);
    if (u.host === "auth" || u.pathname.includes("auth")) {
      const token = u.searchParams.get("token");
      const error = u.searchParams.get("error");
      sendToMain("auth-callback", { token, error: error || null });
    }
  } catch {
    /* malformed link — ignore */
  }
}

/**
 * Wire OS-level deep-link delivery. Windows/Linux deliver via 'second-instance'
 * argv; macOS via the 'open-url' event. Call once from main after the window
 * exists.
 */
function installDeepLinkHandlers(sendToMain, getMainWin) {
  // macOS
  app.on("open-url", (event, url) => {
    event.preventDefault();
    handleDeepLink(url, sendToMain);
    getMainWin()?.show();
  });

  // Windows / Linux: the link arrives as an argv on the second instance.
  app.on("second-instance", (_e, argv) => {
    const link = argv.find((a) => a.startsWith(`${PROTOCOL}://`));
    if (link) handleDeepLink(link, sendToMain);
    getMainWin()?.show();
  });
}

/** Build the Discord authorize URL that points back at our backend callback. */
function buildDiscordAuthUrl(backendBaseUrl) {
  // The backend owns the client_id + secret and the real Discord URL; we just
  // hit its /auth/discord/start endpoint, which 302s to Discord. That keeps
  // all secrets server-side.
  return `${backendBaseUrl}/api/v1/auth/discord/start`;
}

module.exports = {
  registerProtocol,
  installDeepLinkHandlers,
  buildDiscordAuthUrl,
  PROTOCOL,
};
