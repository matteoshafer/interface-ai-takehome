"""Load / save / list capability artifacts. Flat JSON files under ``capabilities/``.

Deliberately not a database: an artifact is a reviewable document that belongs in
version control next to the code that replays it.
"""
from __future__ import annotations

import json
from pathlib import Path

from cua.artifact.schema import Capability

DEFAULT_DIR = Path("capabilities")


def path_for(cap: Capability, root: str | Path = DEFAULT_DIR) -> Path:
    return Path(root) / f"{cap.id}.json"


def save(cap: Capability, root: str | Path = DEFAULT_DIR) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    p = path_for(cap, root)
    p.write_text(json.dumps(cap.model_dump(mode="json"), indent=2) + "\n")
    return p


def load(path: str | Path) -> Capability:
    return Capability.model_validate_json(Path(path).read_text())


def load_all(root: str | Path = DEFAULT_DIR) -> list[Capability]:
    root = Path(root)
    if not root.exists():
        return []
    return [load(p) for p in sorted(root.glob("*.json"))]
