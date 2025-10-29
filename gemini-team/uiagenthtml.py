# pip install google-genai pyautogui pillow playwright

# You can get a Gemini API key at https://aistudio.google.com/app/api-keys 
# ----- IMPORTANT EXPORTS BEFORE RUNNING SCRIPT -----
# Ensure you have the Gemini API key set in your environment (use this command in the terminal):
# export GEMINI_API_KEY="your_api_key_here"

# Paste the below into the terminal before running the script
# export GEMINI_API_KEY="your_api_key_here" \
# SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com" \
# SIGNUP_EMAIL_PASSWORD="ZoomTestPass" \
# SIGNUP_EMAIL_PASSWORD_WEB="$SIGNUP_EMAIL_PASSWORD" \
# PROFILE_NAME="chrome" \
# PLATFORM="https://zoom.us/profile/setting?tab=general"


# Optional (crawler tuning):
# CRAWL_MAX_DEPTH="3"
# CRAWL_MAX_PAGES="25"
# CRAWL_SAME_ORIGIN="1"
# CRAWL_CLICK_DELAY_MS="200"
# configure MAX_TURNS to change how many interaction steps the agent can take

# ----------------------------------------------------

# Run the script using python uiagenthtml.py
# Be sure to set "DEVICE_TYPE" variable below to your actual device type.

# ----------------------------------------------------

import sys
import time
import os, re, random, json
import io
from typing import Any, Dict, List, Tuple, Optional, Set
from datetime import datetime
from pathlib import Path
from hashlib import sha1
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import pyautogui
from playwright.sync_api import sync_playwright, Page

from google import genai
from google.genai import types
from google.genai.types import Content, Part, FunctionCall

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    exit(1)

PLATFORM = os.environ.get("PLATFORM")
if not PLATFORM:
    print("Error: PLATFORM environment variable not set.")
    exit(1)

MODEL_ID = 'gemini-2.5-computer-use-preview-10-2025'
PLANNING_MODEL_ID = 'gemini-2.5-pro'

DEVICE_TYPE = "MacBook"
# DEVICE_TYPE = "Windows 11 PC"

# How many rounds of interaction to allow
MAX_TURNS = 8

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 1.0

client = genai.Client(api_key=API_KEY)

SCREEN_WIDTH, SCREEN_HEIGHT = pyautogui.size()
cuse_grid = 1000

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Playwright Global State ---
playwright_context: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
}

# --- Heuristics / Keywords ---
PRIVACY_KEYWORDS = [
    # high-signal terms
    "privacy", "data", "security", "consent", "recording", "retention", "gdpr", "ccpa",
    "cookie", "cookies", "tracking", "telemetry", "ads", "advertising", "personalization",
    "permissions", "sharing", "third-party", "third party", "download data", "export data",
    "delete account", "deactivate", "archive", "identity", "two-factor", "2fa", "mfa",
    "password", "profile visibility", "who can see", "contacts", "calendar", "camera",
    "microphone", "screen sharing", "meeting", "record", "transcript", "caption", "ai"
]

# ---- Link ranking / denylist helpers ----
DENYLIST_DEFAULT = [
    r"/accessibility",
    r"/legal\b", r"/terms", r"/privacy-policy", r"/cookie(-|_)policy",
    r"/press", r"/newsroom", r"/brand", r"/investors?", r"/about", r"/careers?",
    r"/blog", r"/help", r"/support", r"/status", r"/contact",
    r"^mailto:", r"^tel:", r"^javascript:",
    r"^zoommtg:", r"^msteams:", r"^webex:", r"^lync:", r"^sip:"
]

# Controls we try to extract
CONTROL_ROLE_HINTS = [
    '[role="switch"]', 'input[type="checkbox"]', 'input[type="radio"]',
    'select', 'button', 'a'
]

SAFE_HOST_PATTERN = re.compile(r"^[a-z0-9.-]+$", re.I)

# --- Helper Functions ---
def current_page_url() -> str:
    try:
        pg = playwright_context.get("page")
        if pg:
            return pg.url or ""
    except Exception:
        pass
    return ""

def _is_denied_link(href: str, text: str) -> bool:
    h = (href or "").lower().strip()
    t = (text or "").lower().strip()
    # Allow override via env (comma-separated regexes)
    extra = os.environ.get("CRAWL_DENYLIST", "")
    patterns = DENYLIST_DEFAULT + ([x.strip() for x in extra.split(",") if x.strip()] if extra else [])
    for pat in patterns:
        try:
            if re.search(pat, h) or re.search(pat, t):
                return True
        except re.error:
            # ignore bad regex
            continue
    return False

def _rank_link_score(abs_url: str, href: str, text: str, start_url: str) -> int:
    """
    Higher is better. Keep us in settings-like areas before general pages.
    Signals:
      +4: keyword in text/href
      +3: same path base as start_url
      +2: contains 'settings'/'preference'/'account' path segment
      +1: intra-page (#)
      -3: denied link
    """
    from urllib.parse import urlparse
    score = 0
    if _match_keywords(text) or _match_keywords(href):
        score += 4
    try:
        su = urlparse(start_url)
        au = urlparse(abs_url)
        if au.path and su.path and au.path.split("/")[1:2] == su.path.split("/")[1:2]:
            score += 3
        if any(k in au.path.lower() for k in ["setting", "preference", "privacy", "security", "account", "profile"]):
            score += 2
    except Exception:
        pass
    if href.startswith("#"):
        score += 1
    if _is_denied_link(href, text):
        score -= 3
    return score

def _extract_safety_decision(fc):
    try:
        sd = getattr(fc, "safety_decision", None)
        if isinstance(sd, dict) and sd.get("decision"):
            return sd
        args = getattr(fc, "args", None) or {}
        sd = args.get("safety_decision")
        if isinstance(sd, dict) and sd.get("decision"):
            return sd
        if hasattr(fc, "to_dict"):
            d = fc.to_dict()
            sd = (d.get("safetyDecision") or d.get("safety_decision") or
                  d.get("args",{}).get("safetyDecision") or d.get("args",{}).get("safety_decision"))
            if isinstance(sd, dict) and sd.get("decision"):
                return sd
    except Exception:
        pass
    return None

def _get_function_call_id(part) -> Optional[str]:
    try:
        fc = getattr(part, "function_call", None)
        cid = getattr(fc, "id", None)
        if cid:
            return cid
        cid = getattr(part, "id", None)
        if cid:
            return cid
        cid = getattr(part, "function_call_id", None)
        if cid:
            return cid
        if hasattr(part, "to_dict"):
            d = part.to_dict()
            cid = (
                d.get("functionCall", {}, {}).get("id")
                or d.get("function_call", {}, {}).get("id")
                or d.get("id")
            )
            if cid:
                return cid
    except Exception:
        pass
    return None

def _timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _safe_name(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]+', '_', s.strip()) or "unnamed"

# --- URL Canonicalization ---
CANON_QUERY_WHITELIST = {"tab"}  # Keep only whitelisted keys that truly change content; adjust as needed.
SCRAPE_CACHE: Dict[str, str] = {}  # canon_url -> fingerprint
CRAWL_DONE = False



