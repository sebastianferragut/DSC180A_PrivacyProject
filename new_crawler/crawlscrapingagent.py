# crawlscrapingagent.py
# NAV-ONLY privacy/data settings crawler + full-depth expander harvester — storageState-first, Chromium only.
#
# WHAT THIS IS
# - A deterministic, IN-DEPTH crawler that focuses on SETTINGS NAVIGATION ONLY:
#   1) Reveal/locate relevant navbars/sidebars/tabstrips (nav roots)
#   2) Expand nav trees (nested groups) inside those nav roots
#   3) Enumerate nav items from nav roots and click through them (systematic traversal)
#   4) On each destination page, expand ALL relevant expanders to full depth (recursively)
#   5) Capture ONE primary full-page screenshot per destination after full expansion
#      (+ optional modal evidence screenshots)
#
# WHAT THIS IS NOT
# - Not a generic UI explorer.
# - Not an "LLM clicker". (LLM is removed here for focus/speed.)
#
# REQUIREMENTS / ASSUMPTIONS
# - No sign-in flow: you MUST pre-save storage state per site (see save_state.py).
# - Chromium only.
#
# OUTPUTS (same structure as previous agents)
#   generaloutput/<platform>/screenshots/...
#   generaloutput/<platform>/harvest_report.json
#
# First time per site:
#   python save_state.py "$START_URL"
#   Log in to the site with Google credentials:
#   E: zoomaitester10@gmail.com
#   P: ZoomTestPass
#
# ENV:
#   export START_URL="https://zoom.us/profile/setting?tab=general" \
#   PLATFORM_NAME="zoom"
#
# Optional (tuning):
#   export DEVICE_TYPE="MacBook"
#   export MAX_NAV_ROOTS="2"             # how many nav containers to crawl (top ranked)
#   export MAX_NAV_ITEMS_PER_ROOT="70"   # per nav root
#   export MAX_DESTINATIONS="120"        # total unique UI states to capture
#   export MAX_EXPAND_STEPS="60"         # expanders to click per destination (main content)
#   export MAX_NAV_EXPAND_STEPS="50"     # expanders to click per nav root (inside sidebar/tree)
#   export SCROLL_PASSES="2"             # light scroll on destination before expanding
#   export CAPTURE_MODALS="1"            # capture modal evidence
#
# RUN:
#   python crawlscrapingagent.py

import os, re, sys, json, time, traceback
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse

import pyautogui
from playwright.sync_api import sync_playwright, Page

# =========================
# Config & Globals
# =========================

START_URL = os.environ.get("START_URL") or "about:blank"
DEVICE_TYPE = os.environ.get("DEVICE_TYPE", "MacBook")

MAX_NAV_ROOTS = int(os.environ.get("MAX_NAV_ROOTS", "2"))
MAX_NAV_ITEMS_PER_ROOT = int(os.environ.get("MAX_NAV_ITEMS_PER_ROOT", "70"))
MAX_DESTINATIONS = int(os.environ.get("MAX_DESTINATIONS", "120"))

MAX_EXPAND_STEPS = int(os.environ.get("MAX_EXPAND_STEPS", "60"))
MAX_NAV_EXPAND_STEPS = int(os.environ.get("MAX_NAV_EXPAND_STEPS", "50"))
SCROLL_PASSES = int(os.environ.get("SCROLL_PASSES", "2"))
CAPTURE_MODALS = bool(int(os.environ.get("CAPTURE_MODALS", "1")))

# Where this script lives (not CWD), so outputs are stable if you run from elsewhere.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PLATFORM_NAME priority:
# 1) Explicit env PLATFORM_NAME
# 2) If START_URL host exists, sanitized host
# 3) "default"
_plat_env = os.environ.get("PLATFORM_NAME", "").strip()
if _plat_env:
    PLATFORM_NAME = re.sub(r"[^a-zA-Z0-9._-]+", "_", _plat_env)
else:
    try:
        _host = (urlparse(os.environ.get("START_URL", "")).hostname or "").strip()
        PLATFORM_NAME = re.sub(r"[^a-zA-Z0-9._-]+", "_", _host) if _host else "default"
    except Exception:
        PLATFORM_NAME = "default"

# Output roots like:
#   generaloutput/zoom/screenshots/...
#   generaloutput/zoom/harvest_report.json
OUTPUT_ROOT = os.path.join(BASE_DIR, "generaloutput", PLATFORM_NAME)
OUT_DIR = os.path.join(OUTPUT_ROOT, "screenshots")
JSON_OUT = os.path.join(OUTPUT_ROOT, "harvest_report.json")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_ROOT, exist_ok=True)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

