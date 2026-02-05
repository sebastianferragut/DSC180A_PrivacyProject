import os
import json
import csv
from typing import List, Dict


def _pretty_platform_name(raw_platform: str) -> str:
    """
    Convert a raw platform string like:
        'www.linkedin.com' or 'accountscenter.facebook.com'
    into a title-cased platform name:
        'Linkedin', 'Facebook'
    by:
      - stripping any leading 'www.'
      - taking the portion before '.com'
      - if multiple labels remain, taking the last one
    """
    base = raw_platform
    if base.startswith("www."):
        base = base[len("www.") :]

    # Take the part before '.com' if present
    if ".com" in base:
        base = base.split(".com", 1)[0]

    # If there are still dots, take the last label
    parts = base.split(".")
    base = parts[-1] if parts else base

    return base.title() if base else raw_platform


def flatten_click_counts(root_dir: str, output_csv: str) -> None:
    """
    Iterate through all *_crawl_results.json files in root_dir,
    and write a CSV with rows:
        platform, layer, url
    where:
        - platform is derived from the JSON filename prefix
        - layer is the key from `layer_dict` (e.g. "Layer 0")
        - url is each URL listed under that layer
    """
    rows = []

    for filename in os.listdir(root_dir):
        if not filename.endswith("_crawl_results.json"):
            continue

        filepath = os.path.join(root_dir, filename)

        # Raw platform string from filename prefix
        raw_platform = filename.replace("_crawl_results.json", "")
        platform = _pretty_platform_name(raw_platform)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Skipping {filename}: could not read/parse JSON ({e})")
            continue

        layer_dict = data.get("layer_dict", {})
        if not isinstance(layer_dict, dict):
            print(f"Skipping {filename}: 'layer_dict' is missing or not a dict")
            continue

        for layer_name, urls in layer_dict.items():
            # Expect urls to be a list of strings
            if not isinstance(urls, list):
                continue

            # Extract numeric layer index from names like "Layer 0"
            click_count = layer_name
            if isinstance(layer_name, str) and layer_name.lower().startswith("layer"):
                try:
                    # Split on space and take the numeric part
                    click_count = int(layer_name.split()[1])
                except (IndexError, ValueError):
                    # Fallback: leave as original string
                    click_count = layer_name

            for url in urls:
                if not isinstance(url, str):
                    continue
                rows.append(
                    {
                        "platform": platform,
                        "url": url,
                        "click_count": click_count
                    }
                )

    # Write combined CSV
    with open(output_csv, "w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["platform", "url", "click_count"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    # Root directory containing the *_crawl_results.json files
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

    # Output CSV path (placed in the same directory)
    OUTPUT_CSV = os.path.join(ROOT_DIR, "url_to_click_count_map.csv")

    flatten_click_counts(ROOT_DIR, OUTPUT_CSV)
    print(f"Wrote flattened CSV to: {OUTPUT_CSV}")

