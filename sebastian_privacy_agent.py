# Install dependencies:
# pip install playwright sentence-transformers scikit-learn
# playwright install chromium

# Generic, semantic “Privacy finder” for arbitrary web apps.
# - Playwright navigates and clicks
# - SentenceTransformers ranks candidates semantically
# - Light planning loop with reflection/verification
#
# Usage:
#   python privacy_agent_generic.py https://app.slack.com/client --profile ./profiles/chrome
#   python privacy_agent_generic.py https://zoom.us/profile --profile ./profiles/chrome
#   python privacy_agent_generic.py https://meet.google.com/ --profile ./profiles/chrome



import argparse, time, json, re, math
from contextlib import nullcontext
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

# Basic success check: URL or visible heading mentions privacy-ish keywords
SUCCESS_PATTERNS = [
    r"privacy", r"data[-\s]?and[-\s]?privacy", r"dataprivacy", r"permissions",
    r"privacy[-\s]?and[-\s]?visibility", r"security[-\s]?and[-\s]?privacy"
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

def verify_success(page) -> bool:
    url = page.url.lower()
    if any(re.search(pat, url) for pat in SUCCESS_PATTERNS):
        return True
    # Try headings
    try:
        heads = page.locator(HEADINGS_CSS)
        n = heads.count()
        for i in range(min(n, 20)):
            txt = norm_text(heads.nth(i).inner_text())
            if any(re.search(pat, txt.lower()) for pat in SUCCESS_PATTERNS):
                return True
    except Exception:
        pass
    # Try presence of target strings anywhere
    try:
        for term in ["Privacy", "Data & privacy", "Privacy & visibility"]:
            if page.get_by_text(term, exact=False).count() > 0:
                return True
    except Exception:
        pass
    return False

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
        ctx = (p.chromium.launch_persistent_context(user_data_dir=profile, headless=False)
               if profile else p.chromium.launch(headless=False))
        page = ctx.new_page() if not profile else ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(8000)
        page.goto(start_url)

        model = SentenceTransformer("all-MiniLM-L6-v2")
        query_emb = model.encode(" | ".join(query_terms), convert_to_numpy=True)

        clicks = 0
        path: List[str] = []
        visited: Set[str] = set()

        # Quick wins: if we landed on privacy already
        if verify_success(page):
            result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
            if profile: ctx.close()
            else: page.context.close()
            return result

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

                    if verify_success(page):
                        result = {"success": True, "clicks": clicks, "path": path, "final_url": page.url}
                        if profile: ctx.close()
                        else: page.context.close()
                        return result

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
