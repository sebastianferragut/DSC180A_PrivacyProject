# Usage: privacyagentapp/agenticapp.py
# Main Chainlit app for the Privacy Agent using Gemini + Playwright
# Loads settings DB, handles commands, runs setting change automation.
# Requires GEMINI_API_KEY in env.
# EXPORT
# export GEMINI_API_KEY="your_key_here"
# RUN COMMAND
# chainlit run privacyagentapp/agenticapp.py -w

import re
import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import math
import time, random


import chainlit as cl

from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page, TimeoutError as PwTimeout

from google import genai
from google.genai import types
from google.genai.types import Content, Part

from datetime import datetime

# =========================
# Paths & Config
# =========================

REPO_ROOT = Path(__file__).resolve().parent.parent

RUN_STATS_PATH = REPO_ROOT / "privacyagentapp" / "database" / "run_stats.json"

# Cached exports for UI/dashboards (only updated when content changes)
SETTINGSLIST_DIR = REPO_ROOT / "privacyagentapp" / "settingslist"
SETTINGS_SNAPSHOT_PATH = SETTINGSLIST_DIR / "settings_snapshot.json"
PLATFORM_SUMMARIES_PATH = SETTINGSLIST_DIR / "platform_summaries.json"

try:
    SETTINGS_JSON_PATH = REPO_ROOT / "database" / "data" / "all_platforms_classified.json"
except Exception as e:
    print(f"Warning: could not construct SETTINGS_JSON_PATH from REPO_ROOT ({REPO_ROOT}): {e}")
    SETTINGS_JSON_PATH = Path("all_platforms_classified.json")

try:
    GENERAL_OUTPUT_DIR = REPO_ROOT / "gemini-team" / "general_output"
except Exception as e:
    print(f"Warning: could not construct GENERAL_OUTPUT_DIR from REPO_ROOT ({REPO_ROOT}): {e}")
    GENERAL_OUTPUT_DIR = Path("general_output")

try:
    STORAGE_STATE_DIR = REPO_ROOT / "gemini-team" / "profiles" / "storage"
except Exception as e:
    print(f"Warning: could not construct STORAGE_STATE_DIR from REPO_ROOT ({REPO_ROOT}): {e}")
    STORAGE_STATE_DIR = Path("storage")

SESSION_CHANGES_KEY = "changed_settings"
SESSION_PENDING_KEY = "pending_setting_choice"
SESSION_PENDING_PLATFORM_KEY = "pending_platform"
SESSION_PENDING_VALUE_KEY = "pending_target_value"
SESSION_PENDING_CONFIRM = "pending_confirm_setting"
SESSION_INFERRED_BY_SETTING = "inferred_by_setting"
SESSION_ACTIVE_PLATFORM = "active_platform"
SESSION_PENDING_NL_TEXT = "pending_nl_text"


SESSION_BROWSE_CATEGORY = "browse_category"
SESSION_BROWSE_PAGE = "browse_page"
SESSION_SELECTED_SETTING_ID = "selected_setting_id"
SESSION_SELECTED_PLATFORM = "selected_platform"


ENABLE_NLP = False  

# Categories present in settings_snapshot.json (verified)
CATEGORY_ORDER = [
    "security_authentication",
    "identity_personal_info",
    "device_sensor_access",
    "data_collection_tracking",
    "visibility_audience",
    "communication_notifications",
    "uncategorized",
]

CATEGORY_TITLES = {
    "security_authentication": "Security & Authentication",
    "identity_personal_info": "Identity & Personal Info",
    "device_sensor_access": "Device & Sensor Access",
    "data_collection_tracking": "Data Collection & Tracking",
    "visibility_audience": "Visibility & Audience",
    "communication_notifications": "Communication & Notifications",
    "uncategorized": "Uncategorized",
}

CATEGORY_HELP = {
    "security_authentication": "Passwords, 2FA/passkeys, sessions, suspicious activity, recovery.",
    "identity_personal_info": "Profile details, contact info, identity verification, demographics.",
    "device_sensor_access": "Camera, mic, screen share, recording, device permissions.",
    "data_collection_tracking": "Ads, tracking, telemetry, history, personalization, AI training data.",
    "visibility_audience": "Profile/post visibility, discoverability, followers, blocking.",
    "communication_notifications": "Messaging, calls, comments, notifications, read receipts.",
    "uncategorized": "Not classified yet.",
}


# =========================
# Session-only Gemini API key support
# =========================
SESSION_GEMINI_API_KEY = "session_gemini_api_key"
SESSION_GEMINI_CLIENT = "session_gemini_client"
SESSION_AWAITING_GEMINI_KEY = "awaiting_gemini_key"

SESSION_LAST_ACTIVITY_TS = "last_activity_ts"
SESSION_TIMEOUT_SECONDS = 10 * 60  # 10 minutes idle timeout
# =========================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not set. Setting changes will fail until it is provided.")

MODEL_PLAN = os.environ.get("MODEL_PLAN", "gemini-2.5-pro")
MODEL_NLP = os.environ.get("MODEL_NLP", "gemini-2.5-flash")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


@dataclass
class SettingEntry:
    platform: str
    setting_id: str
    name: str
    category: Optional[str]
    description: Optional[str]
    raw: Dict[str, Any]


SETTINGS_BY_PLATFORM: Dict[str, List[SettingEntry]] = {}


# =========================
# Loading settings DB
# =========================

def load_settings_db() -> Dict[str, List[SettingEntry]]:
    """
    Load settings from all_platforms_classified.json.

    Expected primary format (as in example):

    [
      {
        "platform": "twitterX",
        "image": "after_click__Privacy_and_safety_2025....png",
        "full_image_path": "/generaloutput/twitterX/screenshots/sections/....png",
        "url": "https://x.com/settings/privacy_and_safety",
        "settings": [
           {
             "setting": "Ads preferences",
             "description": "...",
             "state": "not applicable"
           },
           ...
        ],
        "category": "data_collection_tracking"
      },
      ...
    ]
    """
    if not SETTINGS_JSON_PATH.exists():
        raise FileNotFoundError(f"Settings JSON not found at {SETTINGS_JSON_PATH}")

    with SETTINGS_JSON_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    by_platform: Dict[str, List[SettingEntry]] = {}

    # Primary: list of section records with "settings"
    if isinstance(data, list) and data and isinstance(data[0], dict) and "settings" in data[0]:
        for rec in data:
            platform = rec.get("platform") or "unknown"
            url = rec.get("url")
            image = rec.get("image")
            full_image_path = rec.get("full_image_path")
            category = rec.get("category")

            settings_list = rec.get("settings") or []
            for s in settings_list:
                if not isinstance(s, dict):
                    continue
                setting_name = s.get("setting") or s.get("name") or s.get("label")
                if not setting_name:
                    continue
                # slug for id
                setting_id = (
                    "".join(ch.lower() if ch.isalnum() else "_" for ch in str(setting_name))[:80]
                    or "setting"
                )
                desc = s.get("description") or s.get("desc")
                # Combine platform-level and setting-level info in raw
                raw = {
                    "platform": platform,
                    "url": url,
                    "image": image,
                    "full_image_path": full_image_path,
                    "group_category": category,
                    "setting": setting_name,
                    "description": desc,
                    "state": s.get("state"),
                }
                entry = SettingEntry(
                    platform=str(platform),
                    setting_id=str(setting_id),
                    name=str(setting_name),
                    category=str(category) if category is not None else None,
                    description=str(desc) if desc is not None else None,
                    raw=raw,
                )
                by_platform.setdefault(entry.platform, []).append(entry)

        return by_platform

    # Fallback for older / alternate structures
    # (less important, but keeps code robust if file changes)
    by_platform = {}
    if isinstance(data, list):
        for raw in data:
            if not isinstance(raw, dict):
                continue
            platform = raw.get("platform") or raw.get("platform_name") or "unknown"
            name = raw.get("name") or raw.get("setting") or raw.get("label") or raw.get("title") or "setting"
            setting_id = (
                raw.get("setting_id")
                or raw.get("id")
                or raw.get("code")
                or "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name))[:80]
            )
            category = raw.get("category")
            desc = raw.get("description") or raw.get("desc")
            entry = SettingEntry(
                platform=str(platform),
                setting_id=str(setting_id),
                name=str(name),
                category=str(category) if category is not None else None,
                description=str(desc) if desc is not None else None,
                raw=raw,
            )
            by_platform.setdefault(entry.platform, []).append(entry)
    elif isinstance(data, dict):
        for plat, items in data.items():
            if not isinstance(items, list):
                continue
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                name = raw.get("name") or raw.get("setting") or raw.get("label") or raw.get("title") or "setting"
                setting_id = (
                    raw.get("setting_id")
                    or raw.get("id")
                    or raw.get("code")
                    or "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name))[:80]
                )
                category = raw.get("category")
                desc = raw.get("description") or raw.get("desc")
                entry = SettingEntry(
                    platform=str(plat),
                    setting_id=str(setting_id),
                    name=str(name),
                    category=str(category) if category is not None else None,
                    description=str(desc) if desc is not None else None,
                    raw=raw,
                )
                by_platform.setdefault(entry.platform, []).append(entry)

    return by_platform


# =========================
# Utility functions
# =========================
def extract_json(resp, tag: str = "gemini") -> Optional[dict]:
    """
    Extract model text and parse as JSON dict. Returns dict or None.
    """
    raw = extract_model_text(resp)
    if not raw:
        print(f"[{tag}] extract_json: empty text")
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            print(f"[{tag}] extract_json: JSON is not an object (type={type(data)})")
            return None
        return data
    except Exception as e:
        print(f"[{tag}] extract_json: JSON parse error: {e}; raw head={raw[:200]!r}")
        return None

def extract_model_text(resp) -> str:
    """
    Robustly extract text from google-genai responses.
    Prefers resp.text (SDK convenience), then falls back to candidates/parts.
    """
    if resp is None:
        return ""

    # 1) SDK convenience accessor (often the best)
    try:
        t = getattr(resp, "text", None)
        if isinstance(t, str) and t.strip():
            return t.strip()
    except Exception:
        pass

    # 2) Candidates -> content -> parts[*].text
    out = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        for cand in cands[:1]:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            if parts:
                for part in parts:
                    pt = getattr(part, "text", None)
                    if isinstance(pt, str) and pt:
                        out += pt
            # Some SDK versions also have cand.text
            cand_text = getattr(cand, "text", None)
            if isinstance(cand_text, str) and cand_text.strip() and not out.strip():
                out = cand_text
    except Exception:
        pass

    return (out or "").strip()

def debug_print_gemini_response(resp, tag="gemini"):
    try:
        md = getattr(resp, "usage_metadata", None) or getattr(resp, "usage", None)
        print(f"[{tag}] usage_metadata={md!r}")
    except Exception:
        pass

    try:
        pf = getattr(resp, "prompt_feedback", None)
        if pf:
            print(f"[{tag}] prompt_feedback={pf!r}")
    except Exception:
        pass

    try:
        cands = getattr(resp, "candidates", None) or []
        print(f"[{tag}] candidates={len(cands)}")
        if cands:
            c0 = cands[0]
            print(f"[{tag}] finish_reason={getattr(c0,'finish_reason',None)!r}")
            print(f"[{tag}] safety_ratings={getattr(c0,'safety_ratings',None)!r}")
    except Exception as e:
        print(f"[{tag}] cand debug failed: {e!r}")

    try:
        t = getattr(resp, "text", None)
        print(f"[{tag}] resp.text type={type(t)} len={len(t) if isinstance(t,str) else 'n/a'}")
    except Exception:
        pass

def _norm(s: str) -> str:
    """
    Normalize strings for fuzzy matching:
    - Lowercase
    - Treat underscores as spaces
    - Collapse multiple whitespace
    """
    if not s:
        return ""
    s = s.replace("_", " ")
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _token_overlap(a: str, b: str) -> float:
    """
    Very cheap fuzzy-ish score: proportion of shared tokens.
    """
    ta = set(t for t in _norm(a).split() if t)
    tb = set(t for t in _norm(b).split() if t)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / math.sqrt(len(ta) * len(tb))

def _entry_image(entry) -> str:
    """Return image filename from either a raw dict or a SettingEntry object."""
    if isinstance(entry, dict):
        return entry.get("image") or ""
    # SettingEntry: image is stored in raw
    raw = getattr(entry, "raw", {}) or {}
    return raw.get("image") or ""


def _entry_url(entry) -> str:
    """Return the URL string from either a raw dict or a SettingEntry object."""
    if isinstance(entry, dict):
        return entry.get("url") or ""
    # SettingEntry: url is stored in raw
    raw = getattr(entry, "raw", {}) or {}
    return raw.get("url") or ""


def _entry_settings(entry) -> list:
    """
    SettingEntry represents a single setting, so this
    returns a 1-element list using entry.name/description.
    """
    if isinstance(entry, dict):
        return entry.get("settings") or []

    # For SettingEntry, synthesize a single "setting" dict from its fields.
    return [{
        "setting": getattr(entry, "name", ""),
        "description": getattr(entry, "description", ""),
    }]

VALUE_SYNONYMS = {
    "on": {"on", "enable", "enabled", "turn on", "set to on", "yes", "true", "allow"},
    "off": {"off", "disable", "disabled", "turn off", "set to off", "no", "false", "deny"},
    "private": {"private", "make private", "switch to private"},
    "public": {"public", "make public", "switch to public"},
}

