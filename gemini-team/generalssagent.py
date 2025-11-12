# generalssagent.py
# Generalized privacy/data settings screenshot agent — storageState-first, Chromium only.
# - No sign-in flow: you MUST pre-save storage state per site (see save_state.py).
# - Planner (Gemini) returns JSON with actions: selectors to click + what to capture.
# - Executor performs the clicks and captures (full-page + element-level).
# - Outputs to ./generaloutput (screenshots + harvest_report.json).
#
# First time per site:
#   python save_state.py "$START_URL"
#   Log in to the site with credentials:
#   E: zoomaitester10@gmail.com
#   P: ZoomTestPass
#
# ENV:
#   export GEMINI_API_KEY="your_api_key_here" \
#   START_URL="https://zoom.us/profile/setting?tab=general" \
#   PLATFORM_NAME="zoom" 


# Example START_URLs:
# https://zoom.us/profile/setting?tab=general
# https://www.linkedin.com/mypreferences/d/categories/account 
# https://accountscenter.facebook.com/password_and_security 

# Optional:
#   export DEVICE_TYPE="MacBook"
#   export MAX_MODEL_CALLS="5"
#   
#
# RUN:
#   python generalssagent.py

import os, re, io, sys, json, time, random, traceback
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse

import pyautogui
from playwright.sync_api import sync_playwright, Page, TimeoutError as PwTimeout

from google import genai
from google.genai import types
from google.genai.types import Content, Part

# =========================
# Config & Globals
# =========================

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY not set.")
    sys.exit(1)

START_URL = os.environ.get("START_URL") or "about:blank"
DEVICE_TYPE = os.environ.get("DEVICE_TYPE", "MacBook")
MODEL_PLAN = os.environ.get("MODEL_PLAN", "gemini-2.5-pro")
MAX_MODEL_CALLS = int(os.environ.get("MAX_MODEL_CALLS", "5"))

# Where this script lives (not CWD), so outputs are stable if you run from elsewhere.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PLATFORM_NAME priority:
# 1) Explicit env PLATFORM_NAME
# 2) If START_URL host exists, sanitized host
# 3) "default"
_plat_env = os.environ.get("PLATFORM_NAME", "").strip()
if _plat_env:
    PLATFORM_NAME = re.sub(r'[^a-zA-Z0-9._-]+', '_', _plat_env)
else:
    try:
        _host = (urlparse(os.environ.get("START_URL", "")).hostname or "").strip()
        PLATFORM_NAME = re.sub(r'[^a-zA-Z0-9._-]+', '_', _host) if _host else "default"
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
pyautogui.PAUSE = 0.4

client = genai.Client(api_key=API_KEY)

# =========================
# Utilities
# =========================

