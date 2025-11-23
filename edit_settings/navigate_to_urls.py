#!/usr/bin/env python3
"""
URL Navigator - Browser automation tool for navigating and modifying settings on various platforms.

Usage Examples:



Changing Settings (Traditional Methods):
  python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --change-toggle "Enable notifications" disable
  python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --check-checkbox "Allow users to send text feedback" check
  python3 navigate_to_urls.py facebook --ads --change-ad-setting "Ad personalization" disable
  python3 navigate_to_urls.py facebook --find "Personal Details" --change-birthday 5 15 1990

Gemini AI-Powered Toggle (Generic - Works for any setting):
  python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --setting "Allow users to send text feedback" --state enable
  python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --setting "Enable notifications" --state disable --description "Zoom general settings page"
  python3 navigate_to_urls.py facebook --url "https://accountscenter.facebook.com/ads" --setting "Ad personalization" --state disable
  python3 navigate_to_urls.py linkedin --url "https://www.linkedin.com/mypreferences/d/categories/privacy" --setting "Data privacy setting" --state enable

Gemini AI-Powered Toggle (Legacy Zoom-specific):
  python3 navigate_to_urls.py zoom --url "https://zoom.us/profile/setting?tab=general" --gemini-toggle-text-feedback enable


"""


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


def viewport_dom_textmap(page, max_items=120) -> str:
    """Extract visible text elements from the page viewport."""
    items = []
    try:
        for sel in ["h1,h2,h3,[role='heading']", "a,button", "[role='tab']", "[role='menuitem']", "[aria-label]"]:
            loc = page.locator(sel)
            count = min(loc.count(), max_items)
            for i in range(count):
                try:
                    t = loc.nth(i).inner_text().strip()
                except Exception:
                    try:
                        t = loc.nth(i).text_content().strip()
                    except Exception:
                        t = ""
                if t:
                    t = re.sub(r'\s+', ' ', t)
                    items.append(t[:160])
                if len(items) >= max_items:
                    break
            if len(items) >= max_items:
                break
    except Exception:
        pass
    out, seen = [], set()
    for t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return "\n".join(out[:max_items])


def dom_outline(page, max_nodes: int = 300) -> str:
    """Compact DOM outline to anchor CV with roles/labels/expand info."""
    try:
        data = page.evaluate(f"""
(() => {{
  const max = {max_nodes};
  const take = (n) => Array.from(n).slice(0, max);
  const norm = s => (s||"").replace(/\\s+/g,' ').trim();
  const sel = (el) => {{
    const id = el.id ? '#'+CSS.escape(el.id) : '';
    const cls = (el.className && typeof el.className==='string')
      ? '.'+el.className.trim().split(/\\s+/).slice(0,3).map(CSS.escape).join('.') : '';
    return el.tagName.toLowerCase()+id+cls;
  }};
  const nodes = take(document.querySelectorAll('a,button,[role],[aria-label],summary,[aria-expanded]'));
  return nodes.map(el => ({{
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role')||'',
    text: norm(el.innerText||''),
    ariaLabel: norm(el.getAttribute('aria-label')||''),
    expanded: el.getAttribute('aria-expanded'),
    clickable: (typeof el.click==='function'),
    selector: sel(el)
  }}));
}})();
""")
        return json.dumps(data[:max_nodes], ensure_ascii=False)
    except Exception:
        return "[]"