# =========================
# Keyword policy: "settings-relevant" navigation
# =========================

# Used for scoring nav roots and filtering obviously irrelevant nav items.
POS_HINTS = [
    "settings", "preferences", "privacy", "security", "data", "account", "profile",
    "record", "recording", "ads", "tracking", "visibility", "sessions", "devices",
    "permissions", "cookies", "consent", "password", "authentication", "mfa", "2fa",
    "download", "export", "delete", "history", "activity", "audit"
]

NEG_HINTS = [
    "billing", "invoice", "plans", "pricing", "upgrade", "payment", "subscription",
    "marketing", "campaign", "promotions",
    "developer", "api", "integration", "webhook",
    "help", "support", "faq", "community", "docs",
    "blog", "careers", "jobs", "press",
    "download app", "mobile app",
    "admin dashboard", "analytics"
]

def _pos_hits(s: str) -> int:
    s = (s or "").lower()
    return sum(1 for k in POS_HINTS if k in s)

def _neg_hits(s: str) -> int:
    s = (s or "").lower()
    return sum(1 for k in NEG_HINTS if k in s)

def nav_item_allowed(label: str) -> bool:
    """
    Nav-only crawler: allow most items because many are generic, BUT drop obvious non-settings.
    - If negative hits exist and positive hits are 0, skip.
    """
    l = (label or "").lower().strip()
    if not l:
        return False
    if _neg_hits(l) >= 1 and _pos_hits(l) == 0:
        return False
    return True

# =========================
# Utilities
# =========================

def ts() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def safe_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", (s or "").strip()) or "unnamed"

def hostname(u: str) -> str:
    try:
        return urlparse(u).hostname or "unknown"
    except Exception:
        return "unknown"

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _public_path(p: str) -> str:
    """
    Convert an absolute filesystem path into a repo-relative, URL-style path
    prefixed with a leading slash. Examples:
      /.../generaloutput/zoom/...  ->  /generaloutput/zoom/...
    """
    try:
        rel = os.path.relpath(p, BASE_DIR)
        rel = rel.replace(os.sep, "/")
        if not rel.startswith("/"):
            rel = "/" + rel
        return rel
    except Exception:
        return p

def fullpage_screenshot(page: Page, label: str, subdir: str) -> str:
    folder = os.path.join(OUT_DIR, safe_name(subdir))
    ensure_dir(folder)
    fname = f"{safe_name(label)}_{ts()}.png"
    out = os.path.join(folder, fname)
    page.screenshot(path=out, full_page=True)
    print(f"[saved] {out}")
    return _public_path(out)

def element_screenshot(page: Page, locator_query: str, label: str, subdir: str) -> Optional[str]:
    folder = os.path.join(OUT_DIR, safe_name(subdir))
    ensure_dir(folder)
    try:
        loc = page.locator(locator_query).first
        if not loc or loc.count() == 0:
            return None
        fname = f"{safe_name(label)}_{ts()}.png"
        out = os.path.join(folder, fname)
        loc.screenshot(path=out)
        print(f"[saved] {out}")
        return _public_path(out)
    except Exception:
        return None

# =========================
# Report
# =========================

def new_report(h: str) -> Dict[str, Any]:
    return {
        "site": h,
        "ts_iso": datetime.utcnow().isoformat() + "Z",
        "actions": [],
        "sections": [],
        "errors": [],
        "state": {
            "visited_urls": [],
            "visited_states": [],
            "captured_states": [],
            "nav_trail": [],
            "last_capture_url": None,
        },
        "metrics": {
            "run_start_ts": None,
            "run_end_ts": None,
            "total_runtime_sec": None,
            "steps": {
                "nav_roots_found": 0,
                "nav_items_clicked": 0,
                "nav_expand_clicks": 0,
                "content_expand_clicks": 0,
                "destinations_captured": 0,
                "modals_captured": 0,
                "scroll_passes": 0,
            }
        }
    }

def log_action(report: Dict[str, Any], kind: str, detail: Dict[str, Any]):
    report["actions"].append({"ts": ts(), "kind": kind, **detail})

