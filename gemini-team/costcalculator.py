import json
from pathlib import Path

# Folder where this script lives
SCRIPT_DIR = Path(__file__).resolve().parent

# Base directory to search for harvest_report.json files
BASE_DIR = SCRIPT_DIR / "generaloutput"

# Metric fields we care about
TOP_LEVEL_FIELDS = ["total_runtime_sec", "turns"]
API_FIELDS = ["calls", "input_tokens", "output_tokens", "cost_usd"]


def main():
    # Totals for computing averages
    totals = {
        "total_runtime_sec": 0.0,
        "turns": 0.0,
        "api.calls": 0.0,
        "api.input_tokens": 0.0,
        "api.output_tokens": 0.0,
        "api.cost_usd": 0.0,
    }

    file_count = 0

    # Walk generaloutput and find all harvest_report.json files
    for report_path in BASE_DIR.rglob("harvest_report.json"):
        try:
            with report_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Skipping {report_path} (error reading JSON: {e})")
            continue

        metrics = data.get("metrics")
        if not isinstance(metrics, dict):
            print(f"Skipping {report_path} (no 'metrics' object)")
            continue

        file_count += 1

        # Top-level metrics
        for field in TOP_LEVEL_FIELDS:
            val = metrics.get(field)
            if isinstance(val, (int, float)):
                totals[field] += float(val)
            else:
                # Treat missing/non-numeric as 0 for averaging
                pass

        # API metrics nested under metrics["api"]
        api = metrics.get("api", {})
        if isinstance(api, dict):
            for field in API_FIELDS:
                val = api.get(field)
                key = f"api.{field}"
                if isinstance(val, (int, float)):
                    totals[key] += float(val)
                else:
                    # Treat missing/non-numeric as 0
                    pass

    if file_count == 0:
        print("No harvest_report.json files with valid 'metrics' found.")
        return

    # Compute averages across all files
    averages = {name: totals[name] / file_count for name in totals}

    print(f"Processed {file_count} harvest_report.json file(s)\n")
    print("Averages across all files:")
    print(f"  total_runtime_sec : {averages['total_runtime_sec']:.4f}")
    print(f"  turns             : {averages['turns']:.4f}")
    print(f"  api.calls         : {averages['api.calls']:.4f}")
    print(f"  api.input_tokens  : {averages['api.input_tokens']:.4f}")
    print(f"  api.output_tokens : {averages['api.output_tokens']:.4f}")
    print(f"  api.cost_usd      : ${averages['api.cost_usd']:.6f}")


if __name__ == "__main__":
    main()