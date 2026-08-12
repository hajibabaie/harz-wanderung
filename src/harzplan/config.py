"""Load config.toml from the project root."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def load() -> dict:
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)
