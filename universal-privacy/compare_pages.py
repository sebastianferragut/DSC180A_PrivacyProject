import json
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict

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
def aggregate_pages(privacy_maps: List[Path]) -> dict:
    # Extract all controls from all privacy maps
    map_controls = {pmap: extract_file_controls(pmap) for pmap in privacy_maps}
    all_controls = {
        "label": [],
        "type": [],
        "selector": []
    }
    for pmap in map_controls:
        all_controls["label"] += map_controls[pmap]["label"]
        all_controls["type"] += map_controls[pmap]["type"]
        all_controls["selector"] += map_controls[pmap]["selector"]

    return all_controls

# Used to compare a user's preferences to one particular page's controls
def find_intersecting_controls(controls1: str, target: str) -> set[str]:
    # Find intersecting controls between two sets of controls.
    controls1 = extract_file_controls(controls1)
    target = extract_file_controls(target)
    intersecting_controls = {
        "label": [],
        "type": []
    }
    labels = set(controls1["label"]) & set(target["label"])
    for i in range(len(controls1["label"])):
        if controls1["label"][i] in labels:
            intersecting_controls["label"].append(controls1["label"][i])
            intersecting_controls["type"].append(controls1["type"][i])
    return intersecting_controls

def summarize_output(controls1: dict, target: dict, intersecting_controls: dict) -> dict:
    # Summarize the output of the comparison
    summary = {
        "controls1": controls1,
        "target": target,
        "intersecting_controls": intersecting_controls
    }
    return summary