def canonicalize_url(u: str) -> str:
    try:
        pu = urlparse(u)
        # keep scheme/host/path; strip fragment
        q = parse_qsl(pu.query, keep_blank_values=True)
        # keep only selected query params, sorted for stability
        q = sorted([(k, v) for (k, v) in q if k in CANON_QUERY_WHITELIST])
        new = pu._replace(query=urlencode(q), fragment="")
        return urlunparse(new)
    except Exception:
        return u.split("#", 1)[0]
    
def _controls_fingerprint(controls: List[dict]) -> str:
    # stable minimal representation
    try:
        # Only the fields that reflect UI state; adjust as needed
        skinny = [
            {
                "type": c.get("type"),
                "label": (c.get("label") or "").strip().lower(),
                "selector": c.get("selector"),
                "state": c.get("state"),
                "value": c.get("value"),
                "selectedText": c.get("selectedText")
            } for c in controls
        ]
        blob = json.dumps(skinny, sort_keys=True, ensure_ascii=False)
        return sha1(blob.encode("utf-8")).hexdigest()
    except Exception:
        return sha1(str(controls).encode("utf-8")).hexdigest()



# Return a profile path for a URL, prefer explicit PROFILE_NAME if set.
def get_profile_dir_from_env_or_url(url: str) -> Optional[str]:
    """
    Resolution order:
      1) PROFILE_NAME (under PROFILE_DIR)
      2) Host-based folder (e.g., profiles/zoom.us)
      3) 'chrome' fallback (profiles/chrome)
      4) If exactly one subfolder exists under PROFILE_DIR, use it

    Returns absolute path if found and looks like a Chromium profile, else None.
    """
    try:
        profile_root_env = os.environ.get("PROFILE_DIR", os.path.join(BASE_DIR, "profiles"))
        profile_root = Path(profile_root_env).resolve()
        profile_root.mkdir(parents=True, exist_ok=True)

        def exists_dir(p: Path) -> Optional[str]:
            if p.exists() and p.is_dir():
                return str(p.resolve())
            return None

        def looks_like_chromium_profile(p: Path) -> bool:
            # Heuristic: profile root usually contains 'Local State' and a 'Default' dir
            return (p / "Local State").exists() and (p / "Default").exists()

        # 1) Explicit PROFILE_NAME
        explicit = os.environ.get("PROFILE_NAME", "").strip()
        if explicit:
            cand = profile_root / explicit
            if exists_dir(cand) and looks_like_chromium_profile(cand):
                return str(cand.resolve())

        # 2) Host-based
        host = urlparse(url).netloc
        host_name = re.sub(r'[^A-Za-z0-9._-]', '_', host or "profile")
        cand = profile_root / host_name
        if exists_dir(cand) and looks_like_chromium_profile(cand):
            return str(cand.resolve())

        # 3) 'chrome' fallback
        cand = profile_root / "chrome"
        if exists_dir(cand) and looks_like_chromium_profile(cand):
            return str(cand.resolve())

        # 4) Single subdir fallback
        subdirs = [d for d in profile_root.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and looks_like_chromium_profile(subdirs[0]):
            return str(subdirs[0].resolve())

        return None
    except Exception:
        return None
    
# ---- Expand in-page sections before leaving the page ----
def expand_privacy_sections(max_clicks: int = 8, timeout_ms: int = 2000) -> Dict[str, Any]:
    """
    Expand likely privacy/setting sections (accordions/tabs/expando buttons) *on the current page*
    so extract_privacy_controls() can see everything without navigating away.
    We only click elements whose accessible name/innerText matches PRIVACY_KEYWORDS.
    """
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # Find expanders: buttons, summary in details, roles: tab, button, switch-like toggles that expand content
        selectors = [
            "button,[role='button'],summary,[role='tab']",
            # some sites use divs with aria-expanded
            "*[aria-expanded]"
        ]
        clicked = 0

        # Collect candidates in-page and rank by match strength (keyword in label/text)
        cands = pg.evaluate(f"""
() => {{
  const norm = s => (s||"").replace(/\\s+/g," ").trim();
  const k = {json.dumps([kw.lower() for kw in PRIVACY_KEYWORDS])};
  const matches = (s) => {{
    const x = (s||"").toLowerCase();
    return k.some(kw => x.includes(kw));
  }};
  const els = Array.from(document.querySelectorAll("{','.join(selectors)}"));
  const out = [];
  for (const el of els) {{
    const role = el.getAttribute('role') || el.tagName.toLowerCase();
    const name = el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || "";
    const label = norm(name);
    const hasKw = matches(label);
    const expandable = el.tagName.toLowerCase()==='summary' ||
                       role==='tab' ||
                       (el.hasAttribute('aria-expanded')) ||
                       (el.tagName.toLowerCase()==='button' && /expand|show|manage|settings|options/i.test(label));
    if (!expandable) continue;
    // avoid nav links masquerading as buttons
    if (el.closest('a')) continue;
    out.push({{
      label, role, hasKw,
      selector: (()=>{{ 
        const id = el.id ? '#'+CSS.escape(el.id) : '';
        const cls = (el.className && typeof el.className==='string') ? '.'+el.className.trim().split(/\\s+/).slice(0,3).map(CSS.escape).join('.') : '';
        return (el.tagName.toLowerCase()+id+cls);
      }})()
    }});
  }}
  // rank: keyword first, then role==tab, then button/summary
  return out.sort((a,b) => (b.hasKw - a.hasKw) || ((b.role==='tab') - (a.role==='tab')));
}}
""")
        for c in cands:
            if clicked >= max_clicks:
                break
            try:
                loc = pg.locator(c["selector"]).first
                if loc and loc.count():
                    loc.click(timeout=timeout_ms)
                    clicked += 1
                    # brief allow content to render
                    time.sleep(0.15)
            except Exception:
                continue

        return {"status":"success","expanded":clicked}
    except Exception as e:
        return {"status":"error","message":str(e)}
    
# --- Screenshot utilities  ---
def ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def get_screenshot_bytes() -> bytes:
    screenshot = pyautogui.screenshot()
    img_byte_arr = io.BytesIO()
    screenshot.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def denormalize(value: int, max_value: int) -> int:
    return int((value * max_value) / cuse_grid)

def save_desktop_screenshot(label: str = "desktop") -> Dict[str, Any]:
    try:
        ts = _timestamp()
        fname = f"{_safe_name(label)}_{ts}.png"
        full_path = os.path.join(SCREENSHOT_DIR, fname)
        pyautogui.screenshot(full_path)
        print(f"[saved] {full_path}")
        return {"status": "success", "path": full_path, "filename": fname}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def page_full_screenshot(label: str = "page", subfolder: str = "") -> Dict[str, Any]:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        ts = _timestamp()
        folder = os.path.join(SCREENSHOT_DIR, _safe_name(subfolder)) if subfolder else SCREENSHOT_DIR
        os.makedirs(folder, exist_ok=True)
        fname = f"{_safe_name(label)}_{ts}.png"
        out = os.path.join(folder, fname)
        pg.screenshot(path=out, full_page=True)
        print(f"[saved] {out}")
        return {"status": "success", "path": out, "filename": fname}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def page_element_screenshot(selector: str, label: str = "element", subfolder: str = "") -> Dict[str, Any]:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        loc = pg.locator(selector)
        if not loc.count():
            return {"status": "error", "message": f"Selector not found: {selector}"}
        ts = _timestamp()
        folder = os.path.join(SCREENSHOT_DIR, _safe_name(subfolder)) if subfolder else SCREENSHOT_DIR
        os.makedirs(folder, exist_ok=True)
        fname = f"{_safe_name(label)}_{ts}.png"
        out = os.path.join(folder, fname)
        loc.first.screenshot(path=out)
        print(f"[saved] {out}")
        return {"status": "success", "path": out, "filename": fname}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Playwright semantic click helper (dialog-aware; avoids coord clicks) ---
def pw_click_button_by_text(text: str, timeout_ms: int = 5000) -> dict:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # 1) Prefer modal/dialog scope if present
        try:
            dialog = pg.get_by_role("dialog").filter(has_text=re.compile(r".*", re.S)).first
            dialog.wait_for(state="visible", timeout=1500)
            btn = dialog.get_by_role("button", name=text, exact=True)
            if btn.count():
                btn.first.click(timeout=timeout_ms)
                return {"status": "success", "clicked": text, "scope": "dialog"}
        except Exception:
            pass

        # 2) Fallback: page buttons/links/text
        loc = pg.get_by_role("button", name=text, exact=True)
        if not loc or not loc.count():
            loc = pg.get_by_role("link", name=text, exact=True)
        if not loc or not loc.count():
            loc = pg.locator(f"text={text}")
        loc.first.wait_for(state="visible", timeout=timeout_ms)
        loc.first.click(timeout=timeout_ms)
        return {"status": "success", "clicked": text, "scope": "page"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Browser lifecycle / navigation ---
def open_browser_and_navigate(url: str) -> Dict[str, str]:
    """
    Use a persistent profile from PROFILE_DIR/PROFILE_NAME (or heuristics) if present.
    Set FORCE_PROFILE=1 to fail hard when a profile is not found/usable.
    """
    try:
        p = playwright_context.get("playwright")
        if not p:
            return {"status": "error", "message": "Playwright not initialized."}

        force_profile = os.environ.get("FORCE_PROFILE", "0") in ("1", "true", "TRUE")
        profile_dir = get_profile_dir_from_env_or_url(url)

        print(f"[PROFILE] PROFILE_DIR={os.environ.get('PROFILE_DIR', os.path.join(BASE_DIR,'profiles'))} "
              f"PROFILE_NAME={os.environ.get('PROFILE_NAME','')} "
              f"resolved_profile_dir={profile_dir or 'None'} force_profile={force_profile}")

        if profile_dir:
            try:
                print(f"[INFO] Using persistent profile: {profile_dir}")
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    viewport={"width": 1280, "height": 720},
                    args=[
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--window-position=0,0",
                        "--window-size=1280,720",
                    ],
                    accept_downloads=True,
                )
            except Exception as e:
                # If we *must* use a profile, surface the real failure
                if force_profile:
                    return {"status": "error", "message": f"Failed to open persistent context: {e}"}
                print(f"[WARN] Persistent profile failed: {e}. Falling back to ephemeral.")
                ctx = None

            if ctx:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.bring_to_front()
                try:
                    page.goto(url, wait_until="load", timeout=60_000)
                except Exception:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)

                playwright_context["browser"] = None
                playwright_context["context"] = ctx
                playwright_context["page"] = page
                return {"status": "success", "message": f"Navigated to {url} with profile {profile_dir}"}

        if force_profile:
            return {"status": "error", "message": "FORCE_PROFILE=1 but no usable profile was found."}

        # ---- FALLBACK: ephemeral ----
        print("[INFO] No usable profile; launching ephemeral browser/context.")
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-features=IsolateOrigins,site-per-process",
                "--window-position=0,0",
                "--window-size=1280,720",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1.0,
            accept_downloads=True,
        )
        page = context.new_page()
        page.bring_to_front()
        page.goto(url, wait_until="load", timeout=60_000)

        playwright_context["browser"] = browser
        playwright_context["page"] = page
        playwright_context["context"] = context

        time.sleep(0.5)
        return {"status": "success", "message": f"Successfully navigated to {url}."}

    except Exception as e:
        return {"status": "error", "message": str(e)}

