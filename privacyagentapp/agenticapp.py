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

# =========================
# Paths & Config
# =========================

# This file is expected to live in: DSC180A_PrivacyProject/privacyagentapp/agenticapp.py
# Repo root is therefore one level up from this file.
REPO_ROOT = Path(__file__).resolve().parent.parent

SETTINGS_JSON_PATH = REPO_ROOT / "graphdata" / "data" / "all_platforms_classified.json"
GENERAL_OUTPUT_DIR = REPO_ROOT / "gemini-team" / "general_output"
STORAGE_STATE_DIR = REPO_ROOT / "gemini-team" / "profiles" / "storage"

SESSION_CHANGES_KEY = "changed_settings"

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
    For historical reasons, some scoring used a list of settings per entry.
    In our current model, SettingEntry represents a single setting, so this
    returns a 1-element list using entry.name/description.
    """
    if isinstance(entry, dict):
        return entry.get("settings") or []

    # For SettingEntry, synthesize a single "setting" dict from its fields.
    return [{
        "setting": getattr(entry, "name", ""),
        "description": getattr(entry, "description", ""),
    }]


def _entry_platform(entry) -> str:
    """Return platform name from either a raw dict or a SettingEntry object."""
    if isinstance(entry, dict):
        return entry.get("platform") or ""
    return getattr(entry, "platform", "") or ""

def _entry_section_id(entry) -> str:
    """
    Derive a 'section id' from the URL, typically the last non-empty path segment.
    For example:
      https://.../settings/v2/tags_and_mentions/ -> 'tags_and_mentions'
    """
    url = _entry_url(entry)
    if not url:
        return ""
    # Strip scheme
    part = url.split("://", 1)[-1]
    # Drop host
    parts = part.split("/", 1)
    path = parts[1] if len(parts) > 1 else ""
    # Split path segments, take last non-empty
    segs = [p for p in path.split("/") if p]
    if not segs:
        return ""
    return segs[-1]



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

    # 3) Image filename hints (your image names often embed the section label)
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

    # 1) Get all entries for this platform from your existing dict.
    #    Depending on how you keyed SETTINGS_BY_PLATFORM, we try the normalized key first, then raw.
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
            if loc.count():
                loc.first.click(timeout=3500)
                return True
        elif stype == "text":
            # First try exact text selector
            loc = page.locator(f'text="{sval}"')
            if loc.count():
                loc.first.click(timeout=3500)
                return True
            # Fallback: partial text match
            loc2 = page.get_by_text(sval, exact=False)
            if loc2.count():
                loc2.first.click(timeout=3500)
                return True
        elif stype == "role":
            loc = page.locator(sval)
            if loc.count():
                loc.first.click(timeout=3500)
                return True
    except PwTimeout:
        return False
    except Exception:
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
        # If we have a leaf_hint (e.g., "Protect your posts"), fall back to a simple
        # text-based selector so the executor can still try to click it.
        if leaf_hint:
            return {
                "selectors": [
                    {
                        "purpose": "change_value",
                        "type": "text",
                        "selector": leaf_hint,
                    }
                ],
                "done": False,
                "notes": (
                    "model_empty_output: planner received no text; using fallback "
                    f"text selector on leaf_hint '{leaf_hint}'."
                ),
            }

        # No leaf_hint -> nothing actionable, report empty output.
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

            # --- NEW: generic fallback when JSON is broken but we have a leaf_hint ---
            if leaf_hint:
                return {
                    "selectors": [
                        {
                            "purpose": "change_value",
                            "type": "text",
                            "selector": leaf_hint,
                        }
                    ],
                    "done": False,
                    "notes": (
                        "Failed to parse JSON from Gemini; using fallback text selector "
                        f"on leaf_hint '{leaf_hint}'. Original parse error: {e2}"
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


            max_turns = 6
            last_notes = ""
            for turn in range(1, max_turns + 1):
                executor_state["attempts"] = turn
                print(f"[executor] TURN {turn}: starting planner for {platform} / {setting.name!r}")

                # Give the UI a moment to stabilize before each planner call
                page.wait_for_timeout(1000)

                plan = planner_setting_change(
                    page,
                    platform,
                    setting,
                    target_value,
                    executor_state,
                    leaf_hint=leaf_hint,
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
                for sel in selectors[:8]:
                    ok = apply_selector(page, sel)
                    applied_any = applied_any or ok

                # 5) If the planner says done AFTER giving us selectors, verify state visually if we can.
                if done:
                    verified = verify_setting_state(page, platform, leaf_hint, target_value)
                    print(f"[executor] TURN {turn}: verifier result={verified!r}")
                    if verified is True:
                        result["status"] = "success"
                        result["details"] = (
                            f"Planner reports done after applying actions, and verifier agrees the "
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
                        # verifier None / unknown -> *do not* bail immediately.
                        # Ask the planner for a follow-up plan (likely confirmation / save buttons).
                        if turn < max_turns:
                            executor_state["feedback"] = (
                                "After your last plan, a UI is visible but the verifier could not determine "
                                "whether the setting is in the target state. Look carefully for any "
                                "confirmation, Save, Apply, or Protect-style buttons and include "
                                "selectors with purpose='confirm' to finalize the change."
                            )
                            last_notes += " | Verifier: state unknown; requesting follow-up plan for confirmations."
                            continue
                        else:
                            # On the final turn, we really have to give up.
                            result["status"] = "uncertain"
                            result["details"] = (
                                "Planner reported done, but even after multiple attempts the verifier "
                                "could not determine the state with confidence. "
                                f"Last notes: {last_notes}"
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
        "Welcome to the Privacy Agent 👋\n\n"
        "I use your harvested privacy settings to:\n"
        "1. List platforms and known privacy/data settings from `all_platforms_classified.json`.\n"
        "2. Attempt to log into those platforms (via stored `storage_state`) and change specific settings\n"
        "   using Playwright + Gemini.\n"
        "3. Produce a session report of all requested changes.\n\n"
        "**Commands (v1):**\n"
        "- `platforms` — list all platforms from the DB\n"
        "- `settings <platform>` — list known settings for a platform\n"
        "- `change <platform> <setting_id_or_name> to <value>` — request a setting change\n"
        "- `report` — show a summary of this session's changes\n\n"
        f"Currently loaded platforms:\n{plat_list}"
    )

    await cl.Message(content=help_text).send()


@cl.on_message
async def on_message(message: cl.Message):
    text = (message.content or "").strip()

    if not text:
        await cl.Message(content="Please enter a command or request.").send()
        return

    lower = text.lower()

    # Simple command routing for v1
    if lower == "platforms":
        plats = list_platforms()
        if not plats:
            await cl.Message(content="No platforms found in the settings DB.").send()
            return
        await cl.Message(
            content="Supported platforms:\n" + "\n".join(f"- `{p}`" for p in plats)
        ).send()
        return

    if lower.startswith("settings "):
        _, rest = text.split(" ", 1)
        plat_alias = find_platform_alias(rest)
        if not plat_alias:
            await cl.Message(
                content=f"I couldn't find a platform matching `{rest}`. "
                        f"Try one of: {', '.join(list_platforms())}"
            ).send()
            return
        settings = list_settings_for_platform(plat_alias)
        md = format_settings_table(settings)
        await cl.Message(
            content=f"Settings for **{plat_alias}**:\n\n{md}"
        ).send()
        return

    if lower == "report":
        changes = get_changes_log()
        md = build_session_report_md(changes)
        await cl.Message(
            content="Here is your session report:\n\n" + md
        ).send()
        return

    # Handle change command: "change <platform> <setting> to <value>"
    if lower.startswith("change "):
        try:
            # naive parse: change <platform> <rest...>
            _, rest = text.split(" ", 1)
            # split on "to"
            if " to " not in rest.lower():
                raise ValueError
            before_to, target_value = rest.rsplit(" to ", 1)
            before_to = before_to.strip()
            target_value = target_value.strip()

            # first token of before_to = platform, remainder = setting spec
            parts = before_to.split(" ", 1)
            if len(parts) < 2:
                raise ValueError
            platform_part, setting_spec = parts[0], parts[1]

            plat_alias = find_platform_alias(platform_part)
            if not plat_alias:
                await cl.Message(
                    content=f"I couldn't find a platform matching `{platform_part}`. "
                            f"Try one of: {', '.join(list_platforms())}"
                ).send()
                return

            # NEW: allow explicit section::leaf syntax
            section_query = setting_spec
            leaf_hint = None

            if "::" in setting_spec:
                section_query, leaf_raw = setting_spec.split("::", 1)
                section_query = section_query.strip()
                leaf_hint = leaf_raw.strip() or None

            # If user gave section::leaf, resolve the section via DB/fuzzy
            # and keep leaf_hint as provided.
            # If no ::, do flexible resolution (may use Gemini to choose section).
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
                content=(
                    f"Result: status = `{result.get('status')}`\n"
                    f"Details: {result.get('details')}"
                )
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

    # Fallback: generic message for now
    await cl.Message(
        content=(
            "I didn't recognize that command.\n\n"
            "For now, use one of:\n"
            "- `platforms`\n"
            "- `settings <platform>`\n"
            "- `change <platform> <setting_id_or_name> to <value>`\n"
            "- `report`"
        )
    ).send()
