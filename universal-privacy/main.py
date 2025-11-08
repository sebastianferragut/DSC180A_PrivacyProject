import json
from pathlib import Path
from aggregate_pages import aggregate_pages

maps_dir = Path(__file__).parent.parent / "gemini-team" 
all_controls = aggregate_pages(maps_dir)
print(json.dumps(all_controls, indent=4))