def utc_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _load_json_safely(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _atomic_write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def _stable_json_dumps(obj: Any) -> str:
    """
    Deterministic JSON serialization for cache comparisons.
    - sort_keys=True
    - compact separators (stable)
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _read_text_if_exists(path: Path) -> Optional[str]:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None

def cache_write_json_if_changed(path: Path, obj: Any) -> bool:
    """
    Writes JSON only if the *deterministically serialized* content differs.
    Returns True if file was updated, else False.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    new_text = _stable_json_dumps(obj)
    old_text = _read_text_if_exists(path)

    if old_text is not None:
        # normalize whitespace-only diffs by re-parsing old content if possible
        try:
            old_obj = json.loads(old_text)
            old_text_norm = _stable_json_dumps(old_obj)
        except Exception:
            old_text_norm = old_text.strip()
        if old_text_norm == new_text:
            return False

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return True

def build_platform_summaries(
    settings_by_platform: Dict[str, List["SettingEntry"]],
    run_stats_path: Path,
    top_examples: int = 6,
    top_success: int = 6,
) -> Dict[str, Any]:
    """
    Precompute per-platform summary cards for UI.
    This intentionally stays lightweight and purely local.
    """
    run_stats = _load_json_safely(run_stats_path) or {}
    by_setting = (run_stats.get("by_setting") or {}) if isinstance(run_stats, dict) else {}

    out: Dict[str, Any] = {
        "version": 1,
        "updated_at": utc_iso(),
        "platforms": {}
    }

    for plat, entries in (settings_by_platform or {}).items():
        # dedupe by setting_id
        seen = set()
        deduped: List[SettingEntry] = []
        for e in entries or []:
            if e.setting_id in seen:
                continue
            seen.add(e.setting_id)
            deduped.append(e)

        # category counts
        cat_counts: Dict[str, int] = {}
        for e in deduped:
            cat = e.category or "uncategorized"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        # example settings (stable: by setting_id)
        examples = sorted(deduped, key=lambda x: x.setting_id)[:top_examples]
        example_items = [
            {"setting_id": e.setting_id, "name": e.name, "category": e.category, "url": e.raw.get("url")}
            for e in examples
        ]

        # success efficiency from run_stats
        # run_stats keys look like: "<platform>::<setting_id>"
        succ_rows = []
        prefix = f"{plat}::"
        for k, rec in by_setting.items():
            if not isinstance(k, str) or not k.startswith(prefix):
                continue
            if not isinstance(rec, dict):
                continue
            avg = rec.get("avg_clicks_success")
            succ = rec.get("successes", 0)
            if avg is None:
                continue
            succ_rows.append({
                "setting_id": rec.get("setting_id"),
                "name": rec.get("name"),
                "avg_clicks_success": avg,
                "successes": succ,
                "last_success_ts": rec.get("last_success_ts"),
            })

        succ_rows.sort(key=lambda r: (r.get("avg_clicks_success") or 1e9, -(r.get("successes") or 0)))
        top_success_items = succ_rows[:top_success]

        out["platforms"][plat] = {
            "platform": plat,
            "total_settings": len(deduped),
            "category_counts": dict(sorted(cat_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "examples": example_items,
            "top_success_low_clicks": top_success_items,
        }

    return out

def record_run_stats(
    *,
    platform: str,
    setting: SettingEntry,
    target_value: str,
    status: str,
    click_count: int,
    path_log: Optional[dict] = None,
    max_history: int = 50,
):

    """
    Append a run record and update aggregated stats for (platform, setting_id).
    """
    # Only persist successful runs
    if status != "success":
        return
    
    key = f"{platform}::{setting.setting_id}"
    data = _load_json_safely(RUN_STATS_PATH) or {}

    if "version" not in data:
        data["version"] = 1
    data["updated_at"] = utc_iso()
    by_setting = data.setdefault("by_setting", {})

    rec = by_setting.get(key) or {
        "platform": platform,
        "setting_id": setting.setting_id,
        "name": setting.name,
        "runs": 0,
        "successes": 0,
        "avg_clicks_success": None,
        "min_clicks_success": None,
        "max_clicks_success": None,
        "last_success_ts": None,
        "history": [],
    }

    # always append a run record
    rec["runs"] = int(rec.get("runs", 0)) + 1
    run_entry = {
        "ts": utc_iso(),
        "status": status,
        "target_value": target_value,
        "click_count": int(click_count),
        "path": path_log or None,
    }

    hist = rec.get("history") or []
    hist.append(run_entry)
    if len(hist) > max_history:
        hist = hist[-max_history:]
    rec["history"] = hist

    # update success aggregates
    if status == "success":
        rec["successes"] = int(rec.get("successes", 0)) + 1
        rec["last_success_ts"] = run_entry["ts"]

        # update min/max/avg clicks for successful runs
        clicks = int(click_count)
        mn = rec.get("min_clicks_success")
        mx = rec.get("max_clicks_success")
        rec["min_clicks_success"] = clicks if mn is None else min(int(mn), clicks)
        rec["max_clicks_success"] = clicks if mx is None else max(int(mx), clicks)

        # avg update from history of successes (bounded) – simple recompute
        succ_clicks = [h["click_count"] for h in hist if h.get("status") == "success"]
        if succ_clicks:
            rec["avg_clicks_success"] = round(sum(succ_clicks) / len(succ_clicks), 3)

    by_setting[key] = rec
    data["by_setting"] = by_setting
    _atomic_write_json(RUN_STATS_PATH, data)

def infer_target_value_from_text(user_text: str) -> Optional[str]:
    """
    Better intent inference than normalize_target_value() for tricky cases.
    Priority: "hide/disable/turn off" overrides presence of the word "public".
    """
    t = (user_text or "").lower()

    # Strong negative intent -> OFF/PRIVATE
    if any(w in t for w in ["turn off", "disable", "stop", "hide", "don't show", "do not show", "less visible"]):
        # If talking about profile visibility/audience, "private" is closer than "off"
        if "profile" in t or "public" in t or "visibility" in t:
            return "private"
        return "off"

    # Otherwise use your existing synonym logic
    return normalize_target_value(user_text)

def normalize_target_value(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    if not t:
        return None
    # direct
    for canon, alts in VALUE_SYNONYMS.items():
        if t == canon or t in alts:
            return canon
    # phrase containment
    for canon, alts in VALUE_SYNONYMS.items():
        for a in alts:
            if a in t:
                return canon
    return None


def parse_nl_request(user_text: str) -> Dict[str, Optional[str]]:
    """
    Extract platform, target_value, setting_query from a natural language message.
    """
    text = (user_text or "").strip()
    lower = text.lower()

    # target_value: look for "to X", "set X", "enable/disable", etc.
    target_value = None

    m = re.search(r"\bto\s+(on|off|private|public|enabled|disabled)\b", lower)
    if m:
        target_value = normalize_target_value(m.group(1))
        # remove the "to X" part from query
        lower_wo = re.sub(r"\bto\s+" + re.escape(m.group(1)) + r"\b", " ", lower)
    else:
        lower_wo = lower

    if not target_value:
        target_value = infer_target_value_from_text(user_text)


    # platform: if user types "on instagram", "for reddit", etc.
    platform_hint = None
    m2 = re.search(r"\b(on|in|for)\s+([a-zA-Z0-9_]+)\b", lower)
    if m2:
        platform_hint = m2.group(2)

    # setting_query: remove leading verbs that are noise
    setting_query = lower_wo
    setting_query = re.sub(r"^(please\s+)?(change|set|turn|make|update|enable|disable)\s+", "", setting_query).strip()
    setting_query = re.sub(r"\b(my|the)\b", " ", setting_query)
    setting_query = re.sub(r"\s+", " ", setting_query).strip()

    return {
        "platform_hint": platform_hint,
        "target_value": target_value,
        "setting_query": setting_query or None,
    }

def score_setting_candidate(entry: SettingEntry, query: str) -> float:
    q = _norm(query)
    name = _norm(entry.name)
    desc = _norm(entry.description or "")

    score = 0.0

    # strong matches
    if q == name:
        score += 50
    if q and q in name:
        score += 25
    if q and q in desc:
        score += 10

    # token overlap
    score += 15 * _token_overlap(q, name)
    score += 5 * _token_overlap(q, desc)

    # keyword boosts 
    boosts = ["follow", "private", "public", "ads", "tracking", "tag", "mention", "message", "email", "location"]
    for b in boosts:
        if b in q and b in name:
            score += 3

    return score

def export_all_settings_snapshot() -> Dict[str, List[Dict[str, Any]]]:
    snapshot: Dict[str, List[Dict[str, Any]]] = {}
    for plat, entries in SETTINGS_BY_PLATFORM.items():
        # dedupe by setting_id
        seen = set()
        items = []
        for e in entries:
            if e.setting_id in seen:
                continue
            seen.add(e.setting_id)
            items.append({
                "setting_id": e.setting_id,
                "name": e.name,
                "category": e.category,
                "description": e.description,
                "url": e.raw.get("url"),
            })
        snapshot[plat] = sorted(items, key=lambda d: d["setting_id"])
    return snapshot

def find_setting_candidates(platform: str, query: str, limit: int = 8) -> List[SettingEntry]:
    settings = list_settings_for_platform(platform) or []
    if not settings or not query:
        return []

    scored = []
    for s in settings:
        sc = score_setting_candidate(s, query)
        if sc > 1.0:
            scored.append((sc, s))

    scored.sort(key=lambda x: x[0], reverse=True)

    # dedupe by setting_id while keeping rank order
    seen = set()
    out = []
    for _, s in scored:
        if s.setting_id in seen:
            continue
        seen.add(s.setting_id)
        out.append(s)
        if len(out) >= limit:
            break
    return out

def active_platform_label() -> str:
    plat = cl.user_session.get(SESSION_ACTIVE_PLATFORM)
    return plat if plat else "None"

def active_platform_banner() -> str:
    return f"**Active platform:** `{active_platform_label()}`\n\n"

def change_platform_action() -> cl.Action:
    return cl.Action(
        name="change_platform",
        payload={},
        label="Change platform"
    )

def set_gemini_key_action() -> cl.Action:
    return cl.Action(
        name="set_gemini_key",
        payload={},
        label="Set Gemini API key"
    )

def end_session_action() -> cl.Action:
    return cl.Action(
        name="end_session",
        payload={},
        label="End session (wipe key)"
    )

async def _nlp_disabled_notice():
    await cl.Message(
        content=active_platform_banner()
        + "NLP mode is disabled for the demo. Use **Browse settings** or the `change ...` command.",
        actions=[browse_settings_action(), change_platform_action(), set_gemini_key_action(), end_session_action()],
    ).send()

async def present_candidates(platform: str, query: str, candidates: List[SettingEntry], target_value: Optional[str]):
    if not ENABLE_NLP:
        await cl.Message(
            content=active_platform_banner()
            + "NLP selection is disabled for the demo. Use **Browse settings** instead.",
            actions=[browse_settings_action(), change_platform_action(), set_gemini_key_action(), end_session_action()],
        ).send()
        return

    # Keep only top 3
    candidates = candidates[:3]

    if not candidates:
        await cl.Message(
            content=(
                f"I couldn’t find likely matches for **{query}** on `{platform}`.\n\n"
                "Try rephrasing (e.g., include the exact label you see in the UI)."
            )
        ).send()
        return

    cl.user_session.set(SESSION_PENDING_PLATFORM_KEY, platform)
    cl.user_session.set(SESSION_PENDING_VALUE_KEY, target_value)

    # Store candidates in session for lookup
    cl.user_session.set(
        SESSION_PENDING_KEY,
        {c.setting_id: {"name": c.name, "category": c.category, "description": c.description} for c in candidates}
    )

    actions = []
    for i, c in enumerate(candidates, start=1):
        actions.append(
            cl.Action(
                name="pick_setting",
                payload={"setting_id": c.setting_id, "platform": platform},
                label=f"{i}. {c.name}",
            )
        )

    # Add "none of these"
    actions.append(
        cl.Action(
            name="none_match",
            payload={"platform": platform, "query": query},
            label="None of these",
        )
    )

    preview_lines = []
    for i, c in enumerate(candidates, start=1):
        preview_lines.append(
            f"{i}) **{c.name}**  \n"
            f"_{(c.description or '')[:160]}_  \n"
            f"`id: {c.setting_id}`"
        )

    await cl.Message(
        content=active_platform_banner() + (
            f"On `{platform}`, I found these possible matches for: **{query}**\n\n"
            + "\n\n".join(preview_lines)
            + "\n\nPick the correct one (or choose **None of these** to retype):"
        ),
        actions=[change_platform_action(), *actions],
    ).send()

@cl.action_callback("set_gemini_key")
async def on_set_gemini_key(action: cl.Action):
    touch_session_activity()
    cl.user_session.set(SESSION_AWAITING_GEMINI_KEY, True)
    await cl.Message(
        content=(
            "Paste your **GEMINI_API_KEY** in your next message.\n\n"
            "- It will be kept **only in memory for this session**.\n"
            "- It will be **wiped automatically** after idle timeout or when you click **End session**."
        ),
        actions=[end_session_action(), change_platform_action()],
    ).send()

@cl.action_callback("end_session")
async def on_end_session(action: cl.Action):
    touch_session_activity()
    wipe_session_gemini()
    # Optional: also clear pending state so the session truly resets
    cl.user_session.set(SESSION_PENDING_KEY, None)
    cl.user_session.set(SESSION_PENDING_PLATFORM_KEY, None)
    cl.user_session.set(SESSION_PENDING_VALUE_KEY, None)
    cl.user_session.set(SESSION_PENDING_CONFIRM, None)
    cl.user_session.set("final_setting_to_change", None)
    cl.user_session.set("pending_nl_query", None)
    cl.user_session.set(SESSION_PENDING_NL_TEXT, None)

    await cl.Message(
        content="Session cleared. ✅ Gemini key wiped from memory.",
        actions=[set_gemini_key_action(), change_platform_action()],
    ).send()

@cl.action_callback("change_platform")
async def on_change_platform(action: cl.Action):
    # Show the platform picker without requiring any user text
    await prompt_pick_platform()

@cl.action_callback("none_match")
async def on_none_match(action: cl.Action):
    if not ENABLE_NLP:
        await _nlp_disabled_notice()
        return
    payload = action.payload or {}
    platform = payload.get("platform")
    query = payload.get("query")

    # Clear pending selection state
    cl.user_session.set(SESSION_PENDING_KEY, None)
    cl.user_session.set(SESSION_PENDING_PLATFORM_KEY, None)
    cl.user_session.set(SESSION_PENDING_VALUE_KEY, None)

    await cl.Message(
        content=active_platform_banner() + (
            f"Got it — none matched for `{platform}` / **{query}**.\n\n"
            "Please rephrase what you want to change (you can be more specific, or use the exact label you see)."
        ),
        actions=[set_gemini_key_action(), end_session_action(), change_platform_action()]
    ).send()


@cl.action_callback("pick_setting")
async def on_pick_setting(action: cl.Action):
    if not ENABLE_NLP:
        await _nlp_disabled_notice()
        return
    payload = action.payload or {}
    setting_id = payload.get("setting_id")
    platform = payload.get("platform") or cl.user_session.get(SESSION_PENDING_PLATFORM_KEY)

    if not setting_id or not platform:
        await cl.Message(content="Missing selection context (setting/platform). Please try again.").send()
        return

    setting = resolve_setting(platform, setting_id)
    if not setting:
        await cl.Message(content="Could not resolve that setting in the DB. Please try again.").send()
        return
    
    infer_map = cl.user_session.get("inferred_by_setting") or {}
    picked = infer_map.get(setting.setting_id) or {}
    if picked.get("leaf_hint"):
        cl.user_session.set("inferred_leaf_hint", picked["leaf_hint"])
    if picked.get("target_value"):
        cl.user_session.set("inferred_target_value", picked["target_value"])

    print("[UI DEBUG] after pick_setting -> inferred_leaf_hint:", repr(cl.user_session.get("inferred_leaf_hint")))
    print("[UI DEBUG] after pick_setting -> inferred_target_value:", repr(cl.user_session.get("inferred_target_value")))

    # Store pending confirmation (setting inferred from user intent)
    cl.user_session.set(SESSION_PENDING_CONFIRM, {"platform": platform, "setting_id": setting.setting_id})

    suggested = cl.user_session.get(SESSION_PENDING_VALUE_KEY)

    actions = [
        cl.Action(name="confirm_setting", payload={"confirm": True}, label="Confirm"),
        cl.Action(name="confirm_setting", payload={"confirm": False}, label="Cancel"),
        change_platform_action(),
        set_gemini_key_action(),
        end_session_action(),
    ]

    hint_line = f"\n\nSuggested state from your message: `{suggested}`" if suggested else ""

    await cl.Message(
        content=active_platform_banner() + (
            "I think you meant this setting:\n\n"
            f"**{setting.name}** (`{setting.setting_id}`)\n"
            f"{hint_line}\n\n"
            "Confirm this is correct?"
        ),
        actions=actions
    ).send()


async def ask_for_platform(pending_query: str, pending_value: Optional[str]):
    # Store pending intent
    cl.user_session.set("pending_nl_query", {"setting_query": pending_query, "target_value": pending_value})

    # Offer buttons for known platforms
    plats = list_platforms()
    actions = [
        cl.Action(name="pick_platform", payload={"platform": p}, label=p)
        for p in plats[:10]  # safety cap
    ]

    await cl.Message(
        content="Which platform is this for?",
        actions=actions
    ).send()

async def prompt_pick_platform():
    plats = list_platforms()
    actions = [
        cl.Action(
            name="set_platform",
            payload={"platform": p},
            label=p
        )
        for p in plats[:12]  # safety cap
    ]
    await cl.Message(
        content="Session controls (be sure to set your Gemini API key before starting):",
        actions=[set_gemini_key_action(), end_session_action()],
    ).send()

    await cl.Message(
        content="Pick a platform to work on:",
        actions=[*actions],
    ).send()



@cl.action_callback("set_platform")
async def on_set_platform(action: cl.Action):
    payload = action.payload or {}
    plat = payload.get("platform")
    if not plat:
        await cl.Message(content="Missing platform. Try again.").send()
        return

    cl.user_session.set(SESSION_ACTIVE_PLATFORM, plat)

    pending_text = cl.user_session.get(SESSION_PENDING_NL_TEXT)
    cl.user_session.set(SESSION_PENDING_NL_TEXT, None)

    if pending_text:
        if ENABLE_NLP:
            await cl.Message(
                content=active_platform_banner() + f"Platform set to `{plat}`. Continuing with your request…",
                actions=[browse_settings_action(), set_gemini_key_action(), end_session_action(), change_platform_action()],
            ).send()
            await handle_platform_scoped_nl(plat, pending_text)
            return

        # Demo mode: ignore queued NL text and steer user to browse/commands
        await cl.Message(
            content=active_platform_banner()
            + f"Platform set to `{plat}`.\n\n"
            + "Demo mode: please use **Browse settings** (buttons) or the `change ...` command.",
            actions=[browse_settings_action(), set_gemini_key_action(), end_session_action(), change_platform_action()],
        ).send()
        return

    await cl.Message(
        content=active_platform_banner()
        + f"Platform set to `{plat}`.\n\n"
        + "Next: click **Browse settings** to pick a setting, or use the `change ...` command.",
        actions=[browse_settings_action(), set_gemini_key_action(), end_session_action(), change_platform_action()],
    ).send()

@cl.action_callback("confirm_setting")
async def on_confirm_setting(action: cl.Action):
    if not ENABLE_NLP:
        await _nlp_disabled_notice()
        return
    payload = action.payload or {}
    confirm = payload.get("confirm")

    pending = cl.user_session.get(SESSION_PENDING_CONFIRM)
    cl.user_session.set(SESSION_PENDING_CONFIRM, None)

    if not pending:
        await cl.Message(content="No pending setting to confirm. Please try again.").send()
        return

    platform = pending["platform"]
    setting = resolve_setting(platform, pending["setting_id"])
    if not setting:
        await cl.Message(content="Could not resolve that setting. Please try again.").send()
        return
    
    if not confirm:
        # Cancel: allow selecting a platform again (as requested)
        await cl.Message(
            content=active_platform_banner() + "Canceled. Pick a platform to continue.",
            actions=[change_platform_action()]
        ).send()
        await prompt_pick_platform()
        return

    suggested_value = cl.user_session.get("inferred_target_value")
    print("[UI DEBUG] inferred_target_value in session:", repr(suggested_value))
    print("[UI DEBUG] inferred_leaf_hint in session:", repr(cl.user_session.get("inferred_leaf_hint")))

    # If Gemini inferred a target state, confirm it first
    if suggested_value in ("on", "off", "private", "public"):
        actions = [
            cl.Action(name="confirm_value", payload={"confirm": True}, label=f"Confirm: {suggested_value}"),
            cl.Action(name="confirm_value", payload={"confirm": False}, label="Choose different value"),
            change_platform_action(),
            set_gemini_key_action(),
            end_session_action(),
        ]
        cl.user_session.set("final_setting_to_change", {"platform": platform, "setting_id": setting.setting_id})

        await cl.Message(
            content=active_platform_banner()
            + f"Confirmed setting: **{setting.name}** (`{setting.setting_id}`)\n\n"
            + f"I think you want to set it to: **{suggested_value}**.\n\n"
            + "Confirm?",
            actions=actions
        ).send()
        return

    # Otherwise, fall back to full value picker
    actions = [
        cl.Action(name="pick_value", payload={"value": "on"}, label="On"),
        cl.Action(name="pick_value", payload={"value": "off"}, label="Off"),
        cl.Action(name="pick_value", payload={"value": "private"}, label="Private"),
        cl.Action(name="pick_value", payload={"value": "public"}, label="Public"),
        cl.Action(name="pick_value", payload={"value": "cancel"}, label="Cancel"),
        change_platform_action(),
        set_gemini_key_action(),
        end_session_action(),
    ]
    cl.user_session.set("final_setting_to_change", {"platform": platform, "setting_id": setting.setting_id})

    await cl.Message(
        content=active_platform_banner()
        + f"Confirmed: **{setting.name}** (`{setting.setting_id}`)\n\n"
        + "What do you want to change it to?",
        actions=actions
    ).send()
    return

@cl.action_callback("confirm_value")
async def on_confirm_value(action: cl.Action):
    payload = action.payload or {}
    confirm = payload.get("confirm")

    suggested_value = cl.user_session.get("inferred_target_value")

    if not confirm:
        # Show the full value picker
        actions = [
            cl.Action(name="pick_value", payload={"value": "on"}, label="On"),
            cl.Action(name="pick_value", payload={"value": "off"}, label="Off"),
            cl.Action(name="pick_value", payload={"value": "private"}, label="Private"),
            cl.Action(name="pick_value", payload={"value": "public"}, label="Public"),
            cl.Action(name="pick_value", payload={"value": "cancel"}, label="Cancel"),
            change_platform_action(),
        ]
        await cl.Message(
            content=active_platform_banner() + "Choose the value you want:",
            actions=actions
        ).send()
        return

    # Confirmed suggested value -> execute
    if suggested_value not in ("on", "off", "private", "public"):
        await cl.Message(content="No suggested value found. Please choose manually.").send()
        return

    pending = cl.user_session.get("final_setting_to_change")
    if not pending:
        await cl.Message(content=f"No pending setting selection found. Please try again. Active platform: {cl.user_session.get('active_platform')}").send()
        return

    platform = pending["platform"]
    setting = resolve_setting(platform, pending["setting_id"])
    cl.user_session.set("final_setting_to_change", None)

    if not setting:
        await cl.Message(content="Could not resolve the pending setting. Please try again.").send()
        return

    await cl.Message(
        content=active_platform_banner()
        + f"Ok — changing **{setting.name}** on `{platform}` to `{suggested_value}`…"
    ).send()

    
    inferred_leaf_hint = sanitize_leaf_hint(cl.user_session.get("inferred_leaf_hint"), setting.name)

    result = await cl.make_async(apply_setting_change_sync)(
        platform,
        setting,
        suggested_value,
        leaf_hint=inferred_leaf_hint
    )
    append_change(result)

    if result.get("status") == "success":
        await cl.Message(
            content=active_platform_banner()
            + f"✅ Success.\n\nResult details: {result.get('details')}\n\n"
            + "You can type another setting to change on this platform, or click **Change platform**.",
            actions=[set_gemini_key_action(), end_session_action(), change_platform_action()]
        ).send()
    else:
        await cl.Message(
            content=active_platform_banner()
            + f"Result: status = `{result.get('status')}`\nDetails: {result.get('details')}",
            actions=[set_gemini_key_action(), end_session_action(), change_platform_action()]
        ).send()


ACTION_PHRASES = [
    "turn on", "turn off", "switch on", "switch off",
    "enable", "disable", "make", "set", "change", "stop",
    "hide", "show", "allow", "disallow", "block", "unblock",
    "mute", "unmute",
]

STATE_WORDS = {"on", "off", "private", "public", "enabled", "disabled", "yes", "no"}

GENERIC_HINTS = {
    "account", "accounts", "settings", "privacy", "security",
    "profile", "data", "activity", "preferences", "options",
}

def is_generic_hint(h: Optional[str]) -> bool:
    if not h:
        return True
    hn = _norm(h)
    if not hn:
        return True
    if hn in GENERIC_HINTS:
        return True
    # single generic token
    toks = hn.split()
    if len(toks) == 1 and toks[0] in GENERIC_HINTS:
        return True
    return False

def sanitize_leaf_hint(hint: Optional[str], fallback: str) -> str:
    """
    Ensure we never use a garbage hint like 'account' for coord-fallback or label matching.
    """
    if hint and not is_generic_hint(hint):
        return hint
    return fallback

def resolve_visible_leaf_label(page: Page, leaf_hint: Optional[str], fallback: str) -> str:
    """
    Try to map a leaf_hint to an actually visible label on the CURRENT page.
    If not visible, return leaf_hint as-is (or fallback).
    """
    if not leaf_hint:
        return fallback

    # Prefer actionable label match (toggle/checkbox nearby), else any label-like match
    matched = (
        best_actionable_label_match_on_page(page, leaf_hint)
        or best_label_match_on_page(page, leaf_hint)
    )
    return matched or leaf_hint or fallback


def derive_leaf_hint_from_text(user_text: str) -> Optional[str]:
    """
    Platform-agnostic: derive a *hint phrase* from user text.
    This is NOT expected to exactly match a UI label.
    """
    if not user_text:
        return None

    t = user_text.strip()

    # Prefer quoted text if present: "Protect your posts"
    m = re.search(r"['\"]([^'\"]{3,80})['\"]", t)
    if m:
        return m.group(1).strip()

    low = t.lower()

    # Remove common leading action phrases
    for a in ACTION_PHRASES:
        if low.startswith(a + " "):
            t = t[len(a):].strip()
            low = t.lower()
            break

    # Remove trailing "to <state>"
    t = re.sub(r"\bto\s+(on|off|private|public|enabled|disabled)\b.*$", "", t, flags=re.I).strip()

    # Token cleanup: drop platform-ish and state-ish words
    toks = re.findall(r"[a-zA-Z0-9]+", t)
    kept = []
    for tok in toks:
        tl = tok.lower()
        if tl in STATE_WORDS:
            continue
        if tl in {"my", "the", "a", "an", "for", "on", "in", "at", "from", "of", "and", "or"}:
            continue
        kept.append(tok)

    # Keep a short phrase (2–7 tokens) as the hint
    if len(kept) >= 2:
        phrase = " ".join(kept[:7]).strip()
        return None if is_generic_hint(phrase) else phrase
    if kept:
        one = kept[0].strip()
        return None if is_generic_hint(one) else one

    return None

def best_label_match_on_page(page: Page, hint: str, max_scan: int = 120) -> Optional[str]:
    """
    Find the best visible label-like text on the page that matches the hint.
    Returns the matched label text (string) or None.
    """
    hint_norm = _norm(hint)
    if not hint_norm:
        return None
    hint_tokens = set(hint_norm.split())

    # Scan likely label nodes (headings, labels, spans, divs with text)
    # Keep it conservative to avoid massive DOM scanning.
    loc = page.locator("label,span,div,p,button,a,h1,h2,h3")
    n = min(loc.count(), max_scan)

    best = None
    best_score = 0.0

    for i in range(n):
        try:
            txt = loc.nth(i).inner_text().strip()
        except Exception:
            continue
        if not txt or len(txt) > 80:
            continue
        txt_norm = _norm(txt)
        if not txt_norm:
            continue
        tokens = set(txt_norm.split())
        if not tokens:
            continue

        # Score by token overlap + substring bonus
        overlap = len(tokens & hint_tokens) / max(1, len(hint_tokens))
        score = overlap
        if hint_norm in txt_norm or txt_norm in hint_norm:
            score += 0.5

        if score > best_score:
            best_score = score
            best = txt

    # Require some minimum similarity so we don't click random labels
    if best_score >= 0.25:
        return best
    return None


def prefilter_platform_settings(platform: str, user_text: str, k: int = 50) -> List[SettingEntry]:
    """
    Cheap local filter to reduce the number of settings we send to Gemini.
    """
    items = list_settings_for_platform(platform) or []
    q = _norm(user_text)

    scored = []
    for s in items:
        name = _norm(s.name)
        desc = _norm(s.description or "")
        score = 0.0
        if q and q in name:
            score += 25
        if q and q in desc:
            score += 10
        score += 10 * _token_overlap(q, name)
        score += 3 * _token_overlap(q, desc)
        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:k]]

def gemini_pick_candidates_for_platform(platform: str, user_text: str, candidates: List[SettingEntry]) -> Dict[str, Any]:
    """
    Given a platform and a reduced candidate list, ask Gemini to pick the best 1–3 setting_ids
    and infer target_value if present.

    Uses response_mime_type="application/json" and a single JSON parse path.
    Keeps retries/backoff and a minimal salvage fallback if model output is malformed.
    """
    client = get_gemini_client()
    if not client:
        return {"setting_ids": [], "leaf_hint": None, "target_value": None}

    # Limit candidates to reduce token load
    candidates = candidates[:20]

    # Compact candidate list for prompt (truncate descriptions!)
    cand_payload = [
        {
            "setting_id": c.setting_id,
            "name": c.name,
            "description": (c.description or "")[:80],
            "category": c.category or "",
        }
        for c in candidates
    ]

    system_instruction = (
        "You map a natural language privacy-setting request to database entries.\n"
        "You MUST choose only from the provided CANDIDATES list.\n\n"
        "Return ONLY a single JSON object. No markdown. No code fences. No extra text.\n"
        "JSON schema:\n"
        "{\n"
        '  "setting_ids": ["id1","id2","id3"],\n'
        '  "leaf_hint": string|null,\n'
        '  "target_value": "on"|"off"|"private"|"public"|null,\n'
        '  "reason": "<short>"\n'
        "}\n"
        "Rules:\n"
        "- Choose up to 3 setting_ids from CANDIDATES.\n"
        "- If the user implies enable/disable/private/public, set target_value; else null.\n"
        "- If nothing matches, return setting_ids: [].\n"
        "- Output MUST be valid JSON.\n"
    )

    prompt = (
        f"PLATFORM: {platform}\n"
        f"USER_TEXT: {user_text}\n\n"
        "CANDIDATES:\n" + json.dumps(cand_payload, ensure_ascii=False)
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        max_output_tokens=220,
        response_mime_type="application/json",
    )

    last_err = None
    last_raw = ""

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL_NLP,
                contents=[Content(role="user", parts=[Part(text=prompt)])],
                config=config,
            )
            debug_print_gemini_response(resp, tag="gemini_pick_candidates")
        except Exception as e:
            last_err = e
            print(f"[gemini_pick_candidates] model error attempt {attempt+1}: {e}")
            sleep_with_jitter(attempt)
            continue

        raw = (extract_model_text(resp) or "").strip()
        last_raw = raw

        if not raw:
            print(f"[gemini_pick_candidates] empty output attempt {attempt+1}; backing off")
            last_err = "empty_output"
            sleep_with_jitter(attempt)
            continue

        # Primary: strict JSON parse (should succeed with response_mime_type)
        data = None
        try:
            data = json.loads(raw)
        except Exception as e:
            last_err = e
            print(f"[gemini_pick_candidates] JSON parse failed attempt {attempt+1}: {e}; raw head={raw[:200]!r}")
            sleep_with_jitter(attempt)
            continue

        if not isinstance(data, dict):
            last_err = "non_dict_json"
            print(f"[gemini_pick_candidates] non-dict JSON attempt {attempt+1}: type={type(data)}")
            sleep_with_jitter(attempt)
            continue

        setting_ids = data.get("setting_ids") or []
        target_value = data.get("target_value")
        leaf_hint = data.get("leaf_hint")

        # Validate IDs against candidates
        valid_ids = {c["setting_id"] for c in cand_payload}
        cleaned = []
        for sid in setting_ids:
            if sid in valid_ids and sid not in cleaned:
                cleaned.append(sid)

        return {"setting_ids": cleaned[:3], "leaf_hint": leaf_hint, "target_value": target_value}

    # Exhausted retries
    print("[gemini_pick_candidates] exhausted retries; last_err:", last_err)

    # Minimal salvage: if output is truncated but contains a setting_ids array
    raw = (last_raw or "").strip()
    if raw:
        try:
            m_ids = re.search(r'"setting_ids"\s*:\s*\[([^\]]*)\]', raw, flags=re.S)
            if m_ids:
                inside = m_ids.group(1)
                ids = re.findall(r'"([^"]+)"', inside)
                valid_ids = {c["setting_id"] for c in cand_payload}
                cleaned = [sid for sid in ids if sid in valid_ids]
                return {"setting_ids": cleaned[:3], "leaf_hint": None, "target_value": None}
        except Exception:
            pass

    return {"setting_ids": [], "leaf_hint": None, "target_value": None}
    
async def handle_platform_scoped_nl(platform: str, user_text: str):
    # Path tracking metadata for run logs
    cl.user_session.set("last_entrypoint", "nl")

    # Prefilter to top ~50 for prompt size
    pre = prefilter_platform_settings(platform, user_text, k=50)

    pick = gemini_pick_candidates_for_platform(platform, user_text, pre)
    setting_ids = pick.get("setting_ids") or []
    cl.user_session.set("last_candidate_source", "gemini" if setting_ids else "deterministic")
    target_value = pick.get("target_value")

    # If Gemini didn't infer target_value, infer it deterministically from user text
    if not target_value:
        target_value = infer_target_value_from_text(user_text)

    inferred_leaf_hint = pick.get("leaf_hint") or derive_leaf_hint_from_text(user_text)
    cl.user_session.set("last_leaf_hint_source", "gemini" if pick.get("leaf_hint") else "derived")

    if not inferred_leaf_hint:
        inferred_leaf_hint = (pre[0].name if pre else None) or user_text
        cl.user_session.set("last_leaf_hint_source", "setting_name" if pre else "derived")


    print("\n[NLP DEBUG]")
    print("  platform:", platform)
    print("  user_text:", repr(user_text))
    print("  gemini_setting_ids:", setting_ids)
    print("  gemini_leaf_hint:", repr(pick.get("leaf_hint")))
    print("  derived_leaf_hint:", repr(inferred_leaf_hint))
    print("  gemini_target_value:", repr(pick.get("target_value")))
    print("  derived_target_value:", repr(target_value))
    print("[/NLP DEBUG]\n")

    cl.user_session.set("inferred_leaf_hint", inferred_leaf_hint)
    cl.user_session.set("inferred_target_value", target_value)


    # Store inferred hints per returned setting_id so selection can pick the right one
    infer_map = {}
    for sid in setting_ids:
        infer_map[sid] = {
            "leaf_hint": inferred_leaf_hint,
            "target_value": target_value
        }
    cl.user_session.set("inferred_by_setting", infer_map)


    if not setting_ids:
        # Fallback: deterministic candidate search within this platform
        fallback = find_setting_candidates(platform, user_text, limit=3)
        if fallback:
            await present_candidates(platform, user_text, fallback, target_value=None)
            return

        await cl.Message(
            content=active_platform_banner() + (
                f"I couldn’t find likely matches for **{user_text}** on `{platform}`.\n\n"
                "Try rephrasing or use a more specific phrase from the settings page."
            ),
            actions=[change_platform_action()]
        ).send()
        return



    # Resolve SettingEntry objects in the order Gemini returned
    id_map = {s.setting_id: s for s in pre}
    candidates = [id_map[sid] for sid in setting_ids if sid in id_map]

    await present_candidates(platform, user_text, candidates, target_value)


@cl.action_callback("pick_platform")
async def on_pick_platform(action: cl.Action):
    if not ENABLE_NLP:
        await _nlp_disabled_notice()
        return
    payload = action.payload or {}
    plat = payload.get("platform")

    pending = cl.user_session.get("pending_nl_query") or {}
    setting_query = pending.get("setting_query")
    target_value = pending.get("target_value")

    cl.user_session.set("pending_nl_query", None)

    if not plat or not setting_query:
        await cl.Message(content="Missing context. Please retype your request.").send()
        return

    candidates = find_setting_candidates(plat, setting_query, limit=8)
    await present_candidates(plat, setting_query, candidates, target_value)

@cl.action_callback("pick_value")
async def on_pick_value(action: cl.Action):
    if not ENABLE_NLP:
        await _nlp_disabled_notice()
        return
    payload = action.payload or {}
    value = payload.get("value")

    if value == "cancel":
        cl.user_session.set("final_setting_to_change", None)
        await cl.Message(
            content=active_platform_banner() + "Canceled. Pick a platform to continue.",
            actions=[change_platform_action()]
        ).send()
        await prompt_pick_platform()
        return

    # Normalize (handles enable/disable etc if you ever pass them)
    target_value = normalize_target_value(value) or value

    pending = cl.user_session.get("final_setting_to_change")
    if not pending:
        await cl.Message(content="No pending setting selection found. Please try again.").send()
        return

    platform = pending["platform"]
    setting = resolve_setting(platform, pending["setting_id"])
    cl.user_session.set("final_setting_to_change", None)

    if not setting:
        await cl.Message(content="Could not resolve the pending setting. Please try again.").send()
        return

    await cl.Message(
        content=f"Ok — changing **{setting.name}** on `{platform}` to `{target_value}`…"
    ).send()

    result = await cl.make_async(apply_setting_change_sync)(
        platform,
        setting,
        target_value,
        leaf_hint=sanitize_leaf_hint(cl.user_session.get("inferred_leaf_hint"), setting.name)
    )
    append_change(result)

    await cl.Message(
        content=active_platform_banner() + f"Result: status = `{result.get('status')}`\nDetails: {result.get('details')}",
        actions=[change_platform_action()]
    ).send()

    if result.get("status") == "success":
        await cl.Message(
            content=active_platform_banner()
            + "✅ Success. You can type another setting to change on this platform, or click **Change platform**.",
            actions=[change_platform_action()]
        ).send()




def list_platforms() -> List[str]:
    return sorted(SETTINGS_BY_PLATFORM.keys())


def list_settings_for_platform(platform: str) -> List[SettingEntry]:
    return SETTINGS_BY_PLATFORM.get(platform, [])


def find_platform_alias(platform_name: str) -> Optional[str]:
    """Very simple aliasing: case-insensitive, partial match."""
    if not platform_name:
        return None
    target = platform_name.strip().lower()
    # exact
    for plat in SETTINGS_BY_PLATFORM.keys():
        if plat.lower() == target:
            return plat
    # partial
    for plat in SETTINGS_BY_PLATFORM.keys():
        if target in plat.lower():
            return plat
    return None

def score_entry_for_setting(entry, section_query: str, leaf_hint: str | None) -> float:
    """
    Higher score = more relevant for this command.
    Works with either raw dicts or SettingEntry objects.
    """
    score = 0.0

    raw_sq = (section_query or "").strip()
    sq = _norm(section_query)          # e.g. "tags and mentions"
    lh = _norm(leaf_hint) if leaf_hint else None

    # 1) Work over the "settings" list for this entry.
    #    For SettingEntry, this is a synthetic list with one element (name/description).
    settings = _entry_settings(entry)
    for s in settings:
        name = _norm(s.get("setting") or "")
        desc = _norm(s.get("description") or "")

        # Leaf-level match (if we have a leaf_hint)
        if lh:
            if lh == name:
                score += 10.0  # exact leaf match
            elif lh in name:
                score += 6.0   # substring leaf match
            elif lh in desc:
                score += 4.0   # substring in description
            else:
                score += 2.0 * _token_overlap(lh, name)

        # Section-level match (section_query)
        if sq:
            if sq == name:
                score += 5.0   # exact section match
            elif sq in name:
                score += 3.0
            elif sq in desc:
                score += 2.0
            else:
                score += 1.0 * _token_overlap(sq, name)

    # 2) URL-based tie-breakers + section-id hints
    url = _entry_url(entry)
    url_l = url.lower()
    path = url.split("://", 1)[-1]  # strip scheme if present
    path_part = path.split("/", 1)[-1]
    depth = path_part.count("/")
    if depth > 0:
        score += min(depth, 3) * 0.5  # /settings/.../... beats /settings/...

    # Extra boost: raw section id in URL, e.g. "tags_and_mentions"
    if raw_sq:
        rs = raw_sq.lower()
        if rs in url_l:
            score += 8.0
        # also allow the normalized version with underscores (just in case)
        rs2 = _norm(raw_sq).replace(" ", "_")
        if rs2 and rs2 in url_l and rs2 != rs:
            score += 4.0

    # 3) Image filename hints 
    img = _entry_image(entry).lower()
    if raw_sq:
        rs = raw_sq.lower()
        if rs in img:
            score += 6.0
        rs2 = _norm(raw_sq).replace(" ", "_")
        if rs2 and rs2 in img and rs2 != rs:
            score += 3.0

    # 4) Keyword hints in the URL for the leaf (if we have one)
    if lh:
        for token in lh.split():
            token = token.strip()
            if token and token in path_part:
                score += 0.5

    return score

def format_settings_table(settings: List[SettingEntry], max_rows: int = 25) -> str:
    if not settings:
        return "_No settings found for this platform in the DB._"

    header = "| ID | Name | Category |\n| --- | --- | --- |\n"
    rows = []
    for s in settings[:max_rows]:
        cat = s.category or "-"
        rows.append(f"| `{s.setting_id}` | {s.name} | {cat} |")
    if len(settings) > max_rows:
        rows.append(f"| … | _{len(settings) - max_rows} more settings not shown_ | - |")
    return header + "\n".join(rows)


def resolve_setting(platform: str, setting_id_or_name: str) -> Optional[SettingEntry]:
    settings = list_settings_for_platform(platform)
    if not settings:
        return None

    needle = setting_id_or_name.strip().lower()

    # exact id match
    for s in settings:
        if s.setting_id.lower() == needle:
            return s

    # exact name match
    for s in settings:
        if s.name.lower() == needle:
            return s

    # partial name match
    for s in settings:
        if needle in s.name.lower():
            return s

    return None

def gemini_interpret_request(user_text: str, known_platforms: List[str]) -> Dict[str, Optional[str]]:
    """
    Use Gemini to extract platform, setting_query (normalized), and target_value from natural language.
    Returns dict with keys: platform_hint, setting_query, target_value.
    """
    client = get_gemini_client()
    if not client:
        return {"platform_hint": None, "setting_query": None, "target_value": None}

    system_instruction = (
        "You are a parser for natural-language requests about changing privacy/account settings.\n"
        "Return ONLY JSON (no markdown/fences/extra text):\n"
        "{\n"
        '  "platform_hint": string|null,\n'
        '  "setting_query": string|null,\n'
        '  "target_value": "on"|"off"|"private"|"public"|null\n'
        "}\n"
        "Rules:\n"
        "- platform_hint must be one of KNOWN_PLATFORMS if present; else null.\n"
        "- setting_query should remove platform phrases like 'on twitter'.\n"
        "- No extra keys.\n"
    )

    prompt = (
        "KNOWN_PLATFORMS:\n" + json.dumps(known_platforms, ensure_ascii=False) + "\n\n"
        "USER_TEXT:\n" + user_text
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        max_output_tokens=400,
        response_mime_type="application/json",
    )

    try:
        resp = client.models.generate_content(
            model=MODEL_NLP,
            contents=[Content(role="user", parts=[Part(text=prompt)])],
            config=config,
        )
    except Exception as e:
        return {"platform_hint": None, "setting_query": None, "target_value": None, "error": str(e)}

    out = (extract_model_text(resp) or "").strip()
    if not out:
        return {"platform_hint": None, "setting_query": None, "target_value": None}

    try:
        data = json.loads(out)
        if not isinstance(data, dict):
            raise ValueError("json_not_object")
        return {
            "platform_hint": data.get("platform_hint"),
            "setting_query": data.get("setting_query"),
            "target_value": data.get("target_value"),
        }
    except Exception:
        return {"platform_hint": None, "setting_query": None, "target_value": None}


def choose_setting_with_gemini(platform: str, user_query: str) -> Optional[SettingEntry]:
    """
    If the user mentions a leaf-level setting that doesn't exist in our DB,
    ask Gemini which *section* (SettingEntry) is the best starting point.
    """
    client = get_gemini_client()
    if not client:
        return None

    settings = list_settings_for_platform(platform)
    if not settings:
        return None

    candidates = [
        {"setting_id": s.setting_id, "name": s.name, "category": s.category, "description": s.description}
        for s in settings
    ]

    system_instruction = (
        "You are a routing assistant for privacy settings.\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "setting_id": "<best candidate setting_id>",\n'
        '  "reason": "<short>"\n'
        "}\n"
        "Rules:\n"
        "- setting_id MUST be one of the provided candidates.\n"
        "- No extra keys.\n"
    )

    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"USER_QUERY: {user_query}\n\n"
        "CANDIDATE_SECTIONS:\n"
        + json.dumps(candidates, ensure_ascii=False)
        + "\n\nPick the single best setting_id."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        max_output_tokens=400,
        response_mime_type="application/json",
    )

    try:
        resp = client.models.generate_content(
            model=MODEL_NLP,
            contents=[Content(role="user", parts=[Part(text=user_prompt)])],
            config=config,
        )
    except Exception:
        return None

    text = (extract_model_text(resp) or "").strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        sid = data.get("setting_id")
        if not sid:
            return None
        for s in settings:
            if s.setting_id == sid:
                return s
    except Exception:
        return None

    return None

