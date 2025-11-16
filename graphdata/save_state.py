#!/usr/bin/env python3

# First time per site:
#   python save_state.py "$START_URL"
#   Log in to the site with credentials:
#   E: zoomaitester10@gmail.com
#   P: ZoomTestPass


import os
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")

def main():
    if len(sys.argv) < 2:
        print("Usage: python save_state.py <START_URL>")
        sys.exit(1)

    start_url = sys.argv[1].strip()
    # Normalize: if no scheme, assume https://
    parsed = urlparse(start_url)
    if not parsed.scheme:
        start_url = f"https://{start_url}"
        parsed = urlparse(start_url)

    os.makedirs(STATE_DIR, exist_ok=True)
    host = parsed.hostname or "default"
    state_path = os.path.join(STATE_DIR, f"{host}.json")

    with sync_playwright() as p:
        # 1) Launch Chromium (ephemeral)
        browser = p.chromium.launch(headless=False)

        # 2) Create a new context (this is where cookies/localStorage live)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            accept_downloads=True,
            bypass_csp=True,
            java_script_enabled=True,
        )

        # 3) Open a page and navigate
        page = context.new_page()
        page.goto(start_url, wait_until="load", timeout=60_000)

        print(f"[bootstrap] Loaded: {start_url}")
        print("[bootstrap] Complete the sign-in in this window. When you see you are logged in,")
        input("press Enter here to save the session state... ")

        # 4) Save storage state (cookies + localStorage + sessionStorage)
        context.storage_state(path=state_path)
        print(f"[bootstrap] Saved storage state → {state_path}")

        # 5) Cleanup
        context.close()
        browser.close()

if __name__ == "__main__":
    main()


