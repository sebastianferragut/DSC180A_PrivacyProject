# Install dependencies:
# pip install playwright sentence-transformers scikit-learn
# playwright install chromium
# conda install -c conda-forge numpy 
# (or pip install numpy depending on your setup)

# Generic, semantic “Privacy finder” for arbitrary web apps.
# - Playwright navigates and clicks
# - SentenceTransformers ranks candidates semantically
# - Light planning loop with reflection/verification
#
# Usage:
#   python sebastian_privacy_agent.py https://app.slack.com/client --profile ./profiles/chrome
#   python sebastian_privacy_agent.py https://zoom.us --profile ./profiles/chrome
#   python sebastian_privacy_agent.py https://meet.google.com/ --profile ./profiles/chrome



import argparse, time, json, re, math
from contextlib import nullcontext
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple, Optional, Set

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

GOAL_SYNONYMS = [
    # Highest priority target
    "Privacy settings", "Data & privacy", "Privacy & visibility",
    # Secondary concepts / paths
    "Settings", "Preferences", "Account settings", "Security & privacy",
    # Fall-back words commonly seen
    "Privacy", "Data", "Permissions"
]

# If you localize, add Spanish/Portuguese etc.
GOAL_SYNONYMS_MULTI = GOAL_SYNONYMS + [
    "Privacidad", "Datos y privacidad", "Preferencias", "Configuración",
    "Cuenta", "Seguridad y privacidad", "Permisos"
]

CLICKABLE_CSS = "a, button, [role=button], [role=link], [role=menuitem], [role=tab]"


# Only URLs that are actually privacy settings pages
SUCCESS_URL_PATTERNS = [
    r"/privacy($|[/?#])",
    r"data[-_]?and[-_]?privacy",
    r"/account/privacy",
    r"/settings/privacy",
    r"/dataprivacy"
]

# Headings that indicate settings, not policies or cookies
SUCCESS_HEADING_ALLOW = [
    r"^data\s*&\s*privacy$",
    r"^privacy\s*&\s*visibility$",
    r"^privacy\s*settings$",
    r"^account\s*privacy$",
    r"^security\s*&\s*privacy$",
    r"^privacy$"
]

# Words that should NOT count as success (policy/legal/banners)
SUCCESS_HEADING_DENY = [
    r"privacy\s*policy",
    r"cookie",
    r"terms"
]

GOAL_TERMS = [
    # direct goals
    "Privacy settings", "Data & privacy", "Privacy & visibility",
    # intermediate hubs commonly used to reach privacy
    "Settings", "Preferences", "Manage your Google Account", "Account settings",
    "Security & privacy", "Profile", "Account"
    # (plus your Spanish terms if needed)
]


HEADINGS_CSS = "h1, h2, [role=heading]"

def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def is_meaningful(s: str) -> bool:
    s = norm_text(s)
    if len(s) < 2:  # avoid empty/near-empty
        return False
    # discard boilerplate
    bad = {"", "ok", "close", "cancel", "save", "open", "more", "learn more"}
    return s.lower() not in bad

def score_candidates(model, query_emb, labels: List[str]) -> List[Tuple[int, float]]:
    # Return sorted (index, score) desc
    if not labels:
        return []
    embs = model.encode(labels, convert_to_numpy=True)
    sims = cosine_similarity([query_emb], embs)[0]
    ranked = sorted(list(enumerate(sims)), key=lambda x: x[1], reverse=True)
    return ranked

def verify_success(page, clicks_so_far: int) -> bool:
    url = (page.url or "").lower()

    # If zero clicks so far, only accept if URL itself is a privacy URL
    # (prevents landing pages from being "success")
    if clicks_so_far == 0:
        if any(re.search(pat, url) for pat in SUCCESS_URL_PATTERNS):
            return True
        return False  # must click at least once unless already at privacy URL

    # After at least one click, allow URL or strong heading match
    if any(re.search(pat, url) for pat in SUCCESS_URL_PATTERNS):
        return True

    try:
        heads = page.locator(HEADINGS_CSS)
        n = min(heads.count(), 20)
        for i in range(n):
            txt = norm_text(heads.nth(i).inner_text()).lower()
            if any(re.search(p, txt) for p in SUCCESS_HEADING_DENY):
                continue
            if any(re.search(p, txt) for p in SUCCESS_HEADING_ALLOW):
                return True
    except Exception:
        pass
    return False

def grant_site_permissions(ctx, start_url):
    origin = f"{urlparse(start_url).scheme}://{urlparse(start_url).hostname}"
    # Grant only what’s relevant for each site:
    if "meet.google.com" in origin:
        ctx.grant_permissions(["microphone", "camera"], origin=origin)
    elif "zoom.us" in origin:
        ctx.grant_permissions(["microphone", "camera"], origin=origin)
    elif "slack.com" in origin:
        # Usually not needed, but you can pre-approve notifications if desired:
        ctx.grant_permissions(["notifications"], origin=origin)


