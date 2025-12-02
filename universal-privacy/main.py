import json
from pathlib import Path
from compare_pages import find_intersecting_controls

maps_dir = Path(__file__).parent.parent / "gemini-team" / "outputs"
privacy_maps = [file for file in maps_dir.glob("privacy_map_*.json")] 
# all_controls = aggregate_pages(maps_dir)
controls1, controls2 = privacy_maps[0], privacy_maps[1]

overlap = find_intersecting_controls(controls1, controls2)
print(json.dumps(overlap, indent=4))