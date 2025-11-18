#!/usr/bin/env python3
# Usage:
# python3 navigate_to_urls.py facebook --find "Personal Details" --change-birthday 5 15 1990
# python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --list-toggles
# python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --change-toggle "Enable notifications" disable
# python3 navigate_to_urls.py linkedin --ads
# or use --json-file for custom paths: python3 navigate_to_urls.py --json-file custom/path.json --find "password"


import json
from pathlib import Path
from typing import List, Dict, Optional, Any
import time
import argparse
import re
import os
import tempfile
import base64

try:
    from google import genai
    from google.genai import types
    from google.genai.types import Content, Part
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("Warning: google-genai is required for Gemini features")
    print("Install with: pip install google-genai")

try:
    from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Warning: Playwright is required for navigation")
    print("Install with: pip install playwright && playwright install chromium")


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


def click_save_if_present(page, timeout: int = 5000) -> bool:
    """
    If a Save button appears after a setting is changed, click it.
    Return True if Save was clicked, False otherwise.
    
    Behavior:
    - Look for any button whose visible text or aria-label contains "save" (case-insensitive)
    - Wait up to `timeout` ms for it to become visible
    - Scroll into view
    - Click it
    - Handle if "Cancel" is also present but ignore it
    - Should not throw; all errors return False
    """
    try:
        # Try to find a button with text containing "save" (case-insensitive)
        save_button = page.get_by_role("button", name=re.compile(r"save", re.I))
        
        # Wait for it to be visible
        save_button.first.wait_for(state="visible", timeout=timeout)
        
        # Scroll into view
        save_button.first.scroll_into_view_if_needed()
        
        # Click it
        save_button.first.click(timeout=5000)
        
        return True
    except Exception:
        # All errors return False - don't throw
        return False


