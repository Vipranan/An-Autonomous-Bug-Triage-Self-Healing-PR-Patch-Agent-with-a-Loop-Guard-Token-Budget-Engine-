import json
from pathlib import Path


def load_settings():
    cfg_path = Path(__file__).parent / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("timeout", 0) <= 0:
        raise ValueError("timeout must be positive")
    return cfg
