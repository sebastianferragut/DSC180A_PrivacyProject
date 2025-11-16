import json
from pathlib import Path
import os

def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def basename(path_str: str) -> str:
    return os.path.basename(path_str.replace("\\", "/"))

# ----------------------------------------
# Build screenshot entries from harvest
# ----------------------------------------
def build_screenshot_entries(harvest_data: dict, platform: str):
    entries = []

    for action in harvest_data.get("actions", []):
        if action.get("kind") not in ["auto_fullpage", "capture_fullpage"]:
            continue

        img_path = action.get("path")
        if not img_path:
            continue

        entries.append({
            "platform": platform,
            "image": basename(img_path),
            "full_image_path": img_path,
            "url": action.get("url"),
            "settings": []   # will attach OCR results later
        })

    return entries

# ----------------------------------------
# Attach OCR settings by matching filenames
# ----------------------------------------
def attach_settings(entries: list, text_blocks: list):
    index = {}

    for block in text_blocks:
        for s in block.get("all_settings", []):
            fname = basename(s.get("image_path", ""))
            if not fname:
                continue

            index.setdefault(fname, []).append({
                "setting": s.get("setting"),
                "description": s.get("description"),
                "state": s.get("state")
            })

    # attach to entries
    for e in entries:
        fname = e["image"]
        e["settings"] = index.get(fname, [])

    return entries


# ----------------------------------------
# MAIN
# ----------------------------------------
def main():
    # YOUR ACTUAL PATHS
    harvest_dir = Path("../gemini-team/generaloutput")
    text_extractions_path = Path("../screenshot-classifier/extracted_settings.json")
    output_path = Path("data/all_platforms_images.json")

    # HARVEST FILES (REAL PATHS)
    harvest_files = {
        "facebook": harvest_dir / "facebook/harvest_report.json",
        "linkedin": harvest_dir / "linkedin/harvest_report.json",
        "zoom": harvest_dir / "zoom/harvest_report.json"
    }

    # Load text extraction file
    text_blocks = load_json(text_extractions_path)

    all_entries = []

    for platform, h_path in harvest_files.items():
        if not h_path.exists():
            print(f"[WARN] Harvest file missing: {h_path}")
            continue

        print(f"[INFO] Loading harvest: {h_path}")
        harvest_data = load_json(h_path)

        entries = build_screenshot_entries(harvest_data, platform)
        entries = attach_settings(entries, text_blocks)

        all_entries.extend(entries)

    save_json(output_path, all_entries)
    print(f"[DONE] Wrote {len(all_entries)} screenshot entries → {output_path}")


if __name__ == "__main__":
    main()
