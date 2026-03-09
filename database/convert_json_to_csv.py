import json
import pandas as pd
from pathlib import Path

# -----------------------------
# Load JSON
# -----------------------------
def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

# -----------------------------
# Convert to DataFrame
# -----------------------------
def json_to_dataframe(json_data: list) -> pd.DataFrame:
    rows = []

    for entry in json_data:
        platform = entry.get("platform")
        category = entry.get("category", "")  # JSON may not have category
        all_settings = entry.get("all_settings", [])

        for setting in all_settings:
            rows.append({
                "platform": platform,
                "toggle_name": setting.get("setting"),
                "description": setting.get("description"),
                "state": setting.get("state"),
                "click_counts": setting.get("layer"),  # use layer as click_counts
                "category": category,
                "url": setting.get("url"),
                "image_path": setting.get("image_path")
            })

    return pd.DataFrame(rows)

# -----------------------------
# MAIN
# -----------------------------
def main():
    input_path = Path("data/extracted_settings_with_urls_and_layers_classified.json")
    output_path = Path("data/priority_privacy.csv")

    data = load_json(input_path)
    df = json_to_dataframe(data)

    print(df.head())
    print(f"\nRows: {len(df)}")

    # Save to CSV
    df.to_csv(output_path, index=False)
    print(f"[DONE] Saved → {output_path}")

if __name__ == "__main__":
    main()
