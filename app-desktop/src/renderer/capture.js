/**
 * CoachAI Desktop — Renderer capture engine.
 *
 * This is the "records like OBS" part, built in. It uses Electron's
 * desktopCapturer source id with getUserMedia to grab the game video+audio,
 * records it to a file via MediaRecorder (for the post-game report), AND
 * samples frames at 5fps to stream to the local server's live-coach socket
 * (for real-time commentary). All with zero user setup.
 *
 * The user chose auto-record on game detection, so start()/stop() are driven by
 * the main process's game watcher — not by a button.
 */

export class CaptureEngine {
  constructor({ serverBaseUrl, token, onTip, onState, onStatus }) {
    this.serverBaseUrl = serverBaseUrl;
    this.token = token;
    this.onTip = onTip || (() => {});
    this.onState = onState || (() => {});
    this.onStatus = onStatus || (() => {});

    this.stream = null;
    this.recorder = null;
    this.chunks = [];
    this.ws = null;
    this.sampling = false;
    this.hero = null;
    this.recording = false;
  }

  async start(hero) {
    if (this.recording) return;
    this.hero = hero || null;

    // 1. Pick the best source (Overwatch window, else primary screen).
    const src = await window.desktop.getBestCaptureSource();
    if (!src) throw new Error("No capture source available");

    // 2. Grab the stream — Electron's desktop capture constraints.
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: { chromeMediaSource: "desktop" },
      },
      video: {
        mandatory: {
          chromeMediaSource: "desktop",
          chromeMediaSourceId: src.id,
          maxWidth: 1920,
          maxHeight: 1080,
          maxFrameRate: 60,
        },
      },
    });

    // 3. Record full quality for the report.
    this.chunks = [];
    const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
      ? "video/webm;codecs=vp9"
      : "video/webm";
    this.recorder = new MediaRecorder(this.stream, { mimeType: mime });
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.recorder.onstop = () => this._handleRecordingStopped();
    this.recorder.start(1000);

    // 4. Open the live-coach socket and begin sampling frames.
    this._openLiveSocket();
    this._startSampling();

    this.recording = true;
    window.desktop.setRecordingState({ recording: true, hero: this.hero });
    this.onStatus({ recording: true });
  }

  stop() {
    if (!this.recording) return;
    this.sampling = false;
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ws) this.ws.close();
    this.recording = false;
    window.desktop.setRecordingState({ recording: false });
    this.onStatus({ recording: false });
  }

  _openLiveSocket() {
    const wsBase = this.serverBaseUrl.replace(/^http/, "ws");
    this.ws = new WebSocket(
      `${wsBase}/api/v1/live/coach?token=${encodeURIComponent(this.token)}`,
    );
    this.ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "tip") {
        window.desktop.sendTip(msg); // show overlay (main process)
        this.onTip(msg);
      } else if (msg.type === "state") {
        this.onState(msg);
      }
    };
  }

  _startSampling() {
    const video = document.createElement("video");
    video.srcObject = this.stream;
    video.muted = true;
    void video.play();

    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    const ctx = canvas.getContext("2d");
    this.sampling = true;

    const tick = () => {
      if (!this.sampling) return;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        const b64 = canvas.toDataURL("image/jpeg", 0.6).split(",")[1];
        this.ws.send(JSON.stringify({ frame: b64 }));
      }
      setTimeout(tick, 200); // 5 fps
    };
    tick();
  }

  async _handleRecordingStopped() {
    this.onStatus({ recording: false, uploading: true });
    const blob = new Blob(this.chunks, { type: "video/webm" });

    // The local server exposes the same /sessions endpoints as the cloud API,
    // so the upload+analyze flow is identical — just pointed at 127.0.0.1.
    try {
      const res = await fetch(
        `${this.serverBaseUrl}/api/v1/sessions/upload-url?hero=${encodeURIComponent(this.hero || "")}`,
        { method: "POST", headers: { Authorization: `Bearer ${this.token}` } },
      );
      const { session_id, upload_url } = await res.json();

      // Local mode: upload_url is a local PUT endpoint on the mini-server.
      await fetch(upload_url, { method: "PUT", body: blob });

      await fetch(`${this.serverBaseUrl}/api/v1/sessions/${session_id}/analyze`, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.token}` },
      });

      window.desktop.notify(
        "CoachAI",
        "Match recorded — your coaching report is generating.",
      );
      this.onStatus({ recording: false, uploading: false, sessionId: session_id });
    } catch (err) {
      this.onStatus({ recording: false, uploading: false, error: String(err) });
    }
  }
}