def now_ts() -> float:
    return time.time()

def touch_session_activity():
    try:
        cl.user_session.set(SESSION_LAST_ACTIVITY_TS, now_ts())
    except Exception:
        pass

def is_session_timed_out() -> bool:
    try:
        last = cl.user_session.get(SESSION_LAST_ACTIVITY_TS)
        if not last:
            return False
        return (now_ts() - float(last)) > float(SESSION_TIMEOUT_SECONDS)
    except Exception:
        return False

def wipe_session_gemini():
    """
    Wipe key + client from memory only (no disk persistence).
    """
    try:
        cl.user_session.set(SESSION_GEMINI_API_KEY, None)
        cl.user_session.set(SESSION_GEMINI_CLIENT, None)
        cl.user_session.set(SESSION_AWAITING_GEMINI_KEY, False)
    except Exception:
        pass

def get_gemini_client():
    """
    Prefer session client if user provided a key; otherwise fall back to env/global client.
    """
    try:
        sess_client = cl.user_session.get(SESSION_GEMINI_CLIENT)
        if sess_client:
            return sess_client
    except Exception:
        pass
    return client  # global env-based fallback

def have_any_gemini_client() -> bool:
    return bool(get_gemini_client())

def sleep_with_jitter(
    attempt: int,
    base: float = 0.5,
    cap: float = 6.0,
    jitter: float = 0.5,
):
    """
    Exponential backoff with jitter.
    attempt: 0-based retry count
    """
    delay = min(cap, base * (2 ** attempt))
    delay += random.uniform(0, jitter)
    time.sleep(delay)

