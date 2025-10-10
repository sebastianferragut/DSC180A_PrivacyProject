# Install deps:
# pip install playwright sentence-transformers scikit-learn
# playwright install chromium
# conda install -c conda-forge numpy  # or pip install numpy (if using embeddings)

# Usage: 
# Finds privacy settings starting from a given URL, using Playwright to navigate the site.
# Requires a browser profile with an active login session for best results.

# Examples:
# python sebastian_privacy_agent.py https://zoom.us/profile --profile ./profiles/chrome 

# Early success test:
# python sebastian_privacy_agent.py https://zoom.us/profile/setting --profile ./profiles/chrome  

# WIP 
# python sebastian_privacy_agent.py https://app.zoom.us --profile ./profiles/chrome  
# python sebastian_privacy_agent.py https://app.slack.com/client/T09KEQNA0S2/C09LB5R36N4 --profile ./profiles/chrome 

import argparse, time, json, re
from contextlib import nullcontext
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl
from typing import List, Dict, Any, Tuple, Optional, Set

from playwright.sync_api import sync_playwright
from playwright._impl._errors import TimeoutError as PWTimeout

# ----------------------------
# Constants (simple and generic)
# ----------------------------

DESTRUCTIVE_DENY = re.compile(
    r"\b(delete|terminate|remove|discard|erase|clear data|factory\s*reset|"
    r"deactivate|disable|close account|remove account|unlink|revoke|reset|"
    r"log\s*out|logout|sign\s*out|delete account)\b",
    re.I
)

GOAL_TERMS = [
    "privacy settings", "data & privacy", "privacy & visibility",
    "settings", "preferences", "account settings",
    "security & privacy", "account", "profile", "privacy"
]

# Treat these as legal/policy (avoid)
POLICY_LINK_HINTS = re.compile(r"(privacy\s*policy|privacy\s*statement|trust|legal|learn more|policy)", re.I)
POLICY_URL_HINTS  = re.compile(r"/(trust|legal|privacy[-_ ]?(policy|statement)|compliance)(/|$|\?)", re.I)

# --- Hard-stop detectors ---
DATA_PRIVACY_PHRASE = re.compile(r"\b(data\s*&\s*privacy|privacy\s*&\s*data)\b", re.I)
SETTINGS_WORD       = re.compile(r"\b(settings?|preferences?)\b", re.I)
DATA_WORD           = re.compile(r"\bdata\b", re.I)

# Consider success on settings-like pages with real controls
SETTINGS_URL_HINT = re.compile(r"/settings?($|[/?#])", re.I)
HEADINGS_CSS = "h1, h2, [role=heading]"

CONTROL_SELECTORS = [
    "input[type=checkbox]",
    "input[type=radio]",
    "[role=switch]",
    "button[aria-pressed]",
    ".switch, .toggle, .mat-slide-toggle, .ant-switch"
]
PRIVACY_CONTROL_HINTS = re.compile(
    r"(privacy|data|permission|consent|visibility|record|recording|chat history|"
    r"authentication|authenticated users|password|encryption|waiting room|"
    r"participants|who can|allow .* to|share .* data|profile visibility|"
    r"retention|history|cloud recording|local recording|microphone|camera)", re.I
)

CLICKABLE_SELECTORS = [
    "a", "button", "[role=button]", "[role=link]",
    "[role=menuitem]", "[role=tab]",
    "button[aria-label]", "a[aria-label]",
    "[role=button][aria-label]", "button[title]", "a[title]"
]

COOKIE_ACCEPT_HINTS = re.compile(r"(accept|agree|confirm|allow|ok|got it|continue|yes|consent)", re.I)
COOKIE_REJECT_HINTS = re.compile(r"(reject|decline|only necessary|essential|manage cookies|customize)", re.I)
COOKIE_PRIMARY_SELECTORS = [
    "#onetrust-accept-btn-handler", ".onetrust-accept-btn-handler",
    ".ot-pc-accept-all-handler", ".truste_button_1", ".truste-button1",
    "button[aria-label='Accept all']", "button[title='Accept all']",
]

# ----------------------------
# Small helpers
# ----------------------------

