# Vision Model — Data Collection & Training Playbook

You chose the **self-hosted fine-tuned model** route. That's the right call for
unit economics at scale (no per-frame API cost), but it has one hard
prerequisite the API route doesn't: **labelled training data**. This document
is the realistic plan for getting there. Read it before you commit — this is
the single biggest chunk of work in the whole product.

## The honest cost

To get a model that reliably reads hero, health, ult%, and rough position you
need roughly:

- **5,000–15,000 labelled frames** for health/ult regression to be solid.
- **~50+ examples per hero** across maps/skins for hero classification to
  generalise (the full roster is ~40 heroes).
- A **single mid-range GPU** (e.g. RTX 4070+) trains the EfficientNet-B0 model
  in a few hours.

Hand-labelling 10k frames is unrealistic. The plan below gets ~80% of labels
for free, so you only hand-correct the rest.

## Phase 0 — ship on the API backend first

Set `VISION_BACKEND=api`. Real users start generating real gameplay
immediately. Every uploaded VOD is **free training data**. Don't train anything
until you have a backlog of real footage — synthetic-only models break on real
streamer overlays, skins, and resolutions.

## Phase 1 — bootstrap labels (the trick)

Overwatch 2's own systems give you ground truth for free:

1. **Workshop "score" + scoreboard OCR.** End-of-round scoreboards show exact
   stats. OCR them to auto-label accuracy, elims, deaths per player.
2. **Replay viewer + known state.** Record matches in the replay tool where you
   can pause and read exact health/ult from the HUD. Script a capture that
   steps frame-by-frame and reads the HUD numbers via OCR → those become
   regression labels with no manual work.
3. **Health/ult bars are deterministic UI.** The health bar is a fixed-position
   coloured bar. A simple OpenCV pass (measure the filled fraction of the bar's
   bounding box) gives you a health label good enough to bootstrap the
   regression head — then the CNN learns to generalise across heroes/effects.
4. **Hero from the ability icons.** The bottom-right ability HUD is
   hero-specific. Template-match the icon set → hero label, auto-applied to
   every frame in that life.

Write these as a labelling script that emits the JSONL manifest
`OW2FrameDataset` expects. Hand-review a random 5% to measure label noise.

## Phase 2 — train

```bash
cd backend
python -m app.vision.training.train \
  --manifest data/train.jsonl --val data/val.jsonl \
  --images data/frames --epochs 30 --batch 32 \
  --out models/ow2_state_detector.pt
```

Targets before you flip to self-hosted in production:
- hero accuracy > 0.95
- health MAE < 0.05 (i.e. within 5% health)
- ult MAE < 0.06

The training script reports these each epoch and saves the best checkpoint.

## Phase 3 — switch over

1. Copy `ow2_state_detector.pt` to the worker host (mount into `/srv/models`).
2. Set `VISION_BACKEND=self_hosted` and `VISION_MODEL_PATH` on the worker.
3. Run the worker on the GPU host: `--concurrency=1` per GPU.
4. Keep the API backend as automatic fallback for frames where the model's
   confidence is below `VISION_CONFIDENCE_THRESHOLD` (wire this in
   `pipeline.run_pipeline` — currently it uses one backend; the hybrid is a
   small extension and noted in `backend.py`).

## Phase 4 — keep improving

Every misprediction users implicitly flag (e.g. a clip they mark "this wasn't a
mistake") is a hard example. Periodically retrain with the growing dataset.
**Never reorder** `HEROES`/`MAPS` in `labels.py` — append only, or you
invalidate every checkpoint.

## Why not just stay on the API forever?

You can, and many products do. The math: a 47-min session at 5fps ≈ 14k frames.
At API vision prices that's a few dollars per session — fine at low volume,
ruinous at £10/mo × thousands of sessions. The self-hosted model amortises a GPU
you rent for cents/hour across unlimited frames. Cross over the moment your API
vision bill approaches your GPU rental cost.
