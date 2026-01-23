
# Save browser storage state after manual sign-in.

# This script launches a visible Chromium browser via Playwright, navigates to the provided START_URL,
# and lets the user complete an interactive sign-in. After the user confirms by pressing Enter in the
# terminal, the
# script saves the browser context's storage state (cookies, localStorage, sessionStorage) to
# profiles/storage/<hostname>.json (relative to this file).

# Usage:
#     python save_state.py <START_URL>

# Example:
#     python save_state.py https://example.com

# Prerequisites:
#     - Python 3.8+
#     - Install Playwright: pip install playwright
#     - Install Playwright browsers: playwright install

# Behavior:
#     - Browser runs with headless=False so you can interact.
#     - The storage state file is created under profiles/storage and named by the start URL's hostname.
#     - The script waits for you to complete sign-in and press Enter before saving.

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

    start_url = sys.argv[1]
    os.makedirs(STATE_DIR, exist_ok=True)
    host = urlparse(start_url).hostname or "default"
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
