# COLLECTS ALL CONTROLS FROM ONE PRIVACY MAP FILE
import json
from collections import defaultdict
from typing import List, Dict, Set

# load the privacy map JSON file
def load_discoveries(file_path: str) -> dict:
    """Load a privacy map JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f).get("discoveries", [])
# extract the controls from the one file
def extract_controls(discovery: dict) -> dict:
    """Extract all controls from a discovery (page)."""
    controls = discovery.get("controls", [])
    return {key: [d[key] for d in controls] for key in controls[0]}
def extract_file_controls(discoveries: str) -> dict:
    discoveries = load_discoveries(discoveries)
    file_controls = {
        "label": [],
        "type": [],
        "selector": []
    }
    for discovery in discoveries:
        controls = extract_controls(discovery)
        file_controls["label"] += controls["label"]
        file_controls["type"] += controls["type"]
        file_controls["selector"] += controls["selector"]
    return file_controls