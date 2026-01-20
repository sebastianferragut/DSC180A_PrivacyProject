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
import time


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
SESSION_ACTIVE_PLATFORM = "active_platform"
SESSION_PENDING_NL_TEXT = "pending_nl_text"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not set. Setting changes will fail until it is provided.")

MODEL_PLAN = os.environ.get("MODEL_PLAN", "gemini-2.5-pro")

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

def record_run_stats(
    *,
    platform: str,
    setting: SettingEntry,
    target_value: str,
    status: str,
    click_count: int,
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
        target_value = normalize_target_value(lower)

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
        if sc > 5.0:
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

async def present_candidates(platform: str, query: str, candidates: List[SettingEntry], target_value: Optional[str]):
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


@cl.action_callback("change_platform")
async def on_change_platform(action: cl.Action):
    # Show the platform picker without requiring any user text
    await prompt_pick_platform()

@cl.action_callback("none_match")
async def on_none_match(action: cl.Action):
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
        actions=[change_platform_action()]
    ).send()


@cl.action_callback("pick_setting")
async def on_pick_setting(action: cl.Action):
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

    # Store pending confirmation (setting inferred from user intent)
    cl.user_session.set(SESSION_PENDING_CONFIRM, {"platform": platform, "setting_id": setting.setting_id})

    suggested = cl.user_session.get(SESSION_PENDING_VALUE_KEY)

    actions = [
        cl.Action(name="confirm_setting", payload={"confirm": True}, label="Confirm"),
        cl.Action(name="confirm_setting", payload={"confirm": False}, label="Cancel"),
        change_platform_action(),
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
        content="Pick a platform to work on:",
        actions=actions
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
        await cl.Message(
            content=active_platform_banner() + f"Platform set to `{plat}`. Continuing with your request…",
            actions=[change_platform_action()],
        ).send()
        await handle_platform_scoped_nl(plat, pending_text)
        return

    await cl.Message(
        content=active_platform_banner()
        + f"Platform set to `{plat}`.\n\nNow tell me what setting you want to change (in normal language). This works best if you follow the structure: Turn my [setting name] to [desired state].",
        actions=[change_platform_action()],
    ).send()

@cl.action_callback("confirm_setting")
async def on_confirm_setting(action: cl.Action):
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

    # If confirmed, proceed to value selection (same as your previous step)
    actions = [
        cl.Action(name="pick_value", payload={"value": "on"}, label="On"),
        cl.Action(name="pick_value", payload={"value": "off"}, label="Off"),
        cl.Action(name="pick_value", payload={"value": "private"}, label="Private"),
        cl.Action(name="pick_value", payload={"value": "public"}, label="Public"),
        cl.Action(name="pick_value", payload={"value": "cancel"}, label="Cancel"),
        change_platform_action(),
    ]

    # store final setting for value step
    cl.user_session.set("final_setting_to_change", {"platform": platform, "setting_id": setting.setting_id})

    suggested = cl.user_session.get(SESSION_PENDING_VALUE_KEY)
    hint_line = f"\n\nSuggested from your message: `{suggested}`" if suggested else ""

    await cl.Message(
        content=active_platform_banner()
        + f"Confirmed: **{setting.name}** (`{setting.setting_id}`)"
        + hint_line
        + "\n\nWhat do you want to change it to?",
        actions=actions
    ).send()

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

    IMPORTANT: Robust JSON parsing (handles fences / extra text).
    """
    if not client:
        return {"setting_ids": [], "target_value": None}

    # Limit candidates to reduce token load
    candidates = candidates[:30]

    # Build compact candidate list for prompt (truncate descriptions!)
    cand_payload = [
        {
            "setting_id": c.setting_id,
            "name": c.name,
            "description": (c.description or "")[:160],
            "category": c.category or "",
        }
        for c in candidates
    ]

    system_instruction = (
        "You map a natural language privacy-setting request to database entries.\n"
        "You MUST choose only from the provided CANDIDATES list.\n\n"
        "Return STRICT JSON ONLY (no markdown fences, no extra text):\n"
        "{\n"
        '  "setting_ids": ["id1","id2","id3"],\n'
        '  "target_value": "on"|"off"|null,\n'
        '  "reason": "<short>"\n'
        "}\n\n"
        "Rules:\n"
        "- Choose up to 3 setting_ids from CANDIDATES.\n"
        "- If the user implies enable/disable/private/public, set target_value; else null.\n"
        "- If nothing matches, return setting_ids: []\n"
    )

    prompt = (
        f"PLATFORM: {platform}\n"
        f"USER_TEXT: {user_text}\n\n"
        "CANDIDATES:\n" + json.dumps(cand_payload, ensure_ascii=False)
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        max_output_tokens=300,
    )

    try:
        resp = client.models.generate_content(
            model=MODEL_PLAN,
            contents=[Content(role="user", parts=[Part(text=prompt)])],
            config=config,
        )
    except Exception as e:
        print("[gemini_pick_candidates] model error:", e)
        return {"setting_ids": [], "target_value": None}

    # Extract text
    out = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            if parts:
                for part in parts:
                    if getattr(part, "text", None):
                        out += part.text
        out = (out or "").strip()
    except Exception as e:
        print("[gemini_pick_candidates] extraction error:", e)
        out = ""

    if not out:
        print("[gemini_pick_candidates] empty output from model")
        return {"setting_ids": [], "target_value": None}

    print("DEBUG AT LINE 803")
    print("[gemini_pick_candidates] raw model output (first 300 chars):", out[:300])

    # Robust JSON salvage (handles ```json fences and extra text)
    raw = out.strip()
    try:
        data = json.loads(raw)
    except Exception:
        # strip fences
        if raw.startswith("```"):
            raw2 = raw.strip("`")
            # remove leading language tag line if present
            raw2 = re.sub(r"^\s*json\s*", "", raw2, flags=re.I)
            raw = raw2.strip()

        # extract first {...} block
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            print("[gemini_pick_candidates] could not find JSON object in output:", raw[:200])
            return {"setting_ids": [], "target_value": None}
        try:
            data = json.loads(m.group(0))
        except Exception as e:
            print("[gemini_pick_candidates] JSON parse failed:", e, "raw:", raw[:200])
            return {"setting_ids": [], "target_value": None}

    setting_ids = data.get("setting_ids") or []
    target_value = data.get("target_value")

    # Dedupe + keep only valid IDs from the candidates list
    valid_ids = {c["setting_id"] for c in cand_payload}
    cleaned = []
    for sid in setting_ids:
        if sid in valid_ids and sid not in cleaned:
            cleaned.append(sid)

    return {"setting_ids": cleaned[:3], "target_value": target_value}
    
async def handle_platform_scoped_nl(platform: str, user_text: str):
    # Prefilter to top ~50 for prompt size
    pre = prefilter_platform_settings(platform, user_text, k=50)

    pick = gemini_pick_candidates_for_platform(platform, user_text, pre)
    setting_ids = pick.get("setting_ids") or []
    target_value = pick.get("target_value")

    if not setting_ids:
        # deterministic fallback if Gemini fails/overloaded
        fallback = find_setting_candidates(platform, user_text, limit=3)
        if fallback:
            await present_candidates(platform, user_text, fallback, target_value=None)
            return

        await cl.Message(
            content=(
                f"I couldn’t find likely matches for **{user_text}** on `{platform}`.\n\n"
                "Try rephrasing or use the exact label you see in the settings page."
            ),
            actions=[change_platform_action()],
        ).send()
        return


    # Resolve SettingEntry objects in the order Gemini returned
    id_map = {s.setting_id: s for s in pre}
    candidates = [id_map[sid] for sid in setting_ids if sid in id_map]

    await present_candidates(platform, user_text, candidates, target_value)


@cl.action_callback("pick_platform")
async def on_pick_platform(action: cl.Action):
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
        leaf_hint=setting.name
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
    if not client:
        return {"platform_hint": None, "setting_query": None, "target_value": None}

    system_instruction = (
        "You are a parser for natural-language requests about changing privacy/account settings.\n"
        "Extract:\n"
        "- platform_hint: one of the known platforms if mentioned\n"
        "- setting_query: a short normalized setting label/phrase (no platform words)\n"
        "- target_value: one of {on, off, private, public} if implied\n\n"
        "Return STRICT JSON ONLY:\n"
        "{\n"
        '  "platform_hint": string|null,\n'
        '  "setting_query": string|null,\n'
        '  "target_value": "on"|"off"|"private"|"public"|null\n'
        "}\n"
        "Rules:\n"
        "- If the user says 'make my posts protected' on Twitter/X, setting_query should become something like "
        "'Protect your posts'.\n"
        "- Remove phrases like 'on reddit', 'on twitter', etc. from setting_query.\n"
        "- If platform isn't mentioned, platform_hint must be null.\n"
        "- If target state isn't mentioned, target_value must be null.\n"
        "- No markdown fences.\n"
    )

    prompt = (
        "KNOWN_PLATFORMS:\n" + json.dumps(known_platforms, ensure_ascii=False) + "\n\n"
        "USER_TEXT:\n" + user_text
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        max_output_tokens=250,
    )

    try:
        resp = client.models.generate_content(
            model=MODEL_PLAN,
            contents=[Content(role="user", parts=[Part(text=prompt)])],
            config=config,
        )
    except Exception as e:
        return {"platform_hint": None, "setting_query": None, "target_value": None, "error": str(e)}

    # extract text
    out = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            if parts:
                for part in parts:
                    if getattr(part, "text", None):
                        out += part.text
        out = (out or "").strip()
    except Exception:
        out = ""

    # parse json robustly
    try:
        data = json.loads(out)
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

    Example:
      platform = "twitterX"
      user_query = "Protect your posts"

    DB has sections like "Audience, media and tagging", "Mute and block", etc.
    Gemini picks the best one.
    """
    if not client:
        return None

    settings = list_settings_for_platform(platform)
    if not settings:
        return None

    # Build a compact list of candidates for Gemini to choose from
    candidates = [
        {
            "setting_id": s.setting_id,
            "name": s.name,
            "category": s.category,
            "description": s.description,
        }
        for s in settings
    ]

    system_instruction = (
        "You are a routing assistant for privacy settings.\n"
        "You receive:\n"
        "- A PLATFORM name\n"
        "- A USER_QUERY describing a leaf-level setting or goal\n"
        "- A list of CANDIDATE_SECTIONS from our database (higher-level sections)\n\n"
        "Your job is to choose the SINGLE best section from the candidates that a UI automation\n"
        "agent should start from to fulfill the user's request.\n\n"
        "Return ONLY a JSON object of the form:\n"
        "{\n"
        '  "setting_id": "<the best candidate setting_id>",\n'
        '  "reason": "<short why>"\n'
        "}\n"
    )

    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"USER_QUERY: {user_query}\n\n"
        "CANDIDATE_SECTIONS:\n"
        + json.dumps(candidates, ensure_ascii=False)
        + "\n\n"
        "Pick the single best section_id."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        max_output_tokens=400,
    )

    try:
        resp = client.models.generate_content(
            model=MODEL_PLAN,
            contents=[Content(role="user", parts=[Part(text=user_prompt)])],
            config=config,
        )
    except Exception:
        return None

    text = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return None
        first = cands[0]
        content = getattr(first, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if parts:
            for part in parts:
                if getattr(part, "text", None):
                    text += part.text
        else:
            cand_text = getattr(first, "text", None)
            if isinstance(cand_text, str):
                text = cand_text
    except Exception:
        return None

    try:
        data = json.loads(text)
        sid = data.get("setting_id")
        if not sid:
            return None
        # Find that setting_id in our existing list
        for s in settings:
            if s.setting_id == sid:
                return s
    except Exception:
        return None

    return None


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


    # Debug: see what URL we picked
    try:
        print(
            f"[resolver] platform={platform} section_query={sq!r} leaf_hint={lh!r} "
            f"-> best_score={best_score:.3f}, url={_entry_url(best_entry)}"
        )
    except Exception:
        pass

    # 4) Return the chosen entry (SettingEntry or dict) and the leaf_hint unchanged
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


def apply_selector(page: Page, sel: Dict[str, Any]) -> bool:
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
            label_loc = page.get_by_text(sval, exact=True)
            if not label_loc.count():
                label_loc = page.get_by_text(sval, exact=False)

            count = label_loc.count()
            print(f"[apply_selector] text locator matched {count} element(s)")

            if count:
                label_loc.first.click(timeout=3500)
                return True

        elif stype == "role":
            loc = page.locator(sval)
            count = loc.count()
            print(f"[apply_selector] role '{sval}' -> {count} matches")
            if count:
                loc.first.click(timeout=3500)
                return True

        elif stype == "coord":
            if sval.startswith("label:"):
                label_text = sval[len("label:"):].strip()
                print(f"[apply_selector] coord label-mode for {label_text!r}")

                # 1) Find the label by visible text
                label_loc = page.get_by_text(label_text, exact=True)
                if not label_loc.count():
                    label_loc = page.get_by_text(label_text, exact=False)

                if not label_loc.count():
                    print(f"[apply_selector] No label found for {label_text!r}")
                    return False

                label = label_loc.first
                label_box = label.bounding_box()
                if not label_box:
                    print("[apply_selector] No bounding_box for label")
                    return False

                label_right = label_box["x"] + label_box["width"]
                label_center_y = label_box["y"] + label_box["height"] / 2.0

                # 2) Find candidate controls
                candidates_selector = (
                    "input,button,"
                    "[role='switch'],[role='checkbox'],[role='radio'],"
                    "[role='button'],[aria-checked]"
                )
                cand_loc = page.locator(candidates_selector)
                total = cand_loc.count()
                print(f"[apply_selector] searching {total} candidate controls near label {label_text!r}")

                best_box = None
                best_dx = float("inf")
                max_to_check = min(total, 60)

                for i in range(max_to_check):
                    el = cand_loc.nth(i)
                    box = el.bounding_box()
                    if not box:
                        continue

                    # Must be to the right of the label
                    dx = box["x"] - label_right
                    if dx < 0:
                        continue

                    # Must overlap vertically with label row
                    if not (box["y"] <= label_center_y <= (box["y"] + box["height"])):
                        continue

                    # Choose nearest to the right
                    if dx < best_dx:
                        best_dx = dx
                        best_box = box

                if best_box:
                    cx = best_box["x"] + best_box["width"] / 2.0
                    cy = best_box["y"] + best_box["height"] / 2.0
                    print(f"[apply_selector] Clicking center of nearest control at ({cx}, {cy})")
                    page.mouse.click(cx, cy)
                    return True

                print("[apply_selector] No suitable control found near label.")
                return False

            # else: raw numeric "x,y"


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
    Returns a plan dict:
    {
      "selectors": [ { "type": "text"|"css"|"role", "selector": "...", "purpose": "..." }, ... ],
      "done": bool,
      "notes": str
    }
    """
    if not client:
        return {
            "selectors": [],
            "done": True,
            "notes": "Gemini client not configured (no API key)."
        }

    snap = page.screenshot(full_page=True)
    textmap = viewport_dom_textmap(page, max_items=120)
    outline = dom_outline(page, max_nodes=300)

    system_instruction = (
        "You are a UI control agent operating in a desktop browser.\n"
        "Your sole job is to help an executor change a SINGLE privacy/data setting on the current page.\n\n"
        "You are given:\n"
        "- PLATFORM name\n"
        "- TARGET_SECTION_SETTING_NAME and description (a broader settings area)\n"
        "- Optional TARGET_LEAF_SETTING_NAME (the specific toggle like 'Protect your posts')\n"
        "- TARGET_VALUE (e.g., 'on', 'off', 'friends only', 'private')\n"
        "- A screenshot of the current page\n"
        "- DOM_TEXT_MAP: visible texts from headings, buttons, tabs, etc.\n"
        "- DOM_OUTLINE: compact JSON of clickable/role-based elements.\n"
        "- EXECUTOR_STATE_JSON: the executor's state + feedback from previous turns.\n\n"
        "You MUST return a SINGLE, STRICT JSON object of the form:\n"
        "{\n"
        "  \"selectors\": [\n"
        "    {\n"
        "      \"purpose\": \"open_setting_group\" | \"change_value\" | \"confirm\" | \"scroll\" | \"other\",\n"
        "      \"type\": \"text\" | \"css\" | \"role\" | \"coord\",\n"
        "      \"selector\": \"<string to pass to a Playwright-like locator>\"\n"
        "    },\n"
        "    ...\n"
        "  ],\n"
        "  \"done\": true or false,\n"
        "  \"notes\": \"<short explanation>\"\n"
        "}\n\n"
        "STRICT OUTPUT RULES:\n"
        "- DO NOT wrap the JSON in ```json fences or any markdown.\n"
        "- DO NOT include any text before or after the JSON object.\n"
        "- Your response MUST be parseable by JSON.parse with no changes.\n\n"
        "SEMANTIC RULES:\n"
        "- Your selectors must include ALL steps needed to actually set the target setting to TARGET_VALUE.\n"
        "- It is NOT enough to simply navigate to a page where the setting is visible.\n"
        "- If TARGET_LEAF_SETTING_NAME is provided (e.g. 'Protect your posts'):\n"
        "    * You MUST include at least one selector with purpose=\"change_value\" that directly operates on\n"
        "      the control associated with that leaf setting (for example, clicking its label or toggle).\n"
        "- Only set done=true AFTER you have provided selectors that would actually change the value AND\n"
        "  handled any necessary confirmations or save/apply actions.\n"
        "- DO NOT merely describe actions in notes; every action must be encoded as a selector.\n"
        "- If you are unsure, set done=false and propose the next best selectors rather than claiming success.\n\n"
        "- As a last resort, for selection you may use coordinate clicks. \n"
        "CONFIRMATION / SAVE FLOWS:\n"
        "- Some settings show a confirmation dialog, banner, or modal after you change a toggle (e.g., a popup\n"
        "  with buttons like 'Save', 'Apply', 'Confirm', 'OK', 'Got it').\n"
        "- When a confirmation UI is visible and it is required for the change to take effect, you MUST include\n"
        "  one or more selectors with purpose=\"confirm\" that click the appropriate confirmation control\n"
        "  (for example, the primary button labeled 'Save' or 'Confirm').\n"
        "- If the current turn follows a previous turn where the toggle was clicked, FIRST look for any such\n"
        "  confirmation elements on the screen and include confirm selectors before marking done=true.\n"
        "- Never click 'Cancel' or equivalent when the goal is to apply the change.\n\n"
        "- If text/role/css selectors are not sufficient to reliably click the confirmation control, you MAY use\n"
        "  a selector with type=\"coord\" and a \"selector\" string like \"x,y\" giving approximate viewport coordinates \n"
        "  for the control. Use coord selectors only as a last resort when semantic selectors fail.\n\n"

        "EXECUTOR FEEDBACK:\n"
        "- The EXECUTOR_STATE_JSON may include a \"feedback\" field describing why your last plan did not work\n"
        "  (for example, the setting did not actually change to the target value). You MUST read and respond\n        "
        "  to this feedback by proposing more direct or corrective selectors.\n"
        "- For example, if feedback says the state did not change, consider:\n"
        "    * Clicking the toggle again more directly (different selector).\n"
        "    * Looking for a confirmation dialog or save/apply button and adding purpose=\"confirm\" selectors.\n"
        "    * Scrolling the page to bring the setting fully into view before interacting.\n"
    )




    leaf_line = f"TARGET_LEAF_SETTING_NAME: {leaf_hint}\n" if leaf_hint else ""

    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"CURRENT_URL: {page.url}\n"
        f"TARGET_SECTION_SETTING_NAME: {setting.name}\n"
        f"TARGET_SECTION_SETTING_DESCRIPTION: {setting.description or ''}\n"
        + leaf_line +
        f"TARGET_VALUE: {target_value}\n\n"
        "EXECUTOR_STATE (may be empty or partial):\n"
        + json.dumps(executor_state, ensure_ascii=False)
        + "\n\n"
        "If a leaf setting name is provided, focus specifically on that control inside the broader section.\n"
        "Return ONLY a JSON object as described."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.2,
        max_output_tokens=800,
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
        try:
            md = getattr(resp, "usage_metadata", None) or getattr(resp, "usage", None)
            cands = getattr(resp, "candidates", None) or []
            print(
                "[planner_setting_change] Gemini response: "
                f"usage={md}, candidates={len(cands)}"
            )
        except Exception as dbg_e:
            print("[planner_setting_change] Could not introspect resp:", repr(dbg_e))
    except Exception as e:
        print("[planner_setting_change] Gemini error:", e)

        # If we have a leaf_hint, fall back to a coord selector around that label
        if leaf_hint:
            return {
                "selectors": [
                    {
                        "purpose": "change_value",
                        "type": "coord",
                        "selector": f"label:{leaf_hint}",
                    }
                ],
                "done": False,
                "notes": (
                    f"model_error: {e}; using fallback coord selector around label "
                    f"'{leaf_hint}'."
                ),
            }

        # No leaf_hint -> nothing actionable
        return {
            "selectors": [],
            "done": False,
            "notes": f"model_error: {e}",
        }


    # Extract text
    text = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            first = cands[0]
            content = getattr(first, "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            if parts:
                for part in parts:
                    if getattr(part, "text", None):
                        text += part.text
            else:
                cand_text = getattr(first, "text", None)
                if isinstance(cand_text, str):
                    text = cand_text
    except Exception as e:
        print("[planner_setting_change] Text extraction error:", e)
        return {
            "selectors": [],
            "done": False,
            "notes": f"model_text_error: {e}",
        }

    raw = (text or "").strip()
    if not raw:
        print("[planner_setting_change] Empty model output.")

        if leaf_hint:
            # Fallback coord selector around the label text
            return {
                "selectors": [
                    {
                        "purpose": "change_value",
                        "type": "coord",
                        "selector": f"label:{leaf_hint}",
                    }
                ],
                "done": False,
                "notes": (
                    "model_empty_output: planner received no text; using fallback coord "
                    f"selector around label '{leaf_hint}'."
                ),
            }

        # No leaf_hint -> nothing we can synthesize
        return {
            "selectors": [],
            "done": False,
            "notes": "model_empty_output: planner received no text from Gemini.",
        }



    # Try to parse JSON (with fences salvage)
    try:
        data = json.loads(raw)
    except Exception as e1:
        try:
            if raw.startswith("```"):
                parts = raw.split("```", 2)
                raw_inner = parts[1] if len(parts) > 1 else raw
                raw_inner = raw_inner.lstrip("json").lstrip("js").lstrip("python")
                raw_inner = raw_inner.strip()
                if raw_inner.endswith("```"):
                    raw_inner = raw_inner.rsplit("```", 1)[0].strip()
                raw = raw_inner

            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{.*\}", raw, flags=re.S)
                if not m:
                    raise
                json_str = m.group(0)
                data = json.loads(json_str)
        except Exception as e2:
            print("[planner_setting_change] JSON parse error:", e2, "raw:", raw[:200])

            # ---  fallback when JSON is broken but we have a leaf_hint ---
            if leaf_hint:
                # Use a synthetic coord selector that our executor understands as:
                # "click near the control associated with this label text".
                return {
                    "selectors": [
                        {
                            "purpose": "change_value",
                            "type": "coord",
                            "selector": f"label:{leaf_hint}", 
                        }
                    ],
                    "done": False,
                    "notes": (
                        "Failed to parse JSON from Gemini; using fallback coord selector "
                        f"around label '{leaf_hint}'. Original parse error: {e2}"
                    ),
                }

            # No leaf_hint -> we really have nothing actionable.
            return {
                "selectors": [],
                "done": False,
                "notes": f"Failed to parse JSON from Gemini: {e2}; raw: {raw[:200]}"
            }

    if not isinstance(data, dict):
        print("[planner_setting_change] Non-dict planner output.")
        return {
            "selectors": [],
            "done": False,
            "notes": "Planner output was not a JSON object.",
        }

    data.setdefault("selectors", [])
    data.setdefault("done", False)
    data.setdefault("notes", "")

    selectors = data.get("selectors") or []
    has_effective = any(
        (s.get("purpose") or "").lower() in ("change_value", "confirm")
        for s in selectors
    )

    if data["done"] and not has_effective:
        data["done"] = False
        data["notes"] = (
            data.get("notes", "") +
            " | Enforcement: done set to false because no change_value/confirm selector was provided."
        )

    return data






# =========================
# Setting change executor (Playwright + Gemini)
# =========================

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
    result = {
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
    }


    if not GEMINI_API_KEY or not client:
        result["details"] = "GEMINI_API_KEY not configured; cannot run planner."
        return result

    url = setting.raw.get("url")
    if not url:
        result["details"] = "No URL found for this setting in DB."
        return result
    result["url"] = url

    # Map URL host to storage_state file
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
    }


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

            # Try to wait for the SPA / dynamic content to settle a bit more.
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                # Some sites never hit true "networkidle" – that's fine, we just move on.
                pass

            # Small extra pause to let the UI paint fully before we screenshot for Gemini
            page.wait_for_timeout(2000)

            click_count = 0
            max_turns = 6
            last_notes = ""
            for turn in range(1, max_turns + 1):
                executor_state["attempts"] = turn
                print(f"[executor] TURN {turn}: starting planner for {platform} / {setting.name!r}")

                # Give the UI a moment to stabilize before each planner call
                page.wait_for_timeout(1000)

                # Decide what hint string to give the planner / fallback for DOM clicking
                leaf_hint_for_ui = leaf_hint
                if leaf_hint and getattr(setting, "setting_id", None):
                    # If the user-provided leaf_hint is basically just the slug of this setting
                    # (e.g., 'private_account') then use the human-facing name instead
                    if _norm(leaf_hint) == _norm(setting.setting_id):
                        leaf_hint_for_ui = setting.name

                executor_state["leaf_hint"] = leaf_hint_for_ui  # keep state consistent

                # label we will use for visual verification
                verify_label = leaf_hint_for_ui or leaf_hint or setting.name

                plan = planner_setting_change(
                    page,
                    platform,
                    setting,
                    target_value,
                    executor_state,
                    leaf_hint=leaf_hint_for_ui,
                )

                print(
                    f"[executor] TURN {turn}: planner returned "
                    f"{len(plan.get('selectors') or [])} selectors, "
                    f"done={plan.get('done')}, "
                    f"notes={(plan.get('notes') or '')[:120]!r}"
                )

                selectors = plan.get("selectors") or []
                done = bool(plan.get("done"))
                last_notes = str(plan.get("notes") or "")

                # did this plan include an explicit confirmation step?
                had_confirm = any(
                    (s.get("purpose") or "").lower() == "confirm"
                    for s in selectors
                )

                # Detect model-side issues (empty output, error, etc.)
                has_model_issue = any(
                    key in last_notes
                    for key in ("model_empty_output", "model_error", "model_text_error")
                )

                if has_model_issue and not selectors:
                    # True empty / unusable output: retry with feedback or bail on last turn.
                    print(f"[executor] TURN {turn}: planner reported `{last_notes}` with NO selectors.")
                    if turn < max_turns:
                        executor_state["feedback"] = (
                            "The last planner call produced no usable output. "
                            "Please try again with a fresh plan, focusing on concrete selectors "
                            "for the target setting."
                        )
                        page.wait_for_timeout(2000)
                        continue
                    else:
                        result["status"] = "uncertain"
                        result["details"] = (
                            "Planner repeatedly produced empty or invalid output even after retries. "
                            f"Last notes: {last_notes}"
                        )
                        break
                # If has_model_issue but we *do* have selectors (e.g., leaf_hint fallback),
                # we proceed and actually apply those selectors.


                # 1) If planner explicitly reported JSON parsing failure, treat as "retry with feedback",
                #    not as a valid plan.
                if "Failed to parse JSON from Gemini" in last_notes:
                    executor_state["feedback"] = (
                        "Your last response was not valid JSON. "
                        "You must respond with a single JSON object containing: "
                        "{\"selectors\": [...], \"done\": true/false, \"notes\": \"...\"} "
                        "and no markdown fences or extra text."
                    )
                    # Try again next turn
                    continue

                # 2) If planner claims done==true but provided no selectors, do NOT accept that as success.
                #    Ask for a new plan with explicit change_value selectors.
                if done and not selectors:
                    executor_state["feedback"] = (
                        "You set done=true but did not provide any selectors. "
                        "You must include at least one selector with purpose='change_value' "
                        "that actually changes the target setting."
                    )
                    last_notes += " | Executor: done=true but no selectors; requesting new plan."
                    continue

                # 3) If no selectors AND not done, but notes say page is still loading, wait and retry.
                if not selectors and not done:
                    ln = last_notes.lower()
                    if "still loading" in ln or "no interactive elements" in ln:
                        page.wait_for_timeout(2000)
                        continue
                    # Otherwise, we have no actions and no clear reason: bail out.
                    result["status"] = "uncertain"
                    result["details"] = (
                        f"Planner returned no selectors on turn {turn} with no clear loading message. "
                        f"Notes: {last_notes}"
                    )
                    break

                # 4) Apply selectors.
                applied_any = False
                applied_confirm = False  # track if we actually clicked a confirm control
                for sel in selectors[:8]:
                    purpose = (sel.get("purpose") or "").lower()
                    ok = apply_selector(page, sel)
                    if ok:
                        click_count += 1
                        applied_any = True
                        if purpose == "confirm":
                            applied_confirm = True


                # Give the UI a moment to visually update after any clicks.
                if applied_any:
                    try:
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass

                # 4b) PROACTIVE VERIFY: if we did click something and have some label to key on,
                #     but the planner didn't set done=True, we can still ask the verifier.
                if not done and applied_any and verify_label:
                    verified = verify_setting_state(page, platform, verify_label, target_value)
                    if verified is True:
                        result["status"] = "success"
                        result["details"] = (
                            "Executor verified the setting visually after applying selectors, "
                            f"even though the planner did not set done=true. Notes: {last_notes}"
                        )
                        break
                    elif verified is False:
                        executor_state["feedback"] = (
                            "After applying your last selectors, the setting still does not appear "
                            "to be in the requested state. Please try a different way to toggle it "
                            "and confirm if needed."
                        )
                        last_notes += " | Executor (proactive verify): state != target; requesting another plan."
                        continue
                    # verified is None -> can't tell; continue with normal logic


                # 5) If the planner says done AFTER giving us selectors...
                if done:
                    # 5a) If we definitely just clicked a confirmation control on this turn,
                    # trust that flow and stop immediately. This avoids re-toggling the setting
                    # when the verifier is flaky or the model is overloaded.
                    if applied_confirm:
                        result["status"] = "success"
                        result["details"] = (
                            "Planner reported done and a confirmation control was clicked; "
                            "skipping verifier and assuming the setting change succeeded. "
                            f"Notes: {last_notes}"
                        )
                        break

                    # 5b) If we have no leaf_hint, we can't do a meaningful visual verification.
                    #     If we actually clicked something, trust the planner and stop.
                    if not leaf_hint:
                        if applied_any:
                            result["status"] = "success"
                            result["details"] = (
                                "Planner reported done and at least one selector was applied, "
                                "but no leaf_hint was provided for visual verification. "
                                "Assuming the setting change succeeded based on planner + click. "
                                f"Notes: {last_notes}"
                            )
                            break
                        else:
                            # Ask the planner for a more concrete plan.
                            executor_state["feedback"] = (
                                "You set done=true but none of your selectors actually matched "
                                "clickable elements. Please provide selectors that directly "
                                "toggle the target control."
                            )
                            last_notes += " | Executor: done=true but no selectors applied; requesting new plan."
                            continue

                    # 5c) If we *do* have a leaf_hint, try a single verification.
                    verified = verify_setting_state(page, platform, leaf_hint, target_value)
                    print(f"[executor] TURN {turn}: verifier result={verified!r}")

                    if verified is True:
                        result["status"] = "success"
                        result["details"] = (
                            "Planner reports done after applying actions, and verifier agrees the "
                            f"setting matches the target value. Notes: {last_notes}"
                        )
                        break

                    elif verified is False:
                        # Verifier says it's NOT in the desired state: tell planner to try again.
                        executor_state["feedback"] = (
                            "After applying your last plan, the setting still does not appear to be in the "
                            "requested state. Please propose more direct actions (e.g., selectors that "
                            "directly toggle the specific control) to set it to the target value."
                        )
                        last_notes += " | Verifier: state does NOT match target; requesting another plan."
                        # Don't break; go to next turn.
                        continue

                    else:
                        # verifier None / unknown -> STOP instead of looping forever.
                        result["status"] = "uncertain"
                        result["details"] = (
                            "Planner reported done and selectors were applied, but the verifier "
                            "could not determine the final state (or no verification was possible). "
                            "Stopping after a single verification attempt. "
                            f"Notes: {last_notes}"
                        )
                        break

                # 6) If NOTHING was applied successfully from the selectors,
                #    try giving feedback and another planning turn (unless we're out of turns).
                if not applied_any:
                    if turn < max_turns:
                        executor_state["feedback"] = (
                            "None of your selectors matched clickable elements on this page. "
                            "Please propose alternative selectors that directly target the visible controls, "
                            "for example:\n"
                            "- Using role or css selectors instead of text when appropriate;\n"
                            "- For confirmation dialogs, targeting the primary confirmation button explicitly;\n"
                            "- As a last resort, you MAY use a 'coord' selector with approximate x,y viewport "
                            "coordinates of the control."
                        )
                        last_notes += (
                            f" | Executor: no selectors applied on turn {turn}; requesting new selectors."
                        )
                        # Loop to next turn for a revised plan
                        continue
                    else:
                        # Out of turns; bail as uncertain
                        result["status"] = "uncertain"
                        result["details"] = (
                            f"No selectors applied successfully on turn {turn}, and max turns reached. "
                            f"Last planner notes: {last_notes}"
                        )
                        break




            else:
                # loop exhausted
                if result["status"] != "success":
                    result["status"] = "uncertain"
                    result["details"] = (
                        f"Reached max planner turns ({max_turns}) without a clear success signal. "
                        f"Last planner notes: {last_notes}"
                    )

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
    
    result["click_count"] = click_count
    # Record stats to disk (success and non-success are both useful)
    try:
        record_run_stats(
            platform=platform,
            setting=setting,
            target_value=target_value,
            status=result.get("status", "unknown"),
            click_count=int(result.get("click_count", 0)),
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
    if not client or not leaf_hint:
        return None

    snap = page.screenshot(full_page=True)
    textmap = viewport_dom_textmap(page, max_items=120)
    outline = dom_outline(page, max_nodes=300)

    system_instruction = (
        "You are a visual inspector for privacy settings in a web UI.\n"
        "You will be shown:\n"
        "- A screenshot of the current page\n"
        "- A short text hint for the setting name (TARGET_LEAF_SETTING_NAME)\n"
        "- The desired target value (TARGET_VALUE), such as 'on', 'off', 'private'.\n\n"
        "Your job is to look at the screenshot (and supporting DOM text) and answer:\n"
        "  Is the indicated setting currently set to the target value?\n\n"
        "You MUST respond with a single JSON object of the form:\n"
        "{\n"
        '  \"state\": \"on\" | \"off\" | \"unknown\",\n'
        '  \"matches_target\": true | false | null,\n'
        '  \"confidence\": <number between 0 and 1>,\n'
        '  \"notes\": \"<short explanation>\"\n'
        "}\n\n"
        "Rules:\n"
        "- Use your best judgement based on visual indicators (toggles, checkmarks, selected options),\n"
        "  and any visible labels near the setting name.\n"
        "- If you cannot confidently tell, use state=\"unknown\" and matches_target=null.\n"
        "- Do NOT wrap the JSON in markdown fences. No extra text before/after.\n"
    )

    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"TARGET_LEAF_SETTING_NAME: {leaf_hint}\n"
        f"TARGET_VALUE: {target_value}\n\n"
        "DOM_TEXT_MAP (partial, for context):\n" + textmap[:2000] +
        "\n\nDOM_OUTLINE (partial, for context):\n" + outline[:2000] +
        "\n\n"
        "Determine if the TARGET_LEAF_SETTING_NAME appears to be set to TARGET_VALUE."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        max_output_tokens=400,
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

    text = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return None
        first = cands[0]
        content = getattr(first, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if parts:
            for part in parts:
                if getattr(part, "text", None):
                    text += part.text
        else:
            cand_text = getattr(first, "text", None)
            if isinstance(cand_text, str):
                text = cand_text
    except Exception:
        return None

    raw = (text or "").strip()
    try:
        data = json.loads(raw)
    except Exception:
        # try to salvage { ... } block if fences slipped in
        try:
            m = re.search(r"\{.*\}", raw, flags=re.S)
            if not m:
                return None
            data = json.loads(m.group(0))
        except Exception:
            return None

    state = (data.get("state") or "").lower()
    matches_target = data.get("matches_target", None)

    # Prefer explicit matches_target if provided
    if isinstance(matches_target, bool):
        return matches_target

    # Otherwise, infer: treat "on" vs "off" for a target_value like "on"/"off"
    tv = target_value.strip().lower()
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

    plats = list_platforms()
    plat_list = "\n".join(f"- `{p}`" for p in plats) if plats else "_None loaded_"

    help_text = (
        "Welcome to the Agentic Privacy Control Center! \n\n"
        "You can interact with this chatbot in two ways:\n\n"
        "🟢 **Natural language:**\n"
        "Pick a platform from the buttons below, then describe the privacy or account setting you want to change and the desired state.\n\n"
        "You can type normally, as long as you mention:\n"
        "- A **privacy or account setting** you want to change\n"
        "- The **state** you want to change it to (e.g. on/off, private/public)\n\n"
        "Examples:\n"
        "- \"Turn off allowing people to follow me\"\n"
        "- \"Set my account to private\"\n\n"
        "If multiple settings could match your request, I’ll ask you to confirm the correct one before making any changes.\n\n"
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


    await cl.Message(help_text).send()
    await prompt_pick_platform()



@cl.on_message
async def on_message(message: cl.Message):
    text = (message.content or "").strip()
    if not text:
        await cl.Message(content="Please enter a command or request.").send()
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
        out_path = REPO_ROOT / "privacyagentapp" / "settingslist" / "settings_snapshot.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        await cl.Message(content=f"Saved settings snapshot to `{out_path}`").send()
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
            platform, setting, target_value, leaf_hint=setting.name
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

    # If no active platform, store text and prompt platform buttons.
    if not active_plat:
        cl.user_session.set(SESSION_PENDING_NL_TEXT, text)
        await prompt_pick_platform()
        return

    # We have an active platform — interpret + candidate-pick scoped to that platform.
    await handle_platform_scoped_nl(active_plat, text)
    return