def resolve_setting_flexible(platform: str, section_query: str, leaf_hint: str | None = None):
    """
    Return (best_entry, leaf_hint_out) for this platform + section_query + optional leaf_hint.

    best_entry is one of the entries from SETTINGS_BY_PLATFORM[platform], typically a SettingEntry
    instance (or a raw dict if that's how you loaded things). We don't wrap it; we just choose the
    best candidate and return it unchanged.
    """
    sq = (section_query or "").strip()
    lh = (leaf_hint or "").strip() or None

    plat_norm = _norm(platform)

    # 1) Get all entries for this platform from existing dict.
    #    Depending on how SETTINGS_BY_PLATFORM was keyed, we try the normalized key first, then raw.
    platform_entries = (
        SETTINGS_BY_PLATFORM.get(plat_norm)
        or SETTINGS_BY_PLATFORM.get(platform)
        or []
    )
    if not platform_entries:
        return None, lh

    # 2) Score each entry
    scored: list[tuple[float, object]] = []
    for entry in platform_entries:
        score = score_entry_for_setting(entry, sq, lh)
        scored.append((score, entry))

    # Sort once after collecting all entries
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_entry = scored[0]


    # If nothing really matches and we DO have a leaf_hint, bail out.
    # For section-only queries (no leaf_hint), still pick the best candidate even if the score is small.
    if best_score < 0.5 and lh is not None:
        print(
            f"[resolver] Low best_score={best_score:.3f} for platform={platform}, "
            f"section_query={sq!r}, leaf_hint={lh!r}"
        )
        return None, lh

    # Debug: see what URL we picked
    try:
        print(
            f"[resolver] platform={platform} section_query={sq!r} leaf_hint={lh!r} "
            f"-> best_score={best_score:.3f}, url={_entry_url(best_entry)}"
        )
    except Exception:
        pass

    return best_entry, lh

def load_harvest_report_for_platform(platform: str) -> Optional[Dict[str, Any]]:
    plat_dir = GENERAL_OUTPUT_DIR / platform
    hr_path = plat_dir / "harvest_report.json"
    if not hr_path.exists():
        return None
    try:
        with hr_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_changes_log() -> List[Dict[str, Any]]:
    return cl.user_session.get(SESSION_CHANGES_KEY, [])


def append_change(record: Dict[str, Any]) -> None:
    changes = cl.user_session.get(SESSION_CHANGES_KEY, [])
    changes.append(record)
    cl.user_session.set(SESSION_CHANGES_KEY, changes)


def build_session_report_md(changes: List[Dict[str, Any]]) -> str:
    if not changes:
        return "_No settings were changed in this session (or automation failed)._"

    header = "| Platform | Setting | Requested Value | Status |\n| --- | --- | --- | --- |\n"
    rows = []
    for c in changes:
        rows.append(
            f"| {c.get('platform')} | {c.get('setting_name')} "
            f"(`{c.get('setting_id')}`) | {c.get('requested_value')} | {c.get('status')} |"
        )
    return header + "\n".join(rows)


