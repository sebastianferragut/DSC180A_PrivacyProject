# AGGREGATE ALL CONTROLS FROM ALL PRIVACY MAPS
import json
from pathlib import Path
from extract_from_page import extract_all_controls

def aggregate_pages(filepath: Path):
    # Get all privacy map files
    privacy_maps = [file for file in filepath.glob("privacy_map_*.json")] 

    # Extract all controls from all privacy maps
    map_controls = {pmap: extract_all_controls(pmap) for pmap in privacy_maps}
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