def add_section(
    report: Dict[str, Any],
    name: str,
    url: str,
    fullpage_path: str,
    section_id: str,
    fingerprint: str,
    discovered_by: str,
    nav_path: Optional[List[str]] = None,
):
    sec = {
        "name": name,
        "path": [name],
        "url": url,
        "evidence_fullpage": fullpage_path,
        "items": [],
        "section_id": section_id,
        "fingerprint": fingerprint,
        "discovered_by": discovered_by,
    }
    if nav_path:
        sec["nav_path"] = nav_path
        sec["nav_path_desc"] = " > ".join(nav_path)
    report["sections"].append(sec)

def save_report(report: Dict[str, Any]):
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[report] {JSON_OUT}")

def _register_nav_step(report: Dict[str, Any], label: str, url: str, selector: str):
    label = re.sub(r"\s+", " ", (label or "")).strip()
    if not label:
        label = selector
    if not label:
        return
    trail = report.setdefault("state", {}).setdefault("nav_trail", [])
    entry = {"ts": ts(), "label": label[:120], "url": url, "selector": selector[:180]}
    if trail:
        last = trail[-1]
        if last.get("label") == entry["label"] and last.get("url") == entry["url"] and last.get("selector") == entry["selector"]:
            return
    trail.append(entry)

def _current_nav_path(report: Dict[str, Any]) -> List[str]:
    trail = report.get("state", {}).get("nav_trail") or []
    return [t.get("label", "").strip() for t in trail if t.get("label")]

# =========================
# State fingerprint + dedupe
# =========================

def ui_fingerprint(page: Page) -> str:
    """
    Fingerprint UI state (SPA-friendly): url(no hash) + title + interactive structure.
    """
    try:
        url = page.url.split("#", 1)[0]
    except Exception:
        url = ""
    try:
        title = (page.title() or "")[:80]
    except Exception:
        title = ""
    try:
        sig = page.evaluate("""
(() => {
  const norm = s => (s||"").replace(/\\s+/g,' ').trim().slice(0,120);
  const q = [
    'h1,h2,h3,[role="heading"]',
    '[role="tab"][aria-selected="true"]',
    '[aria-expanded]',
    'summary',
    'nav a,nav button',
    '[role="menuitem"],[role="treeitem"]',
    'main a, main button'
  ].join(',');
  const nodes = Array.from(document.querySelectorAll(q)).slice(0,240);
  const mapped = nodes.map(el => {
    const role = el.getAttribute('role') || '';
    const expanded = el.getAttribute('aria-expanded');
    const selected = el.getAttribute('aria-selected');
    const txt = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
    return [el.tagName.toLowerCase(), role, expanded, selected, txt].join('|');
  });
  return String(mapped.length) + '::' + mapped.join('||');
})();
""")
    except Exception:
        sig = str(time.time())
    raw = f"{url}::{title}::{sig}"
    return str(hash(raw))

def state_id_for(page: Page) -> str:
    try:
        url = page.url.split("#", 1)[0]
    except Exception:
        url = ""
    fp = ui_fingerprint(page)
    return f"{url}::{fp}"

# =========================
# Robust interactions
# =========================

def _overlay_present(page: Page) -> bool:
    try:
        return page.locator('[role="dialog"],[aria-modal="true"],[role="menu"],[role="listbox"]').count() > 0
    except Exception:
        return False

def robust_click(page: Page, selector: str, timeout_ms: int = 4500) -> bool:
    """
    Fast click + wait for state change.
    """
    if not selector:
        return False
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return False
        try:
            loc.scroll_into_view_if_needed(timeout=timeout_ms)
        except Exception:
            pass

        before_sid = state_id_for(page)
        before_url = page.url

        try:
            loc.click(timeout=timeout_ms, trial=True)
        except Exception:
            pass

        loc.click(timeout=timeout_ms)

        t0 = time.time()
        while time.time() - t0 < (timeout_ms / 1000.0):
            time.sleep(0.08)
            if page.url != before_url:
                return True
            if state_id_for(page) != before_sid:
                return True
            if _overlay_present(page):
                return True

        # Accept if element becomes expanded/selected
        try:
            exp = loc.get_attribute("aria-expanded")
            sel = loc.get_attribute("aria-selected")
            if exp == "true" or sel == "true":
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False

# =========================
# Nav discovery: roots and items
# =========================