# =========================
# Playwright / DOM helpers
# =========================
def resolve_label_text_anywhere(page: Page, hint: str) -> Optional[str]:
    """
    Deterministic deep fallback: use Playwright's text engine to find the hint anywhere.
    Returns a short visible text string if found.
    """
    if not hint:
        return None
    try:
        loc = page.get_by_text(hint, exact=False)
        if not loc.count():
            return None
        el = loc.first
        try:
            el.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass
        try:
            txt = el.inner_text().strip()
        except Exception:
            txt = (el.text_content() or "").strip()
        txt = " ".join((txt or "").split())
        if txt and len(txt) <= 80:
            return txt
    except Exception:
        pass
    return None

def viewport_dom_textmap(page: Page, max_items: int = 120) -> str:
    items = []
    try:
        for sel in [
            "h1,h2,h3,[role='heading']",
            "a,button",
            "[role='tab']",
            "[role='menuitem']",
            "[aria-label]"
        ]:
            loc = page.locator(sel)
            count = min(loc.count(), max_items)
            for i in range(count):
                try:
                    t = loc.nth(i).inner_text().strip()
                except Exception:
                    try:
                        t = loc.nth(i).text_content().strip()
                    except Exception:
                        t = ""
                if t:
                    t = " ".join(t.split())
                    items.append(t[:160])
                if len(items) >= max_items:
                    break
            if len(items) >= max_items:
                break
    except Exception:
        pass
    out, seen = [], set()
    for t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return "\n".join(out[:max_items])



def dom_outline(page: Page, max_nodes: int = 300) -> str:
    """Compact DOM outline for planner context."""
    try:
        data = page.evaluate(f"""
(() => {{
  const max = {max_nodes};
  const take = (n) => Array.from(n).slice(0, max);
  const norm = s => (s||"").replace(/\\s+/g,' ').trim();
  const sel = (el) => {{
    const id = el.id ? '#'+CSS.escape(el.id) : '';
    const cls = (el.className && typeof el.className==='string')
      ? '.'+el.className.trim().split(/\\s+/).slice(0,3).map(CSS.escape).join('.') : '';
    return el.tagName.toLowerCase()+id+cls;
  }};
  const nodes = take(document.querySelectorAll('a,button,[role],[aria-label],summary,[aria-expanded]'));
  return nodes.map(el => ({
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role')||'',
    text: norm(el.innerText||''),
    ariaLabel: norm(el.getAttribute('aria-label')||''),
    expanded: el.getAttribute('aria-expanded'),
    clickable: (typeof el.click==='function'),
    selector: sel(el)
  }));
}})();
""")
        return json.dumps(data[:max_nodes], ensure_ascii=False)
    except Exception:
        return "[]"
    

def dom_outline_targeted(page: Page, leaf_hint: Optional[str], max_nodes: int = 140) -> str:
    """
    Smaller outline: only elements likely relevant to the leaf hint or confirm/save flows.
    """
    toks = []
    if leaf_hint:
        toks = [t.lower() for t in re.findall(r"[a-zA-Z0-9]+", leaf_hint) if len(t) >= 3][:6]

    try:
        data = page.evaluate(
            """
            ({toks, max}) => {
              const norm = s => (s||"").replace(/\\s+/g,' ').trim().toLowerCase();
              const nodes = Array.from(document.querySelectorAll(
                'button,a,input,select,textarea,[role],[aria-label],summary,[aria-expanded]'
              ));
              const keep = [];
              for (const el of nodes) {
                if (keep.length >= max) break;
                const txt = norm(el.innerText || "");
                const al  = norm(el.getAttribute('aria-label') || "");
                const hay = (txt + " " + al).trim();

                const isConfirm = /(save|apply|confirm|ok|done|continue|next|yes)/.test(hay);
                const isHint = toks && toks.length ? toks.some(t => hay.includes(t)) : false;

                if (isConfirm || isHint) {
                  keep.push({
                    tag: (el.tagName||"").toLowerCase(),
                    role: el.getAttribute('role')||'',
                    text: (el.innerText||'').replace(/\\s+/g,' ').trim().slice(0,120),
                    ariaLabel: (el.getAttribute('aria-label')||'').replace(/\\s+/g,' ').trim().slice(0,120),
                    expanded: el.getAttribute('aria-expanded'),
                    checked: el.getAttribute('aria-checked'),
                    pressed: el.getAttribute('aria-pressed')
                  });
                }
              }
              return keep;
            }
            """,
            {"toks": toks, "max": max_nodes},
        )
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return "[]"


def read_control_state_by_label(page: Page, label_text: str) -> Optional[bool]:
    """
    Try to infer on/off state deterministically using DOM attributes near a label.
    Returns True (on), False (off), or None (unknown).
    """
    try:
        label_loc = page.get_by_text(label_text, exact=True)
        if not label_loc.count():
            label_loc = page.get_by_text(label_text, exact=False)
        if not label_loc.count():
            return None

        label = label_loc.first
        label_box = label.bounding_box()
        if not label_box:
            return None

        label_right = label_box["x"] + label_box["width"]
        label_center_y = label_box["y"] + label_box["height"] / 2.0

        cand_loc = page.locator(
            "input[type='checkbox'],[role='switch'],[role='checkbox'],button[aria-pressed],[aria-checked]"
        )
        total = cand_loc.count()
        max_to_check = min(total, 60)

        best = None
        best_dx = float("inf")

        for i in range(max_to_check):
            el = cand_loc.nth(i)
            box = el.bounding_box()
            if not box:
                continue

            dx = box["x"] - label_right
            if dx < 0:
                continue
            if not (box["y"] <= label_center_y <= (box["y"] + box["height"])):
                continue
            if dx < best_dx:
                best_dx = dx
                best = el

        if not best:
            return None

        # Try common state attributes
        for attr in ["aria-checked", "aria-pressed"]:
            try:
                v = best.get_attribute(attr)
                if v is None:
                    continue
                v = v.strip().lower()
                if v in ("true", "1", "yes", "on"):
                    return True
                if v in ("false", "0", "no", "off"):
                    return False
            except Exception:
                pass

        # Checkbox checked
        try:
            tag = best.evaluate("el => el.tagName.toLowerCase()")
            if tag == "input":
                t = best.get_attribute("type") or ""
                if t.lower() == "checkbox":
                    checked = best.is_checked()
                    return True if checked else False
        except Exception:
            pass

        return None
    except Exception:
        return None

def deterministic_matches_target(page: Page, label_text: str, target_value: str) -> Optional[bool]:
    """
    Deterministically decide whether the UI control near label_text matches target_value.
    Returns:
      True  -> matches target
      False -> definitely does not match
      None  -> cannot determine
    """
    tv = (target_value or "").strip().lower()
    state = read_control_state_by_label(page, label_text)
    if state is None:
        return None

    want_on = tv in ("on", "enabled", "private")
    want_off = tv in ("off", "disabled", "public")

    if want_on:
        return True if state is True else False
    if want_off:
        return True if state is False else False
    return None

def best_actionable_label_match_on_page(page: Page, hint: str, max_scan: int = 160) -> Optional[str]:
    """
    Find the best visible label-like text that matches `hint` AND has a nearby control
    (switch/checkbox/button) associated with it.

    Returns the label text to use with label-mode, or None.
    """
    hint_norm = _norm(hint)
    if not hint_norm:
        return None
    hint_tokens = set(hint_norm.split())

    # likely "labels"
    loc = page.locator("label,span,div,p,h1,h2,h3,button,a")
    n = min(loc.count(), max_scan)

    best_text = None
    best_score = 0.0

    hint_tokens = [t for t in hint_norm.split() if t not in {"and", "or", "to", "of", "in", "my"}]
    anchor = set(hint_tokens[:2]) if len(hint_tokens) >= 2 else set(hint_tokens)


    for i in range(n):
        try:
            txt = loc.nth(i).inner_text().strip()
        except Exception:
            continue
        if not txt:
            continue
        if len(txt) > 70:
            continue
        if "\n" in txt:
            continue
        txt_norm = _norm(txt)
        if not txt_norm:
            continue

        tokens = set(txt_norm.split())
        if not tokens:
            continue

        if anchor and not (anchor & set(txt_norm.split())):
            continue


        # similarity score (token overlap)
        overlap = len(tokens & hint_tokens) / max(1, len(hint_tokens))
        score = overlap

        # Prefer header-ish elements (often the setting label)
        try:
            tag = loc.nth(i).evaluate("el => el.tagName.toLowerCase()")
            if tag in ("h1", "h2", "h3", "h4", "label"):
                score += 0.15
        except Exception:
            pass

        # modest bonus for substring relationship
        if hint_norm in txt_norm or txt_norm in hint_norm:
            score += 0.25

        # Now: must have a nearby actionable control (container search)
        try:
            el = loc.nth(i)
            container = el.locator("xpath=ancestor::*[self::li or self::section or self::div][1]")
            if not container.count():
                container = el

            ctrl = container.locator(
                "[role='switch'],"
                "input[type='checkbox'],"
                "[aria-checked],"
                "button[aria-pressed],"
                "[role='checkbox'],"
                "[role='radio']"
            )

            if not ctrl.count():
                # no control nearby -> not actionable, skip
                continue

            # bonus for being actionable
            score += 0.5

        except Exception:
            continue

        if score > best_score:
            best_score = score
            best_text = txt

    # Require at least some match strength
    if best_text and best_score >= 0.35:
        return best_text

    return None

def apply_selector(page: Page, sel: Dict[str, Any]) -> bool:
    desired_value = (sel.get("value") or "").strip().lower()
    stype = (sel.get("type") or "css").lower()
    sval = sel.get("selector") or ""
    if not sval:
        return False

    try:
        if stype == "css":
            loc = page.locator(sval)
            count = loc.count()
            print(f"[apply_selector] CSS '{sval}' -> {count} matches")
            if count:
                loc.first.click(timeout=3500)
                return True

        elif stype == "text":
            print(f"[apply_selector] Trying stype='text' {sval!r}")

            # If we have a desired value, prefer coord hint-mode so we toggle the associated control,
            # not just click the label text.
            if desired_value in ("on", "off", "enabled", "disabled", "private", "public"):
                ok = apply_selector(page, {
                    "purpose": sel.get("purpose") or "change_value",
                    "type": "coord",
                    "selector": f"hint:{sval}",
                    "value": desired_value,
                })
                if ok:
                    return True

            label_loc = page.get_by_text(sval, exact=True)
            if not label_loc.count():
                label_loc = page.get_by_text(sval, exact=False)

            count = label_loc.count()
            print(f"[apply_selector] text locator matched {count} element(s)")

            if count:
                label_loc.first.click(timeout=3500)
                return True


        elif stype == "role":
            role_sel = sval.strip()

            # If it looks like a simple role name, use [role='...']
            simple_role = re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", role_sel or "") is not None

            # If it looks like CSS (attribute selectors, classes, ids, etc.), treat as CSS
            looks_css = any(ch in role_sel for ch in ["[", "]", "=", ".", "#", ":", "(", ")", " "])

            if simple_role and not looks_css:
                loc = page.locator(f"[role='{role_sel}']")
            else:
                # Allow planner to give CSS-like selectors even if type says "role"
                loc = page.locator(role_sel)

            count = loc.count()
            print(f"[apply_selector] role '{role_sel}' -> {count} matches")
            if count:
                loc.first.click(timeout=3500)
                return True

        elif stype == "coord":
            if sval.startswith("hint:"):
                hint = sval[len("hint:"):].strip()
                print(f"[apply_selector] coord hint-mode for {hint!r}")

                # Prefer labels that have an actual control near them
                matched = best_actionable_label_match_on_page(page, hint)
                if not matched:
                    # fallback: old behavior if nothing actionable is found
                    matched = best_label_match_on_page(page, hint)
                if not matched:
                    matched = resolve_label_text_anywhere(page, hint)
                if not matched:
                    print(f"[apply_selector] No good label match found for hint {hint!r}")
                    return False

                sval = f"label:{matched}"
                print(f"[apply_selector] hint resolved to label {matched!r}")

            if sval.startswith("label:"):
                label_text = sval[len("label:"):].strip()
                print(f"[apply_selector] coord label-mode for {label_text!r}")

                # Always define label_loc so we never hit "referenced before assignment"
                label_loc = None

                # Build variants of the label to increase chance of matching UI text
                variants = []
                orig = (label_text or "").strip()
                if orig:
                    variants.append(orig)

                # Common cleanups
                v = re.sub(r"^\s*edit\s+", "", orig, flags=re.I).strip()
                if v and v not in variants:
                    variants.append(v)

                v2 = re.sub(r"\byour\b", "", v, flags=re.I).strip()
                if v2 and v2 not in variants:
                    variants.append(v2)

                # Add tail phrases (last 2–4 words)
                words = [w for w in re.split(r"\s+", v2) if w]
                for n in (2, 3, 4):
                    if len(words) >= n:
                        tail = " ".join(words[-n:]).strip()
                        if tail and tail not in variants:
                            variants.append(tail)

                # Special common rewrites
                low = v2.lower()
                if "profile visibility" in low and "Public profile" not in variants:
                    variants.append("Public profile")
                if "visibility" in low and "Profile visibility" not in variants:
                    variants.append("Profile visibility")

                # Try each variant until we find a match
                matched_text = None
                for v in variants:
                    if not v:
                        continue
                    loc = page.get_by_text(v, exact=True)
                    if not loc.count():
                        loc = page.get_by_text(v, exact=False)
                    if loc.count():
                        label_loc = loc
                        matched_text = v
                        break

                if not label_loc or not label_loc.count():
                    print(f"[apply_selector] No label found for any variant of {variants!r}")
                    return False

                # Use the matched label element
                label = label_loc.first
                label_box = label.bounding_box()
                # --- Prefer finding a toggle/control in the same container row/card ---
                # This solves layouts where the label container spans across the toggle.
                try:
                    container = label.locator("xpath=ancestor::*[self::li or self::section or self::div][1]")
                    if container.count():
                        # Prefer real checkbox/switch inputs first (most reliable via set_checked)
                        inp = container.locator("input[type='checkbox'], input[role='switch'], [role='switch'][type='checkbox']")
                        if inp.count():
                            el = inp.first

                            # if we know the desired state, set it deterministically
                            want_on = desired_value in ("on", "enabled", "private")
                            want_off = desired_value in ("off", "disabled", "public")

                            if want_on or want_off:
                                try:
                                    cur = el.is_checked()
                                    if want_on and not cur:
                                        el.set_checked(True)
                                        return True
                                    if want_off and cur:
                                        el.set_checked(False)
                                        return True
                                    # already correct
                                    return True
                                except Exception as e:
                                    print("[apply_selector] set_checked failed, falling back to click:", e)
                                    # fall through

                            # Fallback: toggle if we don't know desired state (or set_checked failed)
                            try:
                                el.click(timeout=3500, force=True)
                                return True
                            except Exception:
                                try:
                                    cur = el.is_checked()
                                    el.set_checked(not cur)
                                    return True
                                except Exception:
                                    pass


                        # Fall back to role switch, aria checked, etc.
                        ctrl = container.locator("[role='switch'],[aria-checked],button[aria-pressed]")
                        if ctrl.count():
                            ctrl.first.click(timeout=3500, force=True)
                            return True
                except Exception as e:
                    print("[apply_selector] container-control search failed:", e)


                if not label_box:
                    print("[apply_selector] No bounding_box for label")
                    return False

                label_right = label_box["x"] + label_box["width"]
                label_center_y = label_box["y"] + label_box["height"] / 2.0

                # Find candidate controls to the right in the same row
                candidates_selector = (
                    "input,button,"
                    "[role='switch'],[role='checkbox'],[role='radio'],"
                    "[role='button'],[aria-checked]"
                )
                cand_loc = page.locator(candidates_selector)
                total = cand_loc.count()
                print(f"[apply_selector] searching {total} candidate controls near label {matched_text!r}")

                best_box = None
                best_dx = float("inf")
                max_to_check = min(total, 80)

                for i in range(max_to_check):
                    el = cand_loc.nth(i)
                    box = el.bounding_box()
                    if not box:
                        continue

                    # Must be to the right of the label
                    dx = box["x"] - label_right
                    # Allow controls that are inside the label container but on the right half.
                    if dx < 0:
                        # accept if the control is on the right half of the label box
                        ctrl_center_x = box["x"] + box["width"] / 2.0
                        label_mid_x = label_box["x"] + label_box["width"] * 0.55
                        if ctrl_center_x <= label_mid_x:
                            continue


                    # Must overlap vertically with label row
                    if not (box["y"] <= label_center_y <= (box["y"] + box["height"])):
                        continue

                    if dx < best_dx:
                        best_dx = dx
                        best_box = box

                if not best_box:
                    # Very common: the label itself is the control (opens modal / navigates),
                    # and there is no right-side toggle. Click the label as a safe fallback.
                    try:
                        print("[apply_selector] No nearby toggle found; clicking the label itself.")
                        label.click(timeout=3500)
                        return True
                    except Exception as e:
                        print("[apply_selector] Could not click label fallback:", e)
                        return False


                cx = best_box["x"] + best_box["width"] / 2.0
                cy = best_box["y"] + best_box["height"] / 2.0
                print(f"[apply_selector] Clicking center of nearest control at ({cx}, {cy})")
                page.mouse.click(cx, cy)
                return True

            else:
                # Raw numeric coords "x,y"
                try:
                    x_str, y_str = sval.split(",", 1)
                    x = float(x_str.strip())
                    y = float(y_str.strip())
                    print(f"[apply_selector] Clicking raw coordinates ({x}, {y})")
                    page.mouse.click(x, y)
                    return True
                except Exception as e:
                    print(f"[apply_selector] coord parse failed for {sval!r}: {e}")
                    return False



    except PwTimeout:
        print(f"[apply_selector] Timeout while applying selector {stype!r} {sval!r}")
        return False
    except Exception as e:
        print(f"[apply_selector] Error while applying selector {stype!r} {sval!r}: {e}")
        return False

    return False