class URLNavigator:
    """Navigate to URLs from JSON data for any service."""
    
    def __init__(self, json_file: str = "json_data/facebook.json", headless: bool = False,
                 email: str = "zoomaitester10@gmail.com", password: str = "ZoomTestPass",
                 use_persistent_profile: bool = False, profile_dir: Optional[str] = None,
                 storage_state_file: Optional[str] = None,
                 save_storage_after_login: bool = True):
        """
        Initialize navigator.
        
        Args:
            json_file: Path to JSON file containing URL data
            headless: Whether to run browser in headless mode
            email: Email for login
            password: Password for login
            use_persistent_profile: Use a persistent user data dir for Chromium profile
            profile_dir: Directory for persistent profile (created if missing)
            storage_state_file: Playwright storage state file to load/save cookies/session.
                               If None, will auto-generate based on service name from json_file
            save_storage_after_login: Save storage to storage_state_file after successful login
        """
        self.json_file = Path(json_file)
        self.service_name = extract_service_name(str(self.json_file))
        self.data = self.load_json()
        self.headless = headless
        self.email = email
        self.password = password
        self.use_persistent_profile = use_persistent_profile
        self.profile_dir = Path(profile_dir) if profile_dir else None
        
        # Auto-generate storage state file if not provided
        if storage_state_file is None:
            storage_state_file = get_default_storage_state_file(self.service_name)
        
        self.storage_state_file = Path(storage_state_file) if storage_state_file else None
        self.save_storage_after_login = save_storage_after_login
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.logged_in = False
        
    def load_json(self) -> Dict:
        """Load JSON data from the specified file."""
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
            
            # Check URL patterns (generic login detection)
            login_indicators = [
                "login" in url,
                "signin" in url,
                "sign-in" in url,
                "sign_in" in url,
                "auth" in url,
                "authenticate" in url,
                "account" in url and "login" in url,
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
    
    def navigate_to_url(self, url: str, wait_time: float = 2.0, auto_login: bool = True, auto_list_links: bool = False) -> Dict[str, any]:
        """
        Navigate to a specific URL.
        
        Args:
            url: URL to navigate to
            wait_time: Time to wait after page load (seconds)
            auto_login: Whether to automatically log in if login page is detected
            auto_list_links: Whether to automatically list links after navigation
        
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
            
            result = {
                "status": "success",
                "requested_url": url,
                "actual_url": current_url,
                "title": title,
                "logged_in": self.logged_in,
                "timestamp": time.time()
            }
            
            # Auto-list links if requested
            if auto_list_links and result["status"] == "success":
                self._display_links_after_navigation()
            
            return result
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
    
    def navigate_to_ads_page(self, auto_login: bool = True, auto_list_links: bool = False) -> Dict[str, any]:
        """
        Navigate to the ads preferences page.
        
        Args:
            auto_login: Whether to automatically log in if login page is detected
            auto_list_links: Whether to automatically list links after navigation
        
        Returns:
            Dictionary with navigation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        # Try to find ads URL from JSON data first
        urls = self.get_all_urls()
        ads_url = None
        
        # Look for ads URL in the data
        for url in urls.get("all_unique", []):
            if "/ads" in url.lower() or "ad" in url.lower():
                ads_url = url
                break
        
        # Fallback to common Facebook ads URL
        if not ads_url and self.service_name == "facebook":
            ads_url = "https://accountscenter.facebook.com/ads"
        elif not ads_url:
            # Generic fallback - try to construct from service
            ads_url = f"https://accountscenter.{self.service_name}.com/ads"
        
        if not ads_url:
            return {
                "status": "error",
                "message": "Could not find ads URL. Please navigate manually or provide URL."
            }
        
        return self.navigate_to_url(ads_url, auto_login=auto_login, auto_list_links=auto_list_links)
    
    def find_toggle_by_label(self, label_text: str, partial_match: bool = True) -> Optional[any]:
        """
        Find a toggle/switch control by its label text.
        
        Args:
            label_text: Text to search for in labels
            partial_match: Whether to do partial matching (case-insensitive)
        
        Returns:
            Playwright locator if found, None otherwise
        """
        if not self.page:
            return None
        
        try:
            # Try multiple strategies to find toggles
            # 1. Look for role="switch" with aria-label
            if partial_match:
                switch = self.page.locator(f'[role="switch"][aria-label*="{label_text}" i]').first
            else:
                switch = self.page.locator(f'[role="switch"][aria-label="{label_text}"]').first
            
            if switch.count() > 0:
                return switch
            
            # 2. Look for checkboxes with nearby label text
            labels = self.page.locator("label").filter(has_text=label_text) if partial_match else self.page.get_by_text(label_text, exact=not partial_match)
            if labels.count() > 0:
                # Try to find associated input
                for i in range(labels.count()):
                    label = labels.nth(i)
                    try:
                        # Check if label has for attribute
                        label_for = label.get_attribute("for")
                        if label_for:
                            input_elem = self.page.locator(f"#{label_for}")
                            if input_elem.count() > 0:
                                return input_elem
                        
                        # Try to find input within or next to label
                        input_elem = label.locator("input[type='checkbox'], input[type='radio']").first
                        if input_elem.count() > 0:
                            return input_elem
                        
                        # Try sibling input
                        input_elem = label.locator("xpath=following-sibling::input | preceding-sibling::input").first
                        if input_elem.count() > 0:
                            return input_elem
                    except:
                        continue
            
            # 3. Look for div/span with toggle class and text
            toggle_containers = self.page.locator(".toggle, .switch, [class*='toggle'], [class*='switch']")
            for i in range(min(toggle_containers.count(), 20)):
                container = toggle_containers.nth(i)
                try:
                    text = container.inner_text()
                    if partial_match and label_text.lower() in text.lower():
                        # Find input or switch within
                        input_elem = container.locator("input, [role='switch']").first
                        if input_elem.count() > 0:
                            return input_elem
                    elif not partial_match and text.strip() == label_text:
                        input_elem = container.locator("input, [role='switch']").first
                        if input_elem.count() > 0:
                            return input_elem
                except:
                    continue
            
            return None
        except Exception as e:
            print(f"   ⚠️  Error finding toggle: {e}")
            return None
    
    def change_toggle(self, toggle_label: str, enable: bool = True, wait_time: float = 2.0) -> Dict[str, any]:
        """
        Change any toggle/switch on the current page by finding it by label.
        
        Args:
            toggle_label: Name/label of the toggle to change (e.g., "Enable notifications", "Auto-start")
            enable: True to enable, False to disable
            wait_time: Time to wait after page load (seconds)
        
        Returns:
            Dictionary with operation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            print(f"🔧 Looking for toggle: '{toggle_label}'")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            # Try to expand sections first (some sites use accordions)
            try:
                expand_buttons = self.page.locator("button, [role='button'], summary").filter(has_text=re.compile(r"expand|show|more|manage", re.I))
                for i in range(min(expand_buttons.count(), 10)):
                    try:
                        expand_buttons.nth(i).click(timeout=2000)
                        time.sleep(0.5)
                    except:
                        pass
            except:
                pass
            
            # Find the toggle
            toggle = self.find_toggle_by_label(toggle_label, partial_match=True)
            
            if not toggle or toggle.count() == 0:
                return {
                    "status": "error",
                    "message": f"Could not find toggle: '{toggle_label}'"
                }
            
            # Scroll toggle into view to ensure it's visible and interactable
            try:
                toggle.scroll_into_view_if_needed()
                time.sleep(0.3)  # Small delay after scrolling
            except:
                pass  # Continue even if scrolling fails
            
            # Check current state
            try:
                is_checked = False
                try:
                    is_checked = toggle.is_checked()
                except:
                    # Try aria-checked for role="switch"
                    aria_checked = toggle.get_attribute("aria-checked")
                    if aria_checked == "true":
                        is_checked = True
                
                current_state = "enabled" if is_checked else "disabled"
                target_state = "enabled" if enable else "disabled"
                
                print(f"   📊 Current state: {current_state}")
                print(f"   🎯 Target state: {target_state}")
                
                # Only toggle if needed
                if (enable and not is_checked) or (not enable and is_checked):
                    print(f"   🔄 Toggling switch...")
                    toggle.click(timeout=5000)
                    time.sleep(wait_time)
                    
                    # Verify the change
                    try:
                        new_checked = toggle.is_checked()
                    except:
                        new_aria_checked = toggle.get_attribute("aria-checked")
                        new_checked = new_aria_checked == "true"
                    
                    new_state = "enabled" if new_checked else "disabled"
                    print(f"   ✅ Toggle changed to: {new_state}")
                    
                    return {
                        "status": "success",
                        "message": f"Toggle '{toggle_label}' changed to {target_state}",
                        "previous_state": current_state,
                        "new_state": new_state
                    }
                else:
                    return {
                        "status": "success",
                        "message": f"Toggle '{toggle_label}' is already {target_state}",
                        "current_state": current_state
                    }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Error toggling switch: {str(e)}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to change toggle: {str(e)}"
            }
    
    def change_ad_setting(self, setting_name: str, enable: bool = True, wait_time: float = 2.0) -> Dict[str, any]:
        """
        Change an ad setting by finding and toggling it.
        
        Args:
            setting_name: Name/label of the setting to change (e.g., "Ad personalization", "Data about your activity")
            enable: True to enable, False to disable
            wait_time: Time to wait after page load (seconds)
        
        Returns:
            Dictionary with operation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            print(f"🔧 Looking for ad setting: '{setting_name}'")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            # Try to expand sections first (Facebook often uses accordions)
            try:
                expand_buttons = self.page.locator("button, [role='button'], summary").filter(has_text=re.compile(r"expand|show|more|manage", re.I))
                for i in range(min(expand_buttons.count(), 5)):
                    try:
                        expand_buttons.nth(i).click(timeout=2000)
                        time.sleep(0.5)
                    except:
                        pass
            except:
                pass
            
            # Find the toggle
            toggle = self.find_toggle_by_label(setting_name, partial_match=True)
            
            if not toggle or toggle.count() == 0:
                return {
                    "status": "error",
                    "message": f"Could not find setting: '{setting_name}'"
                }
            
            # Check current state
            try:
                is_checked = False
                try:
                    is_checked = toggle.is_checked()
                except:
                    # Try aria-checked for role="switch"
                    aria_checked = toggle.get_attribute("aria-checked")
                    if aria_checked == "true":
                        is_checked = True
                
                current_state = "enabled" if is_checked else "disabled"
                target_state = "enabled" if enable else "disabled"
                
                print(f"   📊 Current state: {current_state}")
                print(f"   🎯 Target state: {target_state}")
                
                # Only toggle if needed
                if (enable and not is_checked) or (not enable and is_checked):
                    print(f"   🔄 Toggling setting...")
                    toggle.click(timeout=5000)
                    time.sleep(wait_time)
                    
                    # Verify the change
                    try:
                        new_checked = toggle.is_checked()
                    except:
                        new_aria_checked = toggle.get_attribute("aria-checked")
                        new_checked = new_aria_checked == "true"
                    
                    new_state = "enabled" if new_checked else "disabled"
                    print(f"   ✅ Setting changed to: {new_state}")
                    
                    # Check for and click Save button if present
                    save_clicked = click_save_if_present(self.page, timeout=5000)
                    
                    return {
                        "status": "success",
                        "message": f"Setting '{setting_name}' changed to {target_state}",
                        "previous_state": current_state,
                        "new_state": new_state,
                        "save_clicked": save_clicked
                    }
                else:
                    return {
                        "status": "success",
                        "message": f"Setting '{setting_name}' is already {target_state}",
                        "current_state": current_state
                    }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Error toggling setting: {str(e)}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to change ad setting: {str(e)}"
            }
    
    def change_birthday(self, month: int, day: int, year: int, wait_time: float = 2.0) -> Dict[str, any]:
        """
        Change the birthday on the current page.
        
        Args:
            month: Month (1-12)
            day: Day (1-31)
            year: Year (e.g., 1990)
            wait_time: Time to wait after page load (seconds)
        
        Returns:
            Dictionary with operation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            print(f"🎂 Changing birthday to: {month}/{day}/{year}")
            
            # Validate inputs
            if not (1 <= month <= 12):
                return {
                    "status": "error",
                    "message": f"Invalid month: {month}. Must be between 1 and 12."
                }
            if not (1 <= day <= 31):
                return {
                    "status": "error",
                    "message": f"Invalid day: {day}. Must be between 1 and 31."
                }
            if not (1900 <= year <= 2100):
                return {
                    "status": "error",
                    "message": f"Invalid year: {year}. Must be between 1900 and 2100."
                }
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            # Try to expand sections first (Facebook often uses accordions)
            try:
                expand_buttons = self.page.locator("button, [role='button'], summary").filter(has_text=re.compile(r"expand|show|more|manage|edit", re.I))
                for i in range(min(expand_buttons.count(), 10)):
                    try:
                        expand_buttons.nth(i).click(timeout=2000)
                        time.sleep(0.5)
                    except:
                        pass
            except:
                pass
            
            # Find birthday fields - try multiple strategies
            month_filled = False
            day_filled = False
            year_filled = False
            
            # Strategy 1: Look for select elements with month/day/year
            try:
                # Find month select
                month_selectors = [
                    'select[name*="month" i]',
                    'select[id*="month" i]',
                    'select[aria-label*="month" i]',
                    'select:has(option[value*="month" i])',
                ]
                for selector in month_selectors:
                    try:
                        month_select = self.page.locator(selector).first
                        if month_select.count() > 0:
                            month_select.select_option(value=str(month))
                            month_filled = True
                            print(f"   ✅ Filled month: {month}")
                            time.sleep(0.5)
                            break
                    except:
                        continue
                
                # Find day select
                day_selectors = [
                    'select[name*="day" i]',
                    'select[id*="day" i]',
                    'select[aria-label*="day" i]',
                ]
                for selector in day_selectors:
                    try:
                        day_select = self.page.locator(selector).first
                        if day_select.count() > 0:
                            day_select.select_option(value=str(day))
                            day_filled = True
                            print(f"   ✅ Filled day: {day}")
                            time.sleep(0.5)
                            break
                    except:
                        continue
                
                # Find year select
                year_selectors = [
                    'select[name*="year" i]',
                    'select[id*="year" i]',
                    'select[aria-label*="year" i]',
                ]
                for selector in year_selectors:
                    try:
                        year_select = self.page.locator(selector).first
                        if year_select.count() > 0:
                            year_select.select_option(value=str(year))
                            year_filled = True
                            print(f"   ✅ Filled year: {year}")
                            time.sleep(0.5)
                            break
                    except:
                        continue
            except Exception as e:
                print(f"   ⚠️  Select-based search failed: {e}")
            
            # Strategy 2: Look for input fields
            if not month_filled or not day_filled or not year_filled:
                try:
                    # Find all input fields that might be date-related
                    inputs = self.page.locator('input[type="text"], input[type="number"], input:not([type])').all()
                    for input_elem in inputs[:20]:  # Check first 20 inputs
                        try:
                            name = (input_elem.get_attribute("name") or "").lower()
                            input_id = (input_elem.get_attribute("id") or "").lower()
                            placeholder = (input_elem.get_attribute("placeholder") or "").lower()
                            aria_label = (input_elem.get_attribute("aria-label") or "").lower()
                            
                            # Check if it's a month field
                            if not month_filled and ("month" in name or "month" in input_id or "month" in placeholder or "month" in aria_label):
                                input_elem.fill(str(month))
                                month_filled = True
                                print(f"   ✅ Filled month (input): {month}")
                                time.sleep(0.5)
                            
                            # Check if it's a day field
                            if not day_filled and ("day" in name or "day" in input_id or "day" in placeholder or "day" in aria_label):
                                input_elem.fill(str(day))
                                day_filled = True
                                print(f"   ✅ Filled day (input): {day}")
                                time.sleep(0.5)
                            
                            # Check if it's a year field
                            if not year_filled and ("year" in name or "year" in input_id or "year" in placeholder or "year" in aria_label):
                                input_elem.fill(str(year))
                                year_filled = True
                                print(f"   ✅ Filled year (input): {year}")
                                time.sleep(0.5)
                        except:
                            continue
                except Exception as e:
                    print(f"   ⚠️  Input-based search failed: {e}")
            
            # Strategy 3: Look for date picker or combined date field
            if not (month_filled and day_filled and year_filled):
                try:
                    # Look for a single date input field
                    date_inputs = self.page.locator('input[type="date"], input[name*="birth" i], input[id*="birth" i], input[placeholder*="birth" i]').all()
                    for date_input in date_inputs[:5]:
                        try:
                            # Format as YYYY-MM-DD for date input
                            date_value = f"{year:04d}-{month:02d}-{day:02d}"
                            date_input.fill(date_value)
                            month_filled = day_filled = year_filled = True
                            print(f"   ✅ Filled date (combined field): {date_value}")
                            time.sleep(0.5)
                            break
                        except:
                            continue
                except Exception as e:
                    print(f"   ⚠️  Date picker search failed: {e}")
            
            # Check if we found and filled all fields
            if month_filled and day_filled and year_filled:
                time.sleep(wait_time)
                
                # Try to find and click save/submit button
                save_button = None
                save_selectors = [
                    'button:has-text("Save")',
                    'button:has-text("Update")',
                    'button:has-text("Confirm")',
                    'button[type="submit"]',
                    'button[id*="save" i]',
                    '[role="button"]:has-text("Save")',
                ]
                
                for selector in save_selectors:
                    try:
                        save_button = self.page.locator(selector).first
                        if save_button.count() > 0:
                            save_button.click(timeout=5000)
                            print(f"   ✅ Clicked save button")
                            time.sleep(2)
                            break
                    except:
                        continue
                
                return {
                    "status": "success",
                    "message": f"Birthday changed to {month}/{day}/{year}",
                    "month": month,
                    "day": day,
                    "year": year,
                    "saved": save_button is not None and save_button.count() > 0
                }
            else:
                missing = []
                if not month_filled:
                    missing.append("month")
                if not day_filled:
                    missing.append("day")
                if not year_filled:
                    missing.append("year")
                
                return {
                    "status": "error",
                    "message": f"Could not find birthday fields. Missing: {', '.join(missing)}",
                    "month_filled": month_filled,
                    "day_filled": day_filled,
                    "year_filled": year_filled
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to change birthday: {str(e)}"
            }
    
    def list_toggles(self) -> List[Dict[str, any]]:
        """
        List all available toggles/switches on the current page.
        
        Returns:
            List of dictionaries with toggle information
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            toggles_list = []
            
            # Find all toggles/switches - simple selector-based approach
            toggle_selectors = [
                '[role="switch"]',
                'input[type="checkbox"]',
                'input[type="radio"]',
                '[class*="toggle" i]',
                '[class*="switch" i]',
            ]
            
            all_toggles = []
            for selector in toggle_selectors:
                try:
                    toggles = self.page.locator(selector).all()
                    all_toggles.extend(toggles[:50])  # Limit per selector
                except:
                    continue
            
            # Remove duplicates
            seen_elements = set()
            unique_toggles = []
            for toggle in all_toggles:
                try:
                    toggle_id = toggle.get_attribute("id") or ""
                    toggle_name = toggle.get_attribute("name") or ""
                    key = f"{toggle_id}:{toggle_name}"
                    if key and key not in seen_elements:
                        seen_elements.add(key)
                        unique_toggles.append(toggle)
                    elif not key:
                        try:
                            box = toggle.bounding_box()
                            pos_key = f"{box['x']}:{box['y']}"
                            if pos_key not in seen_elements:
                                seen_elements.add(pos_key)
                                unique_toggles.append(toggle)
                        except:
                            unique_toggles.append(toggle)
                except:
                    continue
            
            for toggle in unique_toggles[:100]:  # Limit to first 100
                try:
                    # Scroll toggle into view
                    toggle.scroll_into_view_if_needed()
                    time.sleep(0.1)
                    
                    # Get label
                    label = None
                    try:
                        label = toggle.get_attribute("aria-label")
                    except:
                        pass
                    
                    if not label:
                        try:
                            toggle_id = toggle.get_attribute("id")
                            if toggle_id:
                                label_elem = self.page.locator(f"label[for='{toggle_id}']")
                                if label_elem.count() > 0:
                                    label = label_elem.inner_text()
                        except:
                            pass
                    
                    if not label:
                        try:
                            parent = toggle.locator("xpath=..")
                            label = parent.inner_text()[:100]
                        except:
                            pass
                    
                    # Get state
                    state = "unknown"
                    try:
                        if toggle.get_attribute("type") == "checkbox":
                            state = "checked" if toggle.is_checked() else "unchecked"
                        else:
                            aria_checked = toggle.get_attribute("aria-checked")
                            state = "on" if aria_checked == "true" else "off"
                    except:
                        pass
                    
                    if label:
                        label = ' '.join(label.split())[:150]
                        toggles_list.append({
                            "label": label.strip(),
                            "state": state,
                            "selector": str(toggle)
                        })
                except:
                    continue
            
            return toggles_list
        except Exception as e:
            print(f"⚠️  Error listing toggles: {e}")
            return []
    
    def check_checkbox(self, checkbox_label: str, check: bool = True, wait_time: float = 2.0) -> Dict[str, any]:
        """
        Check or uncheck a checkbox by parsing the HTML DOM to find it by label text.
        
        Args:
            checkbox_label: Label text of the checkbox to check/uncheck
            check: True to check, False to uncheck
            wait_time: Time to wait after checking/unchecking (seconds)
        
        Returns:
            Dictionary with operation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            action = "check" if check else "uncheck"
            print(f"☑️  Parsing DOM to find checkbox: '{checkbox_label}' ({action})")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            # Parse HTML DOM using JavaScript to find the checkbox
            # Use json.dumps to properly escape the label for JavaScript
            search_text_js = json.dumps(checkbox_label)
            checkbox_info = self.page.evaluate(f"""
                (() => {{
                    // Helper function to get XPath
                    function getXPath(element) {{
                        if (element.id !== '') {{
                            return `//*[@id="${{element.id}}"]`;
                        }}
                        if (element === document.body) {{
                            return '/html/body';
                        }}
                        let ix = 0;
                        const siblings = element.parentNode.childNodes;
                        for (let i = 0; i < siblings.length; i++) {{
                            const sibling = siblings[i];
                            if (sibling === element) {{
                                return getXPath(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                            }}
                            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {{
                                ix++;
                            }}
                        }}
                    }}
                    
                    const searchText = {search_text_js}.toLowerCase();
                    const allInputs = document.querySelectorAll('input[type="checkbox"]');
                    
                    for (const checkbox of allInputs) {{
                        // Try multiple ways to find the label
                        let labelText = '';
                        
                        // 1. Check aria-label
                        if (checkbox.getAttribute('aria-label')) {{
                            labelText = checkbox.getAttribute('aria-label').toLowerCase();
                            if (labelText.includes(searchText)) {{
                                return {{
                                    found: true,
                                    id: checkbox.id || '',
                                    name: checkbox.name || '',
                                    selector: checkbox.id ? `#${{checkbox.id}}` : `input[type="checkbox"][name="${{checkbox.name}}"]`,
                                    checked: checkbox.checked,
                                    xpath: getXPath(checkbox)
                                }};
                            }}
                        }}
                        
                        // 2. Check associated label element
                        if (checkbox.id) {{
                            const label = document.querySelector(`label[for="${{checkbox.id}}"]`);
                            if (label) {{
                                labelText = (label.innerText || label.textContent || '').toLowerCase();
                                if (labelText.includes(searchText)) {{
                                    return {{
                                        found: true,
                                        id: checkbox.id,
                                        name: checkbox.name || '',
                                        selector: `#${{checkbox.id}}`,
                                        checked: checkbox.checked,
                                        xpath: getXPath(checkbox)
                                    }};
                                }}
                            }}
                        }}
                        
                        // 3. Check parent element text
                        let parent = checkbox.parentElement;
                        for (let i = 0; i < 3 && parent; i++) {{
                            const text = (parent.innerText || parent.textContent || '').toLowerCase();
                            if (text.includes(searchText)) {{
                                return {{
                                    found: true,
                                    id: checkbox.id || '',
                                    name: checkbox.name || '',
                                    selector: checkbox.id ? `#${{checkbox.id}}` : `input[type="checkbox"][name="${{checkbox.name}}"]`,
                                    checked: checkbox.checked,
                                    xpath: getXPath(checkbox)
                                }};
                            }}
                            parent = parent.parentElement;
                        }}
                        
                        // 4. Check previous siblings
                        let sibling = checkbox.previousElementSibling;
                        for (let i = 0; i < 3 && sibling; i++) {{
                            const text = (sibling.innerText || sibling.textContent || '').toLowerCase();
                            if (text.includes(searchText)) {{
                                return {{
                                    found: true,
                                    id: checkbox.id || '',
                                    name: checkbox.name || '',
                                    selector: checkbox.id ? `#${{checkbox.id}}` : `input[type="checkbox"][name="${{checkbox.name}}"]`,
                                    checked: checkbox.checked,
                                    xpath: getXPath(checkbox)
                                }};
                            }}
                            sibling = sibling.previousElementSibling;
                        }}
                        
                        // 5. Check next siblings
                        sibling = checkbox.nextElementSibling;
                        for (let i = 0; i < 3 && sibling; i++) {{
                            const text = (sibling.innerText || sibling.textContent || '').toLowerCase();
                            if (text.includes(searchText)) {{
                                return {{
                                    found: true,
                                    id: checkbox.id || '',
                                    name: checkbox.name || '',
                                    selector: checkbox.id ? `#${{checkbox.id}}` : `input[type="checkbox"][name="${{checkbox.name}}"]`,
                                    checked: checkbox.checked,
                                    xpath: getXPath(checkbox)
                                }};
                            }}
                            sibling = sibling.nextElementSibling;
                        }}
                    }}
                    
                    return {{ found: false }};
                }})()
            """)
            
            if not checkbox_info or not checkbox_info.get("found"):
                return {
                    "status": "error",
                    "message": f"Could not find checkbox with label containing: '{checkbox_label}'"
                }
            
            # Use the selector or XPath to find the checkbox
            checkbox = None
            selector = checkbox_info.get("selector")
            xpath = checkbox_info.get("xpath")
            
            if selector:
                try:
                    checkbox = self.page.locator(selector).first
                    if checkbox.count() == 0:
                        checkbox = None
                except:
                    checkbox = None
            
            if not checkbox and xpath:
                try:
                    checkbox = self.page.locator(f"xpath={xpath}").first
                    if checkbox.count() == 0:
                        checkbox = None
                except:
                    checkbox = None
            
            if not checkbox:
                # Fallback: try to find by name or id
                checkbox_id = checkbox_info.get("id")
                checkbox_name = checkbox_info.get("name")
                
                if checkbox_id:
                    checkbox = self.page.locator(f"#{checkbox_id}").first
                elif checkbox_name:
                    checkbox = self.page.locator(f'input[type="checkbox"][name="{checkbox_name}"]').first
            
            if not checkbox or checkbox.count() == 0:
                return {
                    "status": "error",
                    "message": f"Found checkbox in DOM but could not create locator for: '{checkbox_label}'"
                }
            
            # Scroll checkbox into view
            try:
                checkbox.scroll_into_view_if_needed()
                time.sleep(0.3)
            except:
                pass
            
            # Check current state
            was_checked = checkbox_info.get("checked", False)
            try:
                is_checked = checkbox.is_checked()
                was_checked = is_checked
            except:
                try:
                    aria_checked = checkbox.get_attribute("aria-checked")
                    was_checked = aria_checked == "true"
                except:
                    pass
            
            # Check if it's already in the desired state
            if check and was_checked:
                return {
                    "status": "success",
                    "message": f"Checkbox '{checkbox_label}' is already checked",
                    "was_checked": True,
                    "now_checked": True
                }
            elif not check and not was_checked:
                return {
                    "status": "success",
                    "message": f"Checkbox '{checkbox_label}' is already unchecked",
                    "was_checked": False,
                    "now_checked": False
                }
            
            # Check or uncheck the checkbox
            if check:
                print(f"   ☑️  Checking checkbox...")
                checkbox.check(timeout=5000)
            else:
                print(f"   ☐  Unchecking checkbox...")
                checkbox.uncheck(timeout=5000)
            
            time.sleep(wait_time)
            
            # Verify the state
            try:
                is_checked = checkbox.is_checked()
            except:
                aria_checked = checkbox.get_attribute("aria-checked")
                is_checked = aria_checked == "true"
            
            # Verify the desired state was achieved
            if check and is_checked:
                print(f"   ✅ Checkbox checked successfully")
                return {
                    "status": "success",
                    "message": f"Checkbox '{checkbox_label}' checked successfully",
                    "was_checked": was_checked,
                    "now_checked": True
                }
            elif not check and not is_checked:
                print(f"   ✅ Checkbox unchecked successfully")
                return {
                    "status": "success",
                    "message": f"Checkbox '{checkbox_label}' unchecked successfully",
                    "was_checked": was_checked,
                    "now_checked": False
                }
            else:
                return {
                    "status": "error",
                    "message": f"Checkbox '{checkbox_label}' was {'checked' if check else 'unchecked'} but may not be in the expected state"
                }
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"Failed to check checkbox: {str(e)}"
            }
    
    def physical_toggle(self, label: str, enable: bool) -> Dict[str, any]:
        """
        Physically click a checkbox/toggle using Playwright's mouse API.
        
        Args:
            label: Label text to find the element
            enable: True to check/enable, False to uncheck/disable
        
        Returns:
            Dictionary with previous_state, new_state, and element_found
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            action = "enable" if enable else "disable"
            print(f"🖱️  Physically clicking to {action}: '{label}'")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            # Find the element by label using the existing method
            element = self.find_toggle_by_label(label, partial_match=True)
            
            if not element or element.count() == 0:
                return {
                    "element_found": False,
                    "previous_state": None,
                    "new_state": None,
                    "status": "error",
                    "message": f"Could not find element with label: '{label}'"
                }
            
            # Scroll element into view
            try:
                element.scroll_into_view_if_needed()
                time.sleep(0.3)
            except Exception as e:
                print(f"   ⚠️  Error scrolling into view: {e}")
            
            # Wait for element to be visible
            try:
                element.wait_for(state="visible", timeout=5000)
            except Exception as e:
                print(f"   ⚠️  Element may not be visible: {e}")
            
            # Get current state before clicking
            previous_state = None
            try:
                if element.get_attribute("type") == "checkbox":
                    previous_state = "checked" if element.is_checked() else "unchecked"
                else:
                    aria_checked = element.get_attribute("aria-checked")
                    previous_state = "on" if aria_checked == "true" else "off"
            except Exception as e:
                print(f"   ⚠️  Could not determine previous state: {e}")
                previous_state = "unknown"
            
            # Get bounding box
            try:
                box = element.bounding_box()
                if not box:
                    return {
                        "element_found": True,
                        "previous_state": previous_state,
                        "new_state": None,
                        "status": "error",
                        "message": f"Could not get bounding box for element: '{label}'"
                    }
                
                # Calculate center coordinates
                center_x = box["x"] + box["width"] / 2
                center_y = box["y"] + box["height"] / 2
                
                print(f"   📍 Element center: ({center_x:.0f}, {center_y:.0f})")
                
                # Move mouse to center of element
                self.page.mouse.move(center_x, center_y)
                time.sleep(0.2)  # Small delay after moving
                
                # Click using mouse API
                print(f"   🖱️  Clicking at ({center_x:.0f}, {center_y:.0f})...")
                self.page.mouse.click(center_x, center_y)
                time.sleep(0.5)  # Wait for state change
                
            except Exception as e:
                return {
                    "element_found": True,
                    "previous_state": previous_state,
                    "new_state": None,
                    "status": "error",
                    "message": f"Error during mouse click: {str(e)}"
                }
            
            # Verify the new state
            new_state = None
            try:
                if element.get_attribute("type") == "checkbox":
                    new_state = "checked" if element.is_checked() else "unchecked"
                else:
                    aria_checked = element.get_attribute("aria-checked")
                    new_state = "on" if aria_checked == "true" else "off"
            except Exception as e:
                print(f"   ⚠️  Could not determine new state: {e}")
                new_state = "unknown"
            
            # Check if state changed as expected
            expected_state = "checked" if enable else "unchecked"
            if element.get_attribute("type") != "checkbox":
                expected_state = "on" if enable else "off"
            
            success = (new_state == expected_state) or (previous_state != new_state)
            
            if success:
                print(f"   ✅ State changed: {previous_state} → {new_state}")
                return {
                    "element_found": True,
                    "previous_state": previous_state,
                    "new_state": new_state,
                    "status": "success",
                    "message": f"Element '{label}' toggled from {previous_state} to {new_state}"
                }
            else:
                print(f"   ⚠️  State may not have changed as expected: {previous_state} → {new_state}")
                return {
                    "element_found": True,
                    "previous_state": previous_state,
                    "new_state": new_state,
                    "status": "warning",
                    "message": f"Element '{label}' clicked but state is {new_state} (expected {expected_state})"
                }
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "element_found": False,
                "previous_state": None,
                "new_state": None,
                "status": "error",
                "message": f"Failed to physically toggle: {str(e)}"
            }
    
    def _call_gemini_for_element_location(self, current_screenshot_path: str, reference_screenshot_path: str, text_elements_json: str) -> Dict[str, Any]:
        """
        Helper function to call Gemini API to locate an element.
        
        Args:
            current_screenshot_path: Path to current page screenshot
            reference_screenshot_path: Path to reference screenshot
            text_elements_json: JSON string of text elements from DOM
            
        Returns:
            Dictionary with Gemini's response or error
        """
        if not GEMINI_AVAILABLE:
            return {
                "status": "error",
                "reason": "Gemini API not available. Install google-genai package.",
                "raw_response": None
            }
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {
                "status": "error",
                "reason": "GEMINI_API_KEY environment variable not set",
                "raw_response": None
            }
        
        try:
            client = genai.Client(api_key=api_key)
            model_id = 'gemini-2.5-pro'
            
            prompt = """
You are helping a browser automation agent.

You are given:
1) A reference screenshot showing the desired setting in Zoom:
   'Allow users to send text feedback'.

2) A screenshot of the current page.

3) A JSON list of text elements extracted from the current HTML, each with:
   - text
   - tag
   - role
   - bounding box (x, y, width, height)

Task:
- Look at the reference screenshot to understand approximately where and how the
  'Allow users to send text feedback' control appears.
- Using the CURRENT screenshot and the JSON list of text elements,
  identify which element corresponds to the label or control for
  'Allow users to send text feedback' (allow for partial matches and similar phrasing).

Output ONLY JSON in this exact format:

{
  "label_text": "<the exact text of the best matching element>",
  "reason": "<short explanation>",
  "mode": "selector" | "coordinates",
  "selector": "<CSS selector or empty string>",
  "x": <number or null>,
  "y": <number or null>
}

- Prefer a CSS selector if possible (mode="selector").
- If you cannot reliably provide a selector, use mode="coordinates"
  with x,y as the center of the target element's bounding box.
"""
            
            # Read image files
            with open(reference_screenshot_path, 'rb') as f:
                reference_image = f.read()
            
            with open(current_screenshot_path, 'rb') as f:
                current_image = f.read()
            
            # Create content with images and text
            contents = Content(
                role="user",
                parts=[
                    Part(text=prompt),
                    Part(text=f"\n\nText elements from DOM:\n{text_elements_json}"),
                    Part.from_bytes(data=reference_image, mime_type='image/png'),
                    Part.from_bytes(data=current_image, mime_type='image/png')
                ]
            )
            
            # Call Gemini
            response = client.models.generate_content(
                model=model_id,
                contents=[contents]
            )
            
            # Extract text response
            response_text = response.candidates[0].content.parts[0].text.strip()
            
            # Try to parse JSON from response (might be wrapped in markdown code blocks)
            json_text = response_text
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(json_text)
            return {
                "status": "success",
                "result": result,
                "raw_response": response_text
            }
            
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "reason": f"Failed to parse JSON from Gemini response: {str(e)}",
                "raw_response": response_text if 'response_text' in locals() else None
            }
        except Exception as e:
            return {
                "status": "error",
                "reason": f"Gemini API call failed: {str(e)}",
                "raw_response": None
            }
    
    def _call_gemini_for_save_button(self, current_screenshot_path: str, text_elements_json: str) -> Dict[str, Any]:
        """
        Helper function to call Gemini API to locate the Save button.
        
        Args:
            current_screenshot_path: Path to current page screenshot
            text_elements_json: JSON string of text elements from DOM
            
        Returns:
            Dictionary with Gemini's response or error
        """
        if not GEMINI_AVAILABLE:
            return {
                "status": "error",
                "reason": "Gemini API not available. Install google-genai package.",
                "raw_response": None
            }
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {
                "status": "error",
                "reason": "GEMINI_API_KEY environment variable not set",
                "raw_response": None
            }
        
        try:
            client = genai.Client(api_key=api_key)
            model_id = 'gemini-2.5-pro'
            
            prompt = """
You are helping a browser automation agent.

You are given:
1) A screenshot of the current page (after a setting was changed).
2) A JSON list of text elements extracted from the current HTML, each with:
   - text
   - tag
   - role
   - bounding box (x, y, width, height)

Task:
- Look at the screenshot and identify the "Save" button (or similar: "Save Changes", "Apply", "Confirm", etc.)
- Using the screenshot and the JSON list of text elements,
  identify which element corresponds to the Save/Apply/Confirm button.

Output ONLY JSON in this exact format:

{
  "button_text": "<the exact text of the button>",
  "reason": "<short explanation>",
  "mode": "selector" | "coordinates",
  "selector": "<CSS selector or empty string>",
  "x": <number or null>,
  "y": <number or null>
}

- Prefer a CSS selector if possible (mode="selector").
- If you cannot reliably provide a selector, use mode="coordinates"
  with x,y as the center of the target button's bounding box.
"""
            
            # Read image file
            with open(current_screenshot_path, 'rb') as f:
                current_image = f.read()
            
            # Create content with image and text
            contents = Content(
                role="user",
                parts=[
                    Part(text=prompt),
                    Part(text=f"\n\nText elements from DOM:\n{text_elements_json}"),
                    Part.from_bytes(data=current_image, mime_type='image/png')
                ]
            )
            
            # Call Gemini
            response = client.models.generate_content(
                model=model_id,
                contents=[contents]
            )
            
            # Extract text response
            response_text = response.candidates[0].content.parts[0].text.strip()
            
            # Try to parse JSON from response (might be wrapped in markdown code blocks)
            json_text = response_text
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(json_text)
            return {
                "status": "success",
                "result": result,
                "raw_response": response_text
            }
            
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "reason": f"Failed to parse JSON from Gemini response: {str(e)}",
                "raw_response": response_text if 'response_text' in locals() else None
            }
        except Exception as e:
            return {
                "status": "error",
                "reason": f"Gemini API call failed: {str(e)}",
                "raw_response": None
            }
    
    def toggle_zoom_text_feedback_setting(self, enable: bool) -> Dict[str, Any]:
        """
        Use Gemini + HTML text to locate and toggle the
        'Allow users to send text feedback' setting on a Zoom settings page.
        
        Args:
            enable: True to enable/check, False to disable/uncheck
            
        Returns:
            Dictionary with status, previous_state, new_state, etc.
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        if not GEMINI_AVAILABLE:
            return {
                "status": "error",
                "target": "Allow users to send text feedback",
                "previous_state": "unknown",
                "new_state": "unknown",
                "selection_mode": "none",
                "gemini_reason": "Gemini API not available"
            }
        
        try:
            print(f"🤖 Using Gemini to locate 'Allow users to send text feedback' setting...")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            # a) Collect structured text info from the current page
            print("   📝 Collecting text elements from DOM...")
            text_elements = self.page.evaluate("""
                () => {
                    const elements = [];
                    const allElements = document.querySelectorAll('*');
                    
                    for (const el of allElements) {
                        try {
                            const text = (el.innerText || el.textContent || '').trim();
                            
                            // Filter to reasonable text length
                            if (text.length < 2 || text.length > 200) continue;
                            
                            // Skip if element is not visible
                            const rect = el.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) continue;
                            
                            // Get role
                            const role = el.getAttribute('role') || '';
                            
                            elements.push({
                                text: text,
                                tag: el.tagName.toLowerCase(),
                                role: role,
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height
                            });
                        } catch (e) {
                            // Skip elements that cause errors
                            continue;
                        }
                    }
                    
                    return elements;
                }
            """)
            
            print(f"   ✅ Collected {len(text_elements)} text elements")
            
            # b) Capture current screenshot
            print("   📸 Capturing current page screenshot...")
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                current_screenshot_path = tmp_file.name
                self.page.screenshot(path=current_screenshot_path, full_page=True)
            
            # c) Load reference screenshot
            # Get the script directory and construct path
            script_dir = Path(__file__).parent
            reference_screenshot_path = script_dir.parent / "screenshot-classifier" / "screenshots" / "zoom" / "allow_text_feedback.png"
            
            # If the specific file doesn't exist, try to find a similar one
            if not reference_screenshot_path.exists():
                # Try to find any zoom screenshot as fallback
                zoom_screenshots_dir = script_dir.parent / "screenshot-classifier" / "screenshots" / "zoom"
                if zoom_screenshots_dir.exists():
                    # Look for a settings-related screenshot
                    for screenshot_file in zoom_screenshots_dir.glob("*.png"):
                        if "setting" in screenshot_file.name.lower() or "initial" in screenshot_file.name.lower():
                            reference_screenshot_path = screenshot_file
                            print(f"   ⚠️  Using fallback reference: {reference_screenshot_path.name}")
                            break
                
                if not reference_screenshot_path.exists():
                    return {
                        "status": "error",
                        "target": "Allow users to send text feedback",
                        "previous_state": "unknown",
                        "new_state": "unknown",
                        "selection_mode": "none",
                        "gemini_reason": f"Reference screenshot not found at {reference_screenshot_path}"
                    }
            
            print(f"   📷 Using reference screenshot: {reference_screenshot_path.name}")
            
            # d) Call Gemini
            print("   🤖 Calling Gemini API...")
            text_elements_json = json.dumps(text_elements, indent=2)
            gemini_result = self._call_gemini_for_element_location(
                current_screenshot_path,
                str(reference_screenshot_path),
                text_elements_json
            )
            
            # Clean up temp screenshot
            try:
                os.unlink(current_screenshot_path)
            except:
                pass
            
            if gemini_result["status"] != "success":
                return {
                    "status": "error",
                    "target": "Allow users to send text feedback",
                    "previous_state": "unknown",
                    "new_state": "unknown",
                    "selection_mode": "none",
                    "gemini_reason": gemini_result.get("reason", "Unknown error")
                }
            
            gemini_response = gemini_result["result"]
            selection_mode = gemini_response.get("mode", "none")
            gemini_reason = gemini_response.get("reason", "")
            
            print(f"   ✅ Gemini found element: {gemini_response.get('label_text', 'N/A')}")
            print(f"   📍 Mode: {selection_mode}")
            
            # e) Parse Gemini's response and toggle
            previous_state = "unknown"
            new_state = "unknown"
            
            if selection_mode == "selector":
                selector = gemini_response.get("selector", "")
                if selector:
                    try:
                        element = self.page.locator(selector).first
                        if element.count() > 0:
                            element.scroll_into_view_if_needed()
                            time.sleep(0.3)
                            
                            # Get current state
                            try:
                                if element.get_attribute("type") == "checkbox":
                                    is_checked = element.is_checked()
                                    previous_state = "enabled" if is_checked else "disabled"
                                else:
                                    aria_checked = element.get_attribute("aria-checked")
                                    previous_state = "enabled" if aria_checked == "true" else "disabled"
                            except:
                                pass
                            
                            # Toggle if needed
                            current_is_enabled = previous_state == "enabled"
                            if current_is_enabled != enable:
                                if element.get_attribute("type") == "checkbox":
                                    if enable:
                                        element.check()
                                    else:
                                        element.uncheck()
                                else:
                                    element.click()
                                time.sleep(0.5)
                            
                            # Get new state
                            try:
                                if element.get_attribute("type") == "checkbox":
                                    is_checked = element.is_checked()
                                    new_state = "enabled" if is_checked else "disabled"
                                else:
                                    aria_checked = element.get_attribute("aria-checked")
                                    new_state = "enabled" if aria_checked == "true" else "disabled"
                            except:
                                pass
                    except Exception as e:
                        return {
                            "status": "error",
                            "target": "Allow users to send text feedback",
                            "previous_state": previous_state,
                            "new_state": new_state,
                            "selection_mode": "selector",
                            "gemini_reason": f"Error using selector: {str(e)}"
                        }
                else:
                    return {
                        "status": "error",
                        "target": "Allow users to send text feedback",
                        "previous_state": "unknown",
                        "new_state": "unknown",
                        "selection_mode": "selector",
                        "gemini_reason": "No selector provided by Gemini"
                    }
            
            elif selection_mode == "coordinates":
                x = gemini_response.get("x")
                y = gemini_response.get("y")
                
                if x is not None and y is not None:
                    try:
                        # Get state before clicking by finding nearby element
                        # Try to find checkbox/toggle near coordinates
                        nearby_element = self.page.evaluate(f"""
                            () => {{
                                const x = {x};
                                const y = {y};
                                const allInputs = document.querySelectorAll('input[type="checkbox"], [role="switch"]');
                                let closest = null;
                                let minDist = Infinity;
                                
                                for (const el of allInputs) {{
                                    const rect = el.getBoundingClientRect();
                                    const centerX = rect.x + rect.width / 2;
                                    const centerY = rect.y + rect.height / 2;
                                    const dist = Math.sqrt(Math.pow(centerX - x, 2) + Math.pow(centerY - y, 2));
                                    
                                    if (dist < minDist && dist < 100) {{
                                        minDist = dist;
                                        closest = el;
                                    }}
                                }}
                                
                                if (closest) {{
                                    const rect = closest.getBoundingClientRect();
                                    if (closest.type === 'checkbox') {{
                                        return {{checked: closest.checked, type: 'checkbox'}};
                                    }} else {{
                                        return {{checked: closest.getAttribute('aria-checked') === 'true', type: 'switch'}};
                                    }}
                                }}
                                return null;
                            }}
                        """)
                        
                        if nearby_element:
                            previous_state = "enabled" if nearby_element.get("checked") else "disabled"
                        
                        # Move mouse and click
                        self.page.mouse.move(x, y)
                        time.sleep(0.2)
                        self.page.mouse.click(x, y)
                        time.sleep(0.5)
                        
                        # Get new state
                        nearby_element_after = self.page.evaluate(f"""
                            () => {{
                                const x = {x};
                                const y = {y};
                                const allInputs = document.querySelectorAll('input[type="checkbox"], [role="switch"]');
                                let closest = null;
                                let minDist = Infinity;
                                
                                for (const el of allInputs) {{
                                    const rect = el.getBoundingClientRect();
                                    const centerX = rect.x + rect.width / 2;
                                    const centerY = rect.y + rect.height / 2;
                                    const dist = Math.sqrt(Math.pow(centerX - x, 2) + Math.pow(centerY - y, 2));
                                    
                                    if (dist < minDist && dist < 100) {{
                                        minDist = dist;
                                        closest = el;
                                    }}
                                }}
                                
                                if (closest) {{
                                    if (closest.type === 'checkbox') {{
                                        return {{checked: closest.checked, type: 'checkbox'}};
                                    }} else {{
                                        return {{checked: closest.getAttribute('aria-checked') === 'true', type: 'switch'}};
                                    }}
                                }}
                                return null;
                            }}
                        """)
                        
                        if nearby_element_after:
                            new_state = "enabled" if nearby_element_after.get("checked") else "disabled"
                        
                    except Exception as e:
                        return {
                            "status": "error",
                            "target": "Allow users to send text feedback",
                            "previous_state": previous_state,
                            "new_state": new_state,
                            "selection_mode": "coordinates",
                            "gemini_reason": f"Error clicking coordinates: {str(e)}"
                        }
                else:
                    return {
                        "status": "error",
                        "target": "Allow users to send text feedback",
                        "previous_state": "unknown",
                        "new_state": "unknown",
                        "selection_mode": "coordinates",
                        "gemini_reason": "No coordinates provided by Gemini"
                    }
            else:
                return {
                    "status": "error",
                    "target": "Allow users to send text feedback",
                    "previous_state": "unknown",
                    "new_state": "unknown",
                    "selection_mode": "none",
                    "gemini_reason": f"Invalid mode from Gemini: {selection_mode}"
                }
            
            # After successful toggle, find and click Save button
            save_clicked = False
            
            # Only skip Save if we're confident the state didn't change
            # (both states are enabled/disabled and they're equal)
            should_skip_save = (
                previous_state in {"enabled", "disabled"} and
                new_state in {"enabled", "disabled"} and
                previous_state == new_state
            )
            
            if should_skip_save:
                print(f"   💾 Save button: ℹ️  skipped (state truly unchanged: {previous_state} → {new_state})")
            else:
                # Try to click Save - either states are unknown or they changed
                print("   💾 Looking for Save button...")
                time.sleep(1)  # Wait for page to update after toggle
                
                save_clicked = click_save_if_present(self.page, timeout=5000)
                
                if save_clicked:
                    print("   💾 Save button: ✅ clicked")
                else:
                    print("   💾 Save button: ⚠️  not found")
            
            # f) Return result
            result = {
                "status": "success",
                "target": "Allow users to send text feedback",
                "previous_state": previous_state,
                "new_state": new_state,
                "selection_mode": selection_mode,
                "gemini_reason": gemini_reason,
                "save_clicked": save_clicked
            }
            
            return result
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "target": "Allow users to send text feedback",
                "previous_state": "unknown",
                "new_state": "unknown",
                "selection_mode": "none",
                "gemini_reason": f"Exception: {str(e)}"
            }
    
    def list_ad_settings(self) -> List[Dict[str, any]]:
        """
        List all available ad settings/toggles on the current page.
        
        Returns:
            List of dictionaries with setting information
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            settings = []
            
            # Find all toggles/switches
            toggles = self.page.locator('[role="switch"], input[type="checkbox"]').all()
            
            for toggle in toggles[:50]:  # Limit to first 50
                try:
                    # Get label
                    label = None
                    try:
                        label = toggle.get_attribute("aria-label")
                    except:
                        pass
                    
                    if not label:
                        # Try to find associated label
                        try:
                            toggle_id = toggle.get_attribute("id")
                            if toggle_id:
                                label_elem = self.page.locator(f"label[for='{toggle_id}']")
                                if label_elem.count() > 0:
                                    label = label_elem.inner_text()
                        except:
                            pass
                    
                    if not label:
                        # Try parent or sibling text
                        try:
                            parent = toggle.locator("xpath=..")
                            label = parent.inner_text()[:100]  # Limit length
                        except:
                            pass
                    
                    # Get state
                    state = "unknown"
                    try:
                        if toggle.get_attribute("type") == "checkbox":
                            state = "checked" if toggle.is_checked() else "unchecked"
                        else:
                            aria_checked = toggle.get_attribute("aria-checked")
                            state = "on" if aria_checked == "true" else "off"
                    except:
                        pass
                    
                    if label:
                        settings.append({
                            "label": label.strip(),
                            "state": state,
                            "selector": str(toggle)
                        })
                except:
                    continue
            
            return settings
        except Exception as e:
            print(f"⚠️  Error listing ad settings: {e}")
            return []
    
    def list_navigation_links(self) -> List[Dict[str, any]]:
        """
        List all available navigation links/buttons on the current page.
        
        Returns:
            List of dictionaries with link/button information (text, href, type, clickable)
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)
            
            links = []
            
            # Find all clickable elements: links, buttons, and elements with click handlers
            selectors = [
                "a[href]",  # Links with href
                "button",   # Button elements
                "[role='button']",  # Elements with button role
                "[role='link']",   # Elements with link role
                "[onclick]",       # Elements with onclick handlers
                "[data-href]",     # Elements with data-href (common in SPAs)
                "div[tabindex='0']",  # Divs that are focusable (often clickable)
                "span[tabindex='0']", # Spans that are focusable
            ]
            
            all_elements = []
            for selector in selectors:
                try:
                    elements = self.page.locator(selector).all()
                    all_elements.extend(elements[:50])  # Limit per selector
                except:
                    continue
            
            # Also find elements that look clickable (have cursor pointer style) using JavaScript
            try:
                clickable_elements_data = self.page.evaluate("""
                    () => {
                        const results = [];
                        const all = Array.from(document.querySelectorAll('*'));
                        for (const el of all) {
                            try {
                                const style = window.getComputedStyle(el);
                                const tag = el.tagName.toLowerCase();
                                const hasPointer = style.cursor === 'pointer';
                                const isClickableTag = ['div', 'span', 'p', 'li', 'td', 'section', 'article'].includes(tag);
                                const hasClickHandler = el.onclick !== null || el.getAttribute('onclick') !== null;
                                const hasDataHref = el.getAttribute('data-href') !== null;
                                const hasTabIndex = el.getAttribute('tabindex') === '0';
                                const text = (el.innerText || el.textContent || '').trim();
                                
                                if ((hasPointer || hasClickHandler || hasDataHref || hasTabIndex) && 
                                    isClickableTag && 
                                    text.length > 0 && 
                                    text.length < 200 &&
                                    el.offsetParent !== null) { // Element is visible
                                    results.push({
                                        tag: tag,
                                        text: text,
                                        hasPointer: hasPointer,
                                        hasClickHandler: hasClickHandler,
                                        hasDataHref: hasDataHref,
                                        hasTabIndex: hasTabIndex,
                                        className: el.className || '',
                                        id: el.id || ''
                                    });
                                }
                            } catch (e) {}
                            if (results.length >= 100) break;
                        }
                        return results;
                    }
                """)
                
                # Now find the actual elements using the data we collected
                for elem_data in clickable_elements_data:
                    try:
                        # Try to find element by various means
                        selectors_to_try = []
                        if elem_data.get('id'):
                            selectors_to_try.append(f"#{elem_data['id']}")
                        if elem_data.get('className'):
                            classes = elem_data['className'].split()
                            if classes:
                                selectors_to_try.append(f".{classes[0]}")
                        
                        # Also try finding by text
                        text = elem_data.get('text', '')
                        if text and len(text) >= 2:
                            # Try to find element containing this text
                            try:
                                text_elem = self.page.locator(f"text={text}").first
                                if text_elem.count() > 0:
                                    # Check if it matches our criteria
                                    tag = text_elem.evaluate("el => el.tagName.toLowerCase()")
                                    if tag in ['div', 'span', 'p', 'li', 'td', 'section', 'article']:
                                        all_elements.append(text_elem)
                            except:
                                pass
                    except:
                        pass
            except Exception as e:
                print(f"   ⚠️  Clickable styled elements search failed: {e}")
            
            for elem in all_elements[:150]:  # Limit total to 150
                try:
                    # Skip if it's a toggle/switch/checkbox
                    try:
                        if elem.locator("input[type='checkbox'], input[type='radio'], [role='switch']").count() > 0:
                            continue
                        # Check if element itself is a checkbox/radio
                        tag = elem.evaluate("el => el.tagName.toLowerCase()")
                        input_type = elem.get_attribute("type")
                        if tag == "input" and input_type in ["checkbox", "radio", "submit", "button"]:
                            # Only include submit/button inputs, not checkboxes
                            if input_type in ["checkbox", "radio"]:
                                continue
                    except:
                        pass
                    
                    text = None
                    href = None
                    elem_type = "unknown"
                    is_clickable = False
                    
                    # Get text from multiple sources - be more thorough
                    try:
                        # Try inner_text first (gets all text including children)
                        text = elem.inner_text().strip()
                        
                        # If empty, try text_content (includes hidden text)
                        if not text:
                            text = elem.evaluate("el => el.textContent || ''").strip()
                        
                        # Also check aria-label, title, alt, and data attributes
                        if not text:
                            text = (elem.get_attribute("aria-label") or 
                                   elem.get_attribute("title") or 
                                   elem.get_attribute("alt") or
                                   elem.get_attribute("data-label") or
                                   elem.get_attribute("data-text") or "").strip()
                        
                        # If still no text, check if text is split across child elements
                        if not text:
                            try:
                                # Get all text from children
                                child_text = elem.evaluate("""
                                    el => {
                                        const texts = [];
                                        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
                                        let node;
                                        while (node = walker.nextNode()) {
                                            const t = node.textContent.trim();
                                            if (t) texts.push(t);
                                        }
                                        return texts.join(' ').trim();
                                    }
                                """)
                                if child_text:
                                    text = child_text
                            except:
                                pass
                    except:
                        try:
                            text = elem.get_attribute("aria-label") or elem.get_attribute("title") or elem.get_attribute("alt") or ""
                        except:
                            text = ""
                    
                    if not text or len(text) > 200:  # Skip empty or too long
                        continue
                    
                    # Skip very short text (likely icons or separators) but allow "Manage Info" type text
                    text_clean = text.strip()
                    if len(text_clean) < 2:
                        continue
                    
                    # Normalize text (remove extra whitespace, newlines)
                    text = ' '.join(text.split())
                    
                    # Determine element type and properties
                    try:
                        tag = elem.evaluate("el => el.tagName.toLowerCase()")
                        role = elem.get_attribute("role") or ""
                        onclick = elem.get_attribute("onclick")
                        data_href = elem.get_attribute("data-href")
                        tabindex = elem.get_attribute("tabindex")
                        
                        if tag == "a":
                            href = elem.get_attribute("href")
                            elem_type = "link"
                            is_clickable = True
                        elif tag == "button" or role == "button":
                            href = elem.get_attribute("href") or data_href
                            onclick = onclick or elem.get_attribute("onclick")
                            if onclick:
                                elem_type = "button_with_action"
                            elif href:
                                elem_type = "link_button"
                            else:
                                elem_type = "button"
                            is_clickable = True
                        elif role == "link":
                            href = elem.get_attribute("href") or data_href
                            elem_type = "link_role"
                            is_clickable = True
                        elif onclick or data_href:
                            href = data_href
                            elem_type = "clickable_element"
                            is_clickable = True
                        elif tabindex == "0" and (tag in ["div", "span", "p", "li", "td"]):
                            # Focusable elements that might be clickable
                            elem_type = "focusable_element"
                            is_clickable = True
                        else:
                            # Check if parent is clickable (more comprehensive)
                            try:
                                # Check multiple levels of parents
                                parent = elem.locator("xpath=ancestor::a | ancestor::button | ancestor::*[@onclick] | ancestor::*[@data-href] | ancestor::*[@role='button'] | ancestor::*[@role='link']").first
                                if parent.count() > 0:
                                    parent_tag = parent.evaluate("el => el.tagName.toLowerCase()")
                                    parent_role = parent.get_attribute("role") or ""
                                    
                                    if parent_tag == "a":
                                        href = parent.get_attribute("href")
                                        elem_type = "link_child"
                                    elif parent_tag == "button" or parent_role == "button":
                                        elem_type = "button_child"
                                    elif parent.get_attribute("onclick") or parent.get_attribute("data-href"):
                                        elem_type = "clickable_child"
                                    else:
                                        elem_type = "clickable_child"
                                    is_clickable = True
                                    
                                    # Update href from parent if available
                                    if not href:
                                        href = parent.get_attribute("href") or parent.get_attribute("data-href")
                            except:
                                pass
                            
                            # Also check if element itself has click handlers via JavaScript
                            if not is_clickable:
                                try:
                                    has_click = elem.evaluate("""
                                        el => {
                                            return el.onclick !== null || 
                                                   el.getAttribute('onclick') !== null ||
                                                   el.getAttribute('data-href') !== null ||
                                                   window.getComputedStyle(el).cursor === 'pointer';
                                        }
                                    """)
                                    if has_click:
                                        elem_type = "js_clickable"
                                        is_clickable = True
                                except:
                                    pass
                    except:
                        pass
                    
                    # Only include if it's actually clickable
                    if not is_clickable:
                        continue
                    
                    # Check if element is visible
                    try:
                        if not elem.is_visible():
                            continue
                    except:
                        pass
                    
                    links.append({
                        "text": text.strip(),
                        "href": href,
                        "type": elem_type,
                        "clickable": is_clickable
                    })
                except:
                    continue
            
            # Remove duplicates (same text)
            seen = set()
            unique_links = []
            for link in links:
                text_key = link["text"].lower().strip()
                if text_key and text_key not in seen:
                    seen.add(text_key)
                    unique_links.append(link)
            
            # Sort by type (links first, then buttons, then other clickable elements)
            type_order = {"link": 0, "link_role": 1, "link_button": 2, "button": 3, "button_with_action": 4, 
                         "clickable_element": 5, "js_clickable": 5, "focusable_element": 6, 
                         "link_child": 7, "button_child": 8, "clickable_child": 9}
            unique_links.sort(key=lambda x: type_order.get(x["type"], 99))
            
            # Debug: Print summary of what we found
            print(f"   🔍 Found {len(unique_links)} clickable elements (links: {sum(1 for l in unique_links if 'link' in l['type'])}, buttons: {sum(1 for l in unique_links if 'button' in l['type'])}, other: {sum(1 for l in unique_links if 'link' not in l['type'] and 'button' not in l['type'])})")
            
            return unique_links
        except Exception as e:
            print(f"⚠️  Error listing navigation links: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def navigate_by_link_text(self, link_text: str, partial_match: bool = True, wait_time: float = 2.0, auto_list_links: bool = False) -> Dict[str, any]:
        """
        Navigate to another page by clicking on a link/button with matching text.
        
        Args:
            link_text: Text to search for in links/buttons
            partial_match: Whether to do partial matching (case-insensitive)
            wait_time: Time to wait after navigation (seconds)
            auto_list_links: Whether to automatically list links after navigation
        
        Returns:
            Dictionary with navigation result
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start_browser() first.")
        
        try:
            print(f"🔗 Looking for link/button: '{link_text}'")
            
            # Wait for page to be ready
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(2)  # Give page more time to render
            
            current_url = self.page.url
            print(f"   📍 Current URL: {current_url}")
            
            # Try multiple strategies to find and click the link
            clicked = False
            click_method = None
            
            # Strategy 1: Try get_by_text (most reliable for text matching)
            try:
                if partial_match:
                    # Use filter for partial match - try both links and buttons
                    all_text_elements = self.page.locator(f"text=/{re.escape(link_text)}/i")
                    if all_text_elements.count() > 0:
                        # Find the first clickable one (prioritize links and buttons)
                        for i in range(min(all_text_elements.count(), 20)):
                            elem = all_text_elements.nth(i)
                            try:
                                tag = elem.evaluate("el => el.tagName.toLowerCase()")
                                role = elem.get_attribute("role") or ""
                                onclick = elem.get_attribute("onclick")
                                data_href = elem.get_attribute("data-href")
                                tabindex = elem.get_attribute("tabindex")
                                
                                # Check if it's clickable
                                is_clickable = (
                                    tag in ["a", "button"] or 
                                    role in ["link", "button"] or
                                    onclick is not None or
                                    data_href is not None or
                                    (tabindex == "0" and tag in ["div", "span", "p", "li"])
                                )
                                
                                # Also check if it's inside a clickable parent
                                if not is_clickable:
                                    parent_clickable = elem.locator("xpath=ancestor::a | ancestor::button | ancestor::*[@onclick] | ancestor::*[@data-href]").first
                                    if parent_clickable.count() > 0:
                                        is_clickable = True
                                        elem = parent_clickable.first
                                
                                if is_clickable:
                                    # Scroll into view
                                    elem.scroll_into_view_if_needed()
                                    time.sleep(0.5)
                                    elem.click(timeout=5000)
                                    clicked = True
                                    click_method = "text_match"
                                    print(f"   ✅ Clicked element (text match, index {i}): {link_text}")
                                    break
                            except Exception as e:
                                continue
                else:
                    # Exact match - try links first, then buttons
                    text_elem = self.page.get_by_text(link_text, exact=True).first
                    if text_elem.count() > 0:
                        # Check if it's clickable or find clickable parent
                        tag = text_elem.evaluate("el => el.tagName.toLowerCase()")
                        role = text_elem.get_attribute("role") or ""
                        is_clickable = tag in ["a", "button"] or role in ["link", "button"]
                        
                        if not is_clickable:
                            # Try to find clickable parent
                            parent = text_elem.locator("xpath=ancestor::a | ancestor::button | ancestor::*[@onclick] | ancestor::*[@data-href]").first
                            if parent.count() > 0:
                                text_elem = parent.first
                                is_clickable = True
                        
                        if is_clickable:
                            text_elem.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            text_elem.click(timeout=5000)
                            clicked = True
                            click_method = "text_exact"
                            print(f"   ✅ Clicked element (exact text): {link_text}")
            except Exception as e:
                print(f"   ⚠️  Text-based search failed: {e}")
            
            # Strategy 2: Try role-based locators
            if not clicked:
                try:
                    if partial_match:
                        # Try link role with partial match
                        link = self.page.get_by_role("link").filter(has_text=re.compile(link_text, re.I)).first
                        if link.count() > 0:
                            link.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            link.click(timeout=5000)
                            clicked = True
                            click_method = "role_link"
                            print(f"   ✅ Clicked link (role='link'): {link_text}")
                    else:
                        link = self.page.get_by_role("link", name=link_text, exact=True).first
                        if link.count() > 0:
                            link.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            link.click(timeout=5000)
                            clicked = True
                            click_method = "role_link"
                            print(f"   ✅ Clicked link (role='link', exact): {link_text}")
                except Exception as e:
                    print(f"   ⚠️  Role-based link search failed: {e}")
            
            if not clicked:
                try:
                    if partial_match:
                        button = self.page.get_by_role("button").filter(has_text=re.compile(link_text, re.I)).first
                        if button.count() > 0:
                            button.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            button.click(timeout=5000)
                            clicked = True
                            click_method = "role_button"
                            print(f"   ✅ Clicked button (role='button'): {link_text}")
                    else:
                        button = self.page.get_by_role("button", name=link_text, exact=True).first
                        if button.count() > 0:
                            button.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            button.click(timeout=5000)
                            clicked = True
                            click_method = "role_button"
                            print(f"   ✅ Clicked button (role='button', exact): {link_text}")
                except Exception as e:
                    print(f"   ⚠️  Role-based button search failed: {e}")
            
            # Strategy 3: Try href-based search for links
            if not clicked:
                try:
                    if partial_match:
                        # Find links containing the text
                        links = self.page.locator(f'a:has-text("{link_text}")').all()
                        if len(links) > 0:
                            for link in links[:5]:  # Try first 5 matches
                                try:
                                    link.scroll_into_view_if_needed()
                                    time.sleep(0.5)
                                    link.click(timeout=5000)
                                    clicked = True
                                    click_method = "href_text"
                                    print(f"   ✅ Clicked link (href with text): {link_text}")
                                    break
                                except:
                                    continue
                    else:
                        link = self.page.locator(f'a:has-text("{link_text}")').first
                        if link.count() > 0:
                            link.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            link.click(timeout=5000)
                            clicked = True
                            click_method = "href_text"
                            print(f"   ✅ Clicked link (href with exact text): {link_text}")
                except Exception as e:
                    print(f"   ⚠️  Href-based search failed: {e}")
            
            # Strategy 4: Try finding by aria-label (for both links and buttons)
            if not clicked:
                try:
                    if partial_match:
                        # Try links and buttons with aria-label
                        for selector in [f'a[aria-label*="{link_text}" i]', f'button[aria-label*="{link_text}" i]', 
                                        f'[role="button"][aria-label*="{link_text}" i]', f'[role="link"][aria-label*="{link_text}" i]']:
                            elem = self.page.locator(selector).first
                            if elem.count() > 0:
                                elem.scroll_into_view_if_needed()
                                time.sleep(0.5)
                                elem.click(timeout=5000)
                                clicked = True
                                click_method = "aria_label"
                                print(f"   ✅ Clicked element (aria-label): {link_text}")
                                break
                    else:
                        for selector in [f'a[aria-label="{link_text}"]', f'button[aria-label="{link_text}"]',
                                        f'[role="button"][aria-label="{link_text}"]', f'[role="link"][aria-label="{link_text}"]']:
                            elem = self.page.locator(selector).first
                            if elem.count() > 0:
                                elem.scroll_into_view_if_needed()
                                time.sleep(0.5)
                                elem.click(timeout=5000)
                                clicked = True
                                click_method = "aria_label"
                                print(f"   ✅ Clicked element (aria-label, exact): {link_text}")
                                break
                except Exception as e:
                    print(f"   ⚠️  Aria-label search failed: {e}")
            
            # Strategy 5: Try finding buttons/clickable divs with onclick or data-href
            if not clicked:
                try:
                    # Look for clickable divs/spans with the text
                    clickable_selectors = [
                        f'div[onclick*="{link_text}" i]',
                        f'span[onclick*="{link_text}" i]',
                        f'div[data-href*="{link_text}" i]',
                        f'*[onclick]:has-text("{link_text}")',
                        f'*[data-href]:has-text("{link_text}")',
                    ]
                    for selector in clickable_selectors:
                        try:
                            elem = self.page.locator(selector).first
                            if elem.count() > 0:
                                elem.scroll_into_view_if_needed()
                                time.sleep(0.5)
                                elem.click(timeout=5000)
                                clicked = True
                                click_method = "clickable_element"
                                print(f"   ✅ Clicked clickable element: {link_text}")
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"   ⚠️  Clickable element search failed: {e}")
            
            if not clicked:
                # List available links for debugging
                print(f"   🔍 Debug: Listing available links on page...")
                available_links = self.list_navigation_links()
                if available_links:
                    print(f"   📋 Found {len(available_links)} links/buttons:")
                    for i, link in enumerate(available_links[:10], 1):
                        print(f"      {i}. '{link['text']}' ({link['type']})")
                
                return {
                    "status": "error",
                    "message": f"Could not find link/button with text: '{link_text}'. Use --list-links to see available options.",
                    "available_links": [l["text"] for l in available_links[:10]] if available_links else []
                }
            
            # Wait for navigation
            print(f"   ⏳ Waiting for navigation...")
            time.sleep(wait_time)
            
            # Wait for URL change or page load
            try:
                # Wait for navigation with timeout
                self.page.wait_for_url("**", timeout=10000, state="domcontentloaded")
            except:
                # If URL didn't change, wait for load anyway
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            new_url = self.page.url
            title = self.page.title()
            
            print(f"   📍 New URL: {new_url}")
            
            result = None
            if new_url != current_url:
                result = {
                    "status": "success",
                    "message": f"Navigated to new page (method: {click_method})",
                    "previous_url": current_url,
                    "new_url": new_url,
                    "title": title,
                    "click_method": click_method
                }
            else:
                # Sometimes navigation happens via JavaScript without URL change
                # Check if page content changed
                result = {
                    "status": "warning",
                    "message": f"Link clicked (method: {click_method}) but URL did not change. Page may have updated via JavaScript.",
                    "url": new_url,
                    "title": title,
                    "click_method": click_method
                }
            
            # Auto-list links if requested and navigation was successful
            if auto_list_links and result["status"] in ["success", "warning"]:
                self._display_links_after_navigation()
            
            return result
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"Failed to navigate: {str(e)}"
            }
    
    def _display_links_after_navigation(self):
        """
        Helper method to display links after navigation.
        Called automatically when auto_list_links is enabled.
        """
        try:
            print("\n" + "=" * 60)
            print("🔗 Available Links/Buttons on This Page")
            print("=" * 60)
            links = self.list_navigation_links()
            if links:
                print(f"\n✅ Found {len(links)} navigation options:")
                for i, link in enumerate(links, 1):
                    # Choose icon based on type
                    if "link" in link["type"].lower():
                        link_type_icon = "🔗"
                    elif "button" in link["type"].lower():
                        link_type_icon = "🔘"
                    else:
                        link_type_icon = "👆"
                    href_info = f" → {link['href']}" if link.get("href") else ""
                    type_info = f" ({link['type']})" if link.get("type") != "link" else ""
                    print(f"  {i}. {link_type_icon} {link['text']}{type_info}{href_info}")
            else:
                print("   ⚠️  No navigation links found on this page.")
        except Exception as e:
            print(f"   ⚠️  Error listing links: {e}")
    
    def close_browser(self):
        """Close the browser."""
        if self.browser:
            self.browser.close()
        if hasattr(self, 'playwright'):
            self.playwright.stop()
        print("✅ Browser closed")
    
    def get_current_settings(self) -> Dict[str, any]:
        """Get current settings as a dictionary."""
        return {
            "json_file": str(self.json_file),
            "email": self.email,
            "password": "***" if self.password else None,  # Don't show password
            "headless": self.headless,
            "use_persistent_profile": self.use_persistent_profile,
            "profile_dir": str(self.profile_dir) if self.profile_dir else None,
            "storage_state_file": str(self.storage_state_file) if self.storage_state_file else None,
            "save_storage_after_login": self.save_storage_after_login
        }
    
    def reload_with_new_settings(self, new_json_file: Optional[str] = None, 
                                 new_email: Optional[str] = None,
                                 new_password: Optional[str] = None,
                                 new_headless: Optional[bool] = None,
                                 new_storage_state_file: Optional[str] = None,
                                 new_profile_dir: Optional[str] = None,
                                 new_use_persistent_profile: Optional[bool] = None):
        """
        Reload navigator with new settings. Browser must be closed first.
        
        Args:
            new_json_file: New JSON file path
            new_email: New email
            new_password: New password
            new_headless: New headless setting
            new_storage_state_file: New storage state file
            new_profile_dir: New profile directory
            new_use_persistent_profile: New persistent profile setting
        """
        if self.page or self.context or self.browser:
            raise RuntimeError("Browser must be closed before reloading settings. Call close_browser() first.")
        
        if new_json_file:
            self.json_file = Path(new_json_file)
            self.data = self.load_json()
        
        if new_email:
            self.email = new_email
        
        if new_password:
            self.password = new_password
        
        if new_headless is not None:
            self.headless = new_headless
        
        if new_storage_state_file:
            self.storage_state_file = Path(new_storage_state_file) if new_storage_state_file else None
        
        if new_profile_dir:
            self.profile_dir = Path(new_profile_dir) if new_profile_dir else None
        
        if new_use_persistent_profile is not None:
            self.use_persistent_profile = new_use_persistent_profile
        
        self.logged_in = False  # Reset login status
        print("✅ Settings reloaded")


