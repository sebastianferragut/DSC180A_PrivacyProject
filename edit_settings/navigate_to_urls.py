#!/usr/bin/env python3
# Usage:
# python3 navigate_to_urls.py --find "password"
# or any other keyword to find a matching URL


import json
from pathlib import Path
from typing import List, Dict, Optional
import time
import argparse

try:
    from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Warning: Playwright is required for navigation")
    print("Install with: pip install playwright && playwright install chromium")


class URLNavigator:
    """Navigate to URLs from Facebook JSON data."""
    
    def __init__(self, json_file: str = "json_data/facebook.json", headless: bool = False,
                 email: str = "zoomaitester10@gmail.com", password: str = "ZoomTestPass",
                 use_persistent_profile: bool = False, profile_dir: Optional[str] = None,
                 storage_state_file: Optional[str] = "profiles/storage/accountscenter.facebook.com.json",
                 save_storage_after_login: bool = True):
        """
        Initialize navigator.
        
        Args:
            json_file: Path to Facebook JSON file
            headless: Whether to run browser in headless mode
            email: Email for login
            password: Password for login
            use_persistent_profile: Use a persistent user data dir for Chromium profile
            profile_dir: Directory for persistent profile (created if missing)
            storage_state_file: Playwright storage state file to load/save cookies/session
            save_storage_after_login: Save storage to storage_state_file after successful login
        """
        self.json_file = Path(json_file)
        self.data = self.load_json()
        self.headless = headless
        self.email = email
        self.password = password
        self.use_persistent_profile = use_persistent_profile
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.storage_state_file = Path(storage_state_file) if storage_state_file else None
        self.save_storage_after_login = save_storage_after_login
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.logged_in = False
        
    def load_json(self) -> Dict:
        """Load Facebook JSON data."""
        if not self.json_file.exists():
            raise FileNotFoundError(f"JSON file not found: {self.json_file}")
        
        with open(self.json_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_all_urls(self) -> Dict[str, List[str]]:
        """
        Extract all URLs from the JSON data.
        
        Returns:
            Dictionary with different URL categories
        """
        urls = {
            "visited_urls": self.data.get("state", {}).get("visited_urls", []),
            "section_urls": [sec.get("url") for sec in self.data.get("sections", []) if sec.get("url")],
            "action_urls": []
        }
        
        # Extract URLs from actions
        for action in self.data.get("actions", []):
            if "url" in action:
                url = action["url"]
                if url and url not in urls["action_urls"]:
                    urls["action_urls"].append(url)
        
        # Get unique URLs
        all_urls = set()
        for url_list in urls.values():
            all_urls.update(url_list)
        
        urls["all_unique"] = sorted(list(all_urls))
        
        return urls
    
    def extract_page_name(self, url: str) -> str:
        """Extract a readable page name from a URL."""
        try:
            if not url:
                return ""
            u = url.replace("https://", "").replace("http://", "")
            parts = u.split("/")
            if len(parts) > 1:
                tail = parts[-1].split("?")[0]
                if tail:
                    return tail.replace("-", " ").replace("_", " ").strip().lower()
            return parts[0].lower()
        except Exception:
            return ""
    
    def find_urls_by_text(self, text: str, url_category: str = "all_unique") -> List[str]:
        """
        Find URLs whose URL or page name contains the given text (case-insensitive).
        Returns candidates sorted by a simple relevance score.
        """
        urls = self.get_all_urls()
        haystack = urls.get(url_category, [])
        q = (text or "").strip().lower()
        if not q:
            return []
        
        scored = []
        for u in haystack:
            u_lower = u.lower()
            page_name = self.extract_page_name(u)
            score = 0
            if q in u_lower:
                score += 2
            if q in page_name:
                score += 3
            # prefer shorter URLs when scores tie (more specific)
            if score > 0:
                scored.append((score, len(u), u))
        # sort by score desc, then length asc
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [u for _, __, u in scored]
    
    def start_browser(self):
        """Start Playwright browser."""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright is not installed. Install with: pip install playwright && playwright install chromium")
        
        self.playwright = sync_playwright().start()
        context_kwargs = {
            "viewport": {"width": 1920, "height": 1080},
            "device_scale_factor": 1.0,
        }
        # Load storage state if provided
        if self.storage_state_file and self.storage_state_file.exists() and not self.use_persistent_profile:
            try:
                context_kwargs["storage_state"] = str(self.storage_state_file)
                print(f"🔐 Loaded storage state: {self.storage_state_file}")
            except Exception as e:
                print(f"⚠️  Could not load storage state: {e}")
        
        # Persistent profile takes precedence if requested
        if self.use_persistent_profile:
            if not self.profile_dir:
                # Default profile directory
                self.profile_dir = Path("profiles/chrome")
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            # Use persistent context (no separate Browser handle)
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport=context_kwargs["viewport"],
                device_scale_factor=context_kwargs["device_scale_factor"],
                args=[
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--window-size=1920,1080",
                ],
            )
            self.page = self.context.new_page() if not self.context.pages else self.context.pages[0]
            print(f"✅ Browser started with persistent profile: {self.profile_dir}")
        else:
            # Ephemeral browser/context
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--window-size=1920,1080",
                ],
            )
            self.context = self.browser.new_context(**context_kwargs)
            self.page = self.context.new_page()
            print("✅ Browser started")
    
    def is_login_page(self) -> bool:
        """
        Check if current page is a login page.
        
        Returns:
            True if login page detected
        """
        if not self.page:
            return False
        
        try:
            url = self.page.url.lower()
            title = self.page.title().lower()
            
            # Check URL patterns
            login_indicators = [
                "login" in url,
                "signin" in url,
                "auth" in url,
                "accountscenter.facebook.com" in url and "login" in url,
                "www.facebook.com/login" in url,
            ]
            
            # Check page content
            try:
                # Look for email/phone input field
                email_input = self.page.locator('input[type="email"], input[name="email"], input[id="email"], input[placeholder*="email" i], input[placeholder*="phone" i]').first
                if email_input.count() > 0:
                    return True
                
                # Look for password field
                password_input = self.page.locator('input[type="password"]').first
                if password_input.count() > 0:
                    return True
            except:
                pass
            
            # Check title
            if "log in" in title or "sign in" in title:
                return True
            
            return any(login_indicators)
        except:
            return False
    
    def perform_login(self, timeout: int = 30000) -> Dict[str, any]:
        """
        Perform login on the current page.
        
        Args:
            timeout: Timeout for login operations (milliseconds)
        
        Returns:
            Dictionary with login result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        if not self.is_login_page():
            return {
                "status": "skipped",
                "message": "Not on a login page"
            }
        
        try:
            print(f"🔐 Detected login page. Attempting to log in...")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
            time.sleep(1)
            
            # Find email input field (try multiple selectors)
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[id="email"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="phone" i]',
                'input[autocomplete="username"]',
                '#email',
                '#pass',
            ]
            
            email_input = None
            for selector in email_selectors:
                try:
                    locator = self.page.locator(selector).first
                    if locator.count() > 0:
                        email_input = locator
                        break
                except:
                    continue
            
            if not email_input or email_input.count() == 0:
                return {
                    "status": "error",
                    "message": "Could not find email input field"
                }
            
            # Fill email
            email_input.click(timeout=5000)
            time.sleep(0.5)
            email_input.fill(self.email)
            time.sleep(0.5)
            print(f"   ✅ Filled email: {self.email}")
            
            # Find password input field
            password_input = self.page.locator('input[type="password"]').first
            if password_input.count() == 0:
                return {
                    "status": "error",
                    "message": "Could not find password input field"
                }
            
            # Fill password
            password_input.click(timeout=5000)
            time.sleep(0.5)
            password_input.fill(self.password)
            time.sleep(0.5)
            print(f"   ✅ Filled password")
            
            # Find and click login button (try multiple selectors)
            login_button_selectors = [
                'button[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("Sign in")',
                'button:has-text("Login")',
                'input[type="submit"][value*="Log" i]',
                'button[id*="login" i]',
                '[role="button"]:has-text("Log in")',
            ]
            
            login_button = None
            for selector in login_button_selectors:
                try:
                    locator = self.page.locator(selector).first
                    if locator.count() > 0:
                        login_button = locator
                        break
                except:
                    continue
            
            if not login_button or login_button.count() == 0:
                # Try pressing Enter as fallback
                password_input.press("Enter")
                print(f"   ⚠️  Login button not found, pressed Enter")
            else:
                login_button.click(timeout=5000)
                print(f"   ✅ Clicked login button")
            
            # Wait for navigation or login to complete
            time.sleep(3)
            
            # Check if we're still on login page (login might have failed)
            if self.is_login_page():
                # Wait a bit more in case it's slow
                time.sleep(2)
                if self.is_login_page():
                    return {
                        "status": "error",
                        "message": "Still on login page after login attempt"
                    }
            
            self.logged_in = True
            print(f"   ✅ Login successful!")
            # Save storage after successful login for reuse
            try:
                if self.save_storage_after_login and not self.use_persistent_profile and self.storage_state_file:
                    self.storage_state_file.parent.mkdir(parents=True, exist_ok=True)
                    self.context.storage_state(path=str(self.storage_state_file))
                    print(f"   💾 Saved storage state to {self.storage_state_file}")
            except Exception as e:
                print(f"   ⚠️  Could not save storage state: {e}")
            
            return {
                "status": "success",
                "message": "Login completed",
                "current_url": self.page.url
            }
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Login failed: {str(e)}"
            }
    
    def navigate_to_url(self, url: str, wait_time: float = 2.0, auto_login: bool = True) -> Dict[str, any]:
        """
        Navigate to a specific URL.
        
        Args:
            url: URL to navigate to
            wait_time: Time to wait after page load (seconds)
            auto_login: Whether to automatically log in if login page is detected
        
        Returns:
            Dictionary with navigation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            print(f"🌐 Navigating to: {url}")
            self.page.goto(url, wait_until="load", timeout=60000)
            time.sleep(wait_time)
            
            # Check if we need to log in
            if auto_login and not self.logged_in and self.is_login_page():
                login_result = self.perform_login()
                if login_result["status"] == "success":
                    # Wait a bit more after login
                    time.sleep(2)
                elif login_result["status"] == "error":
                    print(f"   ⚠️  Login attempt failed: {login_result.get('message')}")
            
            current_url = self.page.url
            title = self.page.title()
            
            return {
                "status": "success",
                "requested_url": url,
                "actual_url": current_url,
                "title": title,
                "logged_in": self.logged_in,
                "timestamp": time.time()
            }
        except Exception as e:
            return {
                "status": "error",
                "url": url,
                "error": str(e),
                "timestamp": time.time()
            }
    
    def navigate_all_urls(self, url_category: str = "all_unique", wait_between: float = 2.0, auto_login: bool = True) -> List[Dict]:
        """
        Navigate to all URLs in a category.
        
        Args:
            url_category: Which URL category to navigate ("visited_urls", "section_urls", "all_unique", etc.)
            wait_between: Time to wait between navigations (seconds)
            auto_login: Whether to automatically log in if login page is detected
        
        Returns:
            List of navigation results
        """
        urls = self.get_all_urls()
        
        if url_category not in urls:
            raise ValueError(f"Invalid URL category: {url_category}. Available: {list(urls.keys())}")
        
        url_list = urls[url_category]
        results = []
        
        print(f"\n📋 Navigating to {len(url_list)} URLs from category: {url_category}")
        print("=" * 60)
        
        for i, url in enumerate(url_list, 1):
            print(f"\n[{i}/{len(url_list)}]")
            result = self.navigate_to_url(url, wait_time=wait_between, auto_login=auto_login)
            results.append(result)
            
            if result["status"] == "success":
                print(f"   ✅ Success: {result['title']}")
                if result.get("logged_in"):
                    print(f"   🔐 Logged in: Yes")
            else:
                print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
        
        return results
    
    def get_page_info(self) -> Dict:
        """Get information about the current page."""
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "viewport": self.page.viewport_size
        }
    
    def take_screenshot(self, filename: Optional[str] = None) -> str:
        """
        Take a screenshot of the current page.
        
        Args:
            filename: Optional filename. If None, generates from URL.
        
        Returns:
            Path to screenshot file
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        if not filename:
            # Generate filename from URL
            url = self.page.url
            safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_").replace("?", "_")
            filename = f"screenshots/{safe_name}.png"
        
        screenshot_path = Path(filename)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"📸 Screenshot saved: {screenshot_path}")
        return str(screenshot_path)
    
    def close_browser(self):
        """Close the browser."""
        if self.browser:
            self.browser.close()
        if hasattr(self, 'playwright'):
            self.playwright.stop()
        print("✅ Browser closed")


def main():
    """Main function to demonstrate URL navigation."""
    print("🔍 Facebook URL Navigator")
    print("=" * 60)
    
    parser = argparse.ArgumentParser(description="Navigate to URLs from facebook.json with optional targeting.")
    parser.add_argument("--url", help="Navigate directly to this URL (takes precedence).")
    parser.add_argument("--find", help="Keyword to find a matching URL (e.g., 'ads', 'password').")
    parser.add_argument("--category", default="all_unique",
                        choices=["visited_urls", "section_urls", "action_urls", "all_unique"],
                        help="URL category to search/use when --find is provided.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--no-headless", action="store_true", help="Force non-headless mode.")
    parser.add_argument("--auto-login", action="store_true", help="Enable auto-login when login page detected.")
    parser.add_argument("--no-auto-login", action="store_true", help="Disable auto-login.")
    parser.add_argument("--screenshot", help="Save a screenshot to this path after navigation.")
    parser.add_argument("--use-persistent-profile", action="store_true", help="Use a persistent Chromium profile.")
    parser.add_argument("--profile-dir", help="Directory for persistent profile (used with --use-persistent-profile).")
    parser.add_argument("--storage-state-file", default="profiles/storage/accountscenter.facebook.com.json",
                        help="Path to Playwright storage state JSON.")
    args, unknown = parser.parse_known_args()
    
    if not PLAYWRIGHT_AVAILABLE:
        print("❌ Error: Playwright is required")
        print("   Install with: pip install playwright")
        print("   Then run: playwright install chromium")
        return
    
    try:
        # Determine headless/auto-login flags
        headless_flag = args.headless or False
        if args.no_headless:
            headless_flag = False
        auto_login_flag = True
        if args.no_auto_login:
            auto_login_flag = False
        if args.auto_login:
            auto_login_flag = True
        
        # Initialize navigator with login credentials
        navigator = URLNavigator(
            "json_data/facebook.json", 
            headless=headless_flag,
            email="zoomaitester10@gmail.com",
            password="ZoomTestPass",
            use_persistent_profile=bool(args.use_persistent_profile),
            profile_dir=args.profile_dir,
            storage_state_file=args.storage_state_file,
            save_storage_after_login=True
        )
        
        # Show available URLs
        print("\n📋 Available URLs:")
        urls = navigator.get_all_urls()
        for category, url_list in urls.items():
            print(f"\n  {category}: {len(url_list)} URLs")
            for url in url_list[:3]:  # Show first 3
                print(f"    • {url}")
            if len(url_list) > 3:
                print(f"    ... and {len(url_list) - 3} more")
        
        # Start browser
        print("\n🚀 Starting browser...")
        navigator.start_browser()
        
        target_url = None
        if args.url:
            target_url = args.url if args.url.startswith("http") else f"https://{args.url}"
        elif args.find:
            candidates = navigator.find_urls_by_text(args.find, url_category=args.category)
            if not candidates:
                print(f"\n❌ No URLs matched '{args.find}' in category '{args.category}'.")
                return
            print(f"\n🔎 Matches for '{args.find}' ({len(candidates)}):")
            for i, u in enumerate(candidates[:5], 1):
                print(f"  {i}. {u}")
            target_url = candidates[0]
            print(f"\n➡️  Choosing best match: {target_url}")
        else:
            # Default: first URL in all_unique
            print("\n🌐 Navigating to first URL as example...")
            target_url = urls["all_unique"][0] if urls["all_unique"] else None
        
        if target_url:
            result = navigator.navigate_to_url(target_url, auto_login=auto_login_flag)
            if result["status"] == "success":
                print(f"   ✅ Successfully navigated to: {result['title']}")
                print(f"   📍 Current URL: {result['actual_url']}")
                if args.screenshot:
                    navigator.take_screenshot(args.screenshot)
            else:
                print(f"   ❌ Failed: {result.get('error')}")
        
        # Skip menu in CLI mode
        
        # Keep browser open for a bit
        print("\n⏳ Keeping browser open for 5 seconds...")
        time.sleep(5)
        
        # Close browser
        navigator.close_browser()
        
        print("\n✅ Navigation complete!")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


