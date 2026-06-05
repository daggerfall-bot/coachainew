/**
 * CoachAI Desktop — Renderer app controller.
 *
 * Orchestrates the user-facing flow with zero required interaction beyond the
 * one-time Discord sign-in:
 *   - waits for the local server to report ready
 *   - handles Discord OAuth (open browser → deep-link token back)
 *   - reflects game-detection + recording state in the UI
 *   - on game-start, auto-creates the CaptureEngine and records
 *
 * State is intentionally tiny and centralised in `state` so the render
 * functions stay declarative.
 */
import { CaptureEngine } from "./capture.js";

const state = {
  serverBaseUrl: null,
  serverReady: false,
  token: localStorage.getItem("coachai_token"),
  gameRunning: false,
  recording: false,
  hero: "Tracer", // default; settings can change it
  engine: null,
};

const $ = (id) => document.getElementById(id);

// ── Screen routing ──
function show(screen) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(screen).classList.add("active");
}

function routeByAuth() {
  show(state.token ? "home" : "login");
}

// ── Titlebar + checks ──
function renderStatus() {
  const dot = $("tb-dot");
  const txt = $("tb-status");
  if (!state.serverReady) {
    dot.classList.remove("on");
    txt.textContent = "Starting engine…";
  } else if (state.recording) {
    dot.classList.add("on");
    txt.textContent = "Recording & coaching";
  } else if (state.gameRunning) {
    dot.classList.add("on");
    txt.textContent = "Overwatch detected";
  } else {
    dot.classList.add("on");
    txt.textContent = "Ready — waiting for game";
  }

  // Check cards
  setCheck("check-engine", state.serverReady, state.serverReady ? "Ready" : "Starting…");
  setCheck("check-game", state.gameRunning, state.gameRunning ? "Detected" : "Not detected");
  setCheck("check-account", !!state.token, "Signed in");

  // Hero status block
  const headline = $("home-headline");
  const sub = $("home-sub");
  const pulse = $("ring-pulse");
  const core = $("ring-core");
  const recBadge = $("rec-badge");
  const liveDot = $("live-dot");

  if (state.recording) {
    headline.textContent = "Coaching you live";
    sub.textContent = "Recording this match. Watch the overlay for real-time tips — your full report lands when the match ends.";
    pulse.style.display = "block";
    core.textContent = "🔴";
    recBadge.classList.add("show");
    liveDot.classList.add("on");
  } else if (state.gameRunning) {
    headline.textContent = "Overwatch is running";
    sub.textContent = "Get into a match — recording starts automatically when the round begins.";
    pulse.style.display = "block";
    core.textContent = "🎯";
    recBadge.classList.remove("show");
    liveDot.classList.remove("on");
  } else {
    headline.textContent = "Watching for Overwatch";
    sub.textContent = "Launch Overwatch 2 and CoachAI starts recording automatically. Just play.";
    pulse.style.display = "none";
    core.textContent = "🎮";
    recBadge.classList.remove("show");
    liveDot.classList.remove("on");
  }
}

function setCheck(id, ok, stateText) {
  const el = $(id);
  el.classList.toggle("ok", ok);
  el.classList.toggle("wait", !ok);
  el.querySelector(".check-state").textContent = stateText;
}

// ── Live tips feed ──
function addTip(tip) {
  const feed = $("tips-feed");
  const empty = feed.querySelector(".tips-empty");
  if (empty) empty.remove();
  const line = document.createElement("div");
  line.className = `tip-line ${tip.severity}`;
  line.textContent = tip.text;
  feed.prepend(line);
  while (feed.children.length > 8) feed.lastChild.remove();
}

// ── Login ──
function requireServerReady() {
  if (!state.serverBaseUrl || !state.serverReady) {
    alert("CoachAI is still starting. Wait a few seconds, then try again.");
    return false;
  }
  return true;
}

// Direct in-app login: POST the email, get a token straight back. No browser,
// no deep link — the reliable path that works today.
async function loginWithEmail(email) {
  const res = await fetch(`${state.serverBaseUrl}/api/v1/auth/local`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(msg || `Login failed (${res.status})`);
  }
  const data = await res.json();
  return data.token;
}

const discordBtn = $("discord-login");

// Discord stays as a (browser+deeplink) option for when the cloud shim exists.
discordBtn.addEventListener("click", async () => {
  if (!requireServerReady()) return;
  window.desktop.openExternal(`${state.serverBaseUrl}/api/v1/auth/discord/start`);
});

// Email/Gmail button — now uses the direct, reliable login.
const emailBtn = document.createElement("button");
emailBtn.id = "email-login";
emailBtn.className = discordBtn.className;
emailBtn.style.marginTop = "12px";
emailBtn.textContent = "Sign in with Email / Gmail";
discordBtn.insertAdjacentElement("afterend", emailBtn);

emailBtn.addEventListener("click", async () => {
  if (!requireServerReady()) return;
  const email = prompt("Enter your email address:");
  if (!email) return;
  const trimmed = email.trim().toLowerCase();
  if (!trimmed.includes("@") || !trimmed.split("@")[1]?.includes(".")) {
    alert("Please enter a valid email address.");
    return;
  }
  try {
    const token = await loginWithEmail(trimmed);
    state.token = token;
    localStorage.setItem("coachai_token", token);
    routeByAuth();
    renderStatus();
  } catch (e) {
    alert("Login failed: " + (e?.message || e));
  }
});

// Deep-link token (Discord flow) still supported if it ever arrives.
window.desktop.onAuthCallback(({ token, error }) => {
  if (error || !token) return;
  state.token = token;
  localStorage.setItem("coachai_token", token);
  routeByAuth();
  renderStatus();
});

// ── Recording control (used by auto-record + tray toggle) ──
async function startRecording() {
  if (state.recording || !state.serverReady || !state.token) return;
  state.engine = new CaptureEngine({
    serverBaseUrl: state.serverBaseUrl,
    token: state.token,
    onTip: (t) => addTip(t),
    onState: () => {},
    onStatus: (s) => {
      state.recording = !!s.recording;
      renderStatus();
    },
  });
  try {
    await state.engine.start(state.hero);
    state.recording = true;
    renderStatus();
  } catch (e) {
    console.error("capture failed", e);
  }
}

function stopRecording() {
  if (state.engine) state.engine.stop();
  state.recording = false;
  renderStatus();
}

// ── Wire main-process events ──
window.desktop.onServerStatus((s) => {
  if (s.state === "ready") {
    state.serverReady = true;
    state.serverBaseUrl = `http://127.0.0.1:${s.port}`;
  } else if (s.state === "error") {
    state.serverReady = false;
  }
  renderStatus();
});

window.desktop.onGameDetected(({ running }) => {
  state.gameRunning = running;
  renderStatus();
});

window.desktop.onAutoRecord(({ action }) => {
  if (action === "start") startRecording();
  else if (action === "stop") stopRecording();
});

window.desktop.onTrayToggleRecord(() => {
  state.recording ? stopRecording() : startRecording();
});

$("btn-reports").addEventListener("click", () => {
  // Reports live on the local server; open the dashboard view (future: in-app).
  if (state.serverBaseUrl)
    window.desktop.openExternal(`${state.serverBaseUrl}/`);
});
$("btn-settings").addEventListener("click", () => show("home"));

// ── Boot ──
(async function boot() {
  const info = await window.desktop.getServerInfo();
  if (info?.ready) {
    state.serverReady = true;
    state.serverBaseUrl = info.baseUrl;
  }
  routeByAuth();
  renderStatus();
})();