def open_sidebar_if_needed(page: Page, report: Dict[str, Any]) -> bool:
    """
    Attempt to reveal a hidden sidebar/nav via common "menu" buttons.
    Conservative: tries only a handful of selectors.
    """
    candidates = [
        'button[aria-label*="menu" i]',
        'button[aria-label*="navigation" i]',
        '[role="button"][aria-label*="menu" i]',
        '[aria-label*="open navigation" i]',
        '[aria-label*="open menu" i]',
        'button:has-text("Menu")',
    ]
    for sel in candidates:
        try:
            if page.locator(sel).count():
                before = state_id_for(page)
                if robust_click(page, sel, timeout_ms=2200):
                    # "success" if state changes or we now have nav containers
                    if state_id_for(page) != before or page.locator("nav,[role='navigation']").count():
                        log_action(report, "sidebar_open", {"selector": sel, "url": page.url})
                        return True
        except Exception:
            pass
    return False

def discover_nav_roots(page: Page, max_roots: int = 2) -> List[Dict[str, Any]]:
    """
    Return ranked nav roots (sidebar navs / navigation / tablists).
    Each root: {rootSelector, kind, score, itemCount}
    """
    js = f"""
(() => {{
  const norm = s => (s||"").replace(/\\s+/g,' ').trim();
  const keys = {json.dumps(POS_HINTS)};
  const kwHits = (t) => {{
    const s = (t||"").toLowerCase();
    let hit = 0;
    for (const k of keys) if (s.includes(k)) hit += 1;
    return hit;
  }};
  const esc = (s) => {{ try {{ return CSS.escape(s); }} catch(e) {{ return s; }} }};
  const makeRootSel = (el) => {{
    // Root selector: prefer ID; else a stable-ish tag + class subset.
    if (el.id) return el.tagName.toLowerCase() + '#' + esc(el.id);
    const cls = (el.className && typeof el.className==='string')
      ? '.'+el.className.trim().split(/\\s+/).slice(0,3).map(esc).join('.')
      : '';
    return el.tagName.toLowerCase() + cls;
  }};

  const candidates = [];

  const push = (el, kind, bonus) => {{
    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
    const items = el.querySelectorAll('a,button,[role="menuitem"],[role="treeitem"],[role="tab"]').length;
    const hit = kwHits(text);
    let score = items * 0.6 + hit * 2.0 + bonus;
    // small preference for left-side navs
    try {{
      const r = el.getBoundingClientRect();
      if (r.left < 140 && r.width < 520) score += 2.0;
      if (r.top < 140 && kind === "tablist") score += 1.5;
    }} catch(e) {{}}
    candidates.push({{
      rootSelector: makeRootSel(el),
      kind,
      itemCount: items,
      score,
      hintText: text.slice(0,160)
    }});
  }};

  // nav / navigation roots
  document.querySelectorAll('nav,[role="navigation"]').forEach(el => push(el, "nav", 3.0));
  // tablists are also navigation
  document.querySelectorAll('[role="tablist"]').forEach(el => push(el, "tablist", 2.5));
  // settings-like labeled containers
  document.querySelectorAll('[aria-label*="settings" i],[aria-label*="preferences" i]').forEach(el => push(el, "labeled", 2.0));

  // dedupe by selector+kind
  const seen = new Set();
  const ded = [];
  for (const c of candidates) {{
    const k = c.kind + "||" + c.rootSelector;
    if (seen.has(k)) continue;
    seen.add(k);
    ded.push(c);
  }}
  ded.sort((a,b) => b.score - a.score);
  return ded.slice(0, {max_roots});
}})();
"""
    try:
        roots = page.evaluate(js) or []
    except Exception:
        roots = []
    # Normalize
    out = []
    for r in roots:
        rs = (r.get("rootSelector") or "").strip()
        if not rs:
            continue
        out.append({
            "rootSelector": rs,
            "kind": r.get("kind") or "nav",
            "score": float(r.get("score") or 0.0),
            "itemCount": int(r.get("itemCount") or 0),
            "hintText": r.get("hintText") or ""
        })
    return out