def try_click_leaf_hint(page: Page, leaf_hint: Optional[str]) -> bool:
    """
    Fallback: try to click the leaf setting by its visible text label.
    For example, if leaf_hint is 'Protect your posts', we attempt to click that text.
    """
    if not leaf_hint:
        return False

    try:
        # Use Playwright's text-based locator; exact=False allows partial matches.
        loc = page.get_by_text(leaf_hint, exact=False)
        if loc.count():
            loc.first.click(timeout=4000)
            return True
    except Exception:
        pass

    return False


# =========================
# Gemini planner for setting change
# =========================

def planner_setting_change(
    page: Page,
    platform: str,
    setting: SettingEntry,
    target_value: str,
    executor_state: Dict[str, Any],
    leaf_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ask Gemini how to change a given setting on the current page.

    Enforces:
    - EXACT top-level keys: selectors, done, notes
    - <=4 selectors
    - change_value requires "value"
    - done cannot be true without change_value/confirm
    """
    client = get_gemini_client()
    if not client:
        return {"selectors": [], "done": True, "notes": "Gemini client not configured (no API key)."}

    snap = page.screenshot(full_page=False)
    textmap = viewport_dom_textmap(page, max_items=80)
    outline = dom_outline_targeted(page, leaf_hint, max_nodes=140)

    system_instruction = (
        "You are a UI control agent operating in a desktop browser.\n"
        "Your job is to help an executor change ONE privacy/data setting.\n\n"
        "Return a SINGLE JSON object with EXACTLY these top-level keys:\n"
        "- selectors\n"
        "- done\n"
        "- notes\n"
        "No other top-level keys are allowed.\n\n"
        "JSON schema:\n"
        "{\n"
        '  "selectors": [\n'
        "    {\n"
        '      "purpose": "open_setting_group" | "change_value" | "confirm" | "scroll" | "other",\n'
        '      "type": "text" | "css" | "role" | "coord",\n'
        '      "selector": "<string>",\n'
        '      "value": "<REQUIRED ONLY when purpose is change_value; otherwise omit>"\n'
        "    }\n"
        "  ],\n"
        '  "done": true|false,\n'
        '  "notes": "<short string>"\n'
        "}\n\n"
        "STRICT OUTPUT RULES:\n"
        "- Output MUST be valid JSON. No markdown. No code fences. No extra text.\n"
        "- First non-whitespace char must be '{' and last must be '}'.\n"
        "- selectors MUST be an array (can be empty).\n"
        "- Provide AT MOST 4 selectors total.\n"
        "- notes MUST be <= 80 characters.\n\n"
        "SEMANTIC RULES:\n"
        "- Include ALL steps needed to actually set the target setting to TARGET_VALUE.\n"
        "- If TARGET_LEAF_SETTING_NAME is provided:\n"
        "  * You MUST include at least one selector with purpose=\"change_value\".\n"
        "  * That change_value selector MUST include value exactly equal to TARGET_VALUE.\n"
        "- Only set done=true if your selectors are sufficient to navigate (if needed), change the value, "
        "and confirm/save if required.\n"
        "- If a confirmation UI is visible/required, include purpose=\"confirm\" selectors before done=true.\n"
        "- Never click Cancel.\n"
        "- Use coord selectors only as a last resort.\n\n"
        "You are given:\n"
        "- PLATFORM\n"
        "- CURRENT_URL\n"
        "- TARGET_SECTION_SETTING_NAME and description\n"
        "- Optional TARGET_LEAF_SETTING_NAME\n"
        "- TARGET_VALUE\n"
        "- Screenshot\n"
        "- DOM_TEXT_MAP and DOM_OUTLINE\n"
        "- EXECUTOR_STATE_JSON (may contain feedback)\n"
    )

    leaf_line = f"TARGET_LEAF_SETTING_NAME: {leaf_hint}\n" if leaf_hint else ""
    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"CURRENT_URL: {page.url}\n"
        f"TARGET_SECTION_SETTING_NAME: {setting.name}\n"
        f"TARGET_SECTION_SETTING_DESCRIPTION: {setting.description or ''}\n"
        + leaf_line +
        f"TARGET_VALUE: {target_value}\n\n"
        "EXECUTOR_STATE_JSON:\n"
        + json.dumps(executor_state, ensure_ascii=False)
        + "\n\nReturn ONLY the JSON object."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        max_output_tokens=900,
        response_mime_type="application/json",
    )

    try:
        print("[planner_setting_change] Calling Gemini planner...")
        resp = client.models.generate_content(
            model=MODEL_PLAN,
            contents=[Content(role="user", parts=[
                Part(text=user_prompt),
                Part(text="DOM_TEXT_MAP_START\n" + textmap + "\nDOM_TEXT_MAP_END"),
                Part(text="DOM_OUTLINE_START\n" + outline + "\nDOM_OUTLINE_END"),
                Part.from_bytes(data=snap, mime_type="image/png"),
            ])],
            config=config,
        )
    except Exception as e:
        print("[planner_setting_change] Gemini error:", e)
        if leaf_hint:
            return {
                "selectors": [{
                    "purpose": "change_value",
                    "type": "coord",
                    "selector": f"hint:{sanitize_leaf_hint(leaf_hint, setting.name)}",
                    "value": target_value,
                }],
                "done": False,
                "notes": f"model_error:{type(e).__name__}"[:80],
            }
        return {"selectors": [], "done": False, "notes": f"model_error:{type(e).__name__}"[:80]}

    debug_print_gemini_response(resp, tag="planner_setting_change")

    # MAX_TOKENS retry: compress instruction but keep output budget
    try:
        cands = getattr(resp, "candidates", None) or []
        fr = getattr(cands[0], "finish_reason", None) if cands else None
    except Exception:
        fr = None

    if fr and "MAX_TOKENS" in str(fr):
        short_instruction = "Return ONLY JSON. Max 3 selectors. notes<=60 chars. No extra keys."
        short_config = types.GenerateContentConfig(
            system_instruction=system_instruction + "\n" + short_instruction,
            temperature=0.0,
            max_output_tokens=900,
            response_mime_type="application/json",
        )
        try:
            resp = client.models.generate_content(
                model=MODEL_PLAN,
                contents=[Content(role="user", parts=[
                    Part(text=user_prompt),
                    Part(text="DOM_TEXT_MAP_START\n" + textmap[:1200] + "\nDOM_TEXT_MAP_END"),
                    Part(text="DOM_OUTLINE_START\n" + outline[:1800] + "\nDOM_OUTLINE_END"),
                    Part.from_bytes(data=snap, mime_type="image/png"),
                ])],
                config=short_config,
            )
            debug_print_gemini_response(resp, tag="planner_setting_change_retry")
        except Exception:
            pass

    raw = (extract_model_text(resp) or "").strip()
    if not raw:
        print("[planner_setting_change] Empty model output.")
        if leaf_hint:
            return {
                "selectors": [{
                    "purpose": "change_value",
                    "type": "coord",
                    "selector": f"hint:{sanitize_leaf_hint(leaf_hint, setting.name)}",
                    "value": target_value,
                }],
                "done": False,
                "notes": "model_empty_output",
            }
        return {"selectors": [], "done": False, "notes": "model_empty_output"}

    try:
        data = json.loads(raw)
    except Exception as e:
        print("[planner_setting_change] JSON parse error:", e, "raw head:", raw[:200])
        if leaf_hint:
            return {
                "selectors": [{
                    "purpose": "change_value",
                    "type": "coord",
                    "selector": f"hint:{sanitize_leaf_hint(leaf_hint, setting.name)}",
                    "value": target_value,
                }],
                "done": False,
                "notes": "model_bad_json",
            }
        return {"selectors": [], "done": False, "notes": "model_bad_json"}

    if not isinstance(data, dict):
        return {"selectors": [], "done": False, "notes": "model_json_not_object"}

    # Normalize keys (ignore any extra keys by rebuilding)
    selectors = data.get("selectors") if isinstance(data.get("selectors"), list) else []
    done = bool(data.get("done", False))
    notes = str(data.get("notes") or "")

    # Hard cap selectors
    selectors = selectors[:4]

    # Enforce value presence for change_value
    for s in selectors:
        if not isinstance(s, dict):
            continue
        if (s.get("purpose") or "").lower() == "change_value":
            if "value" not in s or not str(s.get("value") or "").strip():
                s["value"] = target_value

    # Enforce done cannot be true without change_value/confirm
    has_effective = any(
        isinstance(s, dict) and (s.get("purpose") or "").lower() in ("change_value", "confirm")
        for s in selectors
    )
    if done and not has_effective:
        done = False
        notes = (notes[:60] + " | enforce_done_false") if notes else "enforce_done_false"

    notes = notes[:80]

    return {"selectors": selectors, "done": done, "notes": notes}

# =========================
# Setting change executor (Playwright + Gemini)
# =========================
def categories_for_platform(platform: str) -> List[str]:
    entries = list_settings_for_platform(platform) or []
    counts: Dict[str, int] = {}
    for e in entries:
        c = e.category or "uncategorized"
        counts[c] = counts.get(c, 0) + 1

    ordered = [c for c in CATEGORY_ORDER if c in counts]
    # Append any unexpected categories (future-proof)
    extras = sorted([c for c in counts.keys() if c not in CATEGORY_ORDER])
    ordered += extras
    return ordered

def category_counts_for_platform(platform: str) -> Dict[str, int]:
    entries = list_settings_for_platform(platform) or []
    counts: Dict[str, int] = {}
    for e in entries:
        c = e.category or "uncategorized"
        counts[c] = counts.get(c, 0) + 1
    return counts

def settings_for_platform_category(platform: str, category: Optional[str]) -> List[SettingEntry]:
    """
    Return a deduped list of SettingEntry for a platform/category, sorted for browsing.
    Dedupes by setting_id to prevent repeated entries in the UI.
    """
    entries = list_settings_for_platform(platform) or []

    # Filter by category
    if category and category != "all":
        entries = [e for e in entries if (e.category or "uncategorized") == category]

    # Dedupe by setting_id (keep first occurrence)
    seen = set()
    deduped: List[SettingEntry] = []
    for e in entries:
        sid = (e.setting_id or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        deduped.append(e)

    # Sort for stable browsing
    if category and category != "all":
        return sorted(deduped, key=lambda e: e.name.lower())
    return sorted(deduped, key=lambda e: ((e.category or "uncategorized"), e.name.lower()))

def render_scrollbox_settings(entries: List[SettingEntry], max_lines: int = 160) -> str:
    """
    Human-readable scrollbox using Markdown code fences (Chainlit displays this well).
    Also dedupes by setting_id to avoid repeated rows.
    """
    seen = set()
    lines: List[str] = []

    for e in entries:
        sid = (e.setting_id or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)

        cat = e.category or "uncategorized"
        # Keep it compact and readable
        lines.append(f"{sid:<35}  {e.name}  [{cat}]")

        if len(lines) >= max_lines:
            break

    remaining = 0
    # If we stopped early, estimate remaining based on unseen entries
    if len(lines) >= max_lines:
        # Count remaining unique ids not shown
        for e in entries:
            sid = (e.setting_id or "").strip()
            if sid and sid not in seen:
                remaining += 1

    if not lines:
        body = "(No settings)"
    else:
        body = "\n".join(lines)
        if remaining > 0:
            body += f"\n... ({remaining} more not shown)"

    return "```text\n" + body + "\n```"


def browse_settings_action() -> cl.Action:
    return cl.Action(name="browse_settings", payload={}, label="Browse settings")

def pick_category_action(category: str, count: int) -> cl.Action:
    return cl.Action(
        name="pick_category",
        payload={"category": category},
        label=f"{CATEGORY_TITLES.get(category, category)} ({count})",
    )

def browse_page_action(direction: str) -> cl.Action:
    return cl.Action(name="browse_page", payload={"dir": direction}, label=("Next ▶" if direction == "next" else "◀ Prev"))

def set_value_action(value: str) -> cl.Action:
    return cl.Action(name="set_value_ui", payload={"value": value}, label=value.capitalize())

def apply_setting_change_sync(
    platform: str,
    setting: SettingEntry,
    target_value: str,
    leaf_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synchronous function that:
    - Finds the URL for this setting (from all_platforms_classified)
    - Loads the site's storage_state
    - Uses Playwright + Gemini planner to attempt to change the setting
    - Returns a result dict for logging in the session
    """
    result: Dict[str, Any] = {
        "platform": platform,
        "setting_id": setting.setting_id,
        "setting_name": setting.name,
        "category": setting.category,
        "requested_value": target_value,
        "status": "error",
        "details": "",
        "url": None,
        "leaf_hint": leaf_hint,
        "click_count": 0,
        "path_log": {
            "entrypoint": None,
            "candidate_source": None,
            "leaf_hint_source": None,
            "turns": [],
            "final_decider": None,
        },
    }

    sess_client = get_gemini_client()
    if not sess_client:
        result["details"] = "No Gemini client configured for this session; cannot run planner."
        return result

    url = setting.raw.get("url")
    if not url:
        result["details"] = "No URL found for this setting in DB."
        return result
    result["url"] = url

    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    if not host:
        result["details"] = f"Could not extract hostname from URL: {url}"
        return result

    state_path = STORAGE_STATE_DIR / f"{host}.json"
    if not state_path.exists():
        result["details"] = f"Storage state not found for host `{host}` at `{state_path}`."
        return result

    executor_state: Dict[str, Any] = {
        "target_setting": setting.name,
        "target_value": target_value,
        "platform": platform,
        "url": url,
        "attempts": 0,
        "leaf_hint": leaf_hint,
        "verify_label": setting.name,  # updated dynamically
    }

    try:
        ep = cl.user_session.get("last_entrypoint")
        cs = cl.user_session.get("last_candidate_source")
        lhs = cl.user_session.get("last_leaf_hint_source")
        if ep:
            result["path_log"]["entrypoint"] = ep
        if cs:
            result["path_log"]["candidate_source"] = cs
        if lhs:
            result["path_log"]["leaf_hint_source"] = lhs
    except Exception:
        pass

    def _label_is_actionably_visible(page: Page, label_text: Optional[str]) -> bool:
        if not label_text:
            return False
        try:
            # If we can read state, it's actionable.
            if read_control_state_by_label(page, label_text) is not None:
                return True
        except Exception:
            pass
        # Otherwise, at least check label is present somewhere
        try:
            return page.get_by_text(label_text, exact=False).count() > 0
        except Exception:
            return False


    click_count = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                storage_state=str(state_path),
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
                java_script_enabled=True,
            )

            page = context.new_page()
            page.goto(url, wait_until="load", timeout=60_000)

            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

            page.wait_for_timeout(2000)

            # Initial verify label: may not exist yet; that's OK.
            try:
                executor_state["verify_label"] = resolve_visible_leaf_label(page, leaf_hint, setting.name)
            except Exception:
                executor_state["verify_label"] = leaf_hint or setting.name

            # Early deterministic exit ONLY if label is actionably visible and readable
            desired = (target_value or "").lower().strip()
            if desired in ("on", "off", "private", "public"):
                verify_label0 = executor_state.get("verify_label") or setting.name
                if _label_is_actionably_visible(page, verify_label0):
                    state0 = read_control_state_by_label(page, verify_label0)
                    if state0 is not None:
                        if desired in ("on", "private") and state0 is True:
                            result["status"] = "success"
                            result["details"] = "Already in desired state; no action needed."
                            result["click_count"] = 0
                            result["path_log"]["final_decider"] = "deterministic"
                            return result
                        if desired in ("off", "public") and state0 is False:
                            result["status"] = "success"
                            result["details"] = "Already in desired state; no action needed."
                            result["click_count"] = 0
                            result["path_log"]["final_decider"] = "deterministic"
                            return result

            max_turns = 6
            last_notes = ""

            for turn in range(1, max_turns + 1):
                executor_state["attempts"] = turn
                print(f"[executor] TURN {turn}: starting planner for {platform} / {setting.name!r}")

                page.wait_for_timeout(1000)

                # Leaf hint passed to planner; avoid using setting_id as hint
                leaf_hint_for_ui = leaf_hint
                if leaf_hint and getattr(setting, "setting_id", None):
                    if _norm(leaf_hint) == _norm(setting.setting_id):
                        leaf_hint_for_ui = setting.name
                executor_state["leaf_hint"] = leaf_hint_for_ui

                # Dynamic verify label (may still be raw hint if not visible)
                try:
                    executor_state["verify_label"] = resolve_visible_leaf_label(page, leaf_hint_for_ui, setting.name)
                except Exception:
                    executor_state["verify_label"] = leaf_hint_for_ui or setting.name

                verify_label = executor_state["verify_label"] or setting.name
                verify_ready = _label_is_actionably_visible(page, verify_label)

                plan = planner_setting_change(
                    page,
                    platform,
                    setting,
                    target_value,
                    executor_state,
                    leaf_hint=leaf_hint_for_ui,
                )

                selectors = plan.get("selectors") or []
                done = bool(plan.get("done"))
                last_notes = str(plan.get("notes") or "")

                print(
                    f"[executor] TURN {turn}: planner returned {len(selectors)} selectors, "
                    f"done={done}, notes={last_notes[:120]!r}"
                )

                turn_rec = {
                    "turn": turn,
                    "url": page.url,
                    "notes": last_notes,
                    "selectors": selectors[:8],
                    "applied": [],
                    "deterministic_check": None,
                    "gemini_verify": None,
                }

                try:
                    has_model_issue = any(
                        key in last_notes
                        for key in ("model_empty_output", "model_error", "model_text_error", "model_bad_json")
                    )

                    if has_model_issue and not selectors:
                        print(f"[executor] TURN {turn}: planner reported `{last_notes}` with NO selectors.")
                        if turn < max_turns:
                            executor_state["feedback"] = (
                                "Last planner produced no usable selectors. "
                                "Provide concrete selectors to navigate (if needed) and toggle the target setting."
                            )
                            page.wait_for_timeout(2000)
                            continue
                        else:
                            result["status"] = "uncertain"
                            result["details"] = (
                                "Planner repeatedly produced empty/invalid output. "
                                f"Last notes: {last_notes}"
                            )
                            result["path_log"]["final_decider"] = "unknown"
                            break

                    if done and not selectors:
                        executor_state["feedback"] = (
                            "You set done=true but provided no selectors. "
                            "Include change_value and/or confirm selectors."
                        )
                        last_notes += " | Executor: done=true but no selectors."
                        turn_rec["notes"] = last_notes
                        continue

                    if not selectors and not done:
                        ln = last_notes.lower()
                        if "still loading" in ln or "no interactive elements" in ln:
                            page.wait_for_timeout(2000)
                            continue

                        # If we can verify deterministically, try; otherwise treat as uncertain.
                        if verify_ready:
                            try:
                                tv = (target_value or "").strip().lower()
                                state = read_control_state_by_label(page, verify_label)
                                if state is not None:
                                    want_on = tv in ("on", "enabled", "private")
                                    want_off = tv in ("off", "disabled", "public")
                                    if (want_on and state is True) or (want_off and state is False):
                                        result["status"] = "success"
                                        result["details"] = (
                                            "Planner returned no selectors because setting already matches requested value. "
                                            f"Notes: {last_notes}"
                                        )
                                        result["path_log"]["final_decider"] = "deterministic"
                                        break
                            except Exception:
                                pass

                        result["status"] = "uncertain"
                        result["details"] = (
                            f"Planner returned no selectors on turn {turn} with no clear loading message. "
                            f"Notes: {last_notes}"
                        )
                        result["path_log"]["final_decider"] = "unknown"
                        break

                    applied_any = False
                    applied_confirm = False

                    for sel in selectors[:8]:
                        purpose = (sel.get("purpose") or "").lower()
                        ok = apply_selector(page, sel)

                        turn_rec["applied"].append({
                            "purpose": purpose,
                            "ok": bool(ok),
                            "type": (sel.get("type") or ""),
                            "selector": (sel.get("selector") or "")[:180],
                        })

                        if ok:
                            click_count += 1
                            applied_any = True
                            if purpose == "confirm":
                                applied_confirm = True

                    if applied_any:
                        try:
                            page.wait_for_timeout(2000)
                        except Exception:
                            pass

                        # After actions/navigation, refresh verify label and readiness
                        try:
                            executor_state["verify_label"] = resolve_visible_leaf_label(page, leaf_hint_for_ui, setting.name)
                        except Exception:
                            pass
                        verify_label = executor_state.get("verify_label") or setting.name
                        verify_ready = _label_is_actionably_visible(page, verify_label)

                    # If label not visible/ready yet, guide planner to navigate deeper
                    if applied_any and not verify_ready:
                        executor_state["feedback"] = (
                            "The target control is not visible/actionable on this page yet. "
                            "Navigate deeper (open submenu/modal) until the target control is visible, then toggle it."
                        )
                        last_notes += " | target not visible yet; navigate"
                        turn_rec["notes"] = last_notes
                        continue

                    # Deterministic verification FIRST
                    if applied_any and verify_label and verify_ready:
                        det = deterministic_matches_target(page, verify_label, target_value)
                        turn_rec["deterministic_check"] = det

                        if det is True:
                            result["status"] = "success"
                            result["details"] = (
                                "✅ Deterministic verification confirms the setting matches the target value. "
                                f"Notes: {last_notes}"
                            )
                            result["path_log"]["final_decider"] = "deterministic"
                            break

                        if det is False:
                            executor_state["feedback"] = (
                                "Deterministic verification indicates state != target. "
                                "Toggle the correct control and handle confirmation/save."
                            )
                            last_notes += " | deterministic != target"
                            turn_rec["notes"] = last_notes
                            continue

                    # Gemini verifier fallback (when not done)
                    if not done and applied_any and verify_label:
                        verified = verify_setting_state(page, platform, verify_label, target_value)
                        turn_rec["gemini_verify"] = verified

                        if verified is True:
                            result["status"] = "success"
                            result["details"] = (
                                "Executor verified visually after applying selectors (Gemini verifier fallback). "
                                f"Notes: {last_notes}"
                            )
                            result["path_log"]["final_decider"] = "gemini"
                            break

                        if verified is False:
                            executor_state["feedback"] = (
                                "After applying selectors, setting still appears NOT in requested state. "
                                "Try a more direct toggle and confirm/save if needed."
                            )
                            last_notes += " | gemini != target"
                            turn_rec["notes"] = last_notes
                            continue

                    # Planner says done
                    if done:
                        if applied_confirm:
                            result["status"] = "success"
                            result["details"] = (
                                "Planner reported done and a confirmation control was clicked; assuming success. "
                                f"Notes: {last_notes}"
                            )
                            result["path_log"]["final_decider"] = "assumed_confirm"
                            break

                        if not leaf_hint:
                            if applied_any:
                                result["status"] = "success"
                                result["details"] = (
                                    "Planner reported done and selectors were applied, but no leaf_hint for verification. "
                                    f"Assuming success. Notes: {last_notes}"
                                )
                                result["path_log"]["final_decider"] = "unknown"
                                break
                            else:
                                executor_state["feedback"] = "done=true but none of your selectors applied."
                                last_notes += " | done true but no apply"
                                turn_rec["notes"] = last_notes
                                continue

                        # Verify once using dynamic verify_label (better than raw leaf_hint)
                        verified = verify_setting_state(page, platform, executor_state.get("verify_label") or leaf_hint, target_value)
                        turn_rec["gemini_verify"] = verified

                        if verified is True:
                            result["status"] = "success"
                            result["details"] = (
                                "Planner reports done; verifier agrees setting matches target. "
                                f"Notes: {last_notes}"
                            )
                            result["path_log"]["final_decider"] = "gemini"
                            break

                        if verified is False:
                            executor_state["feedback"] = (
                                "After applying plan, setting still does not appear to match target. "
                                "Propose more direct steps to toggle and confirm."
                            )
                            last_notes += " | verifier != target"
                            turn_rec["notes"] = last_notes
                            continue

                        result["status"] = "uncertain"
                        result["details"] = (
                            "Planner reported done and selectors applied, but verifier couldn't determine final state. "
                            f"Notes: {last_notes}"
                        )
                        result["path_log"]["final_decider"] = "unknown"
                        break

                    # Nothing applied
                    if not applied_any:
                        if turn < max_turns:
                            executor_state["feedback"] = (
                                "None of your selectors matched clickable elements. "
                                "Propose alternative selectors; use coord only as last resort."
                            )
                            last_notes += f" | no selectors applied on turn {turn}"
                            turn_rec["notes"] = last_notes
                            continue

                        result["status"] = "uncertain"
                        result["details"] = (
                            f"No selectors applied successfully on turn {turn}, and max turns reached. "
                            f"Last planner notes: {last_notes}"
                        )
                        result["path_log"]["final_decider"] = "unknown"
                        break

                    continue

                finally:
                    try:
                        result["path_log"]["turns"].append(turn_rec)
                    except Exception:
                        pass

            else:
                if result["status"] != "success":
                    result["status"] = "uncertain"
                    result["details"] = (
                        f"Reached max planner turns ({max_turns}) without a clear success signal. "
                        f"Last planner notes: {last_notes}"
                    )
                    result["path_log"]["final_decider"] = "unknown"

            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    except Exception as e:
        result["status"] = "error"
        result["details"] = f"Playwright/Gemini execution error: {e}"
        result["path_log"]["final_decider"] = "unknown"

    result["click_count"] = click_count

    try:
        record_run_stats(
            platform=platform,
            setting=setting,
            target_value=target_value,
            status=result.get("status", "unknown"),
            click_count=int(result.get("click_count", 0)),
            path_log=result.get("path_log"),
        )
    except Exception as e:
        print("[stats] Failed to record run stats:", e)

    return result

