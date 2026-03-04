import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIFIED_PATH = (
    REPO_ROOT
    / "database"
    / "data"
    / "extracted_settings_with_urls_and_layers_classified.json"
)


def _non_empty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _flatten_classified_records(payload):
    records = []

    if isinstance(payload, list):
        for block in payload:
            if not isinstance(block, dict):
                continue

            block_platform = block.get("platform")

            if isinstance(block.get("all_settings"), list):
                for setting in block["all_settings"]:
                    if not isinstance(setting, dict):
                        continue
                    merged = dict(setting)
                    if _non_empty(block_platform) and not _non_empty(merged.get("platform")):
                        merged["platform"] = block_platform
                    records.append(merged)
            elif isinstance(block.get("settings"), list):
                for setting in block["settings"]:
                    if not isinstance(setting, dict):
                        continue
                    merged = dict(setting)
                    if _non_empty(block_platform) and not _non_empty(merged.get("platform")):
                        merged["platform"] = block_platform
                    records.append(merged)
            else:
                records.append(dict(block))

    elif isinstance(payload, dict):
        for platform, settings in payload.items():
            if not isinstance(settings, list):
                continue
            for setting in settings:
                if not isinstance(setting, dict):
                    continue
                merged = dict(setting)
                if _non_empty(platform) and not _non_empty(merged.get("platform")):
                    merged["platform"] = platform
                records.append(merged)

    return records


def test_classified_json_minimum_schema():
    if not CLASSIFIED_PATH.exists():
        pytest.skip(
            "Classified output file not found: "
            "database/data/extracted_settings_with_urls_and_layers_classified.json"
        )

    with CLASSIFIED_PATH.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    records = _flatten_classified_records(payload)
    assert records, "Classified file exists but contains no records."

    missing_name_count = 0
    missing_url_count = 0
    missing_category_count = 0
    missing_platform_count = 0

    has_layer_key = False
    missing_layer_count = 0

    for rec in records:
        name = rec.get("setting") or rec.get("name") or rec.get("label")
        category = rec.get("category") or rec.get("classification")
        platform = rec.get("platform")

        if not _non_empty(name):
            missing_name_count += 1
        if not _non_empty(rec.get("url")):
            missing_url_count += 1
        if not _non_empty(category):
            missing_category_count += 1
        if not _non_empty(platform):
            missing_platform_count += 1

        if "layer" in rec:
            has_layer_key = True
            if not _non_empty(rec.get("layer")):
                missing_layer_count += 1

    total = len(records)
    assert missing_name_count == 0, (
        f"Missing setting text in {missing_name_count}/{total} records "
        "(requires setting/name/label)."
    )
    assert missing_category_count < total, (
        f"All records are missing category/classification ({missing_category_count}/{total})."
    )
    assert missing_url_count < total, (
        f"All records are missing URL ({missing_url_count}/{total})."
    )
    assert missing_platform_count < total, (
        f"All records are missing platform ({missing_platform_count}/{total})."
    )

    if has_layer_key:
        assert missing_layer_count < total, (
            f"Layer key exists but all values are missing ({missing_layer_count}/{total})."
        )
