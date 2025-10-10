# Install deps:
# pip install playwright sentence-transformers scikit-learn
# playwright install chromium

# Usage: 
# Finds privacy settings starting from a given URL, using Playwright to navigate the site.
# Requires a browser profile with an active login session for best results.

# Examples:
# python sebastian_privacy_agent.py https://app.zoom.us --profile ./profiles/chrome

# Early success test:
# python sebastian_privacy_agent.py https://zoom.us/profile/setting --profile ./profiles/chrome  

# WIP   
# python sebastian_privacy_agent.py https://app.slack.com/client/ --profile ./profiles/chrome 

import argparse, time, json, re
from contextlib import nullcontext
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict
from playwright.sync_api import sync_playwright
from playwright._impl._errors import TimeoutError as PWTimeout

# ==============================
# Constants & Heuristics
# ==============================

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

POLICY_LINK_HINTS = re.compile(r"(privacy\s*policy|privacy\s*statement|trust|legal|learn more|policy)", re.I)
POLICY_URL_HINTS  = re.compile(r"/(trust|legal|privacy[-_ ]?(policy|statement)|compliance)(/|$|\?)", re.I)

DATA_PRIVACY_PHRASE = re.compile(r"\b(data\s*&\s*privacy|privacy\s*&\s*data)\b", re.I)
SETTINGS_WORD       = re.compile(r"\b(settings?|preferences?)\b", re.I)
DATA_WORD           = re.compile(r"\bdata\b", re.I)

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

# Profile/Avatar heuristics (generalized)
PROFILE_TRIGGER_HINTS = re.compile(
    r"(profile|account|avatar|user|my account|google account|workspace|"
    r"open account menu|open user menu|open profile menu|settings)$", re.I
)
MY_PROFILE_HINTS = re.compile(r"\b(my\s*profile|profile)\b", re.I)
SETTINGS_MENU_ITEM_HINTS = re.compile(
    r"(settings?|preferences?|privacy\s*&?\s*visibility|data\s*&?\s*privacy|account\s*settings?|my\s*profile|profile)",
    re.I
)
AVATAR_TRIGGER_CLASS_HINTS = ("avatar", "header-avatar", "user-button", "profile", "account", "user")

# Track visited tabs per canonical URL to avoid ping-pong
visited_tabs: Dict[str, Set[str]] = defaultdict(set)

# ==============================
# Small Utilities
# ==============================

def canonical_url(u: str) -> str:
    try:
        s = urlsplit(u or "")
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

def wait_for_meaningful_change(page, before_sig, timeout_ms=4000, **kw):
    if "timeout" in kw and isinstance(kw["timeout"], (int, float)):
        timeout_ms = kw["timeout"]
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        now = page_state_signature(page)
        if now != before_sig:
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
    out, seen = [], set()
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

# ==============================
# Cookies & Success Detection
# ==============================

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
    if POLICY_URL_HINTS.search(url):
        return False
    tot, lab = count_privacy_controls(page)
    if clicks_so_far == 0:
        if SETTINGS_URL_HINT.search(url):
            return (tot >= 8) or (tot >= 4 and lab >= 1)
        return False
    if SETTINGS_URL_HINT.search(url):
        return (tot >= 8) or (tot >= 4 and lab >= 1)
    try:
        heads = page.locator(HEADINGS_CSS)
        n = min(heads.count(), 20)
        for i in range(n):
            txt = norm_text(heads.nth(i).inner_text()).lower()
            if re.search(r"(privacy\s*policy|cookie|terms)", txt):
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

# ==============================
# Clicking helpers
# ==============================

def safe_click(page_or_frame, node, label: str, timeout_ms=8000):
    # hover helps menus; keep it cheap so we don't collapse popovers
    try:
        node.hover(timeout=800)
        page_or_frame.wait_for_timeout(100)
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
        node.focus(timeout=800); page_or_frame.keyboard.press("Enter"); return True
    except Exception:
        pass
    return False

