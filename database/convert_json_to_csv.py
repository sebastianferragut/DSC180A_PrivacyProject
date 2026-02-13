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
        rows.append({
            "platform": entry.get("platform"),
            "image": entry.get("image"),
            "full_image_path": entry.get("full_image_path"),
            "url": entry.get("url"),
            "settings": entry.get("settings", []),
            "category": entry.get("category")
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

    # Optional: save
    df.to_csv(output_path, index=False)
    print(f"[DONE] Saved → {output_path}")

if __name__ == "__main__":
    main()
