# scanner.py
import argparse, json, time, os, re, pathlib
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

PRIVACY_WORDS = [
    "privacy", "privacy settings", "privacy policy",
    "cookie", "cookies", "consent",
    "data", "data controls", "ad preferences",
    "gdpr", "preferences", "settings", "security"
]

def is_privacy_url(url: str) -> bool:
    u = (url or "").lower()
    return any(w in u for w in ["privacy", "cookie", "consent", "gdpr", "data", "settings", "security"])

def looks_like_privacy_text(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in PRIVACY_WORDS)

def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "unknown").replace(":", "_")
    path = re.sub(r"[^a-zA-Z0-9_-]+", "_", parsed.path)[:50]
    return f"{host}{path}"

def scan_privacy_click_depth(start_url: str, max_depth: int = 6, max_candidates_per_page: int = 30, timeout_ms: int = 15000):
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        visited = set()
        queue = [(start_url, 0, [])]

        try:
            while queue:
                url, depth, path = queue.pop(0)
                if depth > max_depth: 
                    continue
                if url in visited:
                    continue

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as e:
                    continue

                cur_url = page.url
                visited.add(cur_url)

                # quick checks
                if is_privacy_url(cur_url):
                    return {
                        "found": True,
                        "click_depth": depth,
                        "found_url": cur_url,
                        "path": path,
                        "time_ms": int((time.time()-t0)*1000),
                        "start_url": start_url
                    }

                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    pass

                if looks_like_privacy_text(body_text):
                    return {
                        "found": True,
                        "click_depth": depth,
                        "found_url": cur_url,
                        "path": path,
                        "time_ms": int((time.time()-t0)*1000),
                        "start_url": start_url
                    }

                # collect clickable candidates
                loc = page.locator('a,button,[role="button"],[onclick]')
                count = min(loc.count(), max_candidates_per_page)

                candidates = []
                for i in range(count):
                    el = loc.nth(i)
                    txt = ""
                    try:
                        txt = (el.inner_text() or "").strip()
                    except Exception:
                        pass
                    if not txt:
                        try:
                            txt = (el.get_attribute("aria-label") or "").strip()
                        except Exception:
                            pass
                    prio = 0 if any(k in (txt or "").lower() for k in ["menu","account","profile","settings","privacy","cookie","data","preferences","security","more"]) else 1
                    candidates.append((prio, i, txt))

                candidates.sort(key=lambda x: (x[0], x[1]))
                # try clicking top N candidates; enqueue new urls
                for _, i, txt in candidates[:15]:
                    el = loc.nth(i)
                    before = page.url
                    changed = False
                    try:
                        # Hover first to reveal hidden menus
                        try:
                            el.hover(timeout=500)
                        except Exception:
                            pass
                        el.click(timeout=1500)
                        # small wait for SPA route or DOM mutation
                        page.wait_for_timeout(300)
                        after = page.url
                        if after != before:
                            changed = True
                        else:
                            # even if URL didn't change, page text might; treat as new state
                            pass
                    except Exception:
                        continue

                    new_url = page.url
                    if new_url not in visited:
                        queue.append((new_url, depth+1, path + [txt or "(unlabeled)"]))
                        # go back to parent to try other candidates
                        try:
                            page.go_back(timeout=2000)
                        except Exception:
                            # if can't go back (modal or SPA), try re-nav to before
                            try:
                                page.goto(before, wait_until="domcontentloaded", timeout=timeout_ms)
                            except Exception:
                                pass

            return {
                "found": False,
                "click_depth": None,
                "found_url": None,
                "path": [],
                "time_ms": int((time.time()-t0)*1000),
                "start_url": start_url
            }
        finally:
            context.close()
            browser.close()

def write_result_json(result: dict):
    pathlib.Path("results").mkdir(parents=True, exist_ok=True)
    base = safe_filename_from_url(result.get("start_url","unknown"))
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = f"results/{base}-{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return out

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Count clicks to reach privacy settings")
    parser.add_argument("--url", required=True, help="Start URL, e.g. https://example.com")
    parser.add_argument("--max-depth", type=int, default=6)
    args = parser.parse_args()

    res = scan_privacy_click_depth(args.url, max_depth=args.max_depth)
    saved = write_result_json(res)
    print(json.dumps(res, indent=2))
    print(f"\nSaved JSON → {saved}")