def expand_nav_tree(page: Page, root_selector: str, max_steps: int = 50) -> int:
    """
    Expand nested nav groups inside a nav root until no more collapsed nodes.
    Looks for aria-expanded=false or summary elements within the nav root.
    """
    steps = 0
    seen = set()

    for _ in range(max_steps):
        try:
            # Find first collapsed expander within root
            sel = page.evaluate(f"""
(() => {{
  const root = document.querySelector({json.dumps(root_selector)});
  if (!root) return "";
  const candidates = Array.from(root.querySelectorAll('[aria-expanded="false"], summary')).slice(0, 80);
  // Prefer ones that look like nav groups (treeitem/menu)
  const pick = candidates.find(el => {{
    const role = el.getAttribute('role') || '';
    if (role && (role.includes('tree') || role.includes('menu'))) return true;
    // also accept if it contains no href (often a group header)
    const href = el.getAttribute && el.getAttribute('href');
    return !href;
  }}) || candidates[0];
  if (!pick) return "";
  // Build selector
  const esc = (s) => {{ try {{ return CSS.escape(s); }} catch(e) {{ return s; }} }};
  if (pick.id) return pick.tagName.toLowerCase() + '#' + esc(pick.id);
  const al = pick.getAttribute('aria-label');
  if (al && al.length < 80) return pick.tagName.toLowerCase() + '[aria-label="' + al.replace(/"/g,'\\\\\\"') + '"]';
  const cls = (pick.className && typeof pick.className==='string')
    ? '.'+pick.className.trim().split(/\\s+/).slice(0,3).map(esc).join('.')
    : '';
  return pick.tagName.toLowerCase() + cls;
}})();
""")
        except Exception:
            sel = ""

        sel = (sel or "").strip()
        if not sel:
            break
        if sel in seen:
            break
        seen.add(sel)

        ok = robust_click(page, sel, timeout_ms=2500)
        if not ok:
            # try next loop; sometimes first click fails due to overlays
            continue
        steps += 1
        time.sleep(0.10)

    return steps

def enumerate_nav_items(page: Page, root_selector: str, limit: int = 70) -> List[Dict[str, Any]]:
    """
    Enumerate clickable items within a nav root.
    Returns list of: {selector, label}
    """
    js = f"""
(() => {{
  const root = document.querySelector({json.dumps(root_selector)});
  if (!root) return [];
  const norm = s => (s||"").replace(/\\s+/g,' ').trim();
  const esc = (s) => {{ try {{ return CSS.escape(s); }} catch(e) {{ return s; }} }};
  const makeSel = (el) => {{
    if (el.id) return el.tagName.toLowerCase() + '#' + esc(el.id);
    const al = el.getAttribute('aria-label');
    if (al && al.length < 80) return el.tagName.toLowerCase() + '[aria-label="' + al.replace(/"/g,'\\\\\\"') + '"]';
    const cls = (el.className && typeof el.className==='string')
      ? '.'+el.className.trim().split(/\\s+/).slice(0,3).map(esc).join('.')
      : '';
    return el.tagName.toLowerCase() + cls;
  }};

  const items = Array.from(root.querySelectorAll('a,button,[role="menuitem"],[role="treeitem"],[role="tab"]'))
    .slice(0, 300);

  const out = [];
  for (const el of items) {{
    // reminder: we want only meaningful nav items; skip empty labels
    const label = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
    if (!label) continue;
    // skip disabled
    const ariaDisabled = (el.getAttribute('aria-disabled') || '').toLowerCase();
    if (ariaDisabled === "true") continue;
    // skip elements that look like "collapse" toggles with no label (already filtered)
    out.push({{
      selector: makeSel(el),
      label: label.slice(0,120)
    }});
  }}

  // Dedupe (selector+label)
  const seen = new Set();
  const ded = [];
  for (const it of out) {{
    const k = it.selector + "||" + it.label;
    if (seen.has(k)) continue;
    seen.add(k);
    ded.push(it);
  }}

  return ded.slice(0, {limit});
}})();
"""
    try:
        items = page.evaluate(js) or []
    except Exception:
        items = []
    out = []
    for it in items:
        sel = (it.get("selector") or "").strip()
        lab = (it.get("label") or "").strip()
        if not sel or not lab:
            continue
        if not nav_item_allowed(lab):
            continue
        out.append({"selector": sel, "label": lab})
    return out[:limit]

# =========================
# Destination expansion (full depth)
# =========================

def scroll_pass(page: Page, passes: int = 2, pause_sec: float = 0.25) -> int:
    done = 0
    try:
        for _ in range(max(0, passes)):
            page.mouse.wheel(0, 1100)
            time.sleep(pause_sec)
            done += 1
        page.mouse.wheel(0, -600)
        time.sleep(0.15)
    except Exception:
        pass
    return done

def choose_content_root_selector(page: Page) -> str:
    """
    Choose a likely "main content" root to scope expander clicks, so we don't keep opening nav menus.
    """
    # Prefer main/[role=main], else fallback to body
    for sel in ["main", "[role='main']", "#content", "#main", "body"]:
        try:
            if page.locator(sel).count():
                return sel
        except Exception:
            continue
    return "body"

