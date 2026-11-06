"""YAML config loading. All tunables live in configs/*.yaml, never in code."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> dict:
    p = Path(name)
    if not p.is_absolute():
        p = ROOT / p
    with open(p) as f:
        return yaml.safe_load(f)


def load_system(system: str) -> dict:
    return load(f"configs/systems/{system}.yaml")