def verify_setting_state(
    page: Page,
    platform: str,
    leaf_hint: Optional[str],
    target_value: str,
) -> Optional[bool]:
    """
    Use Gemini to visually verify whether the leaf setting is in the desired state.

    Returns:
      True  -> page appears to show the setting in the TARGET state
      False -> page appears to show the setting NOT in the TARGET state
      None  -> unable to determine
    """
    client = get_gemini_client()
    if not client or not leaf_hint:
        return None

    snap = page.screenshot(full_page=True)
    textmap = viewport_dom_textmap(page, max_items=120)
    outline = dom_outline(page, max_nodes=300)

    system_instruction = (
        "You are a visual inspector for privacy settings in a web UI.\n"
        "Return ONLY a JSON object (no markdown/fences/extra text):\n"
        "{\n"
        '  "state": "on" | "off" | "unknown",\n'
        '  "matches_target": true | false | null,\n'
        '  "confidence": <number between 0 and 1>,\n'
        '  "notes": "<short explanation>"\n'
        "}\n"
        "Rules:\n"
        "- If unsure: state=\"unknown\" and matches_target=null.\n"
        "- No extra keys.\n"
    )

    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"TARGET_LEAF_SETTING_NAME: {leaf_hint}\n"
        f"TARGET_VALUE: {target_value}\n\n"
        "DOM_TEXT_MAP (partial):\n" + textmap[:2000] +
        "\n\nDOM_OUTLINE (partial):\n" + outline[:2000] +
        "\n\nReturn the JSON object."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        max_output_tokens=400,
        response_mime_type="application/json",
    )

    try:
        resp = client.models.generate_content(
            model=MODEL_PLAN,
            contents=[Content(role="user", parts=[
                Part(text=user_prompt),
                Part.from_bytes(data=snap, mime_type="image/png"),
            ])],
            config=config,
        )
    except Exception:
        return None

    debug_print_gemini_response(resp, tag="verify_setting_state")

    raw = (extract_model_text(resp) or "").strip()
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    state = (data.get("state") or "").lower()
    matches_target = data.get("matches_target", None)

    if isinstance(matches_target, bool):
        return matches_target

    tv = (target_value or "").strip().lower()
    if tv in ("on", "enabled", "enable", "checked", "private"):
        if state == "on":
            return True
        if state == "off":
            return False
    if tv in ("off", "disabled", "disable", "unchecked", "public"):
        if state == "off":
            return True
        if state == "on":
            return False

    return None

# =========================
# Chainlit Handlers
# =========================

@cl.action_callback("browse_settings")
async def on_browse_settings(action: cl.Action):
    plat = cl.user_session.get(SESSION_ACTIVE_PLATFORM)
    if not plat:
        await cl.Message(content="Pick a platform first.").send()
        await prompt_pick_platform()
        return

    cl.user_session.set(SESSION_BROWSE_CATEGORY, "all")
    cl.user_session.set(SESSION_BROWSE_PAGE, 0)

    counts = category_counts_for_platform(plat)
    cats = categories_for_platform(plat)

    cat_actions = [pick_category_action("all", sum(counts.values()))]
    cat_actions += [pick_category_action(c, counts.get(c, 0)) for c in cats]

    await cl.Message(
        content=active_platform_banner() + "Choose a category to browse:",
        actions=[*cat_actions, change_platform_action(), set_gemini_key_action(), end_session_action()],
    ).send()

@cl.action_callback("pick_category")
async def on_pick_category(action: cl.Action):
    plat = cl.user_session.get(SESSION_ACTIVE_PLATFORM)
    if not plat:
        await prompt_pick_platform()
        return

    category = (action.payload or {}).get("category") or "all"
    cl.user_session.set(SESSION_BROWSE_CATEGORY, category)
    cl.user_session.set(SESSION_BROWSE_PAGE, 0)

    await show_settings_browser_page(plat)

async def show_settings_browser_page(platform: str):
    category = cl.user_session.get(SESSION_BROWSE_CATEGORY) or "all"
    page_idx = int(cl.user_session.get(SESSION_BROWSE_PAGE) or 0)

    entries = settings_for_platform_category(platform, category)

    per_page = 10
    start = page_idx * per_page
    page_items = entries[start:start + per_page]

    # Readable scrollbox (markdown fenced text block)
    scroll_box = render_scrollbox_settings(entries, max_lines=160)

    # Selection actions (these are handled by @cl.action_callback("pick_setting_ui"))
    select_actions: List[cl.Action] = []
    for i, e in enumerate(page_items, start=1):
        select_actions.append(
            cl.Action(
                name="pick_setting_ui",
                payload={"setting_id": e.setting_id},
                label=f"{i}. {e.name[:42]}",
            )
        )

    # Nav actions (handled by @cl.action_callback("browse_page"))
    nav_actions: List[cl.Action] = []
    if start > 0:
        nav_actions.append(cl.Action(name="browse_page", payload={"dir": "prev"}, label="◀ Prev"))
    if start + per_page < len(entries):
        nav_actions.append(cl.Action(name="browse_page", payload={"dir": "next"}, label="Next ▶"))

    # Small page table so buttons correspond to visible rows
    table_rows = []
    for i, e in enumerate(page_items, start=1):
        cat = e.category or "uncategorized"
        table_rows.append(f"| {i} | `{e.setting_id}` | {e.name} | `{cat}` |")
    page_table = (
        "| # | ID | Name | Category |\n"
        "|---:|---|---|---|\n"
        + ("\n".join(table_rows) if table_rows else "| - | - | (No items on this page) | - |")
    )

    cat_title = CATEGORY_TITLES.get(category, category)
    cat_help = CATEGORY_HELP.get(category, "")

    await cl.Message(
        content=(
            active_platform_banner()
            + f"**Browsing:** `{platform}`  |  **Category:** {cat_title}  |  **Page:** {page_idx + 1}\n\n"
            + (f"_{cat_help}_\n\n" if cat_help else "")
            + "\n\n**Current settings page:**\n"
            + page_table
            + "\n\nSelect a setting from this page:"
        ),
        actions=[
            *select_actions,
            *nav_actions,
            browse_settings_action(),
            change_platform_action(),
            set_gemini_key_action(),
            end_session_action(),
        ],
    ).send()



