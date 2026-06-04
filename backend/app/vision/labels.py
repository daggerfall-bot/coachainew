"""
CoachAI — Vision label space + dataset.

Single source of truth for how heroes/maps/abilities map to indices. Training
and inference both import from here so they never disagree (a classic bug:
retrain with a reordered class list and every prediction silently shifts).
"""
from __future__ import annotations

import json
from pathlib import Path

# NOTE: torch / torchvision are imported lazily inside OW2FrameDataset (used
# only for TRAINING). The label constants below are plain Python so the
# inference path — and the bundled API-mode desktop server — can import them
# without torch installed.

# Order is FROZEN. Append new heroes/maps to the end only — never reorder,
# or you invalidate every trained checkpoint.
HEROES = [
    "Ana", "Ashe", "Baptiste", "Bastion", "Brigitte", "Cassidy", "D.Va",
    "Doomfist", "Echo", "Genji", "Hanzo", "Junkrat", "Junker Queen", "Kiriko",
    "Lucio", "Mei", "Mercy", "Moira", "Orisa", "Pharah", "Reaper", "Reinhardt",
    "Roadhog", "Sigma", "Soldier: 76", "Sombra", "Soujourn", "Symmetra",
    "Torbjorn", "Tracer", "Widowmaker", "Winston", "Wrecking Ball", "Zarya",
    "Zenyatta", "Lifeweaver", "Illari", "Mauga", "Venture", "Juno",
]
MAPS = [
    "King's Row", "Numbani", "Eichenwalde", "Hollywood", "Midtown", "Paraiso",
    "Circuit Royal", "Dorado", "Havana", "Junkertown", "Rialto", "Route 66",
    "Shambali", "Watchpoint: Gibraltar", "Blizzard World", "Lijiang Tower",
    "Nepal", "Oasis", "Busan", "Ilios", "Antarctic Peninsula", "Colosseo",
    "Esperanca", "New Queen Street",
]
# Generic ability slots; per-hero meaning resolved at analysis time.
ABILITY_SLOTS = [
    "primary_cd", "ability_1", "ability_2", "ability_3",
    "movement", "defensive", "passive", "reserved",
]

HERO_TO_IDX = {h: i for i, h in enumerate(HEROES)}
MAP_TO_IDX = {m: i for i, m in enumerate(MAPS)}
UNKNOWN_HERO = len(HEROES)
UNKNOWN_MAP = len(MAPS)


def make_ow2_frame_dataset(manifest_path: str, image_root: str, train: bool = True):
    """
    Factory for the training dataset. Defined as a factory (not a top-level
    class) so this module imports without torch/torchvision — the inference
    path and the bundled desktop server only need the label constants above.
    Training (train.py) calls this, at which point torch is available.

    Manifest is JSONL, one labelled frame per line:
      {"image": "frames/0001.jpg", "hero": "Tracer", "map": "King's Row",
       "health": 0.82, "ult": 0.40, "cooldowns": [0,0,1,0,0,0,0,0],
       "minimap": [0.31, 0.58]}

    See docs/VISION_DATA.md for the data-collection playbook.
    """
    import torch
    from PIL import Image
    from torch.utils.data import Dataset
    from torchvision import transforms

    class OW2FrameDataset(Dataset):
        def __init__(self, manifest_path: str, image_root: str, train: bool):
            self.root = Path(image_root)
            self.items = [
                json.loads(line)
                for line in Path(manifest_path).read_text().splitlines()
                if line.strip()
            ]
            base = [transforms.Resize((224, 224))]
            if train:
                base += [
                    transforms.ColorJitter(0.2, 0.2, 0.2, 0.05),
                    transforms.RandomAdjustSharpness(2, p=0.3),
                ]
            base += [
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406],
                                     [0.229, 0.224, 0.225]),
            ]
            self.transform = transforms.Compose(base)

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, idx: int):
            it = self.items[idx]
            img = Image.open(self.root / it["image"]).convert("RGB")
            x = self.transform(img)
            target = {
                "hero": torch.tensor(HERO_TO_IDX.get(it.get("hero"), UNKNOWN_HERO)),
                "map": torch.tensor(MAP_TO_IDX.get(it.get("map"), UNKNOWN_MAP)),
                "health": torch.tensor(it.get("health", 0.0), dtype=torch.float32),
                "ult": torch.tensor(it.get("ult", 0.0), dtype=torch.float32),
                "cooldowns": torch.tensor(
                    it.get("cooldowns", [0] * len(ABILITY_SLOTS)),
                    dtype=torch.float32),
                "minimap": torch.tensor(
                    it.get("minimap", [0.0, 0.0]), dtype=torch.float32),
            }
            return x, target

    return OW2FrameDataset(manifest_path, image_root, train)
