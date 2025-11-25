"""
Utility script to flatten `extracted_settings.json` into a CSV file.

The resulting CSV contains the following columns:
    platform, setting, description, state, image_path

`image_path` is reduced to just the PNG filename (e.g., `Profile-icon_Settings_Data-controls.png`).

Usage:
    python build_extracted_settings_csv.py \
        --input extracted_settings.json \
        --output extracted_settings_flat.csv
"""

import argparse
import csv
import json
from pathlib import Path


def flatten_settings(input_path: Path, output_path: Path) -> None:
    """Read the JSON extraction output and write a flat CSV file."""
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for platform_entry in data:
        platform_name = platform_entry.get("platform", "unknown")
        for setting in platform_entry.get("all_settings", []):
            image_name = Path(setting.get("image_path", "")).name
            rows.append(
                {
                    "platform": platform_name,
                    "setting": setting.get("setting", ""),
                    "description": setting.get("description", ""),
                    "state": setting.get("state", ""),
                    "image_path": image_name,
                }
            )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(
            csvfile, fieldnames=["platform", "setting", "description", "state", "image_path"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ CSV created at {output_path} with {len(rows)} rows")


def main():
    parser = argparse.ArgumentParser(description="Flatten extracted settings JSON into CSV")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("extracted_settings.json"),
        help="Path to the extracted_settings.json file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("extracted_settings_flat.csv"),
        help="Path to the output CSV file",
    )
    args = parser.parse_args()

    flatten_settings(args.input, args.output)


if __name__ == "__main__":
    main()