def pw_navigate(url: str) -> Dict[str, str]:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        pg.bring_to_front()
        pg.goto(url, wait_until="load", timeout=60_000)
        return {"status": "success", "url": pg.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def pw_go_back(steps: int = 1) -> Dict[str, str]:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        pg.bring_to_front()
        for _ in range(max(1, steps)):
            pg.go_back(wait_until="load", timeout=60_000)
        return {"status": "success", "url": pg.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tabs_open_new(url: str) -> Dict[str, str]:
    try:
        ctx = playwright_context.get("context")
        if not ctx:
            return {"status": "error", "message": "No active context"}
        p = ctx.new_page()
        p.goto(url, wait_until="load", timeout=60_000)
        p.bring_to_front()
        playwright_context["page"] = p
        return {"status": "success", "url": p.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tabs_switch_to(substr: str, timeout_ms: int = 10000) -> Dict[str, str]:
    try:
        ctx = playwright_context.get("context")
        if not ctx:
            return {"status": "error", "message": "No active context"}
        deadline = time.time() + (timeout_ms/1000.0)
        while time.time() < deadline:
            for p in ctx.pages:
                if substr.lower() in (p.url or "").lower():
                    p.bring_to_front()
                    playwright_context["page"] = p
                    return {"status": "success", "url": p.url}
            time.sleep(0.2)
        return {"status": "error", "message": f"No tab containing '{substr}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Generic UI label clicks ---
def ui_click_any_label(labels: List[str], timeout_ms: int = 5000) -> dict:
    for lbl in labels:
        r = ui_click_label(lbl, timeout_ms)
        if r.get("status") == "success":
            return r
    return {"status": "error", "message": f"No label matched from {labels}"}

def ui_click_label(label: str, timeout_ms: int = 5000) -> dict:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # 1) Try dialog-scope first
        try:
            dialog = pg.get_by_role("dialog").first
            dialog.wait_for(state="visible", timeout=1200)
            for locator in [
                dialog.get_by_role("button", name=label, exact=True),
                dialog.get_by_role("link", name=label, exact=True),
                dialog.locator(f"text={label}")
            ]:
                if locator.count():
                    locator.first.click(timeout=timeout_ms)
                    return {"status": "success", "scope": "dialog", "clicked": label}
        except Exception:
            pass

        # 2) Fallback to page scope
        for locator in [
            pg.get_by_role("button", name=label, exact=True),
            pg.get_by_role("link", name=label, exact=True),
            pg.locator(f"text={label}")
        ]:
            if locator.count():
                locator.first.wait_for(state="visible", timeout=timeout_ms)
                locator.first.click(timeout=timeout_ms)
                return {"status": "success", "scope": "page", "clicked": label}

        return {"status": "error", "message": f"Label not found: {label}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Credentials helpers ---
def provide_signup_email() -> Dict[str, str]:
    addr = os.environ.get("SIGNUP_EMAIL_ADDRESS", "").strip()
    if not addr:
        return {"status": "error", "message": "SIGNUP_EMAIL_ADDRESS not set"}
    return {"status": "success", "email": addr}

def provide_signup_password() -> Dict[str, str]:
    pwd_web = os.environ.get("SIGNUP_EMAIL_PASSWORD_WEB", "").strip()
    if not pwd_web:
        pwd_web = os.environ.get("SIGNUP_EMAIL_PASSWORD", "").strip()
    if not pwd_web:
        return {"status": "error", "message": "No SIGNUP_EMAIL_PASSWORD_WEB or SIGNUP_EMAIL_PASSWORD found"}
    return {"status": "success", "password": pwd_web}

# ==============================
# HTML SCRAPING & CRAWLING LAYER
# ==============================

def _same_origin(url: str, host: str) -> bool:
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        return (u.netloc == host) or (u.netloc.endswith("." + host))
    except Exception:
        return True

def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        h = urlparse(url).netloc.lower()
        return h
    except Exception:
        return ""

def _normalize_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip()

def _match_keywords(text: str) -> bool:
    t = (text or "").lower()
    for kw in PRIVACY_KEYWORDS:
        if kw in t:
            return True
    return False

def dom_snapshot() -> Dict[str, Any]:
    """Return minimal DOM info for the current page."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        url = pg.url
        title = pg.title()
        # Extract anchors & buttons text/hrefs via JS
        data = pg.evaluate("""
() => {
  const anchors = Array.from(document.querySelectorAll('a'))
    .map(a => ({text: (a.innerText||'').trim(), href: a.getAttribute('href') || ''}))
    .slice(0, 1500);
  const buttons = Array.from(document.querySelectorAll('button,input[type="button"],input[type="submit"]'))
    .map(b => ({text: (b.innerText || b.value || '').trim(), selector: b.outerHTML.slice(0,200)}))
    .slice(0, 1000);
  const switches = Array.from(document.querySelectorAll('[role="switch"], input[type="checkbox"], input[type="radio"]'))
    .map(el => {
      const label = el.getAttribute('aria-label') || el.id || el.name || el.closest('label')?.innerText || el.parentElement?.innerText || '';
      return {label: label.trim(), selector: el.tagName.toLowerCase() + (el.id ? '#'+el.id : '')};
    }).slice(0, 1000);
  return {anchors, buttons, switches};
}
""")
        return {"status": "success", "url": url, "title": title, "dom": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def find_candidate_links(limit: int = 100) -> Dict[str, Any]:
    """Return filtered list of likely-privacy links on the page."""
    snap = dom_snapshot()
    if snap.get("status") != "success":
        return snap
    anchors = snap["dom"].get("anchors", [])
    cands = []
    seen = set()
    for a in anchors:
        text = _normalize_label(a.get("text",""))
        href = a.get("href","") or ""
        if not href or href.startswith("javascript:"):
            continue
        if (text, href) in seen:
            continue
        if _match_keywords(text) or _match_keywords(href):
            cands.append({"text": text, "href": href})
            seen.add((text, href))
        if len(cands) >= max(10, limit):
            break
    return {"status":"success","candidates":cands,"count":len(cands)}

def click_selector(selector: str, timeout_ms: int = 5000) -> Dict[str, Any]:
    """Click an exact selector (semantic; avoids coordinate)."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status":"error","message":"No active page"}
        loc = pg.locator(selector).first
        loc.wait_for(state="visible", timeout=timeout_ms)
        loc.click(timeout=timeout_ms)
        time.sleep( (int(os.environ.get("CRAWL_CLICK_DELAY_MS","200")) / 1000.0) )
        return {"status":"success","url": pg.url}
    except Exception as e:
        return {"status":"error","message":str(e)}

def click_link_with_text(text: str, timeout_ms: int = 5000) -> Dict[str, Any]:
    """Click a link by visible text (first match)."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status":"error","message":"No active page"}
        loc = pg.get_by_role("link", name=text, exact=False).first
        if not loc or loc.count() == 0:
            loc = pg.locator(f"a:has-text('{text}')").first
        loc.wait_for(state="visible", timeout=timeout_ms)
        loc.click(timeout=timeout_ms)
        time.sleep( (int(os.environ.get("CRAWL_CLICK_DELAY_MS","200")) / 1000.0) )
        return {"status":"success","url": pg.url}
    except Exception as e:
        return {"status":"error","message":str(e)}

def resolve_href_and_click(href: str, timeout_ms: int = 5000) -> Dict[str, Any]:
    """Click an anchor with the exact href (best-effort)."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status":"error","message":"No active page"}
        loc = pg.locator(f"a[href='{href}']").first
        if not loc or loc.count() == 0:
            # Try partial match if absolute -> relative issues
            loc = pg.locator(f"a[href*='{href}']").first
        loc.wait_for(state="visible", timeout=timeout_ms)
        loc.click(timeout=timeout_ms)
        time.sleep( (int(os.environ.get("CRAWL_CLICK_DELAY_MS","200")) / 1000.0) )
        return {"status":"success","url": pg.url}
    except Exception as e:
        return {"status":"error","message":str(e)}

def extract_privacy_controls() -> Dict[str, Any]:
    pg: Page = playwright_context.get("page")
    if not pg:
        return {"status": "error", "message": "No active page"}

    controls = []
    elements = pg.locator("input, select, button, textarea, label").all()

    for el in elements:
        tag = el.evaluate("el.tagName.toLowerCase()")
        label = el.evaluate("el.innerText || el.getAttribute('aria-label') || ''").strip()
        ctype = el.get_attribute("type") or tag
        state = (
            "checked" if (ctype in ("checkbox", "radio") and el.is_checked()) else
            "selected" if el.get_attribute("aria-checked") == "true" else
            "disabled" if el.is_disabled() else "on" if el.is_enabled() else "unknown"
        )
        controls.append({"label": label, "type": ctype, "state": state})
    return {"status": "success", "controls": controls}


def write_json_report(data: dict, basename: Optional[str] = None) -> Dict[str, Any]:
    try:
        url = data.get("start_url","")
        host = _host_of(url) or "site"
        if not SAFE_HOST_PATTERN.match(host):
            host = "site"
        ts = _timestamp()
        name = basename or f"privacy_map_{host}_{ts}.json"
        path = os.path.join(OUTPUT_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {"status":"success","path": path,"filename": name}
    except Exception as e:
        return {"status":"error","message":str(e)}

def crawl_privacy_map(max_depth: int = 3, max_pages: int = 25, same_origin_only: bool = True) -> Dict[str, Any]:
    """
    Lightweight BFS from current page:
      - Canonicalizes URLs to avoid duplicate revisits
      - Fingerprints extracted controls to skip re-adding identical pages
      - Prioritizes settings-like links; honors denylist and same-origin
      - Records path (sequence of link clicks) and per-page controls

    Depends on helpers already present in your script:
      _host_of, _same_origin, _normalize_label, _rank_link_score, _is_denied_link,
      canonicalize_url, _controls_fingerprint, dom_snapshot, expand_privacy_sections,
      extract_privacy_controls, playwright_context

    Uses global cache:
      SCRAPE_CACHE : Dict[str, str]   # canon_url -> fingerprint
    """
    try:
        from urllib.parse import urljoin
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # Initialize BFS state
        start_url = pg.url
        start_host = _host_of(start_url)
        visited: Set[str] = set()  # canonical URLs we've processed
        queue: List[Tuple[str, List[Dict[str, str]]]] = [(start_url, [])]  # (url, path_of_clicks)
        discoveries: List[Dict[str, Any]] = []
        nodes: List[Dict[str, str]] = []
        page_count = 0

        def push_node(u: str, t: str):
            nodes.append({"url": u, "title": t})

        # Crawl caps (can be tuned via env)
        cap_prio = int(os.environ.get("CRAWL_CAP_PRIO", "8"))
        cap_other = int(os.environ.get("CRAWL_CAP_OTHER", "2"))
        expand_clicks = int(os.environ.get("CRAWL_EXPAND_CLICKS", "8"))
        click_delay_sec = max(0, int(os.environ.get("CRAWL_CLICK_DELAY_MS", "200")) / 1000.0)

        while queue and page_count < max_pages:
            url, path = queue.pop(0)
            canon_url = canonicalize_url(url)

            # Skip already-visited canonical URL
            if canon_url in visited:
                continue
            visited.add(canon_url)

            # Navigate (only if not already there)
            if url != pg.url:
                try:
                    pg.goto(url, wait_until="load", timeout=60_000)
                except Exception:
                    # Try a lighter wait condition if full load fails
                    try:
                        pg.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    except Exception:
                        # Give up on this URL
                        continue

            page_count += 1
            title = pg.title() or ""
            current_url = pg.url  # may differ (redirects)
            push_node(current_url, title)

            # 1) Expand in-page sections (tabs/accordions) before scraping
            try:
                expand_privacy_sections(max_clicks=expand_clicks)
                if click_delay_sec:
                    time.sleep(min(click_delay_sec, 0.5))
            except Exception:
                pass

            # 2) Extract controls on the fully expanded page
            controls_resp = extract_privacy_controls()
            page_controls = controls_resp.get("controls", []) if controls_resp.get("status") == "success" else []

            # 2a) Always add to discoveries with rich page metadata
            page_data = {
                "url": current_url,
                "title": title,
                "path": path,
                "controls": []
            }

            if page_controls:
                for c in page_controls:
                    control_entry = {
                        "label": c.get("label", ""),
                        "type": c.get("type", ""),
                        "state": c.get("state", ""),
                        "selector": c.get("selector", ""),
                        "options": c.get("options", []),
                        "context": c.get("context", "")
                    }
                    page_data["controls"].append(control_entry)

                # Add fingerprinting only to reduce duplicates, not to skip entirely
                fp = _controls_fingerprint(page_controls)
                prev_fp = SCRAPE_CACHE.get(canon_url)
                if prev_fp != fp:
                    SCRAPE_CACHE[canon_url] = fp

            discoveries.append(page_data)

            # 3) Collect candidate links from the DOM snapshot and rank
            snap = dom_snapshot()
            if snap.get("status") != "success":
                continue

            anchors = snap["dom"].get("anchors", [])
            prio_scored: List[Dict[str, Any]] = []
            other_scored: List[Dict[str, Any]] = []
            seen_links: Set[str] = set()

            for a in anchors:
                href = (a.get("href") or "").strip()
                text = _normalize_label(a.get("text", ""))

                if not href:
                    continue

                abs_url = urljoin(current_url, href)

                # Same-origin gate
                if same_origin_only and not _same_origin(abs_url, start_host):
                    continue

                # Skip denylisted routes (accessibility, legal, protocol handlers, etc.)
                if _is_denied_link(href, text):
                    continue

                # Avoid duplicate per page
                if abs_url in seen_links:
                    continue
                seen_links.add(abs_url)

                score = _rank_link_score(abs_url, href, text, start_url)
                entry = {"text": text, "href": href, "abs": abs_url, "score": score}

                if score >= 4:
                    prio_scored.append(entry)
                else:
                    other_scored.append(entry)

            # Sort by score descending
            prio_scored.sort(key=lambda x: x["score"], reverse=True)
            other_scored.sort(key=lambda x: x["score"], reverse=True)

            def take(candidates: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
                return candidates[:max(0, cap)]

            # 4) Enqueue next steps: prefer high-priority settings-like links; add a small sample of others
            for cand in take(prio_scored, cap_prio) + take(other_scored, cap_other):
                nxt = cand["abs"]
                nxt_canon = canonicalize_url(nxt)
                if nxt_canon in visited:
                    continue
                if len(path) >= max_depth:
                    continue
                new_path = path + [{"action": "link", "label": cand["text"], "href": cand["abs"]}]
                queue.append((nxt, new_path))

        report = {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "start_url": start_url,
            "host": start_host,
            "crawler": {
                "max_depth": max_depth,
                "max_pages": max_pages,
                "same_origin_only": bool(same_origin_only)
            },
            "summary": {
                "unique_pages": len(visited),
                "discoveries": len(discoveries)
            },
            "visited": nodes,         # [{url, title}]
            "discoveries": discoveries # [{url, title, path, controls}]
        }

        return {"status": "success", "report": report}

    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==========================
# Action Execution (includes safety ACK gating/handling)
# ==========================
def call_model_with_retries(client, model, contents, config, max_retries=4):
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            return True, resp
        except Exception as e:
            err = str(e)
            print(f"[Model call error] attempt {attempt}/{max_retries}: {err}")
            if attempt == max_retries:
                return False, err
            time.sleep(delay + random.uniform(0, 0.5))
            delay *= 2

def execute_function_calls(candidate) -> List[Tuple[str, Dict, FunctionCall]]:
    results = []
    wrapped_calls = []
    for p in candidate.content.parts:
        fc = getattr(p, "function_call", None)
        if not fc:
            continue
        call_id = _get_function_call_id(p)
        wrapped_calls.append({"part": p, "fc": fc, "id": call_id})

    # ---- SAFETY-GATED CALL HANDLING (collect acks, do not return early) ----
    gated_call_ids = set()
    retry_needed = False

    for wc in wrapped_calls:
        fc = wc["fc"]
        sd = _extract_safety_decision(fc)
        if sd and sd.get("decision") in ("require_confirmation", "block"):
            name = fc.name
            call_id = wc["id"] or getattr(fc, "id", None)
            if not call_id:
                retry_needed = True
                results.append(("__RETRY_WITH_TEXT__", {"reason":"gated_call_missing_id","name":name}, None))
                continue
            gated_call_ids.add(call_id)
            results.append((
                name,
                {
                    "ack_only": True,
                    "safety_ack_payload": {
                        "id": call_id,
                        "name": name,
                        "response": {"safety_decision":{
                            "decision":"proceed","user_confirmation":"approved","explanation": sd.get("explanation","")
                        }}
                    }
                },
                fc,
                call_id
            ))
            if name == "click_at":
                retry_needed = True
                results.append(("__RETRY_WITH_TEXT__", {"reason":"gated_click_at"}, None))

    # ---- NORMAL EXECUTION for non-gated calls ----
    for wc in wrapped_calls:
        fc = wc["fc"]; call_id = wc["id"] or getattr(fc, "id", None)
        if call_id and call_id in gated_call_ids:
            continue
        fname = fc.name 
        args = getattr(fc, "args", {}) or {}
        print(f"  Executing > {fname}({args})")
        action_result = {}
        try:
            if fname == "click_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.3)
                pyautogui.click()
                action_result = {"status": "success", "x": x, "y": y}

            elif fname == "type_text_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                text = args["text"]
                press_enter = args.get("press_enter", False)
                pyautogui.click(x, y)
                if sys.platform == "darwin":
                    pyautogui.hotkey('command', 'a')
                else:
                    pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('backspace')
                pyautogui.write(text, interval=0.05)
                if press_enter:
                    pyautogui.press('enter')
                action_result = {"status": "success", "typed_len": len(text), "press_enter": press_enter}

            elif fname == "key_combination":
                keys = args["keys"].lower().split('+')
                key_map = {"control": "ctrl", "command": "cmd", "windows": "win"}
                mapped_keys = [key_map.get(k, k) for k in keys]
                pyautogui.hotkey(*mapped_keys)
                action_result = {"status": "success", "keys": mapped_keys}

            elif fname == "wait_5_seconds":
                time.sleep(5)
                action_result = {"status": "success"}

            elif fname == "scroll_at":
                x = denormalize(args.get("x", 500), SCREEN_WIDTH)
                y = denormalize(args.get("y", 500), SCREEN_HEIGHT)
                direction = (args.get("direction") or "down").lower()
                magnitude = int(args.get("magnitude", 200))
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.scroll(-magnitude if direction == "down" else magnitude)
                action_result = {"status": "success", "scrolled": direction, "magnitude": magnitude, "x": x, "y": y}

            elif fname in ("wheel", "page_scroll"):
                dy = int(args.get("dy", args.get("magnitude", 200)))
                direction = "down" if dy > 0 else "up"
                x = denormalize(args.get("x", 500), SCREEN_WIDTH)
                y = denormalize(args.get("y", 500), SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.scroll(-abs(dy) if direction == "down" else abs(dy))
                action_result = {"status": "success", "scrolled": direction, "magnitude": abs(dy), "x": x, "y": y}

            # --- Custom Tools / Navigation ---
            elif fname == "open_browser_and_navigate":
                action_result = open_browser_and_navigate(args["url"])

            elif fname == "save_desktop_screenshot":
                action_result = save_desktop_screenshot(args.get("label","desktop"))

            elif fname == "page_full_screenshot":
                action_result = page_full_screenshot(
                    label=args.get("label","page"),
                    subfolder=args.get("subfolder","")
                )

            elif fname == "page_element_screenshot":
                action_result = page_element_screenshot(
                    selector=args["selector"],
                    label=args.get("label","element"),
                    subfolder=args.get("subfolder","")
                )

            elif fname == "provide_signup_email":
                action_result = provide_signup_email()

            elif fname in ("pw_navigate", "navigate"):
                action_result = pw_navigate(args["url"])

            elif fname == "pw_go_back":
                steps = int(args.get("steps", 1))
                action_result = pw_go_back(steps)

            elif fname == "provide_signup_password":
                action_result = provide_signup_password()

            elif fname == "click_button_by_text":
                txt = args["text"]
                to = int(args.get("timeout_ms", 5000))
                action_result = pw_click_button_by_text(txt, to)

            elif fname == "ui_click_label":
                action_result = ui_click_label(args["label"], int(args.get("timeout_ms", 5000)))

            elif fname == "ui_click_any_label":
                action_result = ui_click_any_label(args["labels"], int(args.get("timeout_ms", 5000)))

            elif fname == "tabs_open_new":
                action_result = tabs_open_new(args["url"])

            elif fname == "tabs_switch_to":
                action_result = tabs_switch_to(args["substr"], int(args.get("timeout_ms", 10000)))

            # --- Scraping/Crawling tools ---
            elif fname == "dom_snapshot":
                action_result = dom_snapshot()

            elif fname == "find_candidate_links":
                lim = int(args.get("limit", 100))
                action_result = find_candidate_links(lim)

            elif fname == "click_selector":
                action_result = click_selector(args["selector"], int(args.get("timeout_ms", 5000)))

            elif fname == "click_link_with_text":
                action_result = click_link_with_text(args["text"], int(args.get("timeout_ms", 5000)))

            elif fname == "resolve_href_and_click":
                action_result = resolve_href_and_click(args["href"], int(args.get("timeout_ms", 5000)))

            elif fname == "extract_privacy_controls":
                action_result = extract_privacy_controls()

            elif fname == "crawl_privacy_map":
                global CRAWL_DONE
                if CRAWL_DONE:
                    action_result = {"status":"skipped","reason":"crawl_already_done"}
                else:
                    md = int(args.get("max_depth", int(os.environ.get("CRAWL_MAX_DEPTH","3"))))
                    mp = int(args.get("max_pages", int(os.environ.get("CRAWL_MAX_PAGES","25"))))
                    so = bool(int(args.get("same_origin_only", int(os.environ.get("CRAWL_SAME_ORIGIN","1")))))
                    action_result = crawl_privacy_map(md, mp, so)
                    # Mark done if we visited at least one page
                    if action_result.get("status") == "success":
                        CRAWL_DONE = True

            elif fname == "write_json_report":
                action_result = write_json_report(args["data"], args.get("basename"))
                if action_result.get("status") == "success":
                    # signal to outer loop to stop
                    action_result["done"] = True

            else:
                print(f"Warning: Skipping unimplemented function {fname}")
                action_result = {"error": f"Function {fname} not implemented locally."}

        except Exception as e:
            action_result = {"error": str(e)}
    if retry_needed:
        results.append(("__RETRY_WITH_TEXT__", {"reason":"retry_after_gating"}, None))

    return results

# --- Planning (generalized plan) ---
def generate_plan(client, user_prompt: str, screenshot_bytes: bytes, config) -> str:
    planning_prompt = f"""
Based on the user's goal and the current screen state, create a concise plan.

User Goal: {user_prompt}

Requirements:
- Prefer Playwright DOM scraping over screenshots.
- Use:
  * open_browser_and_navigate(PLATFORM)
  * Sign-in (Google if available) with provide_signup_email / provide_signup_password
  * dom_snapshot → find_candidate_links
  * crawl_privacy_map(max_depth=3..4, same_origin_only=1)
  * extract_privacy_controls at interesting pages
  * write_json_report({{report}})

Plan format:
PLAN:
1. [Open URL]
2. [Sign in (through Google sign-on, pick zoomaitester10@gmail.com)]
3. [Run crawl_privacy_map]
4. [Save JSON report]
"""
    try:
        planning_config = types.GenerateContentConfig(
            system_instruction="You are a planning assistant. Create lean, actionable plans for browser automation. Do not execute actions."
        )

        response = client.models.generate_content(
            model=PLANNING_MODEL_ID,
            contents=[Content(
                role="user",
                parts=[
                    Part(text=planning_prompt),
                    Part.from_bytes(data=screenshot_bytes, mime_type='image/png')
                ]
            )],
            config=planning_config
        )

        plan = response.candidates[0].content.parts[0].text
        print(f"📋 Generated Plan:\n{plan}\n")
        return plan

    except Exception as e:
        print(f"Error generating plan: {e}")
        return "PLAN:\n1. Navigate, sign in using the provided account (pick zoomaitester10@gmail.com from the Google SSO), run crawl_privacy_map, write_json_report\n"

def run_agent():
    with sync_playwright() as p:
        playwright_context["playwright"] = p
        print(f"[BANNER] BASE_DIR={BASE_DIR}  PLATFORM={PLATFORM}  "
      f"PROFILE_DIR={os.environ.get('PROFILE_DIR', os.path.join(BASE_DIR,'profiles'))}  "
      f"PROFILE_NAME={os.environ.get('PROFILE_NAME','')}")


        print(f"Display resolution: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        print("Starting agent (HTML-scrape mode). Please avoid touching mouse/keyboard.")

        # 1) Define tools (kept + new)
        custom_tools = [
            types.FunctionDeclaration(
                name="open_browser_and_navigate",
                description="Launch Chromium and navigate to the specified URL.",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(
                name="pw_navigate",
                description="Navigate current tab to the given URL.",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(
                name="pw_go_back",
                description="Go back in browser history.",
                parameters={"type":"object","properties":{"steps":{"type":"integer","default":1}}}
            ),
            types.FunctionDeclaration(
                name="tabs_open_new",
                description="Open URL in a NEW tab.",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(
                name="tabs_switch_to",
                description="Switch to a tab with URL containing substring.",
                parameters={"type":"object","properties":{"substr":{"type":"string"},"timeout_ms":{"type":"integer","default":10000}},"required":["substr"]}
            ),
            types.FunctionDeclaration(
                name="click_button_by_text",
                description="Click a visible button/link by exact text via Playwright.",
                parameters={"type":"object","properties":{"text":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["text"]}
            ),
            types.FunctionDeclaration(
                name="ui_click_label",
                description="Click a visible control by label (dialog preferred).",
                parameters={"type":"object","properties":{"label":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["label"]}
            ),
            types.FunctionDeclaration(
                name="ui_click_any_label",
                description="Click the first match from a list of labels.",
                parameters={"type":"object","properties":{"labels":{"type":"array","items":{"type":"string"}},"timeout_ms":{"type":"integer","default":5000}},"required":["labels"]}
            ),
            # Screenshots (optional)
            types.FunctionDeclaration(
                name="save_desktop_screenshot",
                description="Capture a full-desktop screenshot (optional fallback).",
                parameters={"type":"object","properties":{"label":{"type":"string"}}}
            ),
            types.FunctionDeclaration(
                name="page_full_screenshot",
                description="Capture a full-page screenshot of current Playwright page.",
                parameters={"type":"object","properties":{"label":{"type":"string"},"subfolder":{"type":"string"}}}
            ),
            types.FunctionDeclaration(
                name="page_element_screenshot",
                description="Capture a screenshot of a specific element by selector.",
                parameters={"type":"object","properties":{"selector":{"type":"string"},"label":{"type":"string"},"subfolder":{"type":"string"}},"required":["selector"]}
            ),
            # Credentials
            types.FunctionDeclaration(
                name="provide_signup_email",
                description="Returns env email for sign-in.",
                parameters={"type":"object","properties":{}}
            ),
            types.FunctionDeclaration(
                name="provide_signup_password",
                description="Returns env password for sign-in.",
                parameters={"type":"object","properties":{}}
            ),
            # NEW: Scrape / Crawl
            types.FunctionDeclaration(
                name="dom_snapshot",
                description="Return minimal DOM info (anchors/buttons/switches).",
                parameters={"type":"object","properties":{}}
            ),
            types.FunctionDeclaration(
                name="find_candidate_links",
                description="Return top likely privacy-related links on the current page.",
                parameters={"type":"object","properties":{"limit":{"type":"integer","default":100}}}
            ),
            types.FunctionDeclaration(
                name="click_selector",
                description="Click a CSS selector (semantic click).",
                parameters={"type":"object","properties":{"selector":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["selector"]}
            ),
            types.FunctionDeclaration(
                name="click_link_with_text",
                description="Click first link containing given text.",
                parameters={"type":"object","properties":{"text":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["text"]}
            ),
            types.FunctionDeclaration(
                name="resolve_href_and_click",
                description="Click a link with exact (or partial) href.",
                parameters={"type":"object","properties":{"href":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["href"]}
            ),
            types.FunctionDeclaration(
                name="extract_privacy_controls",
                description="Extract likely privacy/security/data controls on the page.",
                parameters={"type":"object","properties":{}}
            ),
            types.FunctionDeclaration(
                name="crawl_privacy_map",
                description="BFS crawl for privacy paths and controls (lightweight).",
                parameters={"type":"object","properties":{
                    "max_depth":{"type":"integer","default": int(os.environ.get("CRAWL_MAX_DEPTH","3"))},
                    "max_pages":{"type":"integer","default": int(os.environ.get("CRAWL_MAX_PAGES","25"))},
                    "same_origin_only":{"type":"integer","default": int(os.environ.get("CRAWL_SAME_ORIGIN","1"))}
                }}
            ),
            types.FunctionDeclaration(
                name="write_json_report",
                description="Persist the JSON privacy map to ./outputs",
                parameters={"type":"object","properties":{
                    "data":{"type":"object"},
                    "basename":{"type":"string"}
                },"required":["data"]}
            ),
        ]

        # 2) System instructions for HTML mode
        config = types.GenerateContentConfig(
            tools=[types.Tool(computer_use=types.ComputerUse()),
                   types.Tool(function_declarations=custom_tools)],
            system_instruction=f"""You are an agent operating a {DEVICE_TYPE} computer with a web browser.

Primary Objective (HTML-scrape mode)
- Open {PLATFORM} using open_browser_and_navigate.
- **AUTHENTICATION FIRST:** If the page shows a sign-in gate (email/password fields, or “Sign in”, or “Continue with Google/Google”), you MUST complete sign-in before any scraping or crawling.
  • Try in order: click_button_by_text("Sign in") → click_button_by_text("Google") or "Continue with Google" → proceed with Google SSO.
  • If a pop-up or dialog is used, prefer dialog-scoped clicks (get_by_role('dialog')).
  • After sign-in succeeds (profile menu or settings become visible), proceed.
- After you are authenticated:
  • Prefer DOM scraping & lightweight crawling over screenshots.
  • On each page: expand in-page sections (expand_privacy_sections) → extract_privacy_controls.
  • Use click_link_with_text/resolve_href_and_click only when needed to move within settings.
- Do not use click_link_with_text or resolve_href_and_click for navigation unless crawl_privacy_map explicitly failed to discover links; always fully expand and scrape the current page first (expand_privacy_sections → extract_privacy_controls).
- Discover *privacy/data/security/recording/consent* settings across the product.
   
Behavioral Rules
- Use crawl_privacy_map(max_depth 3-4, same_origin_only=1) to discover pages efficiently.
- On each discovered page, call extract_privacy_controls to gather controls with keywords.
- Avoid scrolling/screenshots unless necessary; prefer dom_snapshot, find_candidate_links.
- Never rely on coordinate clicks; prefer semantic selectors and role/text-based actions.
- Do not navigate outside same-origin unless explicitly necessary.

Output Discipline
- After crawl_privacy_map returns, immediately call write_json_report with the report.
- Keep actions minimal; prioritize efficiency and generalization.
- Maintain safety ACK gating and use semantic tools after gating when needed.

Closure Protocol
-- Produce a JSON report with:
   - start_url, host
   - visited pages (url, descriptive_title with subtitle if available)
   - discoveries: for each page with relevant title or controls, include `path` (sequence of clicks with labels/hrefs) and `controls` (label, type, selector)
   - summary counts

- Once completing the primary objective, save the report and end the session. 
- Do not perform unnecessary actions after report generation, and do not continually scrape the same pages.
"""
        )

        user_prompt = "Navigate, sign in with the provided account through Google sign-on, crawl for privacy/data/security settings using HTML scraping, and save a generalized JSON privacy map to ./outputs."
        print(f"\nGoal: {user_prompt}\n")

        initial_screenshot = get_screenshot_bytes()
        plan = generate_plan(client, user_prompt, initial_screenshot, config)

        planning_context = f"""
I will execute the plan with DOM-first scraping to minimize tokens. I will only use screenshots if absolutely required. Operate only in the browser context.
{plan}
"""

        chat_history = [
            Content(role="user", parts=[
                Part(text=user_prompt),
                Part(text=planning_context),
                Part.from_bytes(data=initial_screenshot, mime_type='image/png')
            ])
        ]

        # 4) Interaction Loop
        for turn in range(1, MAX_TURNS + 1):
            print(f"--- Turn {turn} ---")
            time.sleep(1.2)
            print("Analyzing screen...")

            ok, response = call_model_with_retries(client, MODEL_ID, chat_history, config)
            if not ok:
                print(f"API Error (after retries): {response}")
                break

            cands = getattr(response, "candidates", None) or []
            if not cands:
                print("No candidates returned; continuing.")
                time.sleep(0.6)
                continue

            model_response = cands[0].content
            chat_history.append(model_response)

            if model_response.parts and getattr(model_response.parts[0], "text", None):
                print(f"🤖 Agent: {model_response.parts[0].text.strip()}")

            if not any(p.function_call for p in model_response.parts):
                print("No tool calls detected. Continuing.")
                continue

            action_results = execute_function_calls(response.candidates[0])

            # If any retry sentinel is present, we will send the nudge message after sending any valid acks.
            needs_retry = any(item[0] == "__RETRY_WITH_TEXT__" for item in action_results)

            # Build FunctionResponses (with inline screenshot) — but NEVER for __RETRY_WITH_TEXT__
            function_response_parts = []
            names_emitted = []

            for item in action_results:
                # Unpack
                if len(item) == 4:
                    fname, result, fcall, call_id = item
                else:
                    fname, result, fcall = item
                    call_id = getattr(fcall, "id", None)

                # Skip the sentinel — we don't emit a FunctionResponse for it
                if fname == "__RETRY_WITH_TEXT__":
                    continue

                names_emitted.append(fname)

                try:
                    response_name = fname

                    if isinstance(result, dict) and result.get("ack_only"):
                        ack = result["safety_ack_payload"]
                        rn = ack["name"]
                        fr = types.FunctionResponse(
                            id=ack["id"],           # <-- original id only
                            name=rn,
                            response=ack["response"],
                        )
                        function_response_parts.append(fr)
                    elif isinstance(result, dict) and result.get("deferred"):
                        exec_id = call_id or getattr(fcall, "id", None) or f"deferred-{fname}-{int(time.time()*1000)}"
                        fr = types.FunctionResponse(
                            id=exec_id,
                            name=response_name,
                            response={"status": "deferred_due_to_safety_ack"},
                        )
                        function_response_parts.append(fr)
                    else:
                        url = current_page_url()
                        base_ack = {
                            "function_name": fname,
                            "acknowledged": True,
                            "url": url,
                            "page_url": url,
                            "result": result if isinstance(result, dict) else {"result": str(result)}
                        }
                        new_screenshot = get_screenshot_bytes()
                        exec_id = call_id or getattr(fcall, "id", None) or f"exec-{fname}-{int(time.time()*1000)}"

                        fr = types.FunctionResponse(
                            id=exec_id,
                            name=response_name,
                            response=base_ack,
                            parts=[types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=new_screenshot
                                )
                            )],
                        )
                        function_response_parts.append(fr)
                        session_done = any(
                                    isinstance(fr.response, dict) and fr.response.get("result", {}).get("done") 
                                    for fr in function_response_parts
                                )
                        if session_done:
                            print("✅ Primary objective completed; ending session.")
                            return

                except Exception as e:
                    fr = types.FunctionResponse(
                        id=call_id or getattr(fcall, "id", None) or f"error-{fname}-{int(time.time()*1000)}",
                        name=fname,
                        response={"status": "error", "message": f"builder_exception: {str(e)}"},
                    )
                    function_response_parts.append(fr)


            # --- RESPONSE LOGIC ---

            # Prefer tool role for function responses (Gemini stability)
            use_tool_role = os.environ.get("FORCE_TOOL_ROLE", "1").lower() in ("1", "true", "yes")
            role_for_response = "tool" if use_tool_role else "user"

            # 0) Defensive: if nothing to emit (e.g., the model sent text only), still feed pixels
            if not function_response_parts:
                latest = get_screenshot_bytes()
                chat_history.append(Content(
                    role="user",
                    parts=[
                        Part(text="[state update] No tool responses to emit; continue the plan (authenticate if needed, then crawl & extract)."),
                        Part.from_bytes(data=latest, mime_type="image/png")
                    ]
                ))
                # If we expect a gated retry, still nudge; otherwise proceed to next model call
                if needs_retry:
                    chat_history.append(Content(
                        role="user",
                        parts=[Part(text=(
                            "Safety requirement: Your last tool call was gated. Re-issue the same action with a proper function_call.id, "
                            "and prefer semantic actions (e.g., click_button_by_text/ui_click_label) instead of coordinate clicks."
                        ))]
                    ))
                # Go to next turn
                continue

            # 1) Append the FunctionResponse(s) ONCE (ACKs and normal results together)
            print(f"[Debug] Emitted {len(function_response_parts)} FunctionResponses as role={role_for_response} "
                f"for: {', '.join([fr.name for fr in function_response_parts])}")
            chat_history.append(Content(
                role=role_for_response,
                parts=[Part(function_response=fr) for fr in function_response_parts]
            ))

            # 1b) Always provide a *fresh* screenshot right after tool responses so the model
            # has current visual context on the next turn.
            latest = get_screenshot_bytes()
            page_url = current_page_url()
            chat_history.append(Content(
                role="user",
                parts=[
                    Part(text=f"[state update] url: {page_url or '(unknown)'}"),
                    Part.from_bytes(data=latest, mime_type="image/png")
                ]
            ))

            # 2) AFTER appending responses and the state update, optionally send a nudge for gated calls.
            # This guarantees ACKs arrive before the instruction, avoiding INVALID_ARGUMENT churn.
            if needs_retry:
                chat_history.append(Content(
                    role="user",
                    parts=[Part(text=(
                        "Safety requirement: Your last tool call was gated. Re-issue the same action with a proper function_call.id, "
                        "and prefer semantic actions (e.g., click_button_by_text/ui_click_label) instead of coordinate clicks."
                    ))]
                ))
                continue  # proceed to next turn


        print("--- Agent session finished ---")
        if playwright_context.get("context"):
            try:
                playwright_context["context"].close()
            except Exception:
                pass
        if playwright_context.get("browser"):
            try:
                playwright_context["browser"].close()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        run_agent()
    except pyautogui.FailSafeException:
        print("\n[ABORTED] Fail-safe triggered — mouse moved to top-left corner.")
        if playwright_context.get("browser"):
            playwright_context["browser"].close()
        exit(0)
