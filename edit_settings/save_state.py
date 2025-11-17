#!/usr/bin/env python3

# First time per site:
#   python save_state.py "$START_URL"
#   or
#   python save_state.py --service facebook
#   python save_state.py --json-file json_data/linkedin.json
#
#   Log in to the site with credentials:
#   E: zoomaitester10@gmail.com
#   P: ZoomTestPass


import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")


def extract_service_name(json_file_path: str) -> str:
    """
    Extract service name from JSON file path.
    
    Args:
        json_file_path: Path to JSON file (e.g., "json_data/facebook.json")
        
    Returns:
        Service name (e.g., "facebook", "linkedin", "zoom")
    """
    path = Path(json_file_path)
    # Get filename without extension
    service_name = path.stem
    return service_name.lower()


def get_default_storage_state_file(service_name: str) -> str:
    """
    Generate default storage state file path based on service name.
    Matches the same function in navigate_to_urls.py.
    
    Args:
        service_name: Service name (e.g., "facebook", "linkedin", "zoom")
        
    Returns:
        Default storage state file path
    """
    # Map service names to default storage file patterns
    storage_patterns = {
        "facebook": "profiles/storage/accountscenter.facebook.com.json",
        "linkedin": "profiles/storage/www.linkedin.com.json",
        "zoom": "profiles/storage/zoom.us.json",
    }
    
    # Use pattern if available, otherwise generate generic one
    if service_name in storage_patterns:
        return storage_patterns[service_name]
    else:
        return f"profiles/storage/{service_name}.json"


def main():
    parser = argparse.ArgumentParser(
        description="Save browser storage state (cookies, localStorage) for a service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using URL (legacy method)
  python save_state.py https://www.facebook.com
  
  # Using service name
  python save_state.py --service facebook
  
  # Using JSON file (auto-detects service)
  python save_state.py --json-file json_data/linkedin.json
        """
    )
    parser.add_argument("url", nargs="?", help="Start URL (legacy method, optional if --service or --json-file provided)")
    parser.add_argument("--service", help="Service name (e.g., 'facebook', 'linkedin', 'zoom')")
    parser.add_argument("--json-file", help="Path to JSON file (auto-detects service from filename)")
    parser.add_argument("--start-url", help="Start URL to navigate to (required with --service or --json-file)")
    args = parser.parse_args()
    
    # Determine service name and storage state file path
    service_name = None
    state_path = None
    start_url = None
    
    if args.json_file:
        # Extract service from JSON file
        service_name = extract_service_name(args.json_file)
        state_path = get_default_storage_state_file(service_name)
        start_url = args.start_url
        if not start_url:
            print("❌ Error: --start-url is required when using --json-file")
            print("   Example: --json-file json_data/linkedin.json --start-url https://www.linkedin.com")
            sys.exit(1)
    elif args.service:
        # Use provided service name
        service_name = args.service.lower()
        state_path = get_default_storage_state_file(service_name)
        start_url = args.start_url
        if not start_url:
            print("❌ Error: --start-url is required when using --service")
            print("   Example: --service linkedin --start-url https://www.linkedin.com")
            sys.exit(1)
    elif args.url:
        # Legacy method: derive from URL
        start_url = args.url.strip()
        # Normalize: if no scheme, assume https://
        parsed = urlparse(start_url)
        if not parsed.scheme:
            start_url = f"https://{start_url}"
            parsed = urlparse(start_url)
        
        host = parsed.hostname or "default"
        state_path = os.path.join(STATE_DIR, f"{host}.json")
        service_name = host.split('.')[0] if host else "default"
    else:
        parser.print_help()
        sys.exit(1)
    
    # Convert relative path to absolute if needed
    if state_path and not os.path.isabs(state_path):
        state_path = os.path.join(BASE_DIR, state_path)
    
    os.makedirs(os.path.dirname(state_path), exist_ok=True)

    print("=" * 60)
    print("💾 Save Storage State")
    print("=" * 60)
    if service_name:
        print(f"🔐 Service: {service_name}")
    print(f"🌐 Start URL: {start_url}")
    print(f"📁 Storage state will be saved to: {state_path}")
    print("=" * 60)
    
    with sync_playwright() as p:
        # 1) Launch Chromium (ephemeral)
        browser = p.chromium.launch(headless=False)

        # 2) Create a new context (this is where cookies/localStorage live)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            accept_downloads=True,
            bypass_csp=True,
            java_script_enabled=True,
        )

        # 3) Open a page and navigate
        page = context.new_page()
        print(f"\n🚀 Navigating to: {start_url}")
        page.goto(start_url, wait_until="load", timeout=60_000)

        print(f"\n✅ Loaded: {start_url}")
        print("\n💡 Instructions:")
        print("   1. Complete the sign-in process in the browser window")
        print("   2. Make sure you are logged in and can see the main interface")
        print("   3. When ready, return here and press Enter to save the session state")
        input("\n👉 Press Enter here to save the session state... ")

        # 4) Save storage state (cookies + localStorage + sessionStorage)
        context.storage_state(path=state_path)
        print(f"\n✅ Saved storage state → {state_path}")
        
        if service_name:
            print(f"\n💡 You can now use this storage state with navigate_to_urls.py:")
            print(f"   python navigate_to_urls.py --json-file json_data/{service_name}.json")

        # 5) Cleanup
        context.close()
        browser.close()
        
    print("\n✅ Complete!")

if __name__ == "__main__":
    main()


