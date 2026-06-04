# Download Setup — from code to a working Download button

This explains how the automated build turns into the `CoachAI-Setup.exe` a
gamer downloads from your site, and how to wire your Download button to it.
You never run a build on your own machine.

## The flow, end to end

```
You push a version tag ─▶ GitHub Actions builds 3 installers on GitHub's
                          Windows / Mac / Linux machines (free)
                              │
                              ▼
                          A GitHub Release is created with all 3 files attached
                              │
                              ▼
                          Your website's Download button links to those files
                              │
                              ▼
                          Gamer clicks → downloads CoachAI-Setup.exe → runs it
```

## One-time setup

1. **Put this whole project in a GitHub repo.** The folder layout must stay as
   is — the workflow expects `app-desktop/` and `backend/` side by side, and
   `.github/workflows/build-installers.yml` at the repo root.

2. **Add repository secrets** (Settings → Secrets and variables → Actions). All
   are optional for a first test build; without them you get a working but
   *unsigned* installer.

   | Secret | What it's for | Needed when |
   |---|---|---|
   | `DISCORD_CLIENT_ID` | Discord sign-in | before real users |
   | `DISCORD_CALLBACK_URL` | your OAuth proxy URL | before real users |
   | `WINDOWS_CSC_LINK` / `WINDOWS_CSC_KEY_PASSWORD` | Win code-signing | before public launch |
   | `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID` | Mac notarisation | before public launch |

   `GITHUB_TOKEN` is provided automatically — you don't create it.

## Cutting a release (every time you ship)

```bash
git tag v1.0.0
git push origin v1.0.0
```

That's it. Watch it build under the repo's **Actions** tab (~10–15 min for all
three OSes). When it finishes, a **Release** appears under the repo's Releases
page with:

- `CoachAI-Setup-1.0.0.exe`   (Windows)
- `CoachAI-1.0.0.dmg`         (macOS)
- `CoachAI-1.0.0.AppImage`    (Linux)

You can also trigger a build without tagging from the **Actions** tab
(“Build Installers” → Run workflow) — useful for testing. Note: untagged runs
upload the installers as downloadable **artifacts** but do NOT publish a public
Release (only `v*` tags do).

## Wiring your website's Download button

Every release has stable, predictable URLs. Two options:

### Option A — always point at the latest release (recommended)
GitHub gives every repo a "latest release" redirect. Your button just links to:

```
https://github.com/<you>/<repo>/releases/latest/download/CoachAI-Setup-1.0.0.exe
```

The catch: the filename includes the version, which changes. The clean fix is
to give the Windows artifact a **fixed name** so the URL never changes. In
`app-desktop/package.json` the Windows `artifactName` is already
`CoachAI-Setup-${version}.${ext}`; change it to a fixed
`CoachAI-Setup.${ext}` and your button URL becomes permanent:

```
https://github.com/<you>/<repo>/releases/latest/download/CoachAI-Setup.exe
```

Then a smart Download button auto-serves the right OS file:

```html
<a id="dl" href="https://github.com/<you>/<repo>/releases/latest/download/CoachAI-Setup.exe">
  Download CoachAI
</a>
<script>
  // Swap the link + label based on the visitor's OS.
  const base = "https://github.com/<you>/<repo>/releases/latest/download/";
  const ua = navigator.userAgent;
  const dl = document.getElementById("dl");
  if (/Macintosh|Mac OS X/.test(ua)) {
    dl.href = base + "CoachAI.dmg";
    dl.textContent = "Download for Mac";
  } else if (/Windows/.test(ua)) {
    dl.href = base + "CoachAI-Setup.exe";
    dl.textContent = "Download for Windows";
  } else if (/Linux/.test(ua)) {
    dl.href = base + "CoachAI.AppImage";
    dl.textContent = "Download for Linux";
  }
</script>
```

### Option B — host the files yourself
Download the installers from the Release and upload them to your own
CDN/storage, then point the button at those URLs. More control, more manual work.

## The two honest caveats (unchanged from before)

1. **Day-one builds use the cloud vision API**, not the on-device model — the
   workflow sets `VISION_BACKEND=api`. The installer works and demos perfectly,
   but each session makes vision API calls you pay for. Flip to the local model
   once it's trained (see `docs/VISION_DATA.md`) by committing the model and
   changing that one env line in the workflow.

2. **Discord + the LLM key need a tiny cloud shim** (covered in
   `app-desktop/BUILD.md`). Until that exists, the workflow's Discord secrets
   can be left unset and the local build falls back to a dev sign-in so you can
   test the full app — it just isn't real Discord auth yet.

## First-run OS warnings (until you code-sign)

Unsigned installers trigger SmartScreen (Windows) and Gatekeeper (Mac). For
testing that's fine. Before a public launch, add the signing secrets above —
the workflow uses them automatically and the warnings disappear.
