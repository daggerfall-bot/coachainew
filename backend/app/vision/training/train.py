"""
CoachAI — Vision model training entrypoint.

Usage:
    python -m app.vision.training.train \
        --manifest data/train.jsonl --val data/val.jsonl \
        --images data/frames --epochs 30 --batch 32 --out models/ow2_state_detector.pt

This trains the multi-head GameStateNet. Designed for a single GPU; for
multi-GPU wrap the model in DDP. Mixed precision is on by default — it ~halves
memory and speeds up training with no accuracy cost on this architecture.

Realistic expectations: you need on the order of 5–15k labelled frames before
health/ult regression is reliable and ~50+ examples per hero before hero
classification generalises. The bootstrapping playbook in docs/VISION_DATA.md
gets you there without hand-labelling everything.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from app.vision.labels import make_ow2_frame_dataset
from app.vision.model import GameStateNet, MultiTaskLoss


def evaluate(model, loader, device) -> dict[str, float]:
    model.eval()
    hero_correct = hero_total = 0
    health_err = ult_err = n = 0.0
    with torch.no_grad():
        for x, target in loader:
            x = x.to(device)
            out = model(x)
            hero_pred = out["hero"].argmax(1).cpu()
            hero_correct += (hero_pred == target["hero"]).sum().item()
            hero_total += len(hero_pred)
            health_err += (out["health"].cpu() - target["health"]).abs().sum().item()
            ult_err += (out["ult"].cpu() - target["ult"]).abs().sum().item()
            n += len(hero_pred)
    return {
        "hero_acc": hero_correct / max(hero_total, 1),
        "health_mae": health_err / max(n, 1),
        "ult_mae": ult_err / max(n, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", default="models/ow2_state_detector.pt")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[train] device={device}")

    train_ds = make_ow2_frame_dataset(args.manifest, args.images, train=True)
    val_ds = make_ow2_frame_dataset(args.val, args.images, train=False)
    train_dl = DataLoader(train_ds, batch_size=args.batch, shuffle=True,
                          num_workers=4, pin_memory=True, drop_last=True)
    val_dl = DataLoader(val_ds, batch_size=args.batch, num_workers=2)

    model = GameStateNet(pretrained=True).to(device)
    criterion = MultiTaskLoss().to(device)
    optim = torch.optim.AdamW(
        list(model.parameters()) + list(criterion.parameters()),
        lr=args.lr, weight_decay=1e-4,
    )
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(optim, T_max=args.epochs)
    scaler = torch.cuda.amp.GradScaler(enabled=device == "cuda")

    best = 0.0
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        model.train()
        running = 0.0
        for x, target in train_dl:
            x = x.to(device)
            target = {k: v.to(device) for k, v in target.items()}
            optim.zero_grad()
            with torch.cuda.amp.autocast(enabled=device == "cuda"):
                out = model(x)
                loss = criterion(out, target)
            scaler.scale(loss).backward()
            scaler.step(optim)
            scaler.update()
            running += loss.item()
        sched.step()

        metrics = evaluate(model, val_dl, device)
        print(f"[epoch {epoch+1}/{args.epochs}] loss={running/len(train_dl):.3f} "
              f"hero_acc={metrics['hero_acc']:.3f} "
              f"health_mae={metrics['health_mae']:.3f} ult_mae={metrics['ult_mae']:.3f}")

        score = metrics["hero_acc"] - metrics["health_mae"] - metrics["ult_mae"]
        if score > best:
            best = score
            torch.save({"model": model.state_dict(), "metrics": metrics}, args.out)
            print(f"  ↳ saved new best to {args.out}")

    print(f"[train] done. best composite={best:.3f}")


if __name__ == "__main__":
    main()
