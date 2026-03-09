import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_STATS_PATH = REPO_ROOT / "privacyagentapp" / "database" / "run_stats.json"


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _is_non_negative_number(value) -> bool:
    return isinstance(value, (int, float)) and value >= 0


def test_run_stats_schema():
    if not RUN_STATS_PATH.exists():
        pytest.skip("run_stats.json not found: privacyagentapp/database/run_stats.json")

    data = _load_json(RUN_STATS_PATH)
    assert isinstance(data, dict), "run_stats.json must be a top-level JSON object."
    assert "by_setting" in data, "run_stats.json missing top-level key: by_setting"
    assert isinstance(data["by_setting"], dict), "by_setting must be a JSON object."

    required_record_keys = {
        "platform",
        "setting_id",
        "name",
        "runs",
        "successes",
        "avg_clicks_success",
        "min_clicks_success",
        "max_clicks_success",
        "last_success_ts",
        "history",
    }

    required_history_keys = {"ts", "status", "target_value", "click_count"}

    for setting_key, rec in data["by_setting"].items():
        assert isinstance(setting_key, str) and "::" in setting_key
        assert isinstance(rec, dict), f"Record for {setting_key} must be an object."

        missing = required_record_keys - set(rec.keys())
        assert not missing, f"Record {setting_key} missing keys: {sorted(missing)}"

        assert isinstance(rec["history"], list), f"Record {setting_key} history must be a list."
        assert isinstance(rec["runs"], int) and rec["runs"] >= 0
        assert isinstance(rec["successes"], int) and rec["successes"] >= 0
        assert rec["runs"] >= rec["successes"], (
            f"Record {setting_key} has runs < successes ({rec['runs']} < {rec['successes']})."
        )

        if rec["avg_clicks_success"] is not None:
            assert _is_non_negative_number(rec["avg_clicks_success"])
        if rec["min_clicks_success"] is not None:
            assert _is_non_negative_number(rec["min_clicks_success"])
        if rec["max_clicks_success"] is not None:
            assert _is_non_negative_number(rec["max_clicks_success"])

        for i, hist in enumerate(rec["history"]):
            assert isinstance(hist, dict), f"{setting_key} history[{i}] must be an object."
            missing_hist = required_history_keys - set(hist.keys())
            assert not missing_hist, (
                f"{setting_key} history[{i}] missing keys: {sorted(missing_hist)}"
            )
            assert isinstance(hist["click_count"], int) and hist["click_count"] >= 0


def test_harvest_report_metrics_schema_if_present():
    report_paths = sorted(
        (REPO_ROOT / "new_crawler" / "generaloutput").glob("*/harvest_report.json")
    ) + sorted((REPO_ROOT / "gemini-team" / "generaloutput").glob("*/harvest_report.json"))

    if not report_paths:
        pytest.skip("No harvest_report.json files found under new_crawler/ or gemini-team/")

    for path in report_paths:
        payload = _load_json(path)
        assert isinstance(payload, dict), f"{path} must contain a JSON object."

        metrics = payload.get("metrics")
        assert isinstance(metrics, dict), f"{path} missing metrics object."

        for key in ("run_start_ts", "run_end_ts", "total_runtime_sec", "steps"):
            assert key in metrics, f"{path} metrics missing key: {key}"

        assert isinstance(metrics["steps"], dict), f"{path} metrics.steps must be an object."
