import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENUE_PATH = Path(os.getenv("VENUE_CONFIG", ROOT / "config" / "venue.json"))

def load_venue() -> dict:
    with VENUE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)