def canonical_url(u: str) -> str:
    try:
        s = urlsplit(u or "")
        # keep only meaningful query params
        keep = []
        for k, v in parse_qsl(s.query, keep_blank_values=True):
            if k.lower() in {"tab"}:
                keep.append((k, v))
        return urlunsplit((s.scheme, s.netloc, s.path.rstrip("/"),
                           "&".join([f"{k}={v}" for k,v in keep]), ""))  # strip fragment
    except Exception:
        return (u or "").split("#",1)[0].split("?",1)[0]

def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def is_safe_label(label: str) -> bool:
    return not DESTRUCTIVE_DENY.search((label or ""))

def page_state_signature(page) -> str:
    url = canonical_url(page.url or "")
    try:
        body_len = len(page.locator("body").inner_text()[:4000])
    except Exception:
        body_len = 0
    return f"{url}||{body_len}"

def wait_for_meaningful_change(page, before_sig, timeout_ms=4000) -> bool:
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        if page_state_signature(page) != before_sig:
            return True
        page.wait_for_timeout(120)
    return False

def get_human_label(node) -> str:
    try:
        t = node.inner_text().strip()
        if t: return t
    except Exception: pass
    for attr in ("aria-label", "title", "aria-describedby"):
        try:
            v = node.get_attribute(attr)
            if v and v.strip(): return v.strip()
        except Exception: pass
    try:
        img = node.locator("img[alt]").first
        if img.count():
            alt = img.get_attribute("alt") or ""
            if alt.strip(): return alt.strip()
    except Exception: pass
    return ""

def extract_clickables(scope):
    nodes = scope.locator(", ".join(CLICKABLE_SELECTORS))
    n = min(nodes.count(), 400)
    out = []
    seen = set()
    for i in range(n):
        nd = nodes.nth(i)
        try:
            if not nd.is_visible(): continue
        except Exception:
            continue
        label = get_human_label(nd)
        if not label or not is_safe_label(label): continue
        key = (label.lower(), str(nd.bounding_box() or {}))
        if key in seen: continue
        seen.add(key)
        out.append((label, nd))
    return out

def handle_cookie_banner(page, tries: int = 2) -> bool:
    acted = False
    for _ in range(tries):
        try:
            for sel in COOKIE_PRIMARY_SELECTORS:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible():
                    safe_click(page, loc.first, "cookie-accept")
                    acted = True
                    break
            if not acted:
                cand = page.locator("button, [role=button], a, input[type=button]")
                n = min(cand.count(), 80)
                for i in range(n):
                    node = cand.nth(i)
                    if not node.is_visible(): continue
                    label = (node.inner_text() or node.get_attribute("aria-label") or "").strip().lower()
                    if not label: continue
                    if COOKIE_ACCEPT_HINTS.search(label) and not COOKIE_REJECT_HINTS.search(label):
                        safe_click(page, node, label)
                        acted = True
                        break
        except Exception:
            pass
        page.wait_for_timeout(300)
    return acted

def count_privacy_controls(page) -> Tuple[int, int]:
    total = 0; labeled = 0
    try:
        nodes = page.locator(", ".join(CONTROL_SELECTORS))
        n = min(nodes.count(), 300)
        for i in range(n):
            nd = nodes.nth(i)
            try:
                if not nd.is_visible(): continue
            except Exception:
                continue
            total += 1
            txt = ""
            try:
                aria = nd.get_attribute("aria-labelledby")
                if aria:
                    t = page.locator("#" + aria.replace(" ", ", #")).all_inner_texts()
                    txt = " ".join(t or [])
            except Exception: pass
            if not txt:
                try:
                    txt = nd.locator("xpath=ancestor-or-self::*[self::label or @role='group' or @role='switch' or @role='radiogroup'][1]").inner_text()
                except Exception: pass
            if not txt:
                try:
                    txt = nd.locator("xpath=ancestor::*[self::div or self::section][1]").inner_text()[:400]
                except Exception: pass
            if txt and PRIVACY_CONTROL_HINTS.search(txt):
                labeled += 1
    except Exception:
        pass
    return total, labeled