def prompt_for_settings_switch(navigator: URLNavigator) -> bool:
    """
    Prompt user to switch settings interactively.
    
    Args:
        navigator: Current URLNavigator instance
        
    Returns:
        True if settings were changed, False otherwise
    """
    print("\n" + "=" * 60)
    print("⚙️  SETTINGS MENU")
    print("=" * 60)
    
    # Show current settings
    settings = navigator.get_current_settings()
    print("\n📋 Current Settings:")
    print(f"  JSON File: {settings['json_file']}")
    print(f"  Email: {settings['email']}")
    print(f"  Headless: {settings['headless']}")
    print(f"  Storage State: {settings['storage_state_file']}")
    print(f"  Persistent Profile: {settings['use_persistent_profile']}")
    
    print("\n🔄 Available Options:")
    print("  1. Switch JSON file")
    print("  2. Change email")
    print("  3. Change password")
    print("  4. Toggle headless mode")
    print("  5. Change storage state file")
    print("  6. Change profile directory")
    print("  7. Toggle persistent profile")
    print("  8. Show all settings")
    print("  0. Continue without changes")
    
    try:
        choice = input("\n👉 Enter your choice (0-8): ").strip()
        
        if choice == "0":
            return False
        
        # Check if browser is open - need to close it first
        browser_open = navigator.page is not None or navigator.context is not None or navigator.browser is not None
        
        if choice == "1":
            # Switch JSON file
            print("\n📁 Available JSON files:")
            # Discover available JSON files in json_data directory
            json_data_dir = Path("json_data")
            if json_data_dir.exists():
                json_files = sorted([f.name for f in json_data_dir.glob("*.json")])
            else:
                json_files = ["facebook.json", "linkedin.json", "zoom.json"]
            
            if json_files:
                for i, f in enumerate(json_files, 1):
                    full_path = f"json_data/{f}"
                    exists = Path(full_path).exists()
                    marker = "✅" if exists else "❌"
                    print(f"  {i}. {marker} {f}")
            
            file_choice = input(f"👉 Select JSON file (1-{len(json_files)}) or enter custom path: ").strip()
            
            if file_choice.isdigit() and 1 <= int(file_choice) <= len(json_files):
                new_file = f"json_data/{json_files[int(file_choice) - 1]}"
            else:
                new_file = file_choice
            
            if browser_open:
                print("⚠️  Browser is open. Closing browser to apply changes...")
                navigator.close_browser()
            
            # Auto-update storage state file based on new service
            new_service = extract_service_name(new_file)
            new_storage = get_default_storage_state_file(new_service)
            
            navigator.reload_with_new_settings(new_json_file=new_file, new_storage_state_file=new_storage)
            print(f"✅ Switched to: {new_file}")
            print(f"✅ Service: {new_service}")
            print(f"✅ Storage state: {new_storage}")
            return True
        
        elif choice == "2":
            new_email = input("👉 Enter new email: ").strip()
            if new_email:
                if browser_open:
                    print("⚠️  Browser is open. Closing browser to apply changes...")
                    navigator.close_browser()
                navigator.reload_with_new_settings(new_email=new_email)
                print(f"✅ Email updated to: {new_email}")
                return True
        
        elif choice == "3":
            new_password = input("👉 Enter new password: ").strip()
            if new_password:
                if browser_open:
                    print("⚠️  Browser is open. Closing browser to apply changes...")
                    navigator.close_browser()
                navigator.reload_with_new_settings(new_password=new_password)
                print("✅ Password updated")
                return True
        
        elif choice == "4":
            new_headless = not navigator.headless
            if browser_open:
                print("⚠️  Browser is open. Closing browser to apply changes...")
                navigator.close_browser()
            navigator.reload_with_new_settings(new_headless=new_headless)
            print(f"✅ Headless mode: {'ON' if new_headless else 'OFF'}")
            return True
        
        elif choice == "5":
            new_storage = input("👉 Enter storage state file path (or 'none' to clear): ").strip()
            if new_storage.lower() == "none":
                new_storage = None
            if browser_open:
                print("⚠️  Browser is open. Closing browser to apply changes...")
                navigator.close_browser()
            navigator.reload_with_new_settings(new_storage_state_file=new_storage)
            print(f"✅ Storage state file: {new_storage or 'None'}")
            return True
        
        elif choice == "6":
            new_profile = input("👉 Enter profile directory path (or 'none' to clear): ").strip()
            if new_profile.lower() == "none":
                new_profile = None
            if browser_open:
                print("⚠️  Browser is open. Closing browser to apply changes...")
                navigator.close_browser()
            navigator.reload_with_new_settings(new_profile_dir=new_profile)
            print(f"✅ Profile directory: {new_profile or 'None'}")
            return True
        
        elif choice == "7":
            new_persistent = not navigator.use_persistent_profile
            if browser_open:
                print("⚠️  Browser is open. Closing browser to apply changes...")
                navigator.close_browser()
            navigator.reload_with_new_settings(new_use_persistent_profile=new_persistent)
            print(f"✅ Persistent profile: {'ON' if new_persistent else 'OFF'}")
            return True
        
        elif choice == "8":
            settings = navigator.get_current_settings()
            print("\n📋 All Current Settings:")
            for key, value in settings.items():
                print(f"  {key}: {value}")
            return False
        
        else:
            print("❌ Invalid choice")
            return False
            
    except KeyboardInterrupt:
        print("\n⚠️  Cancelled")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Main function to demonstrate URL navigation."""
    parser = argparse.ArgumentParser(
        description="Navigate to URLs from JSON data files with optional targeting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s facebook --find "Personal Details" --change-birthday 5 15 1990
  %(prog)s zoom --url "https://zoom.us/profile/setting?tab=general" --list-toggles
  %(prog)s zoom --url "https://zoom.us/profile/setting?tab=general" --change-toggle "Enable notifications" disable
  %(prog)s linkedin --ads
  %(prog)s --json-file custom/path.json --find "settings"
        """
    )
    parser.add_argument("service", nargs="?", default=None,
                        help="Service name (facebook, zoom, linkedin). Auto-generates json_data/{service}.json")
    parser.add_argument("--json-file",
                        help="Path to JSON file containing URL data (overrides service name if provided)")
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
    parser.add_argument("--storage-state-file", default=None,
                        help="Path to Playwright storage state JSON. If not provided, auto-generated from service name.")
    parser.add_argument("--interactive", action="store_true", 
                        help="Enable interactive mode to switch settings when prompted.")
    parser.add_argument("--ads", action="store_true",
                        help="Navigate to ads preferences page.")
    parser.add_argument("--list-ads", action="store_true",
                        help="List all available ad settings on current page.")
    parser.add_argument("--change-ad-setting", nargs=2, metavar=("SETTING_NAME", "STATE"),
                        help="Change an ad setting. STATE should be 'enable' or 'disable'. Example: --change-ad-setting 'Ad personalization' disable")
    parser.add_argument("--list-links", action="store_true",
                        help="List all available navigation links/buttons on current page.")
    parser.add_argument("--auto-list-links", action="store_true",
                        help="Automatically list all links/buttons after each navigation.")
    parser.add_argument("--navigate-to", metavar="LINK_TEXT",
                        help="Navigate to another page by clicking a link/button with this text. Example: --navigate-to 'Ad preferences'")
    parser.add_argument("--change-birthday", nargs=3, metavar=("MONTH", "DAY", "YEAR"),
                        help="Change birthday. Will auto-navigate to Personal Details if needed. Example: facebook --find 'Personal Details' --change-birthday 5 15 1990")
    parser.add_argument("--list-toggles", action="store_true",
                        help="List all available toggles/switches on current page.")
    parser.add_argument("--change-toggle", nargs=2, metavar=("TOGGLE_LABEL", "STATE"),
                        help="Change a toggle/switch. STATE should be 'enable' or 'disable'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --change-toggle 'Enable notifications' disable")
    parser.add_argument("--check-checkbox", nargs=2, metavar=("CHECKBOX_LABEL", "STATE"),
                        help="Check or uncheck a checkbox by label. STATE should be 'check' or 'uncheck'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --check-checkbox 'Allow users to send text feedback' check")
    parser.add_argument("--physical-toggle", nargs=2, metavar=("LABEL", "STATE"),
                        help="Physically click a toggle/checkbox using mouse API. STATE should be 'enable' or 'disable'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --physical-toggle 'Allow users to send text feedback' enable")
    parser.add_argument("--gemini-toggle-text-feedback", metavar="STATE",
                        help="Use Gemini AI to locate and toggle 'Allow users to send text feedback' setting. STATE should be 'enable' or 'disable'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --gemini-toggle-text-feedback enable")
    args, unknown = parser.parse_known_args()
    
    # Determine JSON file path
    if args.json_file:
        # Use explicitly provided JSON file
        json_file_path = args.json_file
    elif args.service:
        # Auto-generate from service name
        json_file_path = f"json_data/{args.service.lower()}.json"
    else:
        # Default to facebook for backward compatibility
        json_file_path = "json_data/facebook.json"
        print("⚠️  No service specified, defaulting to 'facebook'")
        print("   Usage: python3 navigate_to_urls.py <service> [options]")
        print("   Example: python3 navigate_to_urls.py facebook --find 'Personal Details'")
    
    # Extract service name for display
    service_name = extract_service_name(json_file_path)
    print(f"🔍 URL Navigator - {service_name.upper()}")
    print("=" * 60)
    
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
            json_file_path, 
            headless=headless_flag,
            email="zoomaitester10@gmail.com",
            password="ZoomTestPass",
            use_persistent_profile=bool(args.use_persistent_profile),
            profile_dir=args.profile_dir,
            storage_state_file=args.storage_state_file,
            save_storage_after_login=True
        )
        
        print(f"📁 Using JSON file: {navigator.json_file}")
        print(f"🔐 Service: {navigator.service_name}")
        if navigator.storage_state_file:
            print(f"💾 Storage state: {navigator.storage_state_file}")
        
        # Interactive settings switch if enabled
        if args.interactive:
            while True:
                settings_changed = prompt_for_settings_switch(navigator)
                if settings_changed:
                    # Ask if user wants to change more settings
                    continue_choice = input("\n👉 Change more settings? (y/n): ").strip().lower()
                    if continue_choice != 'y':
                        break
                else:
                    break
        
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
        
        # Determine if we should auto-list links
        auto_list_links_flag = args.auto_list_links or args.list_links
        
        target_url = None
        if args.ads:
            # Navigate to ads page
            print("\n📢 Navigating to ads preferences page...")
            result = navigator.navigate_to_ads_page(auto_login=auto_login_flag, auto_list_links=auto_list_links_flag)
            if result["status"] == "success":
                print(f"   ✅ Successfully navigated to ads page: {result['title']}")
                print(f"   📍 Current URL: {result['actual_url']}")
            else:
                print(f"   ❌ Failed: {result.get('error')}")
        elif args.url:
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
            result = navigator.navigate_to_url(target_url, auto_login=auto_login_flag, auto_list_links=auto_list_links_flag)
            if result["status"] == "success":
                print(f"   ✅ Successfully navigated to: {result['title']}")
                print(f"   📍 Current URL: {result['actual_url']}")
                if args.screenshot:
                    navigator.take_screenshot(args.screenshot)
            else:
                print(f"   ❌ Failed: {result.get('error')}")
        
        # Handle ad settings operations
        if args.list_ads:
            print("\n📋 Listing available ad settings...")
            settings = navigator.list_ad_settings()
            if settings:
                print(f"\n✅ Found {len(settings)} ad settings:")
                for i, setting in enumerate(settings, 1):
                    state_icon = "✅" if setting["state"] in ["checked", "on"] else "❌"
                    print(f"  {i}. {state_icon} {setting['label']} ({setting['state']})")
            else:
                print("   ⚠️  No ad settings found. Make sure you're on the ads preferences page.")
        
        if args.change_ad_setting:
            setting_name, state_str = args.change_ad_setting
            enable = state_str.lower() in ["enable", "on", "true", "1", "yes"]
            print(f"\n🔧 Changing ad setting: '{setting_name}' to {'enabled' if enable else 'disabled'}")
            result = navigator.change_ad_setting(setting_name, enable=enable)
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
        
        # Handle birthday change operation
        if args.change_birthday:
            month_str, day_str, year_str = args.change_birthday
            try:
                month = int(month_str)
                day = int(day_str)
                year = int(year_str)
                
                # If --find was used, we should already be on the Personal Details page
                # But if not, try to navigate there
                if args.find and "personal" in args.find.lower() and "detail" in args.find.lower():
                    print(f"\n🎂 Birthday change requested. Already navigating to Personal Details via --find...")
                else:
                    # Try to navigate to Personal Details if not already there
                    print(f"\n🎂 Birthday change requested. Navigating to Personal Details...")
                    personal_details_result = navigator.navigate_by_link_text("Personal details", partial_match=True, wait_time=2.0)
                    if personal_details_result["status"] not in ["success", "warning"]:
                        print(f"   ⚠️  Could not navigate to Personal Details. Attempting to change birthday on current page anyway...")
                
                print(f"\n🎂 Changing birthday to: {month}/{day}/{year}")
                result = navigator.change_birthday(month, day, year)
                if result["status"] == "success":
                    print(f"   ✅ {result['message']}")
                    if result.get("saved"):
                        print(f"   💾 Changes saved")
                    else:
                        print(f"   ⚠️  Changes made but save button not found/clicked. Please verify manually.")
                else:
                    print(f"   ❌ {result.get('message', 'Unknown error')}")
            except ValueError:
                print(f"   ❌ Invalid birthday format. Please provide three integers: MONTH DAY YEAR")
                print(f"   Example: --change-birthday 5 15 1990")
        
        # Handle toggle operations
        if args.list_toggles:
            print("\n🔘 Listing available toggles/switches...")
            toggles = navigator.list_toggles()
            if toggles:
                print(f"\n✅ Found {len(toggles)} toggles/switches:")
                for i, toggle in enumerate(toggles, 1):
                    state_icon = "✅" if toggle["state"] in ["checked", "on"] else "❌"
                    print(f"  {i}. {state_icon} {toggle['label']} ({toggle['state']})")
            else:
                print("   ⚠️  No toggles found on this page.")
        
        if args.change_toggle:
            toggle_label, state_str = args.change_toggle
            enable = state_str.lower() in ["enable", "on", "true", "1", "yes"]
            print(f"\n🔧 Changing toggle: '{toggle_label}' to {'enabled' if enable else 'disabled'}")
            result = navigator.change_toggle(toggle_label, enable=enable)
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
        
        if args.check_checkbox:
            checkbox_label, state_str = args.check_checkbox
            check = state_str.lower() in ["check", "checked", "true", "1", "yes", "on"]
            action = "checking" if check else "unchecking"
            print(f"\n☑️  {action.capitalize()} checkbox: '{checkbox_label}'")
            result = navigator.check_checkbox(checkbox_label, check=check)
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
        
        if args.physical_toggle:
            toggle_label, state_str = args.physical_toggle
            enable = state_str.lower() in ["enable", "on", "true", "1", "yes", "check", "checked"]
            print(f"\n🖱️  Physically toggling: '{toggle_label}' to {'enabled' if enable else 'disabled'}")
            result = navigator.physical_toggle(toggle_label, enable=enable)
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
                print(f"   📊 Previous state: {result.get('previous_state', 'unknown')}")
                print(f"   📊 New state: {result.get('new_state', 'unknown')}")
            elif result["status"] == "warning":
                print(f"   ⚠️  {result['message']}")
                print(f"   📊 Previous state: {result.get('previous_state', 'unknown')}")
                print(f"   📊 New state: {result.get('new_state', 'unknown')}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
                if not result.get("element_found"):
                    print(f"   ⚠️  Element not found")
        
        if args.gemini_toggle_text_feedback:
            state_str = args.gemini_toggle_text_feedback
            enable = state_str.lower() in ["enable", "on", "true", "1", "yes", "check", "checked"]
            print(f"\n🤖 Using Gemini to toggle 'Allow users to send text feedback' to {'enabled' if enable else 'disabled'}")
            result = navigator.toggle_zoom_text_feedback_setting(enable=enable)
            if result["status"] == "success":
                print(f"   ✅ Success!")
                print(f"   📊 Target: {result.get('target', 'N/A')}")
                print(f"   📊 Previous state: {result.get('previous_state', 'unknown')}")
                print(f"   📊 New state: {result.get('new_state', 'unknown')}")
                print(f"   📊 Selection mode: {result.get('selection_mode', 'none')}")
                if result.get("gemini_reason"):
                    print(f"   💡 Gemini reason: {result.get('gemini_reason')}")
                # Save status is already logged in toggle_zoom_text_feedback_setting
            else:
                print(f"   ❌ Error: {result.get('gemini_reason', 'Unknown error')}")
                print(f"   📊 Selection mode: {result.get('selection_mode', 'none')}")
        
        # Handle navigation operations
        if args.list_links:
            print("\n🔗 Listing available navigation links/buttons...")
            links = navigator.list_navigation_links()
            if links:
                print(f"\n✅ Found {len(links)} navigation options:")
                for i, link in enumerate(links, 1):
                    # Choose icon based on type
                    if "link" in link["type"].lower():
                        link_type_icon = "🔗"
                    elif "button" in link["type"].lower():
                        link_type_icon = "🔘"
                    else:
                        link_type_icon = "👆"
                    href_info = f" → {link['href']}" if link.get("href") else ""
                    type_info = f" ({link['type']})" if link.get("type") != "link" else ""
                    print(f"  {i}. {link_type_icon} {link['text']}{type_info}{href_info}")
                
                # Interactive navigation prompt
                print("\n" + "=" * 60)
                print("🎯 INTERACTIVE NAVIGATION")
                print("=" * 60)
                print("You can navigate to any of the links above.")
                print("Enter a number (1-{}) to navigate, or type the link text.".format(len(links)))
                print("Press Enter without input to skip navigation.")
                
                try:
                    user_input = input("\n👉 Enter your choice: ").strip()
                    
                    if user_input:
                        selected_link = None
                        
                        # Try to parse as number
                        try:
                            link_num = int(user_input)
                            if 1 <= link_num <= len(links):
                                selected_link = links[link_num - 1]
                            else:
                                print(f"❌ Invalid number. Please enter a number between 1 and {len(links)}.")
                        except ValueError:
                            # Not a number, try to find by text (partial match)
                            matching_links = [l for l in links if user_input.lower() in l["text"].lower()]
                            if len(matching_links) == 1:
                                selected_link = matching_links[0]
                            elif len(matching_links) > 1:
                                print(f"\n⚠️  Found {len(matching_links)} matches:")
                                for i, link in enumerate(matching_links, 1):
                                    print(f"  {i}. {link['text']}")
                                try:
                                    choice = input("👉 Select which one (enter number): ").strip()
                                    choice_num = int(choice)
                                    if 1 <= choice_num <= len(matching_links):
                                        selected_link = matching_links[choice_num - 1]
                                    else:
                                        print("❌ Invalid selection.")
                                except (ValueError, KeyboardInterrupt):
                                    print("⚠️  Navigation cancelled.")
                            else:
                                print(f"❌ No link found matching '{user_input}'. Use --list-links to see available options.")
                        
                        if selected_link:
                            print(f"\n🚀 Navigating to: {selected_link['text']}")
                            # Use auto_list_links if the flag is set
                            result = navigator.navigate_by_link_text(
                                selected_link['text'], 
                                partial_match=False, 
                                wait_time=2.0,
                                auto_list_links=args.auto_list_links
                            )
                            if result["status"] == "success":
                                print(f"   ✅ {result['message']}")
                                print(f"   📍 New URL: {result.get('new_url', result.get('url'))}")
                                print(f"   📄 Title: {result.get('title', 'N/A')}")
                            elif result["status"] == "warning":
                                print(f"   ⚠️  {result['message']}")
                                print(f"   📍 URL: {result.get('url')}")
                            else:
                                print(f"   ❌ {result.get('message', 'Unknown error')}")
                except KeyboardInterrupt:
                    print("\n⚠️  Navigation cancelled by user.")
                except Exception as e:
                    print(f"\n❌ Error during navigation: {e}")
            else:
                print("   ⚠️  No navigation links found.")
        
        if args.navigate_to:
            print(f"\n🔗 Navigating to page: '{args.navigate_to}'")
            result = navigator.navigate_by_link_text(args.navigate_to, partial_match=True, auto_list_links=auto_list_links_flag)
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
                print(f"   📍 New URL: {result.get('new_url', result.get('url'))}")
                print(f"   📄 Title: {result.get('title', 'N/A')}")
            elif result["status"] == "warning":
                print(f"   ⚠️  {result['message']}")
                print(f"   📍 URL: {result.get('url')}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
        
        # Interactive settings switch after navigation (if enabled)
        if args.interactive:
            while True:
                switch_choice = input("\n👉 Switch settings? (y/n): ").strip().lower()
                if switch_choice == 'y':
                    settings_changed = prompt_for_settings_switch(navigator)
                    if settings_changed:
                        # Restart browser with new settings
                        print("\n🚀 Restarting browser with new settings...")
                        navigator.start_browser()
                        # Optionally navigate again
                        nav_choice = input("👉 Navigate to a URL with new settings? (y/n): ").strip().lower()
                        if nav_choice == 'y':
                            url_input = input("👉 Enter URL or keyword to find: ").strip()
                            if url_input:
                                if url_input.startswith("http"):
                                    target_url = url_input
                                else:
                                    candidates = navigator.find_urls_by_text(url_input, url_category=args.category)
                                    if candidates:
                                        target_url = candidates[0]
                                        print(f"➡️  Using: {target_url}")
                                    else:
                                        print(f"❌ No matches found for '{url_input}'")
                                        continue
                                
                                if target_url:
                                    result = navigator.navigate_to_url(target_url, auto_login=auto_login_flag)
                                    if result["status"] == "success":
                                        print(f"   ✅ Successfully navigated to: {result['title']}")
                                    else:
                                        print(f"   ❌ Failed: {result.get('error')}")
                else:
                    break
        
        # Keep browser open until user chooses to exit
        print("\n" + "=" * 60)
        print("🌐 Browser is open and ready for use")
        print("=" * 60)
        print("\n💡 The browser will stay open until you choose to exit.")
        print("   You can interact with the browser window freely.")
        
        try:
            user_input = input("\n👉 Press Enter to close the browser and exit (or type 'exit'/'quit'): ").strip().lower()
            if user_input in ['exit', 'quit', 'q']:
                print("\n👋 Closing browser...")
            else:
                print("\n👋 Closing browser...")
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user. Closing browser...")
        except Exception as e:
            print(f"\n⚠️  Error: {e}. Closing browser...")
        finally:
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