def click_maybe_popup(frame_or_page, node, label, timeout_ms=8000):
    """
    Click a node that may open a new tab/window. Works for Frame or Page.
    Returns (clicked_ok: bool, new_page_or_none).
    """
    try:
        owning_page = frame_or_page if hasattr(frame_or_page, "expect_popup") else frame_or_page.page
    except Exception:
        owning_page = None

    if owning_page is not None:
        try:
            with owning_page.expect_popup() as pop_info:
                ok = safe_click(frame_or_page, node, label, timeout_ms=timeout_ms)
            if ok:
                try:
                    new_pg = pop_info.value
                    try: new_pg.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception: pass
                    try: new_pg.bring_to_front()
                    except Exception: pass
                except Exception:
                    new_pg = None
                return ok, new_pg
        except Exception:
            pass

    ok = safe_click(frame_or_page, node, label, timeout_ms=timeout_ms)
    return ok, None

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
    url = (page.url or "").lower()
    if POLICY_URL_HINTS.search(url) or POLICY_LINK_HINTS.search(url):
        return False
    if DATA_PRIVACY_PHRASE.search(url):
        return True
    try:
        t = (page.title() or "").lower()
        if DATA_PRIVACY_PHRASE.search(t): return True
        if SETTINGS_WORD.search(t) and DATA_WORD.search(t): return True
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, [role=heading]")
        n = min(heads.count(), 10)
        for i in range(n):
            txt = (heads.nth(i).inner_text() or "").strip().lower()
            if not txt: continue
            if re.search(r"(privacy\s*policy|terms|cookie)", txt): continue
            if DATA_PRIVACY_PHRASE.search(txt): return True
            if SETTINGS_WORD.search(txt) and DATA_WORD.search(txt): return True
    except Exception:
        pass
    if SETTINGS_URL_HINT.search(url):
        try:
            above = (page.locator("body").inner_text() or "")[:1200].lower()
            if "data" in above and not re.search(r"(privacy\s*policy|terms|cookie|legal|trust)", above):
                return True
        except Exception:
            pass
    return False

# ==============================
# Avatar menu: find, open, pick item
# ==============================

def frame_candidates(frame):
    return frame.locator(
        "a, button, [role=button], [role=link], [role=menuitem], [aria-haspopup], [aria-controls], "
        "div, span"
    )

def score_as_avatar_trigger(node, label: str) -> float:
    s = 0.0
    lab = (label or "").lower()
    try:
        if (node.get_attribute("aria-haspopup") or "").lower() == "menu": s += 1.0
        if node.get_attribute("aria-controls") is not None:               s += 0.6
        if node.get_attribute("aria-expanded") is not None:               s += 0.6
    except Exception:
        pass
    try:
        role = (node.get_attribute("role") or "").lower()
        if role in {"button", "link", "menuitem"}: s += 0.3
    except Exception:
        pass
    try:
        cls = (node.get_attribute("class") or "").lower()
        if any(h in cls for h in AVATAR_TRIGGER_CLASS_HINTS): s += 0.9
    except Exception:
        pass
    if re.search(r"(profile|account|user|my account|google account|workspace)", lab): s += 0.8
    return s

def find_avatar_candidates_across_frames(page):
    out = []
    for fr in page.frames:
        nodes = frame_candidates(fr)
        n = min(nodes.count(), 500)
        for i in range(n):
            nd = nodes.nth(i)
            try:
                if not nd.is_visible(): continue
            except Exception:
                continue
            label = get_human_label(nd)
            lab = (label or "").lower()
            href = ""
            try: href = nd.get_attribute("href") or ""
            except Exception: pass
            if is_policy_target(lab, href): 
                continue
            score = score_as_avatar_trigger(nd, label)
            if score >= 1.2:
                out.append((fr, label, nd, score))
    out.sort(key=lambda x: x[3], reverse=True)
    return out

def wait_for_aria_expanded_toggle(node, timeout_ms=2500) -> bool:
    try:
        before = node.get_attribute("aria-expanded")
    except Exception:
        before = None
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        try:
            after = node.get_attribute("aria-expanded")
        except Exception:
            after = None
        if (before is None and after is not None) or (before is not None and after != before):
            return True
        time.sleep(0.06)
    return False