def verify_success(page, clicks_so_far: int) -> bool:
    url = (page.url or "").lower()
    if POLICY_URL_HINTS.search(url):      # never count legal/trust
        return False
    # detect many controls (generic “settings surface”)
    tot, lab = count_privacy_controls(page)
    if clicks_so_far == 0:
        if SETTINGS_URL_HINT.search(url):
            return (tot >= 8) or (tot >= 4 and lab >= 1)
        return False
    if SETTINGS_URL_HINT.search(url):
        return (tot >= 8) or (tot >= 4 and lab >= 1)
    # Headings + controls
    try:
        heads = page.locator(HEADINGS_CSS)
        n = min(heads.count(), 20)
        for i in range(n):
            txt = norm_text(heads.nth(i).inner_text()).lower()
            if re.search(r"(privacy\s*policy|cookie|terms)", txt):  # deny
                continue
            if re.search(r"(privacy|data\s*&\s*privacy|privacy\s*&\s*visibility|security\s*&\s*privacy|settings)", txt):
                return (tot >= 8) or (tot >= 4 and lab >= 1)
    except Exception:
        pass
    return False

def is_policy_target(node_label: str, href: str) -> bool:
    lab = (node_label or "").lower()
    if POLICY_LINK_HINTS.search(lab): return True
    if href and (POLICY_URL_HINTS.search(href) or POLICY_LINK_HINTS.search(href)): return True
    return False

def safe_click(page, node, label: str, timeout_ms=8000):
    try:
        node.hover(timeout=800)
        page.wait_for_timeout(100)
    except Exception:
        pass
    try:
        node.click(timeout=timeout_ms)
        return True
    except PWTimeout:
        pass
    except Exception:
        pass
    try:
        node.click(timeout=timeout_ms, force=True)
        return True
    except Exception:
        pass
    try:
        node.evaluate("el => el.click()")
        return True
    except Exception:
        pass
    try:
        node.focus(timeout=800); page.keyboard.press("Enter"); return True
    except Exception:
        pass
    return False

# Cooldown (avoid double clicking same label immediately)
recent_click_block: Dict[str, float] = {}
def can_click_again(label, cool_ms=1600):
    t = recent_click_block.get(label.lower(), 0)
    return (time.time() * 1000 - t) > cool_ms

def grant_site_permissions(ctx, start_url):
    origin = f"{urlparse(start_url).scheme}://{urlparse(start_url).hostname}"
    if "meet.google.com" in origin or "zoom.us" in origin:
        ctx.grant_permissions(["microphone", "camera"], origin=origin)
    elif "slack.com" in origin:
        ctx.grant_permissions(["notifications"], origin=origin)

