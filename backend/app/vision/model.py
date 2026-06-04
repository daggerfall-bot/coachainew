"""
CoachAI — Overwatch 2 game-state vision model.

A single frame of Overwatch 2 contains many independent signals we want to
read at once: which hero, current health, ult charge, ability cooldowns,
and minimap position. Rather than one model per signal, we use a shared
CNN backbone with multiple lightweight heads — this is far cheaper to run
at 5fps on your own GPU than calling a vision LLM per frame, which is the
whole reason you chose the self-hosted route.

Backbone: EfficientNet-B0 (good accuracy/latency trade-off, ~5ms/frame on
a mid GPU). Swap for a ViT later if you have the compute.

Heads:
  - hero_head:        classification over the hero roster (+ "unknown")
  - health_head:      regression, 0..1
  - ult_head:         regression, 0..1
  - cooldown_head:    multi-label regression over tracked abilities
  - map_head:         classification over map pool
  - minimap_head:     2D regression (x, y) for self-position

The killfeed and exact ally/enemy distances are read by a separate OCR +
template-matching pass (see ocr.py) because text is better handled by OCR
than by a regression head.
"""
from __future__ import annotations

import torch
import torch.nn as nn

# Tracked abilities per hero get mapped into a fixed-width cooldown vector.
# Index assignment lives in vision/labels.py so training + inference agree.
N_TRACKED_ABILITIES = 8
HERO_CLASSES = 40   # current OW2 roster size, padded for new releases
MAP_CLASSES = 24


class GameStateNet(nn.Module):
    def __init__(
        self,
        n_heroes: int = HERO_CLASSES,
        n_maps: int = MAP_CLASSES,
        n_abilities: int = N_TRACKED_ABILITIES,
        pretrained: bool = True,
    ):
        super().__init__()
        # Lazy import so the package imports cleanly without torchvision at
        # API-only deploys (the inference server pins torchvision explicitly).
        from torchvision.models import efficientnet_b0, EfficientNet_B0_Weights

        weights = EfficientNet_B0_Weights.IMAGENET1K_V1 if pretrained else None
        backbone = efficientnet_b0(weights=weights)
        feat_dim = backbone.classifier[1].in_features
        backbone.classifier = nn.Identity()  # we attach our own heads
        self.backbone = backbone

        def mlp(out: int, act: nn.Module | None = None) -> nn.Sequential:
            layers: list[nn.Module] = [
                nn.Linear(feat_dim, 256), nn.ReLU(inplace=True),
                nn.Dropout(0.2), nn.Linear(256, out),
            ]
            if act is not None:
                layers.append(act)
            return nn.Sequential(*layers)

        self.hero_head = mlp(n_heroes + 1)           # +1 = unknown/no-hero
        self.map_head = mlp(n_maps + 1)
        self.health_head = mlp(1, nn.Sigmoid())
        self.ult_head = mlp(1, nn.Sigmoid())
        self.cooldown_head = mlp(n_abilities, nn.Sigmoid())  # 0=ready,1=full cd
        self.minimap_head = mlp(2, nn.Sigmoid())             # (x, y) in 0..1

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        f = self.backbone(x)
        return {
            "hero": self.hero_head(f),
            "map": self.map_head(f),
            "health": self.health_head(f).squeeze(-1),
            "ult": self.ult_head(f).squeeze(-1),
            "cooldowns": self.cooldown_head(f),
            "minimap": self.minimap_head(f),
        }


class MultiTaskLoss(nn.Module):
    """
    Combines the per-head losses. Uses learned uncertainty weighting
    (Kendall et al. 2018) so you don't have to hand-tune the balance between
    a classification head and a regression head — the model learns how much
    to trust each task. log_vars are learnable.
    """

    def __init__(self):
        super().__init__()
        self.ce = nn.CrossEntropyLoss()
        self.mse = nn.MSELoss()
        self.bce = nn.BCELoss()
        # one log-variance per task
        self.log_vars = nn.Parameter(torch.zeros(6))

    def forward(self, pred: dict, target: dict) -> torch.Tensor:
        losses = [
            self.ce(pred["hero"], target["hero"]),
            self.ce(pred["map"], target["map"]),
            self.mse(pred["health"], target["health"]),
            self.mse(pred["ult"], target["ult"]),
            self.bce(pred["cooldowns"], target["cooldowns"]),
            self.mse(pred["minimap"], target["minimap"]),
        ]
        total = 0.0
        for i, l in enumerate(losses):
            precision = torch.exp(-self.log_vars[i])
            total = total + precision * l + self.log_vars[i]
        return total