def ts() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def safe_name(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]+', '_', s.strip()) or "unnamed"

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
      /Users/you/repo/.../generaloutput/zoom/...  ->  /generaloutput/zoom/...
    """
    try:
        rel = os.path.relpath(p, BASE_DIR)  # from repo root
        rel = rel.replace(os.sep, "/")      # normalize slashes for JSON/portability
        if not rel.startswith("/"):
            rel = "/" + rel
        return rel
    except Exception:
        # Fallback: at least return something readable
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
    except PwTimeout:
        return None
    except Exception:
        return None

def viewport_dom_textmap(page: Page, max_items=120) -> str:
    items = []
    try:
        for sel in ["h1,h2,h3,[role='heading']", "a,button", "[role='tab']", "[role='menuitem']", "[aria-label]"]:
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
                    t = re.sub(r'\s+', ' ', t)
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
    """Compact DOM outline to anchor CV with roles/labels/expand info."""
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

# =========================
# Metrics / Cost Config
# =========================

# Pricing
# Input:  $1.25 per 1M tokens
# Output: $10.00 per 1M tokens
# You can override via env; keep values PER 1M tokens.
COST_IN_PER_1M  = float(os.environ.get("GEM_COST_IN_PER_1M",  "1.25"))
COST_OUT_PER_1M = float(os.environ.get("GEM_COST_OUT_PER_1M", "10.0"))

def _rough_token_estimate(text: str) -> int:
    # 1 token ≈ 4 chars heuristic; used ONLY if API doesn't return usage.
    try:
        return max(1, int(len(text) / 4))
    except Exception:
        return 0

def _usd(input_tokens: int, output_tokens: int) -> float:
    # Price per ONE token
    in_per_token  = COST_IN_PER_1M  / 1_000_000.0
    out_per_token = COST_OUT_PER_1M / 1_000_000.0
    return round(input_tokens * in_per_token + output_tokens * out_per_token, 8)

# =========================
# Report and State
# =========================

def new_report(h: str) -> Dict[str, Any]:
    return {
        "site": h,
        "ts_iso": datetime.utcnow().isoformat() + "Z",
        "actions": [],
        "sections": [],
        "errors": [],
        "model_calls": 0,
        "state": {
            "visited_urls": [],
            "captured_sections": [],
            "last_capture_url": None
        },
        "metrics": {
            # Efficiency
            "run_start_ts": None,
            "run_end_ts": None,
            "total_runtime_sec": None,
            "turns": 0,
            "steps": {  # executor actions
                "batch_clicks": 0,
                "selectors_applied": 0,
                "fullpage_screens": 0,
                "element_screens": 0,
                "auto_screens": 0
            },
            # API usage/costs
            "api": {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "per_call": []  # list of {turn, input_tokens, output_tokens, cost_usd, source:"usage|estimate"}
            }
        }
    }

def log_action(report: Dict[str, Any], kind: str, detail: Dict[str, Any]):
    report["actions"].append({"ts": ts(), "kind": kind, **detail})

def add_section(report: Dict[str, Any], name: str, path: List[str], url: str, fullpage_path: Optional[str]):
    report["sections"].append({
        "name": name,
        "path": path,
        "url": url,
        "evidence_fullpage": fullpage_path,
        "items": []
    })

def save_report(report: Dict[str, Any]):
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[report] {JSON_OUT}")

# =========================
# Planner (model)
# =========================

class Budget:
    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0
    def allow(self, n=1) -> bool:
        return (self.used + n) <= self.limit
    def consume(self, n=1):
        self.used += n

def planner(page: Page, budget: Budget, mode: str, executor_state: Dict[str, Any], extra_note: str = "") -> Optional[Dict[str, Any]]:
    if not budget.allow(1):
        return None
    budget.consume(1)

    # Visual + DOM context
    snap = page.screenshot(full_page=True)
    textmap = viewport_dom_textmap(page, max_items=120)
    outline = dom_outline(page, max_nodes=300)

    system_instruction = (
        f"You are a UI analyst agent operating a {DEVICE_TYPE}. "
        f"The starting URL is {START_URL}. The goal is to REVEAL and CAPTURE all privacy/data/security/recording SETTINGS "
        "for the signed-in user across any web app UI. You control nothing directly—you return structured guidance for an executor.\n\n"
        "GENERAL RULES\n"
        "- Stay generalized. Do NOT assume site-specific structures or names. Work only from the screenshot and the DOM signals provided.\n"
        "- Use both the screenshot and the provided DOM_TEXT_MAP and DOM_OUTLINE to propose precise role/text/CSS selectors; "
        "avoid coordinates unless no semantic target exists.\n"
        "- AVOID LEGAL/POLICY detours: If a policy/legal/marketing/external page is opened, deprioritize it and return to the app context.\n"
        "- CAPTURE POLICY: When a relevant settings surface is visible, request a full-page capture for that surface. "
        "For dialogs/popovers/toggles that reveal sensitive settings, you may also specify element-level captures.\n\n"
        "STATE AWARENESS\n"
        "- Do not propose navigation to URLs already in executor_state.visited_urls unless needed.\n"
        "- Do not propose captures for section names present in executor_state.captured_sections.\n"
        "- Prefer discovering new settings areas not yet captured; avoid loops/duplicates.\n\n"
        "OUTPUT CONTRACT (prefer JSON; plain text allowed):\n"
        "Option A (JSON):\n"
        "{\n"
        '  \"on_settings_page\": <bool>,\n'
        '  \"selectors\": [ { \"purpose\": <string>, \"selector\": <string>, \"type\": \"css\"|\"text\"|\"role\"|\"coord\", \"confidence\": <0..1> } ],\n'
        '  \"capture\": { \"fullpage\": <bool>, \"section_name\": <string|null>, \"elements\": [ { \"selector\": <string>, \"label\": <string> } ] },\n'
        '  \"batch\": { \"clicks\": [ { \"selector\": <string>, \"type\": \"css|text|role|coord\" } ], \"screenshots\": [ { \"fullpage\": true, \"section_name\": <string> } ] },\n'
        '  \"notes\": <short rationale>\n'
        "}\n"
        "Option B (Plain text micro-script):\n"
        "Lines of the form:\n"
        "CLICK    <type>    <selector>\n"
        "SHOTFP   <section_name>\n"
        "SHOTEL   <selector>   <label>\n\n"
        "TOKEN EFFICIENCY: If a visible tab strip or settings menu includes multiple relevant tabs/subtabs (e.g., Privacy, Security, Recording), "
        "propose up to 3–5 CLICK lines followed by a SHOTFP for the current tab in one response. Avoid loops and previously captured sections.\n"
    )

    prompt = (
        f"MODE: {mode}\n"
        f"EXECUTOR NOTE: {extra_note}\n"
        "Return either valid JSON (Option A) or plain-text micro-script lines (Option B). Do not mix styles.\n"
        "The DOM text map contains a lossy list of visible strings; it is not exhaustive.\n"
        "EXECUTOR_STATE_JSON:\n" + json.dumps(executor_state, ensure_ascii=False)
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.2,
        max_output_tokens=1200
    )

    last_err, resp = None, None

    # METRICS defaults so early returns can reference them safely
    usage_in = 0
    usage_out = 0
    src = "estimate"
    plan_gen_time = 0.0

    for attempt in range(3):
        t0 = time.time()
        try:
            resp = client.models.generate_content(
                model=MODEL_PLAN,
                contents=[Content(role="user", parts=[
                    Part(text=prompt),
                    Part(text="DOM_TEXT_MAP_START\n" + textmap + "\nDOM_TEXT_MAP_END"),
                    Part(text="DOM_OUTLINE_START\n" + outline + "\nDOM_OUTLINE_END"),
                    Part.from_bytes(data=snap, mime_type="image/png")
                ])],
                config=config
            )
            dt = time.time() - t0

            # --- METRICS: try to extract usage from response
            usage_in, usage_out, src = 0, 0, "estimate"
            try:
                md = getattr(resp, "usage_metadata", None) or getattr(resp, "usage", None)
                if md:
                    usage_in  = int(getattr(md, "input_tokens",  0) or 0)
                    usage_out = int(getattr(md, "output_tokens", 0) or 0)
                    if (usage_in + usage_out) > 0:
                        src = "usage"
                if (usage_in + usage_out) == 0:
                    c0 = (getattr(resp, "candidates", None) or [None])[0]
                    if c0:
                        md2 = getattr(c0, "usage_metadata", None)
                        if md2:
                            usage_in  = int(getattr(md2, "input_tokens",  0) or 0)
                            usage_out = int(getattr(md2, "output_tokens", 0) or 0)
                            if (usage_in + usage_out) > 0:
                                src = "usage"
            except Exception:
                pass

            if (usage_in + usage_out) == 0:
                est_in = _rough_token_estimate(prompt) + _rough_token_estimate(textmap) + _rough_token_estimate(outline)
                usage_in = est_in

            plan_gen_time = dt
            break

        except Exception as e:
            last_err = str(e)
            time.sleep(0.6 + attempt * 0.6)

    if resp is None:
        plan_usage = {
            "input_tokens": int(usage_in),
            "output_tokens": 0,
            "source": src,
            "latency_sec": float(plan_gen_time)
        }
        return {
            "on_settings_page": False,
            "selectors": [],
            "capture": {"fullpage": False, "section_name": None, "elements": []},
            "notes": f"planner_call_failed: {last_err or 'unknown'}",
            "_usage": plan_usage
        }

    text = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            plan_usage = {
                "input_tokens": int(usage_in),
                "output_tokens": 0,
                "source": src,
                "latency_sec": float(plan_gen_time)
            }
            return {
                "on_settings_page": False,
                "selectors": [],
                "capture": {"fullpage": False, "section_name": None, "elements": []},
                "notes": "no_candidates",
                "_usage": plan_usage
            }
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
        if not text or not isinstance(text, str):
            plan_usage = {
                "input_tokens": int(usage_in),
                "output_tokens": 0,
                "source": src,
                "latency_sec": float(plan_gen_time)
            }
            return {
                "on_settings_page": False,
                "selectors": [],
                "capture": {"fullpage": False, "section_name": None, "elements": []},
                "notes": "empty_text",
                "_usage": plan_usage
            }
    except Exception as e:
        plan_usage = {
            "input_tokens": int(usage_in),
            "output_tokens": 0,
            "source": src,
            "latency_sec": float(plan_gen_time)
        }
        return {
            "on_settings_page": False,
            "selectors": [],
            "capture": {"fullpage": False, "section_name": None, "elements": []},
            "notes": f"extract_error: {e}",
            "_usage": plan_usage
        }

    # ---- Robust parse: JSON first, else try micro-script ----
    out_tokens_est = _rough_token_estimate(text or "")
    plan_usage = {
        "input_tokens": int(locals().get("usage_in", 0)),
        "output_tokens": int(locals().get("usage_out", 0) or (out_tokens_est if locals().get("src","estimate")=="estimate" else 0)),
        "source": locals().get("src", "estimate"),
        "latency_sec": float(locals().get("plan_gen_time", 0.0))
    }
    # 1) JSON path
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # if legacy planners include an 'authenticated' field, ignore it silently
            data.pop("authenticated", None)
            data["_usage"] = plan_usage
            return data
    except Exception:
        pass

    # 2) Micro-script path
    parsed = {
        "on_settings_page": None,
        "selectors": [],
        "capture": {"fullpage": False, "section_name": None, "elements": []},
        "batch": {"clicks": [], "screenshots": []},
        "notes": "parsed_from_script"
    }
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines:
        # CLICK <type> <selector>
        m = re.match(r'^(CLICK)\s+(\w+)\s+(.+)$', ln, flags=re.I)
        if m:
            _, t, sel = m.groups()
            parsed["batch"]["clicks"].append({"type": t.lower(), "selector": sel.strip()})
            continue
        # SHOTFP <section_name>
        m = re.match(r'^(SHOTFP)\s+(.+)$', ln, flags=re.I)
        if m:
            _, sec = m.groups()
            parsed["batch"]["screenshots"].append({"fullpage": True, "section_name": sec.strip()})
            continue
        # SHOTEL <selector> <label>
        m = re.match(r'^(SHOTEL)\s+(\S+)\s+(.+)$', ln, flags=re.I)
        if m:
            _, sel, label = m.groups()
            parsed["capture"]["elements"].append({"selector": sel.strip(), "label": label.strip()})
            continue

    # If actionable items exist, return them
    if parsed["batch"]["clicks"] or parsed["batch"]["screenshots"] or parsed["capture"]["elements"]:
        parsed["_usage"] = plan_usage
        return parsed

    # Fallback if nothing parsed
    return {
        "on_settings_page": False,
        "selectors": [],
        "capture": {"fullpage": False, "section_name": None, "elements": []},
        "notes": "no_parse",
        "_usage": plan_usage
    }

# =========================
# Executor helpers
# =========================

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
                time.sleep(0.6)
                return True
        elif stype == "text":
            loc = page.locator(f'text="{sval}"')
            if loc.count():
                loc.first.click(timeout=3500)
                time.sleep(0.6)
                return True
        elif stype == "role":
            # Allow role= style selectors passed through (e.g., [role="tab"]:has-text("Recording"))
            loc = page.locator(sval)
            if loc.count():
                loc.first.click(timeout=3500)
                time.sleep(0.6)
                return True
        elif stype == "coord":
            parts = re.split(r'[, ]+', sval.strip())
            if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]):
                x, y = int(parts[0]), int(parts[1])
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.click()
                time.sleep(0.6)
                return True
    except Exception:
        return False
    return False

def apply_clicks_batch(page: Page, clicks: List[Dict[str, str]], report: Dict[str, Any], delay: float = 0.5):
    for c in clicks[:5]:
        ok = apply_selector(page, c)
        log_action(report, "batch_click", {"ok": ok, "selector": c, "url": page.url})
        if ok:
            report["metrics"]["steps"]["batch_clicks"] += 1
        time.sleep(delay)
        if ok:
            sec = c.get("selector") or "step"
            path = autosnap(page, report, label=f"after_click__{safe_name(sec)[:50]}", subdir="sections")
            if path:
                report["metrics"]["steps"]["auto_screens"] += 1
        if page.url not in report["state"]["visited_urls"]:
            report["state"]["visited_urls"].append(page.url)

def apply_screenshots_batch(page: Page, shots: List[Dict[str, Any]], report: Dict[str, Any]):
    for s in shots[:2]:  # safety cap per turn
        if s.get("fullpage"):
            sec = (s.get("section_name") or "Settings").strip()
            fp = fullpage_screenshot(page, label=sec.lower().replace(" ","_"), subdir="sections")
            add_section(report, sec, [sec], page.url, fullpage_path=fp)
            log_action(report, "capture_fullpage", {"url": page.url, "path": fp, "section": sec})
            report["metrics"]["steps"]["fullpage_screens"] += 1
            norm = sec.lower()
            if norm and norm not in report["state"]["captured_sections"]:
                report["state"]["captured_sections"].append(norm)
            report["state"]["last_capture_url"] = page.url
            if page.url not in report["state"]["visited_urls"]:
                report["state"]["visited_urls"].append(page.url)

def capture_block(page: Page, capture: Dict[str, Any], report: Dict[str, Any]):
    if not capture:
        return
    section_name = capture.get("section_name") or "Settings"
    if capture.get("fullpage"):
        fp = fullpage_screenshot(page, label=section_name.lower().replace(" ", "_"), subdir="sections")
        add_section(report, section_name, [section_name], page.url, fullpage_path=fp)
        log_action(report, "capture_fullpage", {"url": page.url, "path": fp, "section": section_name})
        report["metrics"]["steps"]["fullpage_screens"] += 1
        norm = section_name.strip().lower()
        if norm and norm not in report["state"]["captured_sections"]:
            report["state"]["captured_sections"].append(norm)
        report["state"]["last_capture_url"] = page.url
        if page.url not in report["state"]["visited_urls"]:
            report["state"]["visited_urls"].append(page.url)

    for el in capture.get("elements", []) or []:
        sel = el.get("selector") or ""
        label = el.get("label") or "element"
        if not sel:
            continue
        path = None
        try:
            path = element_screenshot(page, sel, label=label, subdir="elements")
        except Exception:
            path = None
        if path:
            log_action(report, "capture_element", {"url": page.url, "path": path, "label": label})
            report["metrics"]["steps"]["element_screens"] += 1

# --- Auto screenshot throttle to avoid spam on same URL frame-to-frame ---
_last_shot = {"url": None, "t": 0.0}
def autosnap(page: Page, report: Dict[str, Any], label: str, subdir: str = "sections", min_interval_sec: float = 0.8):
    try:
        import time as _time
        now = _time.time()
        url = page.url
        if _last_shot["url"] == url and (now - _last_shot["t"]) < min_interval_sec:
            return None
        path = fullpage_screenshot(page, label=label, subdir=subdir)
        log_action(report, "auto_fullpage", {"url": url, "path": path, "label": label})
        report["metrics"]["steps"]["auto_screens"] += 1
        _last_shot["url"] = url
        _last_shot["t"] = now
        if url not in report["state"]["visited_urls"]:
            report["state"]["visited_urls"].append(url)
        return path
    except Exception:
        return None

def page_change_signature(page: Page) -> Tuple[str, str]:
    """Lightweight change detector: (url_no_hash, dom_sig)."""
    try:
        url = page.url.split("#", 1)[0]
    except Exception:
        url = ""
    try:
        html = page.content()
        sig = str(hash(html[:200000]))
    except Exception:
        sig = str(time.time())
    return url, sig

# =========================
# Main flow (planner loop)
# =========================

def harvest():
    site = hostname(START_URL)
    report = new_report(site)
    report["metrics"]["run_start_ts"] = datetime.utcnow().isoformat() + "Z"
    budget = Budget(MAX_MODEL_CALLS)

    # StorageState-first launch (Chromium), else persistent profile
    STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")
    os.makedirs(STATE_DIR, exist_ok=True)
    host = urlparse(START_URL).hostname or "default"
    state_path = os.path.join(STATE_DIR, f"{host}.json")

    with sync_playwright() as p:
        context = None
        page = None

        if os.path.exists(state_path):
            # Ephemeral Chromium + storageState
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                storage_state=state_path,
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
                bypass_csp=True,
                java_script_enabled=True,
            )
            page = context.new_page()
            print(f"[state] Loaded storage state for {host} → {state_path}")
        else:
            # Fallback: persistent profile (first-time run)
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
        # initial baseline shot
        autosnap(page, report, label="initial_load", subdir="sections")

        MAX_TURNS = 10
        for turn in range(1, MAX_TURNS + 1):
            print(f"--- Planner Turn {turn} ---")
            report["metrics"]["turns"] = turn
            mode = "bootstrap" if turn == 1 else "iterate"

            plan = planner(
                page, budget, mode=mode,
                executor_state=report["state"],
                extra_note="Return JSON or micro-script only; the executor will follow your selectors and perform captures as instructed."
            )
            report["model_calls"] = budget.used
            # metrics: api usage per call
            u = (plan or {}).get("_usage") or {}
            if u:
                report["metrics"]["api"]["calls"] += 1
                report["metrics"]["api"]["input_tokens"] += int(u.get("input_tokens", 0))
                report["metrics"]["api"]["output_tokens"] += int(u.get("output_tokens", 0))
                cost = _usd(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)))
                report["metrics"]["api"]["cost_usd"] = round(report["metrics"]["api"]["cost_usd"] + cost, 6)
                report["metrics"]["api"]["per_call"].append({
                    "turn": report["metrics"]["turns"],
                    "input_tokens": int(u.get("input_tokens", 0)),
                    "output_tokens": int(u.get("output_tokens", 0)),
                    "latency_sec": float(u.get("latency_sec", 0.0)),
                    "cost_usd": round(cost, 6),
                    "source": u.get("source", "estimate")
                })
                log_action(report, "planner_usage", {
                    "turn": report["metrics"]["turns"],
                    "input_tokens": u.get("input_tokens", 0),
                    "output_tokens": u.get("output_tokens", 0),
                    "latency_sec": u.get("latency_sec", 0.0),
                    "cost_usd": round(cost, 6),
                    "source": u.get("source", "estimate")
                })

                # Optional live console line
                print(f"[metrics] turn={report['metrics']['turns']} calls={report['metrics']['api']['calls']} "
                      f"in={report['metrics']['api']['input_tokens']} out={report['metrics']['api']['output_tokens']} "
                      f"cost=${report['metrics']['api']['cost_usd']:.4f}")
            if not plan:
                log_action(report, "planner_empty", {"turn": turn})
                if not budget.allow(1):
                    break
                time.sleep(0.8)
                continue

            log_action(report, "planner_plan", {"turn": turn, "plan": plan})

            on_settings_page = bool(plan.get("on_settings_page", False))
            selectors = plan.get("selectors", []) or []
            capture = plan.get("capture", {}) or {}
            batch = plan.get("batch") or {}
            batch_clicks = batch.get("clicks") or []
            batch_shots = batch.get("screenshots") or []

            # 1) Execute batch clicks (multi-step)
            if batch_clicks:
                apply_clicks_batch(page, batch_clicks, report, delay=0.6)

            # 2) Then apply classic selectors (backward-compat)
            applied_any = False
            prev_url, prev_sig = page_change_signature(page)
            for sel in selectors[:6]:
                ok = apply_selector(page, sel)
                log_action(report, "apply_selector", {"ok": ok, "selector": sel, "url": page.url})
                if ok:
                    report["metrics"]["steps"]["selectors_applied"] += 1
                    applied_any = True
                    time.sleep(0.7)
                    sec = sel.get("selector") or "selector_step"
                    autosnap(page, report, label=f"after_click__{safe_name(sec)[:50]}", subdir="sections")
                    if page.url not in report["state"]["visited_urls"]:
                        report["state"]["visited_urls"].append(page.url)
                    cur_url, cur_sig = page_change_signature(page)
                    changed = (cur_url != prev_url) or (cur_sig != prev_sig)
                    if changed:
                        try:
                            title = (page.title() or "").strip()
                        except Exception:
                            title = ""
                        if not title:
                            try:
                                tail = cur_url.rstrip("/").split("/")[-1]
                            except Exception:
                                tail = "section"
                            title = tail or "section"
                        label = title.lower().replace(" ", "_")[:60]
                        fp = fullpage_screenshot(page, label=label, subdir="sections")
                        add_section(report, title or "Section", [title or "Section"], page.url, fullpage_path=fp)
                        log_action(report, "auto_capture_fullpage", {"url": page.url, "path": fp, "label": title})
                        norm = (title or "section").strip().lower()
                        if norm and norm not in report["state"]["captured_sections"]:
                            report["state"]["captured_sections"].append(norm)
                        report["state"]["last_capture_url"] = page.url
                        prev_url, prev_sig = cur_url, cur_sig
                    else:
                        prev_url, prev_sig = cur_url, cur_sig

            # 3) Capture block (no auth gating)
            if capture and (capture.get("fullpage") or capture.get("elements")):
                sec = (capture.get("section_name") or "Settings").strip().lower()
                if capture.get("fullpage") and sec in report["state"]["captured_sections"]:
                    capture = {**capture, "fullpage": False}
                capture_block(page, capture, report)

            # 4) Execute any batch screenshots (no gating)
            if batch_shots:
                apply_screenshots_batch(page, batch_shots, report)

            # Exit heuristic: on settings + something captured + no next selectors
            if on_settings_page and not selectors and report["state"]["captured_sections"]:
                break

            if not budget.allow(1):
                break
            time.sleep(0.6)

        # Safety: if nothing captured, take one full-page for traceability
        if not report["sections"]:
            try:
                fp = fullpage_screenshot(page, label="safety_capture", subdir="sections")
                add_section(report, "Safety Capture", ["Safety"], page.url, fullpage_path=fp)
                log_action(report, "capture_fullpage", {"url": page.url, "path": fp, "section": "Safety Capture"})
            except Exception:
                pass

        try:
            autosnap(page, report, label="end_of_run", subdir="sections")
        except Exception:
            pass
        report["metrics"]["run_end_ts"] = datetime.utcnow().isoformat() + "Z"
        try:
            t0 = datetime.fromisoformat(report["metrics"]["run_start_ts"].replace("Z",""))
            t1 = datetime.fromisoformat(report["metrics"]["run_end_ts"].replace("Z",""))
            report["metrics"]["total_runtime_sec"] = (t1 - t0).total_seconds()
        except Exception:
            pass
        save_report(report)

        # Refresh storage state for future runs
        try:
            STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")
            os.makedirs(STATE_DIR, exist_ok=True)
            state_path = os.path.join(STATE_DIR, f"{host}.json")
            context.storage_state(path=state_path)
            print(f"[state] Refreshed storage state → {state_path}")
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