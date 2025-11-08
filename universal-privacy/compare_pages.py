from typing import List, Dict, Set
from extract_from_page import extract_file_controls
from aggregate_pages import aggregate_pages

def find_intersecting_controls(controls1: dict, controls2: dict) -> set[str]:
    # Find intersecting controls between two sets of controls.
    intersecting_controls = {
        label: [],
        type: []
    }
    labels = set(controls1["label"]) & set(controls2["label"])
    for control in controls1:
        if control["label"] in labels:
            intersecting_controls["label"].append(control["label"])
            intersecting_controls["type"].append(control["type"])
    return intersecting_controls