def expand_content_to_full_depth(page: Page, max_steps: int = 60) -> int:
    """
    Expand nested settings in the content area until no more expandable elements.
    Strategy:
      - Scope to main content root (main/[role=main]/body)
      - Click aria-expanded=false, summary, and "advanced/more/show" buttons/links
      - Stop when a full pass yields no successful clicks or max_steps hit
    """
    root_sel = choose_content_root_selector(page)
    steps = 0
    seen = set()

    # Candidates that often reveal nested settings
    # (We keep this deterministic; no LLM.)
    reveal_words = ["advanced", "more", "show", "see more", "additional", "details", "expand"]

    for _ in range(max_steps):
        try:
            pick = page.evaluate(f"""
(() => {{
  const root = document.querySelector({json.dumps(root_sel)}) || document.body;
  const norm = s => (s||"").replace(/\\s+/g,' ').trim();
  const esc = (s) => {{ try {{ return CSS.escape(s); }} catch(e) {{ return s; }} }};

  const revealWords = {json.dumps(reveal_words)};

  // Gather candidate expanders in content.
  const cands = [];

  // aria-expanded=false (accordions, collapsible panels)
  root.querySelectorAll('[aria-expanded="false"]').forEach(el => cands.push(el));

  // details/summary
  root.querySelectorAll('summary').forEach(el => cands.push(el));

  // "Advanced/More/Show" buttons/links
  root.querySelectorAll('button,a,[role="button"]').forEach(el => {{
    const t = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '').toLowerCase();
    if (!t) return;
    if (revealWords.some(w => t.includes(w))) cands.push(el);
  }});

  // Prefer ones that actually have some label and are visible-ish
  const visible = cands.filter(el => {{
    const r = el.getBoundingClientRect();
    return r.width > 6 && r.height > 6 && r.bottom > 0 && r.right > 0;
  }});

  // Choose first reasonable candidate
  const el = visible[0];
  if (!el) return {{ selector: "", label: "" }};

  let selector = "";
  if (el.id) selector = el.tagName.toLowerCase() + '#' + esc(el.id);
  else {{
    const al = el.getAttribute('aria-label');
    if (al && al.length < 80) selector = el.tagName.toLowerCase() + '[aria-label="' + al.replace(/"/g,'\\\\\\"') + '"]';
    else {{
      const cls = (el.className && typeof el.className==='string')
        ? '.'+el.className.trim().split(/\\s+/).slice(0,3).map(esc).join('.')
        : '';
      selector = el.tagName.toLowerCase() + cls;
    }}
  }}

  const label = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '').slice(0,120);
  return {{ selector, label }};
}})();
""")
        except Exception:
            pick = {"selector": "", "label": ""}

        sel = (pick or {}).get("selector", "").strip()
        lab = (pick or {}).get("label", "").strip()

        if not sel:
            break
        key = sel + "||" + lab
        if key in seen:
            # We've looped on same candidate; stop.
            break
        seen.add(key)

        ok = robust_click(page, sel, timeout_ms=3500)
        if not ok:
            # mark it and try another iteration; if we keep failing, loop will exit via seen cap
            continue

        steps += 1
        time.sleep(0.10)

        # If modal opened, stop expanding content here (modal handled separately)
        if _overlay_present(page):
            break

    return steps

# =========================
# Modal handling (optional)
# =========================

def capture_modal_if_present(report: Dict[str, Any], page: Page) -> bool:
    if not CAPTURE_MODALS:
        return False
    if not _overlay_present(page):
        return False
    dialog_sel = '[role="dialog"],[aria-modal="true"]'
    p = element_screenshot(page, dialog_sel, label="modal_dialog", subdir="elements")
    if not p:
        p = fullpage_screenshot(page, label="modal_dialog_fullpage", subdir="sections")
    report["metrics"]["steps"]["modals_captured"] += 1
    log_action(report, "modal_capture", {"url": page.url, "path": p})
    return True

def try_close_modal(page: Page) -> bool:
    try:
        for sel in [
            '[role="dialog"] button:has-text("Close")',
            '[role="dialog"] button[aria-label*="Close" i]',
            '[aria-modal="true"] button[aria-label*="Close" i]',
            '[role="dialog"] [aria-label="Close"]',
            '[role="dialog"] button:has-text("Done")',
            '[role="dialog"] button:has-text("Cancel")',
        ]:
            if page.locator(sel).count():
                robust_click(page, sel, timeout_ms=2500)
                time.sleep(0.15)
                if not _overlay_present(page):
                    return True
        page.keyboard.press("Escape")
        time.sleep(0.15)
        return not _overlay_present(page)
    except Exception:
        return False