@cl.action_callback("browse_page")
async def on_browse_page(action: cl.Action):
    plat = cl.user_session.get(SESSION_ACTIVE_PLATFORM)
    if not plat:
        await prompt_pick_platform()
        return

    direction = (action.payload or {}).get("dir")
    page_idx = int(cl.user_session.get(SESSION_BROWSE_PAGE) or 0)
    if direction == "next":
        page_idx += 1
    elif direction == "prev" and page_idx > 0:
        page_idx -= 1

    cl.user_session.set(SESSION_BROWSE_PAGE, page_idx)
    await show_settings_browser_page(plat)

@cl.action_callback("pick_setting_ui")
async def on_pick_setting_ui(action: cl.Action):
    plat = cl.user_session.get(SESSION_ACTIVE_PLATFORM)
    if not plat:
        await prompt_pick_platform()
        return

    setting_id = (action.payload or {}).get("setting_id")
    if not setting_id:
        await cl.Message(content="Missing setting_id.").send()
        return

    setting = resolve_setting(plat, setting_id)
    if not setting:
        await cl.Message(content=f"Could not resolve setting `{setting_id}` on `{plat}`.").send()
        return

    cl.user_session.set(SESSION_SELECTED_SETTING_ID, setting.setting_id)
    cl.user_session.set(SESSION_SELECTED_PLATFORM, plat)

    # Value picker
    actions = [
        set_value_action("on"),
        set_value_action("off"),
        set_value_action("private"),
        set_value_action("public"),
        browse_settings_action(),
        change_platform_action(),
        set_gemini_key_action(),
        end_session_action(),
    ]

    await cl.Message(
        content=active_platform_banner()
        + f"Selected: **{setting.name}** (`{setting.setting_id}`)\n\nChoose the value:",
        actions=actions,
    ).send()

@cl.action_callback("set_value_ui")
async def on_set_value_ui(action: cl.Action):
    plat = cl.user_session.get(SESSION_SELECTED_PLATFORM)
    setting_id = cl.user_session.get(SESSION_SELECTED_SETTING_ID)
    value = (action.payload or {}).get("value")

    if not plat or not setting_id or not value:
        await cl.Message(content="Missing selection context. Please browse and select a setting again.").send()
        return

    setting = resolve_setting(plat, setting_id)
    if not setting:
        await cl.Message(content="Could not resolve selected setting.").send()
        return

    target_value = normalize_target_value(value) or value

    await cl.Message(
        content=active_platform_banner()
        + f"Ok — changing **{setting.name}** on `{plat}` to `{target_value}`…"
    ).send()

    # For UI-selection demo: leaf_hint should default to setting.name (deterministic)
    result = await cl.make_async(apply_setting_change_sync)(
        plat,
        setting,
        target_value,
        leaf_hint=setting.name
    )
    append_change(result)

    await cl.Message(
        content=active_platform_banner() + f"Result: status = `{result.get('status')}`\nDetails: {result.get('details')}",
        actions=[browse_settings_action(), change_platform_action(), set_gemini_key_action(), end_session_action()],
    ).send()


@cl.on_chat_start
async def on_chat_start():
    global SETTINGS_BY_PLATFORM
    if not SETTINGS_BY_PLATFORM:
        try:
            SETTINGS_BY_PLATFORM = load_settings_db()
        except Exception as e:
            await cl.Message(
                content=f"⚠️ Failed to load settings DB: `{e}`\n"
                        f"Expected at: `{SETTINGS_JSON_PATH}`"
            ).send()
            return

    cl.user_session.set(SESSION_CHANGES_KEY, [])
    touch_session_activity()

    # If env key exists, we can still use global client, but allow user to override per-session.
    # If no client at all, prompt for key.
    if not have_any_gemini_client():
        await cl.Message(
            content=(
                "⚠️ No Gemini API key is configured.\n\n"
                "Click **Set Gemini API key** at the bottom of the welcome message to provide one for this session only."
            )
        ).send()


    # Precompute cached setting snapshot + platform summaries for the dashboard UI.
    # IMPORTANT: snapshot file is only written if content differs.
    try:
        snapshot = export_all_settings_snapshot()
        snapshot_changed = cache_write_json_if_changed(SETTINGS_SNAPSHOT_PATH, snapshot)

        # Only regenerate summaries if snapshot changed OR summaries missing.
        if snapshot_changed or not PLATFORM_SUMMARIES_PATH.exists():
            summaries = build_platform_summaries(SETTINGS_BY_PLATFORM, RUN_STATS_PATH)
            cache_write_json_if_changed(PLATFORM_SUMMARIES_PATH, summaries)
    except Exception as e:
        print("[cache] Failed to update settings snapshot/summaries:", e)


    plats = list_platforms()
    plat_list = "\n".join(f"- `{p}`" for p in plats) if plats else "_None loaded_"

    help_text = (
        "Welcome to the Agentic Privacy Control Center! \n\n"
        "Be sure to set your Gemini API key before starting (it will auto-wipe on session end or upon user request.)\n\n"
        "You can interact with this chatbot in two ways:\n\n"
        "✅ **Recommended:** Click **Browse settings** after choosing a platform to select a setting from the database.\n"
        "⚙️ **Alternative (Commands):** Use `settings <platform>` and `change <platform> <setting_id> to <value>`.\n"
        "🔧 **Command-based (advanced):**\n"
        "- `platforms` — list all supported platforms\n"
        "- `settings <platform>` — list known settings for a platform\n"
        "- `change <platform> <section_id_or_name> to <value>`\n"
        "- `change <platform> <section_id_or_name>::<leaf_setting_name> to <value>`\n"
        "- `report` — show a summary of this session's changes\n\n"
        
    )

    #DEBUG add into help_text:
    # "Supported platforms currently loaded:\n"
    #     + "\n".join(f"- `{p}`" for p in plats)


    await cl.Message(
        help_text,
    ).send()
    await prompt_pick_platform()




@cl.on_message
async def on_message(message: cl.Message):
    text = (message.content or "").strip()
    if not text:
        await cl.Message(content="Please enter a command or request.").send()
        return

    # Idle timeout: wipe session key/client if user was away too long
    if is_session_timed_out():
        wipe_session_gemini()
        touch_session_activity()
        await cl.Message(
            content=(
                "⏳ Session timed out due to inactivity. Your Gemini key was wiped from memory.\n\n"
                "Click **Set Gemini API key** to continue."
            ),
            actions=[set_gemini_key_action(), end_session_action(), change_platform_action()],
        ).send()
        return

    touch_session_activity()

    # If we are awaiting the key, treat this message as the key itself.
    if cl.user_session.get(SESSION_AWAITING_GEMINI_KEY):
        key = text.strip()
        cl.user_session.set(SESSION_AWAITING_GEMINI_KEY, False)

        # Minimal validation: looks like a non-trivial token
        if len(key) < 20:
            await cl.Message(
                content="That doesn’t look like a valid API key (too short). Try again: click **Set Gemini API key**.",
                actions=[set_gemini_key_action(), end_session_action()],
            ).send()
            return

        try:
            # Store in session memory only
            cl.user_session.set(SESSION_GEMINI_API_KEY, key)
            cl.user_session.set(SESSION_GEMINI_CLIENT, genai.Client(api_key=key))
        except Exception as e:
            wipe_session_gemini()
            await cl.Message(
                content=f"Failed to initialize Gemini client with that key. Error: {e}",
                actions=[set_gemini_key_action(), end_session_action()],
            ).send()
            return

        await cl.Message(
            content="✅ Gemini API key set for this session (memory only). You can proceed.",
            actions=[end_session_action(), change_platform_action()],
        ).send()

        # Optionally continue pending NL request if user was blocked earlier
        return


    lower = text.lower().strip()

    if lower in ("change platform", "switch platform", "platform"):
        await prompt_pick_platform()
        return

    # ---------------------------------------------------------------------
    # Debug command: dump_settings -> export current settings DB to JSON file
    # ---------------------------------------------------------------------
    if lower == "dump_settings":
        data = export_all_settings_snapshot()
        changed = cache_write_json_if_changed(SETTINGS_SNAPSHOT_PATH, data)

        # Summaries depend on the snapshot (and run stats)
        summaries = build_platform_summaries(SETTINGS_BY_PLATFORM, RUN_STATS_PATH)
        summaries_changed = cache_write_json_if_changed(PLATFORM_SUMMARIES_PATH, summaries)

        msg = f"Snapshot {'updated' if changed else 'unchanged'} at `{SETTINGS_SNAPSHOT_PATH}`.\n"
        msg += f"Summaries {'updated' if summaries_changed else 'unchanged'} at `{PLATFORM_SUMMARIES_PATH}`."
        await cl.Message(content=msg).send()
        return

    # ---------------------------------------------------------------------
    # 0) If we previously asked for a missing value after a setting pick (typed reply)
    # ---------------------------------------------------------------------
    pending = cl.user_session.get("final_setting_to_change")
    if pending and lower in ("on", "off", "private", "public", "enable", "disable", "enabled", "disabled"):
        target_value = normalize_target_value(lower)
        platform = pending["platform"]
        setting = resolve_setting(platform, pending["setting_id"])
        cl.user_session.set("final_setting_to_change", None)

        if not setting or not target_value:
            await cl.Message(content="Sorry — I couldn’t parse that value. Try `on/off/private/public`.").send()
            return

        await cl.Message(content=f"Ok — changing **{setting.name}** on `{platform}` to `{target_value}`…").send()
        result = await cl.make_async(apply_setting_change_sync)(
            platform, setting, target_value, leaf_hint=cl.user_session.get("inferred_leaf_hint") or setting.name
        )
        append_change(result)
        await cl.Message(
            content=active_platform_banner() + f"Result: status = `{result.get('status')}`\nDetails: {result.get('details')}",
            actions=[change_platform_action()]
        ).send()

        return

    # ---------------------------------------------------------------------
    # 1) Commands
    # ---------------------------------------------------------------------
    if lower == "platforms":
        plats = list_platforms()
        if not plats:
            await cl.Message(content="No platforms found in the settings DB.").send()
            return
        await cl.Message(content="Supported platforms:\n" + "\n".join(f"- `{p}`" for p in plats)).send()
        return

    if lower.startswith("settings "):
        _, rest = text.split(" ", 1)
        plat_alias = find_platform_alias(rest)
        if not plat_alias:
            await cl.Message(
                content=f"I couldn't find a platform matching `{rest}`. Try one of: {', '.join(list_platforms())}"
            ).send()
            return
        settings = list_settings_for_platform(plat_alias)
        md = format_settings_table(settings)
        await cl.Message(content=f"Settings for **{plat_alias}**:\n\n{md}").send()
        return

    if lower == "report":
        changes = get_changes_log()
        md = build_session_report_md(changes)
        await cl.Message(content="Here is your session report:\n\n" + md).send()
        return

    # ---------------------------------------------------------------------
    # 2) Advanced command: change <platform> <section_id_or_name>[::leaf] to <value>
    # ---------------------------------------------------------------------
    if lower.startswith("change "):
        try:
            _, rest = text.split(" ", 1)
            if " to " not in rest.lower():
                raise ValueError

            before_to, target_value = rest.rsplit(" to ", 1)
            before_to = before_to.strip()
            target_value = target_value.strip()

            parts = before_to.split(" ", 1)
            if len(parts) < 2:
                raise ValueError

            platform_part, setting_spec = parts[0], parts[1]

            plat_alias = find_platform_alias(platform_part)
            if not plat_alias:
                await cl.Message(
                    content=f"I couldn't find a platform matching `{platform_part}`. Try one of: {', '.join(list_platforms())}"
                ).send()
                return

            section_query = setting_spec
            leaf_hint = None

            if "::" in setting_spec:
                section_query, leaf_raw = setting_spec.split("::", 1)
                section_query = section_query.strip()
                leaf_hint = leaf_raw.strip() or None

            # Resolve section
            if "::" in setting_spec:
                setting, _ = resolve_setting_flexible(plat_alias, section_query)
            else:
                setting, leaf_hint = resolve_setting_flexible(plat_alias, section_query)

            if not setting:
                await cl.Message(
                    content=(
                        f"I couldn't map `{section_query}` to any known section on `{plat_alias}`.\n"
                        f"Use `settings {plat_alias}` to see available top-level sections."
                    )
                ).send()
                return

            leaf_line = f"- **Leaf hint:** `{leaf_hint}`\n" if leaf_hint else ""
            await cl.Message(
                content=(
                    f"Got it. I'll attempt the following change using Playwright + Gemini:\n\n"
                    f"- **Platform:** `{plat_alias}`\n"
                    f"- **Section:** {setting.name} (`{setting.setting_id}`)\n"
                    f"{leaf_line}"
                    f"- **Requested value:** `{target_value}`\n\n"
                    f"URL from DB: `{setting.raw.get('url')}`"
                )
            ).send()

            cl.user_session.set("last_entrypoint", "command")
            cl.user_session.set("last_candidate_source", "deterministic")
            cl.user_session.set("last_leaf_hint_source", "derived" if leaf_hint else "setting_name")

            result = await cl.make_async(apply_setting_change_sync)(
                plat_alias,
                setting,
                target_value,
                leaf_hint=leaf_hint,
            )
            append_change(result)

            await cl.Message(
                content=active_platform_banner() + f"Result: status = `{result.get('status')}`\nDetails: {result.get('details')}",
                actions=[change_platform_action()]
            ).send()
            return

        except ValueError:
            await cl.Message(
                content=(
                    "I couldn't parse that `change` command.\n"
                    "Use one of these formats:\n"
                    "- `change <platform> <section_id_or_name> to <value>`\n"
                    "- `change <platform> <section_id_or_name>::<leaf_setting_name> to <value>`\n\n"
                    "Example:\n"
                    "`change twitterX audience__media_and_tagging::Protect your posts to on`"
                )
            ).send()
            return

    # ---------------------------------------------------------------------
    # 3) Platform-first Natural Language flow (platform-scoped Gemini + DB)
    # ---------------------------------------------------------------------
    

    active_plat = cl.user_session.get(SESSION_ACTIVE_PLATFORM)

    if not active_plat:
        cl.user_session.set(SESSION_PENDING_NL_TEXT, text)
        await prompt_pick_platform()
        return

    if ENABLE_NLP:
        await handle_platform_scoped_nl(active_plat, text)
        return

    # Demo mode: commands + UI browse only
    await cl.Message(
        content=active_platform_banner()
        + "Use **Browse settings** (buttons) or the `change ...` advanced commands.\n\n"
        + "Examples:\n"
        + "- `settings instagram`\n"
        + "- `change instagram private_account to on`\n",
        actions=[browse_settings_action(), change_platform_action(), set_gemini_key_action(), end_session_action()],
    ).send()
    return


@cl.on_chat_end
async def on_chat_end():
    # Best-effort wipe on chat end
    wipe_session_gemini()
    print("[session] Wiped Gemini API key/client on chat end.")

@cl.on_app_shutdown
async def on_app_shutdown():
    wipe_session_gemini()
    print("[session] Wiped Gemini API key/client on app shutdown.")