def extract_clickables(page) -> List[Tuple[str, Any]]:
    """Return list of (label, locator) for visible clickables."""
    loc = page.locator(CLICKABLE_CSS).filter(has_text=re.compile(r".+"))
    count = min(loc.count(), 400)  # cap for speed
    items = []
    for i in range(count):
        node = loc.nth(i)
        if not node.is_visible():
            continue
        label = norm_text(try_text(node))
        if is_meaningful(label):
            items.append((label, node))
    # Deduplicate by label (keep first occurrence)
    seen = set()
    dedup = []
    for label, node in items:
        k = label.lower()
        if k in seen: 
            continue
        seen.add(k)
        dedup.append((label, node))
    return dedup

def try_text(node) -> str:
    # Try multiple sources for a human-visible label
    try:
        t = node.inner_text()
        if is_meaningful(t): return t
    except Exception: pass
    try:
        t = node.get_attribute("aria-label") or ""
        if is_meaningful(t): return t
    except Exception: pass
    try:
        t = node.get_attribute("title") or ""
        if is_meaningful(t): return t
    except Exception: pass
    return ""

def elem_signature(page) -> str:
    """Tiny signature of a page state for visited-set (url + top heading)."""
    url = page.url
    top = ""
    try:
        h = page.locator(HEADINGS_CSS)
        if h.count() > 0: top = norm_text(h.nth(0).inner_text())[:80]
    except Exception:
        pass
    return f"{url}||{top}"

def run_agent(start_url: str, profile: Optional[str], max_steps: int = 12,
              query_terms: List[str] = None) -> Dict[str, Any]:
    query_terms = query_terms or GOAL_SYNONYMS_MULTI
    with sync_playwright() as p:
        # Persistent context keeps logins
        ctx = (p.chromium.launch_persistent_context(user_data_dir=profile, headless=False, args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream"])
               if profile else p.chromium.launch(headless=False))
        grant_site_permissions(ctx, start_url)
        page = ctx.new_page() if not profile else ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(8000)
        page.goto(start_url)

        model = SentenceTransformer("all-MiniLM-L6-v2")
        query_emb = model.encode(" | ".join(query_terms), convert_to_numpy=True)

        clicks = 0
        path: List[str] = []
        visited: Set[str] = set()

        # Quick wins: if we landed on privacy already
        # before starting the loop
        if verify_success(page, clicks):
            return {"success": True, "clicks": clicks, "path": [], "final_url": page.url}

        # after each click
        if verify_success(page, clicks):
            return {"success": True, "clicks": clicks, "path": path, "final_url": page.url}


        for step in range(max_steps):
            sig = elem_signature(page)
            if sig in visited:
                # avoid loops; try a small scroll nudge
                try:
                    page.mouse.wheel(0, 500)
                except Exception:
                    pass
            visited.add(sig)

            # Collect visible candidates
            candidates = extract_clickables(page)
            labels = [c[0] for c in candidates]
            ranked = score_candidates(model, query_emb, labels)

            # Try top-K (breadth-ish)
            tried_any = False
            for idx, score in ranked[:12]:
                label, node = candidates[idx]
                # Prefer strong matches or likely paths ("Settings", "Preferences", "Account", then "Privacy")
                if score < 0.25 and step < 2:
                    # early steps: keep quality high to reduce drift
                    continue
                tried_any = True
                try:
                    with page.expect_popup() if opens_new_tab(label) else nullcontext():
                        node.click()
                    clicks += 1
                    path.append(label)
                    time.sleep(0.4)  # allow DOM to settle

                    # Switch to newest page if a new tab opened
                    if hasattr(page.context, "pages") and len(page.context.pages) > 1:
                        page = page.context.pages[-1]

                    # before starting the loop
                    if verify_success(page, clicks):
                        return {"success": True, "clicks": clicks, "path": [], "final_url": page.url}

                    # after each click
                    if verify_success(page, clicks):
                        return {"success": True, "clicks": clicks, "path": path, "final_url": page.url}


                    # Small heuristic: after clicking a generic “Settings/Preferences”, re-focus the query
                    # (already done by using broad GOAL_SYNONYMS_MULTI)
                    break  # move to next outer step after a click
                except PWTimeout:
                    # ignore and try next candidate
                    continue
                except Exception:
                    continue

            if not tried_any:
                break  # stuck

        result = {"success": False, "clicks": clicks, "path": path, "final_url": page.url, "reason": "Max steps or no candidates"}
        if profile: ctx.close()
        else: page.context.close()
        return result

def opens_new_tab(label: str) -> bool:
    # Lightweight heuristic: some “Manage your account” / “View more settings” links open new tabs
    l = label.lower()
    return any(x in l for x in ["manage your", "view more", "account.google.com", "admin", "portal"])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("start_url", help="Where to start (e.g., https://app.slack.com/client)")
    ap.add_argument("--profile", help="Playwright persistent profile dir (keeps sign-in)", default=None)
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--query", nargs="*", help="Override goal terms (e.g., Privacy, Data & privacy)")
    args = ap.parse_args()
    r = run_agent(args.start_url, args.profile, max_steps=args.max_steps, query_terms=args.query)
    print(json.dumps(r, indent=2))