# =========================
# Capture + dedupe
# =========================

def capture_destination(report: Dict[str, Any], page: Page, label: str, discovered_by: str):
    sid = state_id_for(page)
    fp = sid.split("::")[-1] if "::" in sid else ui_fingerprint(page)

    mem = report.setdefault("_mem", {})
    captured = mem.setdefault("captured_states", set())
    visited = mem.setdefault("visited_states", set())

    visited.add(sid)

    if sid in captured:
        return

    # One primary screenshot per destination (after full expansion)
    path = fullpage_screenshot(page, label=safe_name(label)[:60] or "settings_surface", subdir="sections")
    nav_path = _current_nav_path(report)
    add_section(
        report,
        name=label[:120] or "Settings Surface",
        url=page.url,
        fullpage_path=path,
        section_id=sid,
        fingerprint=fp,
        discovered_by=discovered_by,
        nav_path=nav_path
    )
    captured.add(sid)
    report["metrics"]["steps"]["destinations_captured"] += 1
    report["state"]["last_capture_url"] = page.url
    if page.url not in report["state"]["visited_urls"]:
        report["state"]["visited_urls"].append(page.url)

# =========================
# Main flow
# =========================

def harvest():
    site = hostname(START_URL)
    report = new_report(site)
    report["metrics"]["run_start_ts"] = datetime.utcnow().isoformat() + "Z"

    # StorageState-first launch (Chromium), else persistent profile
    STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")
    os.makedirs(STATE_DIR, exist_ok=True)
    host = urlparse(START_URL).hostname or "default"
    storage_path = os.path.join(STATE_DIR, f"{host}.json")

    with sync_playwright() as p:
        context = None
        page = None

        if os.path.exists(storage_path):
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                storage_state=storage_path,
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
                bypass_csp=True,
                java_script_enabled=True,
            )
            page = context.new_page()
            print(f"[state] Loaded storage state for {host} → {storage_path}")
        else:
            PROFILE_DIR = os.path.join(BASE_DIR, "profiles", "chrome")
            os.makedirs(PROFILE_DIR, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=False,
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
                args=[
                    "--disable-features=BlockThirdPartyCookies",
                    "--window-position=0,0",
                    "--window-size=1280,900",
                ],
            )
            page = context.pages[0] if context.pages else context.new_page()
            print(f"[state] No storage file for {host}. Using persistent profile at {PROFILE_DIR}")

        page.goto(START_URL, wait_until="load", timeout=60_000)
        time.sleep(0.4)

        # Make sure sidebar/nav is visible if it exists
        open_sidebar_if_needed(page, report)

        # Discover nav roots
        nav_roots = discover_nav_roots(page, max_roots=MAX_NAV_ROOTS)
        report["metrics"]["steps"]["nav_roots_found"] = len(nav_roots)
        log_action(report, "nav_roots", {"roots": nav_roots, "url": page.url})

        if not nav_roots:
            # fallback: treat body as root; still try to expand + capture start page
            report["errors"].append({"ts": ts(), "error": "no_nav_roots_found"})
            # Expand content and capture the start state
            report["metrics"]["steps"]["scroll_passes"] += scroll_pass(page, passes=SCROLL_PASSES)
            if _overlay_present(page):
                capture_modal_if_present(report, page)
                try_close_modal(page)
            report["metrics"]["steps"]["content_expand_clicks"] += expand_content_to_full_depth(page, max_steps=MAX_EXPAND_STEPS)
            capture_destination(report, page, label="Start Page (no nav roots)", discovered_by="bootstrap")
        else:
            # Crawl each nav root sequentially
            mem = report.setdefault("_mem", {})
            captured = mem.setdefault("captured_states", set())
            visited = mem.setdefault("visited_states", set())

            destinations_captured = 0

            for root in nav_roots:
                # Ensure nav still visible
                open_sidebar_if_needed(page, report)

                root_sel = root["rootSelector"]
                root_kind = root.get("kind", "nav")
                root_label = f"NavRoot:{root_kind}:{root_sel}"

                # Expand nav tree in this root
                nav_expand = expand_nav_tree(page, root_sel, max_steps=MAX_NAV_EXPAND_STEPS)
                report["metrics"]["steps"]["nav_expand_clicks"] += nav_expand
                log_action(report, "nav_expand", {"root": root_sel, "steps": nav_expand})

                # Enumerate items
                items = enumerate_nav_items(page, root_sel, limit=MAX_NAV_ITEMS_PER_ROOT)
                log_action(report, "nav_items", {"root": root_sel, "count": len(items)})

                # Click each nav item (systematic traversal)
                for idx, it in enumerate(items):
                    if destinations_captured >= MAX_DESTINATIONS:
                        break

                    sel = it["selector"]
                    lab = it["label"]

                    # Ensure nav visible and expanded again (some sites collapse after navigation)
                    open_sidebar_if_needed(page, report)
                    nav_expand2 = expand_nav_tree(page, root_sel, max_steps=MAX_NAV_EXPAND_STEPS)
                    report["metrics"]["steps"]["nav_expand_clicks"] += nav_expand2

                    before_url = page.url
                    before_sid = state_id_for(page)

                    ok = robust_click(page, sel, timeout_ms=4500)
                    report["metrics"]["steps"]["nav_items_clicked"] += 1
                    log_action(report, "nav_click", {
                        "ok": ok,
                        "index": idx,
                        "label": lab,
                        "selector": sel,
                        "root": root_sel,
                        "before_url": before_url,
                        "after_url": page.url
                    })
                    _register_nav_step(report, label=lab, url=before_url, selector=sel)

                    if not ok:
                        continue

                    # If modal appeared right after nav click, capture it (optional), then close
                    if _overlay_present(page):
                        capture_modal_if_present(report, page)
                        try_close_modal(page)

                    # Light scroll to reveal lazy sections in destination
                    report["metrics"]["steps"]["scroll_passes"] += scroll_pass(page, passes=SCROLL_PASSES)

                    # Expand destination content to full depth
                    expand_steps = expand_content_to_full_depth(page, max_steps=MAX_EXPAND_STEPS)
                    report["metrics"]["steps"]["content_expand_clicks"] += expand_steps
                    log_action(report, "content_expand", {"label": lab, "steps": expand_steps, "url": page.url})

                    # If expansions triggered a modal, capture and close, then attempt one more expansion pass
                    if _overlay_present(page):
                        capture_modal_if_present(report, page)
                        try_close_modal(page)
                        expand_steps2 = expand_content_to_full_depth(page, max_steps=max(10, MAX_EXPAND_STEPS // 3))
                        report["metrics"]["steps"]["content_expand_clicks"] += expand_steps2
                        log_action(report, "content_expand_after_modal", {"label": lab, "steps": expand_steps2, "url": page.url})

                    # Capture destination (deduped by state_id)
                    before_capture_count = len(captured)
                    capture_destination(report, page, label=lab, discovered_by="nav_click")
                    after_capture_count = len(captured)
                    if after_capture_count > before_capture_count:
                        destinations_captured += 1

                    # Record visited state for loop prevention
                    visited.add(state_id_for(page))

                if destinations_captured >= MAX_DESTINATIONS:
                    break

        # End-of-run capture (optional trace)
        try:
            fullpage_screenshot(page, label="end_of_run_trace", subdir="sections")
        except Exception:
            pass

        # Serialize in-memory sets
        mem = report.get("_mem", {})
        report["state"]["visited_states"] = sorted(list(mem.get("visited_states", set())))[:5000]
        report["state"]["captured_states"] = sorted(list(mem.get("captured_states", set())))[:5000]
        report.pop("_mem", None)

        report["metrics"]["run_end_ts"] = datetime.utcnow().isoformat() + "Z"
        try:
            t0 = datetime.fromisoformat(report["metrics"]["run_start_ts"].replace("Z", ""))
            t1 = datetime.fromisoformat(report["metrics"]["run_end_ts"].replace("Z", ""))
            report["metrics"]["total_runtime_sec"] = (t1 - t0).total_seconds()
        except Exception:
            pass

        save_report(report)

        # Refresh storage state for future runs
        try:
            STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")
            os.makedirs(STATE_DIR, exist_ok=True)
            storage_path = os.path.join(STATE_DIR, f"{host}.json")
            context.storage_state(path=storage_path)
            print(f"[state] Refreshed storage state → {storage_path}")
        except Exception as e:
            print("[state] Could not refresh storage state:", e)

        try:
            context.close()
        except Exception:
            pass

    print("[done] Harvest complete.")

# =========================
# Entrypoint
# =========================

if __name__ == "__main__":
    try:
        harvest()
    except KeyboardInterrupt:
        print("\n[ABORTED] KeyboardInterrupt.")
    except Exception as e:
        print("[fatal]", e)
        traceback.print_exc()