def toggle_setting_with_gemini(
    page,
    setting_label: str,
    enable: bool,
    description: Optional[str] = None,
    save_after: bool = True,
) -> dict:
    """
    Use screenshot + DOM text + Gemini to locate and toggle a UI setting whose
    label roughly matches `setting_label`.

    Arguments:
      - page: Playwright Page
      - setting_label: visible label near the toggle, e.g. 'Allow users to send text feedback'
      - enable: True => setting should end up ON, False => OFF
      - description: optional extra natural-language hint (e.g. 'Zoom general settings page')
      - save_after: if True, try to click a Save button after toggling

    Returns a dict with at least:
      - status: 'success' | 'error'
      - target: setting_label
      - previous_state: 'enabled' | 'disabled' | 'unknown'
      - new_state: 'enabled' | 'disabled' | 'unknown'
      - selection_mode: 'selector' | 'coordinates' | 'none'
      - gemini_reason: short explanation string
      - save_clicked: bool (whether a Save button was actually clicked)
    """
    result = {
        "status": "error",
        "target": setting_label,
        "previous_state": "unknown",
        "new_state": "unknown",
        "selection_mode": "none",
        "gemini_reason": "",
        "save_clicked": False
    }

    if not page:
        result["gemini_reason"] = "Page object not provided"
        return result

    if not GEMINI_AVAILABLE:
        result["gemini_reason"] = "Gemini API not available. Install google-genai package."
        return result

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        result["gemini_reason"] = "GEMINI_API_KEY environment variable not set"
        return result

    try:
        print(f"🤖 Using Gemini to locate '{setting_label}' setting...")
        
        # Wait for page to be ready
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        time.sleep(1)

        # a) Collect context similar to planner()
        print("   📝 Collecting DOM context...")
        DOM_TEXT_MAP = viewport_dom_textmap(page, max_items=120)
        DOM_OUTLINE = dom_outline(page, max_nodes=300)
        screenshot_bytes = page.screenshot(full_page=True)
        print(f"   ✅ Collected context (text map: {len(DOM_TEXT_MAP.split(chr(10)))} items, outline: {len(json.loads(DOM_OUTLINE))} nodes)")

        # b) Build Gemini prompt
        system_instruction = (
            "You are a UI assistant that helps locate and operate a single setting "
            "in a web app UI based on its label. You see:\n"
            "- a full-page screenshot,\n"
            "- a DOM_TEXT_MAP listing visible strings,\n"
            "- a DOM_OUTLINE listing clickable-like nodes.\n\n"
            "Your task is to identify the element that controls the setting associated "
            "with the given label (allow fuzzy/partial match), infer whether it is currently "
            "ON/OFF if possible (checkbox checked, aria-checked, etc.), and return ONLY JSON "
            "in the specified schema.\n\n"
            "Prefer mode='selector' if a stable CSS or role-based selector can be derived from "
            "DOM_OUTLINE; fall back to coordinates otherwise."
        )

        user_prompt_parts = [
            f"Setting label to find: '{setting_label}'",
            f"Target state: {'enabled' if enable else 'disabled'}",
        ]
        if description:
            user_prompt_parts.append(f"Context: {description}")

        user_prompt_parts.extend([
            "\nDOM_TEXT_MAP_START",
            DOM_TEXT_MAP,
            "DOM_TEXT_MAP_END",
            "\nDOM_OUTLINE_START",
            DOM_OUTLINE,
            "DOM_OUTLINE_END",
            "\n\nReturn ONLY valid JSON in this exact schema:",
            '{\n'
            '  "mode": "selector" | "coordinates",\n'
            '  "selector": "<CSS or text selector or empty>",\n'
            '  "x": <number or null>,\n'
            '  "y": <number or null>,\n'
            '  "previous_state": "enabled" | "disabled" | "unknown",\n'
            '  "reason": "<short explanation>"\n'
            '}'
        ])

        user_prompt = "\n".join(user_prompt_parts)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
            max_output_tokens=800
        )

        # c) Call Gemini
        print("   🤖 Calling Gemini API...")
        gemini_response = None
        last_error = None
        for attempt in range(3):
            try:
                client = genai.Client(api_key=api_key)
                gemini_response = client.models.generate_content(
                    model='gemini-2.5-pro',
                    contents=[Content(role="user", parts=[
                        Part(text=user_prompt),
                        Part.from_bytes(data=screenshot_bytes, mime_type="image/png")
                    ])],
                    config=config
                )
                # Verify we got a response
                if gemini_response is None:
                    raise ValueError("Gemini returned None response")
                break
            except Exception as e:
                last_error = e
                print(f"   ⚠️  Attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    result["gemini_reason"] = f"Gemini call failed after 3 attempts: {last_error}"
                    return result
                time.sleep(0.6 + attempt * 0.6)
        
        if gemini_response is None:
            result["gemini_reason"] = f"Gemini returned None response. Last error: {last_error}"
            return result

        # Extract text from response
        response_text = ""
        try:
            # Check for safety filters first
            if hasattr(gemini_response, "candidates") and gemini_response.candidates:
                first_candidate = gemini_response.candidates[0]
                
                # Check for finish_reason (safety filters)
                finish_reason = getattr(first_candidate, "finish_reason", None)
                if finish_reason and finish_reason != "STOP":
                    safety_ratings = getattr(first_candidate, "safety_ratings", None) or []
                    safety_info = ", ".join([f"{r.category}:{r.probability}" for r in safety_ratings if hasattr(r, "category")])
                    result["gemini_reason"] = f"Gemini response blocked (finish_reason: {finish_reason}, safety: {safety_info})"
                    return result
                
                # Extract content
                content = getattr(first_candidate, "content", None)
                if content:
                    parts = getattr(content, "parts", None) or []
                    for part in parts:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            response_text += part_text
                
                # Fallback: try direct text attribute
                if not response_text:
                    cand_text = getattr(first_candidate, "text", None)
                    if isinstance(cand_text, str):
                        response_text = cand_text
            
            # If still empty, try alternative extraction methods
            if not response_text:
                # Try accessing response directly
                if hasattr(gemini_response, "text"):
                    response_text = gemini_response.text
                elif hasattr(gemini_response, "candidates") and gemini_response.candidates:
                    # Last resort: try to stringify the response for debugging
                    print(f"   ⚠️  Debug: Response structure: {type(gemini_response)}")
                    print(f"   ⚠️  Debug: Candidates count: {len(gemini_response.candidates) if gemini_response.candidates else 0}")
                    if gemini_response.candidates:
                        print(f"   ⚠️  Debug: First candidate type: {type(gemini_response.candidates[0])}")
                        print(f"   ⚠️  Debug: First candidate attrs: {dir(gemini_response.candidates[0])}")
                        
        except Exception as e:
            import traceback
            print(f"   ⚠️  Debug: Exception extracting response: {e}")
            print(f"   ⚠️  Debug: Traceback: {traceback.format_exc()}")
            result["gemini_reason"] = f"Failed to extract response text: {e}"
            return result

        if not response_text:
            # Add more debugging info
            print(f"   ⚠️  Debug: Response object type: {type(gemini_response)}")
            print(f"   ⚠️  Debug: Response has candidates: {hasattr(gemini_response, 'candidates')}")
            if hasattr(gemini_response, 'candidates'):
                print(f"   ⚠️  Debug: Candidates: {gemini_response.candidates}")
            result["gemini_reason"] = "Empty response from Gemini - check API key and model availability"
            return result

        # Parse JSON response
        try:
            # Try to extract JSON from response (handle markdown code blocks)
            json_text = response_text.strip()
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0].strip()
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0].strip()
            
            gemini_data = json.loads(json_text)
        except Exception as e:
            result["gemini_reason"] = f"Failed to parse JSON from response: {e}. Response: {response_text[:200]}"
            return result

        mode = gemini_data.get("mode", "none")
        selector = gemini_data.get("selector", "").strip()
        x = gemini_data.get("x")
        y = gemini_data.get("y")
        previous_state_str = gemini_data.get("previous_state", "unknown")
        reason = gemini_data.get("reason", "")

        result["previous_state"] = previous_state_str
        result["selection_mode"] = mode
        result["gemini_reason"] = reason

        print(f"   ✅ Gemini found element (mode: {mode}, state: {previous_state_str})")

        # d) Execute based on mode
        if mode == "selector" and selector:
            try:
                loc = page.locator(selector).first
                if loc.count() == 0:
                    result["gemini_reason"] = f"Selector '{selector}' found no elements"
                    return result

                loc.scroll_into_view_if_needed()
                time.sleep(0.3)

                # Determine current state
                current_state = "unknown"
                tag = None
                input_type = None
                try:
                    tag = loc.evaluate("el => el.tagName.toLowerCase()")
                    input_type = loc.get_attribute("type")
                    if tag == "input" and input_type == "checkbox":
                        current_state = "enabled" if loc.is_checked() else "disabled"
                    else:
                        aria_checked = loc.get_attribute("aria-checked")
                        if aria_checked == "true":
                            current_state = "enabled"
                        elif aria_checked == "false":
                            current_state = "disabled"
                except Exception:
                    pass

                # Use Gemini's inferred state if we couldn't determine it
                if current_state == "unknown":
                    current_state = previous_state_str

                result["previous_state"] = current_state

                # Check if toggle is needed
                desired_state = "enabled" if enable else "disabled"
                if current_state != desired_state:
                    loc.click(timeout=5000)
                    time.sleep(0.5)

                    # Re-check state after click
                    try:
                        if tag == "input" and input_type == "checkbox":
                            new_state = "enabled" if loc.is_checked() else "disabled"
                        else:
                            aria_checked = loc.get_attribute("aria-checked")
                            if aria_checked == "true":
                                new_state = "enabled"
                            elif aria_checked == "false":
                                new_state = "disabled"
                            else:
                                new_state = "unknown"
                        result["new_state"] = new_state
                    except Exception:
                        result["new_state"] = "unknown"
                else:
                    result["new_state"] = current_state

                result["status"] = "success"

            except Exception as e:
                result["gemini_reason"] = f"Failed to execute selector '{selector}': {e}"
                return result

        elif mode == "coordinates" and x is not None and y is not None:
            try:
                page.mouse.click(int(x), int(y))
                time.sleep(0.5)

                # Try to infer new state by re-locating element
                # This is best-effort; coordinates mode is less reliable
                result["new_state"] = "unknown"
                result["status"] = "success"
            except Exception as e:
                result["gemini_reason"] = f"Failed to click coordinates ({x}, {y}): {e}"
                return result
        else:
            result["gemini_reason"] = f"Invalid mode '{mode}' or missing selector/coordinates"
            return result

        # e) Save button handling
        if save_after:
            # Only skip Save if we're confident the state didn't change
            should_skip_save = (
                result["previous_state"] in {"enabled", "disabled"} and
                result["new_state"] in {"enabled", "disabled"} and
                result["previous_state"] == result["new_state"]
            )

            if not should_skip_save:
                time.sleep(1)  # Wait for page to update after toggle
                result["save_clicked"] = click_save_if_present(page, timeout=5000)
                if result["save_clicked"]:
                    print("   💾 Save button: ✅ clicked")
                else:
                    print("   💾 Save button: ⚠️  not found")
            else:
                print(f"   💾 Save button: ℹ️  skipped (state unchanged: {result['previous_state']} → {result['new_state']})")

        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        result["gemini_reason"] = f"Exception: {str(e)}"
        return result


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
            
            result = {
                "status": "success",
                "requested_url": url,
                "actual_url": current_url,
                "title": title,
                "logged_in": self.logged_in,
                "timestamp": time.time()
            }
            
            return result
        except Exception as e:
            return {
                "status": "error",
                "url": url,
                "error": str(e),
                "timestamp": time.time()
            }
    
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
    
    def _call_gemini_for_element_location_with_prompt(self, current_screenshot_path: str, reference_screenshot_path: str, text_elements_json: str, prompt: str) -> Dict[str, Any]:
        """
        Helper function to call Gemini API to locate an element with a custom prompt.
        
        Args:
            current_screenshot_path: Path to current page screenshot
            reference_screenshot_path: Path to reference screenshot
            text_elements_json: JSON string of text elements from DOM
            prompt: Custom prompt text for Gemini
            
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
        
        return toggle_setting_with_gemini(
            page=self.page,
            setting_label="Allow users to send text feedback",
            enable=enable,
            description="Zoom general settings page",
            save_after=True
        )
    
    def close_browser(self):
        """Close the browser."""
        if self.browser:
            self.browser.close()
        if hasattr(self, 'playwright'):
            self.playwright.stop()
        print("✅ Browser closed")
    
    # Removed methods: list_ad_settings, list_navigation_links, navigate_by_link_text, 
    # _display_links_after_navigation, get_current_settings, reload_with_new_settings
    # These were removed to keep only setting-changing functionality.


# Removed prompt_for_settings_switch - not needed for setting changes


def main():
    """Main function to demonstrate URL navigation."""
    parser = argparse.ArgumentParser(
        description="Navigate to URLs from JSON data files with optional targeting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s zoom --url "https://zoom.us/profile/setting?tab=general" --setting "Allow users to send text feedback" --state enable
  %(prog)s facebook --url "https://accountscenter.facebook.com/ads" --change-ad-setting "Ad personalization" disable
        """
    )
    parser.add_argument("service", nargs="?", default=None,
                        help="Service name (facebook, zoom, linkedin). Auto-generates json_data/{service}.json")
    parser.add_argument("--json-file",
                        help="Path to JSON file containing URL data (overrides service name if provided)")
    parser.add_argument("--url", help="Navigate directly to this URL (takes precedence).")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--no-headless", action="store_true", help="Force non-headless mode.")
    parser.add_argument("--auto-login", action="store_true", help="Enable auto-login when login page detected.")
    parser.add_argument("--no-auto-login", action="store_true", help="Disable auto-login.")
    parser.add_argument("--use-persistent-profile", action="store_true", help="Use a persistent Chromium profile.")
    parser.add_argument("--profile-dir", help="Directory for persistent profile (used with --use-persistent-profile).")
    parser.add_argument("--storage-state-file", default=None,
                        help="Path to Playwright storage state JSON. If not provided, auto-generated from service name.")
    parser.add_argument("--change-ad-setting", nargs=2, metavar=("SETTING_NAME", "STATE"),
                        help="Change an ad setting. STATE should be 'enable' or 'disable'. Example: --change-ad-setting 'Ad personalization' disable")
    parser.add_argument("--change-birthday", nargs=3, metavar=("MONTH", "DAY", "YEAR"),
                        help="Change birthday. Will auto-navigate to Personal Details if needed. Example: facebook --find 'Personal Details' --change-birthday 5 15 1990")
    parser.add_argument("--change-toggle", nargs=2, metavar=("TOGGLE_LABEL", "STATE"),
                        help="Change a toggle/switch. STATE should be 'enable' or 'disable'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --change-toggle 'Enable notifications' disable")
    parser.add_argument("--check-checkbox", nargs=2, metavar=("CHECKBOX_LABEL", "STATE"),
                        help="Check or uncheck a checkbox by label. STATE should be 'check' or 'uncheck'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --check-checkbox 'Allow users to send text feedback' check")
    parser.add_argument("--physical-toggle", nargs=2, metavar=("LABEL", "STATE"),
                        help="Physically click a toggle/checkbox using mouse API. STATE should be 'enable' or 'disable'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --physical-toggle 'Allow users to send text feedback' enable")
    parser.add_argument("--gemini-toggle-text-feedback", metavar="STATE",
                        help="Use Gemini AI to locate and toggle 'Allow users to send text feedback' setting. STATE should be 'enable' or 'disable'. Example: zoom --url 'https://zoom.us/profile/setting?tab=general' --gemini-toggle-text-feedback enable")
    parser.add_argument("--setting", metavar="SETTING_LABEL",
                        help="Generic setting label to toggle using Gemini AI. Use with --state. Example: --setting 'Allow users to send text feedback' --state enable")
    parser.add_argument("--state", metavar="STATE", choices=["enable", "disable", "on", "off", "check", "uncheck"],
                        help="Target state for --setting. Should be 'enable' or 'disable'. Example: --setting 'My Setting' --state enable")
    parser.add_argument("--description", metavar="DESCRIPTION",
                        help="Optional description/hint for Gemini when using --setting. Example: --setting 'My Setting' --state enable --description 'Zoom general settings page'")
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
        
        # Start browser
        print("\n🚀 Starting browser...")
        navigator.start_browser()
        
        # Navigate to URL if provided
        if args.url:
            print(f"\n🌐 Navigating to: {args.url}")
            result = navigator.navigate_to_url(args.url, auto_login=auto_login_flag)
            if result["status"] == "success":
                print(f"   ✅ Successfully navigated to: {result['title']}")
                print(f"   📍 Current URL: {result['actual_url']}")
            else:
                print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
        
        # Handle setting changes
        if args.change_ad_setting:
            setting_name, state_str = args.change_ad_setting
            enable = state_str.lower() in ["enable", "on", "true", "1", "yes"]
            print(f"\n🔧 Changing ad setting: '{setting_name}' to {'enabled' if enable else 'disabled'}")
            result = navigator.change_ad_setting(setting_name, enable=enable)
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
        
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
        
        if args.setting:
            if not args.state:
                print("❌ Error: --setting requires --state to be specified")
                print("   Example: --setting 'My Setting' --state enable")
            else:
                enable = args.state.lower() in ["enable", "on", "check"]
                print(f"\n🤖 Using Gemini to toggle '{args.setting}' to {'enabled' if enable else 'disabled'}")
                result = toggle_setting_with_gemini(
                    page=navigator.page,
                    setting_label=args.setting,
                    enable=enable,
                    description=args.description,
                    save_after=True
                )
                if result["status"] == "success":
                    print(f"   ✅ Success!")
                    print(f"   📊 Target: {result.get('target', 'N/A')}")
                    print(f"   📊 Previous state: {result.get('previous_state', 'unknown')}")
                    print(f"   📊 New state: {result.get('new_state', 'unknown')}")
                    print(f"   📊 Selection mode: {result.get('selection_mode', 'none')}")
                    if result.get("gemini_reason"):
                        print(f"   💡 Gemini reason: {result.get('gemini_reason')}")
                    if result.get("save_clicked") is not None:
                        if result.get("save_clicked"):
                            print(f"   💾 Save button: ✅ clicked")
                        else:
                            print(f"   💾 Save button: ⚠️  not found")
                else:
                    print(f"   ❌ Error: {result.get('gemini_reason', 'Unknown error')}")
                    print(f"   📊 Selection mode: {result.get('selection_mode', 'none')}")
        
        if args.change_birthday:
            month, day, year = args.change_birthday
            print(f"\n🎂 Changing birthday to: {month}/{day}/{year}")
            result = navigator.change_birthday(int(month), int(day), int(year))
            if result["status"] == "success":
                print(f"   ✅ {result['message']}")
            else:
                print(f"   ❌ {result.get('message', 'Unknown error')}")
        
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
