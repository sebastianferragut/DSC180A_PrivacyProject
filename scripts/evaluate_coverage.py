#!/usr/bin/env python3
"""
Compute lightweight coverage metrics for privacy settings artifacts.

Usage:
  python scripts/evaluate_coverage.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    if not path.exists():
        return None, "not_found"
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"json_error: {exc}"


def _flatten_records(payload: Any) -> List[Dict[str, Any]]:
    """
    Best-effort flattening for known repository schemas.
    """
    records: List[Dict[str, Any]] = []

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
                continue

            if isinstance(block.get("settings"), list):
                for setting in block["settings"]:
                    if not isinstance(setting, dict):
                        continue
                    merged = dict(setting)
                    if _non_empty(block_platform) and not _non_empty(merged.get("platform")):
                        merged["platform"] = block_platform
                    records.append(merged)
                continue

            # fallback: already a flat record
            records.append(dict(block))

    elif isinstance(payload, dict):
        for platform, items in payload.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                merged = dict(item)
                if _non_empty(platform) and not _non_empty(merged.get("platform")):
                    merged["platform"] = platform
                records.append(merged)

    return records


def _infer_raw_total(repo_root: Path, fallback_total: int) -> Tuple[int, str]:
    data_dir = repo_root / "database" / "data"
    raw_candidates = sorted(
        p
        for p in data_dir.glob("*.json")
        if "classified" not in p.name.lower()
        and "category_embeddings" not in p.name.lower()
        and "extracted_settings" in p.name.lower()
    )

    raw_counts: List[Tuple[int, str]] = []
    for candidate in raw_candidates:
        payload, err = _read_json(candidate)
        if err is not None:
            continue
        raw_records = _flatten_records(payload)
        if raw_records:
            raw_counts.append((len(raw_records), str(candidate.relative_to(repo_root))))

    if raw_counts:
        # choose the largest raw source to be conservative
        raw_counts.sort(key=lambda x: x[0], reverse=True)
        return raw_counts[0]

    harvest_paths = sorted(
        (repo_root / "new_crawler" / "generaloutput").glob("*/harvest_report.json")
    ) + sorted((repo_root / "gemini-team" / "generaloutput").glob("*/harvest_report.json"))

    harvest_estimate = 0
    for path in harvest_paths:
        payload, err = _read_json(path)
        if err is not None or not isinstance(payload, dict):
            continue

        sections = payload.get("sections")
        if isinstance(sections, list):
            section_count = len(sections)
            item_count = 0
            for section in sections:
                if isinstance(section, dict) and isinstance(section.get("items"), list):
                    item_count += len(section["items"])
            harvest_estimate += max(section_count, item_count)

    if harvest_estimate > 0:
        return harvest_estimate, "harvest_report_estimate"

    return fallback_total, "unknown"


def _build_metrics(repo_root: Path) -> Dict[str, Any]:
    primary_path = (
        repo_root
        / "database"
        / "data"
        / "extracted_settings_with_urls_and_layers_classified.json"
    )

    payload, err = _read_json(primary_path)
    if err is not None:
        return {
            "status": "missing_inputs",
            "missing_inputs": [str(primary_path.relative_to(repo_root))],
            "total_records": 0,
            "categorized_count": 0,
            "uncategorized_count": 0,
            "categorized_ratio": 0.0,
            "missing_url_count": 0,
            "missing_layer_count": None,
            "raw_total": 0,
            "raw_source": "unknown",
            "per_platform": {},
            "top_categories": [],
        }

    records = _flatten_records(payload)
    total_records = len(records)

    categorized_count = 0
    missing_url_count = 0
    has_layer = any("layer" in rec for rec in records)
    missing_layer_count = 0

    category_counter: Counter[str] = Counter()
    platform_totals: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "total_records": 0,
            "categorized_count": 0,
            "uncategorized_count": 0,
            "missing_url_count": 0,
        }
    )

    for rec in records:
        category_val = rec.get("category") or rec.get("classification")
        platform_val = rec.get("platform")
        platform = str(platform_val).strip() if _non_empty(platform_val) else "unknown"

        is_categorized = _non_empty(category_val)
        if is_categorized:
            categorized_count += 1
            category_counter[str(category_val).strip()] += 1
            platform_totals[platform]["categorized_count"] += 1

        if not _non_empty(rec.get("url")):
            missing_url_count += 1
            platform_totals[platform]["missing_url_count"] += 1

        if has_layer and "layer" in rec and not _non_empty(rec.get("layer")):
            missing_layer_count += 1

        platform_totals[platform]["total_records"] += 1

    uncategorized_count = total_records - categorized_count
    categorized_ratio = round(categorized_count / total_records, 4) if total_records else 0.0

    for stats in platform_totals.values():
        stats["uncategorized_count"] = stats["total_records"] - stats["categorized_count"]

    raw_total, raw_source = _infer_raw_total(repo_root, total_records)

    top_categories = [
        {"category": cat, "count": count}
        for cat, count in category_counter.most_common(15)
    ]

    return {
        "status": "ok",
        "missing_inputs": [],
        "primary_source": str(primary_path.relative_to(repo_root)),
        "raw_total": raw_total,
        "raw_source": raw_source,
        "total_records": total_records,
        "categorized_count": categorized_count,
        "uncategorized_count": uncategorized_count,
        "categorized_ratio": categorized_ratio,
        "missing_url_count": missing_url_count,
        "missing_layer_count": missing_layer_count if has_layer else None,
        "per_platform": dict(sorted(platform_totals.items(), key=lambda kv: kv[0].lower())),
        "top_categories": top_categories,
    }


def _to_markdown(metrics: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Coverage Metrics")
    lines.append("")
    lines.append(f"- Status: `{metrics.get('status', 'unknown')}`")

    missing_inputs = metrics.get("missing_inputs") or []
    if missing_inputs:
        lines.append("- Missing Inputs:")
        for item in missing_inputs:
            lines.append(f"  - `{item}`")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| raw_total | {metrics.get('raw_total', 0)} |")
    lines.append(f"| total_records | {metrics.get('total_records', 0)} |")
    lines.append(f"| categorized_count | {metrics.get('categorized_count', 0)} |")
    lines.append(f"| uncategorized_count | {metrics.get('uncategorized_count', 0)} |")
    lines.append(f"| categorized_ratio | {metrics.get('categorized_ratio', 0)} |")
    lines.append(f"| missing_url_count | {metrics.get('missing_url_count', 0)} |")
    lines.append(f"| missing_layer_count | {metrics.get('missing_layer_count')} |")
    lines.append("")

    per_platform = metrics.get("per_platform") or {}
    if per_platform:
        lines.append("## Per-Platform Breakdown")
        lines.append("")
        lines.append("| Platform | Total | Categorized | Uncategorized | Missing URL |")
        lines.append("|---|---:|---:|---:|---:|")
        for platform, stats in per_platform.items():
            lines.append(
                f"| {platform} | {stats.get('total_records', 0)} | "
                f"{stats.get('categorized_count', 0)} | {stats.get('uncategorized_count', 0)} | "
                f"{stats.get('missing_url_count', 0)} |"
            )
        lines.append("")

    top_categories = metrics.get("top_categories") or []
    if top_categories:
        lines.append("## Top Categories (Top 15)")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|---|---:|")
        for row in top_categories:
            lines.append(f"| {row['category']} | {row['count']} |")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    metrics = _build_metrics(repo_root)

    json_out = reports_dir / "coverage_metrics.json"
    md_out = reports_dir / "coverage_metrics.md"

    json_out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    md_out.write_text(_to_markdown(metrics), encoding="utf-8")

    print("[coverage] status:", metrics.get("status"))
    print("[coverage] json:", json_out)
    print("[coverage] markdown:", md_out)

    missing = metrics.get("missing_inputs") or []
    if missing:
        print("[coverage] missing inputs:", ", ".join(missing))
    else:
        print(
            "[coverage] totals:",
            f"total_records={metrics.get('total_records', 0)}",
            f"categorized={metrics.get('categorized_count', 0)}",
            f"ratio={metrics.get('categorized_ratio', 0)}",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