def simple_rank(labels: List[str], terms: List[str]) -> List[Tuple[int, float]]:
    terms = [t.lower() for t in terms]
    scored = []
    for i, L in enumerate(labels):
        s = (L or "").lower()
        score = sum(2.0 for t in terms if t in s)
        if "privacy" in s: score += 1.5
        scored.append((i, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored

def opens_new_tab(label: str) -> bool:
    l = (label or "").lower()
    return any(x in l for x in ["manage your", "view more", "account.google.com", "admin", "portal"])

def looks_like_data_privacy_or_settings_with_data(page) -> bool:
    """
    Return True if the current surface is:
      - explicitly a Data & Privacy page, OR
      - a Settings/Preferences page that clearly mentions 'data'
    (Trust/Legal/Policy pages are excluded.)
    """
    url = (page.url or "").lower()

    # Never treat Trust/Legal/Policy as success
    if POLICY_URL_HINTS.search(url) or POLICY_LINK_HINTS.search(url):
        return False

    # 1) URL says "data & privacy" (common on many products)
    if DATA_PRIVACY_PHRASE.search(url):
        return True

    # 2) Headings/Title checks
    try:
        # Page <title>
        t = (page.title() or "").lower()
        if DATA_PRIVACY_PHRASE.search(t):
            return True
        if SETTINGS_WORD.search(t) and DATA_WORD.search(t):
            return True
    except Exception:
        pass

    try:
        # Top headings / sections
        heads = page.locator("h1, h2, [role=heading]")
        n = min(heads.count(), 10)
        for i in range(n):
            txt = (heads.nth(i).inner_text() or "").strip().lower()
            if not txt:
                continue
            # exclude policy-ish headings
            if re.search(r"(privacy\s*policy|terms|cookie)", txt):
                continue
            if DATA_PRIVACY_PHRASE.search(txt):
                return True
            if SETTINGS_WORD.search(txt) and DATA_WORD.search(txt):
                return True
    except Exception:
        pass

    # 3) Tabs / obvious controls areas with "data" visible
    try:
        tabs = page.locator("[role=tab], .tab, .tabs, nav[role=tablist]")
        m = min(tabs.count(), 12)
        saw_settings = SETTINGS_WORD.search(url) is not None  # URL hint
        saw_data = False
        for i in range(m):
            text = (tabs.nth(i).inner_text() or "").lower()
            if "data" in text:
                saw_data = True
        if saw_settings and saw_data:
            return True
    except Exception:
        pass

    # 4) Fallback: settings-like URL AND visible word 'data' somewhere above the fold
    if SETTINGS_URL_HINT.search(url):
        try:
            above_fold = (page.locator("body").inner_text() or "")[:1200].lower()
            if "data" in above_fold:
                # Guard: avoid policy words
                if not re.search(r"(privacy\s*policy|terms|cookie|legal|trust)", above_fold):
                    return True
        except Exception:
            pass

    return False

# ----------------------------
# Agent (lean loop)
# ----------------------------

def run_agent(start_url: str, profile: Optional[str], max_steps: int = 12,
              query_terms: List[str] = None) -> Dict[str, Any]:
    terms = (query_terms or GOAL_TERMS)

    with sync_playwright() as p:
        # Context (persistent keeps login)
        if profile:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=profile, headless=False,
                args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream"]
            )
        else:
            browser = p.chromium.launch(headless=False,
                args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream"])
            ctx = browser.new_context()

        grant_site_permissions(ctx, start_url)
        page = ctx.new_page()
        page.set_default_timeout(8000)
        page.goto(start_url)
        handle_cookie_banner(page)

        # HARD-STOP early if we already landed on Data & Privacy or Settings+Data
        if looks_like_data_privacy_or_settings_with_data(page):
            result = {"success": True, "clicks": 0, "path": [], "final_url": page.url}
            ctx.close()
            return result

        clicks = 0
        path: List[str] = []
        visited: Set[str] = set()

        if verify_success(page, clicks):
            result = {"success": True, "clicks": clicks, "path": [], "final_url": page.url}
            ctx.close(); return result

        for step in range(max_steps):
            sig = page_state_signature(page)
            if sig in visited:
                try: page.mouse.wheel(0, 500)
                except Exception: pass
            visited.add(sig)

            handle_cookie_banner(page)

            candidates = extract_clickables(page)
            if not candidates: break
            labels = [c[0] for c in candidates]

            ranked = simple_rank(labels, terms)

            tried_any = False
            for idx, score in ranked[:12]:
                label, node = candidates[idx]

                if not is_safe_label(label): continue
                href = ""
                try: href = node.get_attribute("href") or ""
                except Exception: pass
                # Avoid policy/legal links by label or URL
                if is_policy_target(label, href): continue
                if not can_click_again(label): continue

                tried_any = True
                before_sig = page_state_signature(page)

                # Popup-aware but simple
                clicked_ok = False
                new_page_obj = None
                if opens_new_tab(label):
                    try:
                        with page.expect_popup() as pop:
                            clicked_ok = safe_click(page, node, label)
                        if clicked_ok:
                            new_page_obj = pop.value
                    except Exception:
                        clicked_ok = safe_click(page, node, label)
                else:
                    clicked_ok = safe_click(page, node, label)

                if not clicked_ok: continue

                # If a popup appeared, switch to it
                if new_page_obj is not None:
                    try: new_page_obj.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception: pass
                    page = new_page_obj

                # Count click only if state changed
                changed = wait_for_meaningful_change(page, before_sig, timeout_ms=4500)
                if not changed:
                    continue

                clicks += 1
                path.append(label)
                recent_click_block[label.lower()] = time.time() * 1000

                handle_cookie_banner(page)

                # HARD-STOP as soon as we hit Data & Privacy or Settings+Data
                if looks_like_data_privacy_or_settings_with_data(page):
                    result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
                    ctx.close()
                    return result


                if verify_success(page, clicks):
                    result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
                    ctx.close(); return result

            if not tried_any:
                break

        result = {"success": False, "clicks": clicks, "path": path, "final_url": page.url,
                  "reason": "Max steps or no candidates"}
        ctx.close(); return result

# ----------------------------
# CLI
# ----------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("start_url", help="Where to start (e.g., https://zoom.us)")
    ap.add_argument("--profile", help="Playwright persistent profile dir (keeps sign-in)", default=None)
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--query", nargs="*", help="Override goal terms (e.g., Privacy, Data & privacy)")
    args = ap.parse_args()
    r = run_agent(args.start_url, args.profile, max_steps=args.max_steps, query_terms=args.query)
    print(json.dumps(r, indent=2))