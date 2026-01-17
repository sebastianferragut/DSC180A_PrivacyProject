"""
Pipeline to extract settings from screenshots, merge with harvest data,
classify categories, and build a CSV dataframe.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict
import importlib.util

import convert_json_to_csv as json_to_csv
import merge_harvest_text as merge_harvest
import classify_categories as classify


def load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def extract_settings_from_screenshots(
    extractor_module,
    screenshots_root: Path,
    output_file: Path,
) -> List[Dict]:
    extractor = extractor_module.PrivacySettingsExtractor()
    return extractor.batch_extract(str(screenshots_root), str(output_file))


def merge_harvest_and_settings(
    harvest_root: Path,
    text_extractions_path: Path,
    output_path: Path,
) -> None:
    text_blocks = merge_harvest.load_json(text_extractions_path)
    all_entries = []

    for platform_dir in harvest_root.iterdir():
        if not platform_dir.is_dir():
            continue

        harvest_path = platform_dir / "harvest_report.json"
        if not harvest_path.exists():
            continue

        platform_name = platform_dir.name
        print(f"[INFO] Loading harvest: {harvest_path}")
        harvest_data = merge_harvest.load_json(harvest_path)

        entries = merge_harvest.build_screenshot_entries(harvest_data, platform_name)
        entries = merge_harvest.attach_settings(entries, text_blocks)
        all_entries.extend(entries)

    merge_harvest.save_json(output_path, all_entries)
    print(f"[DONE] Wrote {len(all_entries)} screenshot entries → {output_path}")


def classify_entries(input_path: Path, output_path: Path, embed_path: Path) -> None:
    print("[INFO] Loading screenshot dataset...")
    entries = json.loads(input_path.read_text())

    classify.CATEGORY_EMBED_PATH = embed_path
    print("[INFO] Loading or computing category embeddings...")
    category_embeddings = classify.load_or_compute_category_embeddings()

    print("[INFO] Classifying screenshots using Gemini embeddings...")
    for entry in entries:
        entry["category"] = classify.classify_entry(entry, category_embeddings)

    output_path.write_text(json.dumps(entries, indent=2))
    print(f"[DONE] Classification written to → {output_path}")


def write_csv(input_path: Path, output_path: Path) -> None:
    data = json_to_csv.load_json(input_path)
    df = json_to_csv.json_to_dataframe(data)
    df.to_csv(output_path, index=False)
    print(f"[DONE] Saved → {output_path}")


def main():
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "database" / "data"

    screenshots_root = repo_root / "gemini-team" / "generaloutput"
    extracted_settings_path = repo_root / "screenshot-classifier" / "extracted_settings.json"
    all_images_path = data_dir / "all_platforms_images.json"
    classified_path = data_dir / "all_platforms_classified.json"
    classified_csv_path = data_dir / "all_platforms_classified.csv"
    embed_path = data_dir / "category_embeddings.json"

    extractor_path = repo_root / "screenshot-classifier" / "screenshot_settings_extractor.py"
    extractor_module = load_module_from_path("screenshot_settings_extractor", extractor_path)

    print("[STEP] Extracting settings from screenshots...")
    extract_settings_from_screenshots(extractor_module, screenshots_root, extracted_settings_path)

    print("[STEP] Merging harvest data with extracted settings...")
    merge_harvest_and_settings(screenshots_root, extracted_settings_path, all_images_path)

    print("[STEP] Classifying settings into categories...")
    classify_entries(all_images_path, classified_path, embed_path)

    print("[STEP] Building CSV dataframe...")
    write_csv(classified_path, classified_csv_path)


if __name__ == "__main__":
    main()