def find_revealed_menu_scope(frame, trigger_node):
    """
    Try to localize the revealed menu/panel area after trigger click.
    1) aria-controls target
    2) nearest role=menu/listbox/dialog/tablist
    3) fallback: the frame (works with extract_clickables because Frame has .locator)
    """
    try:
        cid = trigger_node.get_attribute("aria-controls")
        if cid:
            scope = frame.locator(f"#{cid}")
            if scope.count() and scope.first.is_visible():
                return scope
    except Exception:
        pass
    try:
        menu = frame.locator("[role=menu], [role=listbox], [role=dialog], nav[role=tablist]").first
        if menu and menu.count() and menu.is_visible():
            return menu
    except Exception:
        pass
    return frame

def open_avatar_then_settings(page) -> Tuple[bool, int, List[str], Optional[object]]:
    """
    Click avatar trigger once, keep the menu open,
    then click a menu item (My Profile preferred; otherwise Settings/Preferences/Data & Privacy).
    Returns (did_anything, clicks_added, labels_added, new_page_or_none).
    """
    cands = find_avatar_candidates_across_frames(page)
    if not cands:
        return (False, 0, [], None)

    for (fr, trig_label, trig_node, _) in cands[:6]:
        if not can_click_again(trig_label):
            continue

        before = page_state_signature(page)

        # Click the avatar/menu trigger ONCE (don’t use expect_popup here)
        if not safe_click(fr, trig_node, trig_label):
            continue

        # Start a short cooldown on the trigger so we don't re-click and collapse it
        recent_click_block[trig_label.lower()] = time.time() * 1000

        # Give the menu time to render; track aria-expanded if present
        wait_for_aria_expanded_toggle(trig_node, timeout_ms=1800)
        page.wait_for_timeout(160)

        # Menu/list scope
        scope = find_revealed_menu_scope(fr, trig_node)

        # Prefer My Profile first, then Settings-like items
        items = extract_clickables(scope)
        passes = [
            lambda lab: MY_PROFILE_HINTS.search(lab),
            lambda lab: SETTINGS_MENU_ITEM_HINTS.search(lab),
        ]

        for match_fn in passes:
            for label, node in items:
                lab = (label or "").lower()
                href = ""
                try: href = node.get_attribute("href") or ""
                except Exception: pass
                if not match_fn(lab):
                    continue
                if is_policy_target(lab, href):
                    continue
                if not can_click_again(label):
                    continue

                # Menu item MAY open new tab → capture it
                ok, new_page_obj = click_maybe_popup(fr, node, label)
                if not ok:
                    continue

                target = new_page_obj if new_page_obj is not None else page
                changed = wait_for_meaningful_change(target, before, timeout_ms=4000)
                if not changed:
                    continue

                recent_click_block[label.lower()] = time.time() * 1000
                return (True, 2, [trig_label, label], new_page_obj)

        # Only the trigger was clicked; no good item found
        return (True, 1, [trig_label], None)

    return (False, 0, [], None)

# ==============================
# Tabs (avoid ping-pong)
# ==============================

def is_tab(node) -> bool:
    try:
        role = (node.get_attribute("role") or "").lower()
        if role == "tab": return True
        if node.get_attribute("aria-selected") is not None: return True
        cls = (node.get_attribute("class") or "").lower()
        if "tab" in cls: return True
    except Exception:
        pass
    return False

def tab_is_active(node) -> bool:
    try:
        sel = (node.get_attribute("aria-selected") or "").lower()
        if sel == "true": return True
        cls = (node.get_attribute("class") or "").lower()
        if any(k in cls for k in ("active", "selected", "current", "is-active")): return True
    except Exception:
        pass
    return False

def should_skip_tab(page, label, node) -> bool:
    cur = canonical_url(page.url or "")
    lab = (label or "").strip().lower()
    if tab_is_active(node): return True
    if lab in visited_tabs[cur]: return True
    return False

def mark_tab_visited(page, label):
    cur = canonical_url(page.url or "")
    visited_tabs[cur].add((label or "").strip().lower())

# ==============================
# Agent (lean loop)
# ==============================

def run_agent(start_url: str, profile: Optional[str], max_steps: int = 12,
              query_terms: List[str] = None) -> Dict[str, Any]:
    terms = (query_terms or GOAL_TERMS)

    with sync_playwright() as p:
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

        # Hard-stop if we already landed on Data & Privacy or Settings+Data
        if looks_like_data_privacy_or_settings_with_data(page):
            result = {"success": True, "clicks": 0, "path": [], "final_url": page.url}
            ctx.close(); return result

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
            if handle_cookie_banner(page, tries=2):
                page.wait_for_timeout(200)

            # 1) Try avatar → My Profile/Settings/Data & Privacy first
            if not looks_like_data_privacy_or_settings_with_data(page):
                did_nav, added_clicks, added_labels, new_pg = open_avatar_then_settings(page)

                if did_nav and new_pg is not None:
                    try: new_pg.bring_to_front()
                    except Exception: pass
                    page = new_pg

                if did_nav:
                    for lab in added_labels:
                        recent_click_block[lab.lower()] = time.time() * 1000
                    clicks += added_clicks
                    path.extend(added_labels)

                    handle_cookie_banner(page)

                    if looks_like_data_privacy_or_settings_with_data(page) or verify_success(page, clicks):
                        result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
                        ctx.close(); return result

            # 2) Generic exploration (rank → click)
            candidates = extract_clickables(page)
            if not candidates:
                break
            labels = [c[0] for c in candidates]
            ranked = simple_rank(labels, terms)

            tried_any = False
            for idx, score in ranked[:12]:
                label, node = candidates[idx]
                if not is_safe_label(label): continue
                href = ""
                try: href = node.get_attribute("href") or ""
                except Exception: pass
                if is_policy_target(label, href): continue
                if not can_click_again(label): continue
                if is_tab(node) and should_skip_tab(page, label, node): continue

                tried_any = True
                before_sig = page_state_signature(page)

                clicked_ok, new_page_obj = click_maybe_popup(page, node, label)
                if not clicked_ok:
                    continue

                if new_page_obj is not None:
                    try: new_page_obj.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception: pass
                    try: new_page_obj.bring_to_front()
                    except Exception: pass
                    page = new_page_obj

                changed = wait_for_meaningful_change(page, before_sig, timeout_ms=4500)
                if not changed:
                    continue

                clicks += 1
                path.append(label)
                recent_click_block[label.lower()] = time.time() * 1000

                if is_tab(node):
                    mark_tab_visited(page, label)

                handle_cookie_banner(page)

                if looks_like_data_privacy_or_settings_with_data(page):
                    result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
                    ctx.close(); return result

                if verify_success(page, clicks):
                    result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
                    ctx.close(); return result

            if not tried_any:
                break

        result = {"success": False, "clicks": clicks, "path": path, "final_url": page.url,
                  "reason": "Max steps or no candidates"}
        ctx.close(); return result

# ==============================
# CLI
# ==============================
if __name__ == "__main__":
    import sys

    ap = argparse.ArgumentParser(
        prog="sebastian_privacy_agent.py",
        description="Agentic navigator to reach Data & Privacy or Settings surfaces."
    )
    # Make start_url optional; we'll show a welcome message if missing.
    ap.add_argument("start_url", nargs="?", help="Where to start (e.g., https://zoom.us)")
    ap.add_argument("--profile", help="Playwright persistent profile dir (keeps sign-in)", default=None)
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--query", nargs="*", help="Override goal terms (e.g., Privacy, Data & privacy)")
    args = ap.parse_args()

    if not args.start_url:
        print(
            "\n👋 Welcome to the Privacy Data Agent!\n"
            "This tool auto-navigates to a site's Data & Privacy / Settings pages.\n\n"
            "Examples:\n"
            "  python sebastian_privacy_agent.py https://zoom.us/profile --profile ./profiles/chrome\n"
            "  python sebastian_privacy_agent.py https://app.zoom.us --profile ./profiles/chrome\n"
            "  python sebastian_privacy_agent.py https://zoom.us/profile/setting --profile ./profiles/chrome\n\n"
            "Options:\n"
            "  --profile ./profiles/chrome   Use a persistent profile (keeps you signed in)\n"
            "  --max_steps 12                Limit the number of navigation steps\n"
        )
        sys.exit(0)

    result = run_agent(args.start_url, args.profile, max_steps=args.max_steps, query_terms=args.query)
    print(json.dumps(result, indent=2))

