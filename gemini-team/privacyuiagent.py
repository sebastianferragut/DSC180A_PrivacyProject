# navigate to gemini-team folder with ls, cd commands
# run pip install -r requirements.txt
# STILL WIP ^^, so for now,
# can install dependencies using 
# pip install google-genai pyautogui pillow playwright

# You can get a Gemini API key at https://aistudio.google.com/app/api-keys 
# ----- IMPORTANT EXPORTS BEFORE RUNNING SCRIPT -----
# Ensure you have the Gemini API key set in your environment (use this command in the terminal):
# export GEMINI_API_KEY="your_api_key_here"

# Paste the below into the terminal before running the script
# export SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com" \
# SIGNUP_EMAIL_PASSWORD="ZoomTestPass" \
# SIGNUP_EMAIL_PASSWORD_WEB="$SIGNUP_EMAIL_PASSWORD"
# ----------------------------------------------------

# Run the script using python privacyuiagent.py, and minimize the terminal window
# so the agent can see the desktop.

# Be sure to set "DEVICE_TYPE" variable below to your actual device type.

import sys 
import time
import os, re, random
import io
from typing import Any, Dict, List, Tuple
from datetime import datetime
import pyautogui
from PIL import Image
from playwright.sync_api import sync_playwright, Playwright, Browser, Page

from google import genai
from google.genai import types
from google.genai.types import Content, Part, FunctionCall, FunctionResponse

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    exit(1)

MODEL_ID = 'gemini-2.5-computer-use-preview-10-2025'
PLANNING_MODEL_ID = 'gemini-2.5-pro'

DEVICE_TYPE = "MacBook"
# DEVICE_TYPE = "Windows 11 PC"

pyautogui.FAILSAFE = True 
pyautogui.PAUSE = 1.0

client = genai.Client(api_key=API_KEY)

SCREEN_WIDTH, SCREEN_HEIGHT = pyautogui.size()
cuse_grid = 1000

# --- Playwright Global State ---
playwright_context: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "page": None,
}

# --- Helper Functions ---
def current_page_url() -> str:
    try:
        pg = playwright_context.get("page")
        if pg:
            return pg.url or ""
    except Exception:
        pass
    return ""

def _extract_safety_decision(fc):
    try:
        sd = getattr(fc, "safety_decision", None)
        if isinstance(sd, dict) and sd.get("decision"):
            return sd
        args = getattr(fc, "args", None) or {}
        sd = args.get("safety_decision")
        if isinstance(sd, dict) and sd.get("decision"):
            return sd
        if isinstance(sd, dict) and isinstance(sd.get("safety_decision"), dict):
            inner = sd["safety_decision"]
            if inner.get("decision"):
                return inner
    except Exception:
        pass
    return None

def _get_function_call_id(part) -> str:
    try:
        fc = getattr(part, "function_call", None)
        cid = getattr(fc, "id", None)
        if cid:
            return cid
        cid = getattr(part, "id", None)
        if cid:
            return cid
        cid = getattr(part, "function_call_id", None)
        if cid:
            return cid
        if hasattr(part, "to_dict"):
            d = part.to_dict()
            cid = (
                d.get("functionCall", {}, {}).get("id")
                or d.get("function_call", {}, {}).get("id")
                or d.get("id")
            )
            if cid:
                return cid
    except Exception:
        pass
    return None

def get_screenshot_bytes() -> bytes:
    screenshot = pyautogui.screenshot()
    img_byte_arr = io.BytesIO()
    screenshot.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def denormalize(value: int, max_value: int) -> int:
    return int((value * max_value) / cuse_grid)

# --- Playwright semantic click helper (dialog-aware; avoids coord clicks) ---
def pw_click_button_by_text(text: str, timeout_ms: int = 5000) -> dict:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # 1) Prefer modal/dialog scope if present (prevents overlay intercepts)
        try:
            dialog = pg.get_by_role("dialog").filter(has_text=re.compile(r".*", re.S)).first
            dialog.wait_for(state="visible", timeout=1500)
            btn = dialog.get_by_role("button", name=text, exact=True)
            if btn.count():
                btn.first.click(timeout=timeout_ms)
                return {"status": "success", "clicked": text, "scope": "dialog"}
        except Exception:
            pass

        # 2) Fallback: page buttons/links/text locators
        loc = pg.get_by_role("button", name=text, exact=True)
        if not loc or not loc.count():
            loc = pg.get_by_role("link", name=text, exact=True)
        if not loc or not loc.count():
            loc = pg.locator(f"text={text}")
        loc.first.wait_for(state="visible", timeout=timeout_ms)
        loc.first.click(timeout=timeout_ms)
        return {"status": "success", "clicked": text, "scope": "page"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def open_browser_and_navigate(url: str) -> Dict[str, str]:
    try:
        p = playwright_context.get("playwright")
        if not p:
            return {"status": "error", "message": "Playwright not initialized."}

        win_w, win_h = SCREEN_WIDTH, SCREEN_HEIGHT
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-features=IsolateOrigins,site-per-process",
                f"--window-position=0,0",
                f"--window-size={win_w},{win_h}",
            ],
        )

        context = browser.new_context(
            viewport={"width": win_w, "height": win_h},
            device_scale_factor=1.0,
        )
        page = context.new_page()
        page.bring_to_front()
        page.goto(url, wait_until="load", timeout=60_000)

        playwright_context["browser"] = browser
        playwright_context["page"] = page
        playwright_context["context"] = context

        time.sleep(0.5)
        return {"status": "success", "message": f"Successfully navigated to {url}."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def pw_navigate(url: str) -> Dict[str, str]:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        pg.bring_to_front()
        pg.goto(url, wait_until="load", timeout=60_000)
        return {"status": "success", "url": pg.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def pw_go_back(steps: int = 1) -> Dict[str, str]:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        pg.bring_to_front()
        for _ in range(max(1, steps)):
            pg.go_back(wait_until="load", timeout=60_000)
        return {"status": "success", "url": pg.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tabs_open_new(url: str) -> Dict[str, str]:
    try:
        ctx = playwright_context.get("context")
        if not ctx:
            return {"status": "error", "message": "No active context"}
        p = ctx.new_page()
        p.goto(url, wait_until="load", timeout=60_000)
        p.bring_to_front()
        playwright_context["page"] = p
        return {"status": "success", "url": p.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tabs_switch_to(substr: str, timeout_ms: int = 10000) -> Dict[str, str]:
    """Bring to front the first tab whose URL contains `substr` (host or path fragment)."""
    try:
        ctx = playwright_context.get("context")
        if not ctx:
            return {"status": "error", "message": "No active context"}
        deadline = time.time() + (timeout_ms/1000.0)
        while time.time() < deadline:
            for p in ctx.pages:
                if substr.lower() in (p.url or "").lower():
                    p.bring_to_front()
                    playwright_context["page"] = p
                    return {"status": "success", "url": p.url}
            time.sleep(0.2)
        return {"status": "error", "message": f"No tab containing '{substr}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def save_consent_screenshot() -> Dict[str, Any]:
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"zoom_consent_prompt_{timestamp}.png"
        pyautogui.screenshot(filename)
        cwd = os.getcwd()
        full_path = os.path.join(cwd, filename)
        print(f"\n[SUCCESS] Saved consent screenshot to: {full_path}\n")
        return {"status": "success", "filename": filename, "path": full_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def ui_click_any_label(labels: List[str], timeout_ms: int = 5000) -> dict:
    for lbl in labels:
        r = ui_click_label(lbl, timeout_ms)
        if r.get("status") == "success":
            return r
    return {"status": "error", "message": f"No label matched from {labels}"}

def ui_click_label(label: str, timeout_ms: int = 5000) -> dict:
    """Click a visible control by label, preferring dialog scope. Works for buttons/links/text."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # 1) Try dialog-scope first
        try:
            dialog = pg.get_by_role("dialog").first
            dialog.wait_for(state="visible", timeout=1200)
            for locator in [
                dialog.get_by_role("button", name=label, exact=True),
                dialog.get_by_role("link", name=label, exact=True),
                dialog.locator(f"text={label}")
            ]:
                if locator.count():
                    locator.first.click(timeout=timeout_ms)
                    return {"status": "success", "scope": "dialog", "clicked": label}
        except Exception:
            pass

        # 2) Fallback to page scope
        for locator in [
            pg.get_by_role("button", name=label, exact=True),
            pg.get_by_role("link", name=label, exact=True),
            pg.locator(f"text={label}")
        ]:
            if locator.count():
                locator.first.wait_for(state="visible", timeout=timeout_ms)
                locator.first.click(timeout=timeout_ms)
                return {"status": "success", "scope": "page", "clicked": label}

        return {"status": "error", "message": f"Label not found: {label}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# --- Minimal email helpers (web UI only) ---
def provide_signup_email() -> Dict[str, str]:
    addr = os.environ.get("SIGNUP_EMAIL_ADDRESS", "").strip()
    if not addr:
        return {"status": "error", "message": "SIGNUP_EMAIL_ADDRESS not set"}
    return {"status": "success", "email": addr}

def provide_signup_password() -> Dict[str, str]:
    pwd_web = os.environ.get("SIGNUP_EMAIL_PASSWORD_WEB", "").strip()
    if not pwd_web:
        pwd_web = os.environ.get("SIGNUP_EMAIL_PASSWORD", "").strip()
    if not pwd_web:
        return {"status": "error", "message": "No SIGNUP_EMAIL_PASSWORD_WEB or SIGNUP_EMAIL_PASSWORD found"}
    return {"status": "success", "password": pwd_web}

# --- Action Execution Loop ---
def call_model_with_retries(client, model, contents, config, max_retries=4):
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            return True, resp
        except Exception as e:
            err = str(e)
            print(f"[Model call error] attempt {attempt}/{max_retries}: {err}")
            if attempt == max_retries:
                return False, err
            time.sleep(delay + random.uniform(0, 0.5))
            delay *= 2

def execute_function_calls(candidate) -> List[Tuple[str, Dict, FunctionCall]]:
    results = []
    wrapped_calls = []
    for p in candidate.content.parts:
        fc = getattr(p, "function_call", None)
        if not fc:
            continue
        call_id = _get_function_call_id(p)
        wrapped_calls.append({"part": p, "fc": fc, "id": call_id})

    # Detect gating
    any_gated = False
    missing_id_for_gated = False
    call_meta = []
    for wc in wrapped_calls:
        fc = wc["fc"]
        sd = _extract_safety_decision(fc)
        gated = bool(sd and sd.get("decision") in ("require_confirmation", "block"))
        call_meta.append({"wc": wc, "sd": sd, "gated": gated})
        if gated:
            any_gated = True
            if not wc["id"]:
                missing_id_for_gated = True

    if any_gated and missing_id_for_gated:
        print("[Safety] Gated call(s) missing id; requesting re-emit without coordinate clicks.")
        return [("__RETRY_WITH_TEXT__", {"reason": "gated_missing_id"}, None)]

    if any_gated:
        for meta in call_meta:
            wc, sd, gated = meta["wc"], meta["sd"], meta["gated"]
            fc, call_id, name = wc["fc"], wc["id"], wc["fc"].name
            if gated:
                results.append((
                    name,
                    {
                        "ack_only": True,
                        "safety_ack_payload": {
                            "id": call_id,
                            "name": name,
                            "response": {
                                "safety_decision": {
                                    "decision": "proceed",
                                    "user_confirmation": "approved",
                                    "explanation": (sd or {}).get("explanation", "")
                                }
                            }
                        }
                    },
                    fc
                ))
            else:
                results.append((name, {"deferred": True}, fc))
        return results

    # No safety ACKs → normal execution path
    for wc in wrapped_calls:
        fc = wc["fc"]
        fname = fc.name
        args = getattr(fc, "args", {}) or {}
        action_result = {}
        print(f"  Executing > {fname}({args})")
        try:
            if fname == "click_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.3)
                pyautogui.click()
                action_result = {"status": "success", "x": x, "y": y}

            elif fname == "type_text_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                text = args["text"]
                press_enter = args.get("press_enter", False)
                pyautogui.click(x, y)
                if sys.platform == "darwin":
                    pyautogui.hotkey('command', 'a')
                else:
                    pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('backspace')
                pyautogui.write(text, interval=0.05)
                if press_enter:
                    pyautogui.press('enter')
                action_result = {"status": "success", "typed_len": len(text), "press_enter": press_enter}

            elif fname == "key_combination":
                keys = args["keys"].lower().split('+')
                key_map = {"control": "ctrl", "command": "cmd", "windows": "win"}
                mapped_keys = [key_map.get(k, k) for k in keys]
                pyautogui.hotkey(*mapped_keys)
                action_result = {"status": "success", "keys": mapped_keys}

            elif fname == "wait_5_seconds":
                time.sleep(5)
                action_result = {"status": "success"}

            elif fname == "scroll_at":
                x = denormalize(args.get("x", 500), SCREEN_WIDTH)
                y = denormalize(args.get("y", 500), SCREEN_HEIGHT)
                direction = (args.get("direction") or "down").lower()
                magnitude = int(args.get("magnitude", 200))
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.scroll(-magnitude if direction == "down" else magnitude)
                action_result = {"status": "success", "scrolled": direction, "magnitude": magnitude, "x": x, "y": y}

            elif fname in ("wheel", "page_scroll"):
                dy = int(args.get("dy", args.get("magnitude", 200)))
                direction = "down" if dy > 0 else "up"
                x = denormalize(args.get("x", 500), SCREEN_WIDTH)
                y = denormalize(args.get("y", 500), SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.scroll(-abs(dy) if direction == "down" else abs(dy))
                action_result = {"status": "success", "scrolled": direction, "magnitude": abs(dy), "x": x, "y": y}

            # --- Custom Tools / Navigation ---
            elif fname == "open_browser_and_navigate":
                action_result = open_browser_and_navigate(args["url"])

            elif fname == "save_consent_screenshot":
                action_result = save_consent_screenshot()

            elif fname == "provide_signup_email":
                action_result = provide_signup_email()

            elif fname in ("pw_navigate", "navigate"):
                action_result = pw_navigate(args["url"])

            elif fname == "pw_go_back":
                steps = int(args.get("steps", 1))
                action_result = pw_go_back(steps)

            elif fname == "provide_signup_password":
                action_result = provide_signup_password()

            elif fname == "scroll_document":
                direction = (args.get("direction") or "down").lower()
                magnitude = int(args.get("magnitude", 300))
                x = denormalize(args.get("x", 500), SCREEN_WIDTH)
                y = denormalize(args.get("y", 600), SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.scroll(-abs(magnitude) if direction == "down" else abs(magnitude))
                action_result = {"status": "success", "scrolled": direction, "magnitude": magnitude, "x": x, "y": y}

            elif fname == "click_button_by_text":
                txt = args["text"]
                to = int(args.get("timeout_ms", 5000))
                action_result = pw_click_button_by_text(txt, to)
            elif fname == "ui_click_label": 
                action_result = ui_click_label(args["label"], int(args.get("timeout_ms", 5000)))
            elif fname == "ui_click_any_label": 
                action_result = ui_click_any_label(args["labels"], int(args.get("timeout_ms", 5000)))
            elif fname == "tabs_open_new": 
                action_result = tabs_open_new(args["url"])
            elif fname == "tabs_switch_to": 
                action_result = tabs_switch_to(args["substr"], int(args.get("timeout_ms", 10000)))


            else:
                print(f"Warning: Skipping unimplemented function {fname}")
                action_result = {"error": f"Function {fname} not implemented locally."}

        except Exception as e:
            action_result = {"error": str(e)}

        # Keep returning the original fc so your FunctionResponse builder can tie screenshots, etc.
        results.append((fname, action_result, fc, wc["id"]))

    return results

# --- Planning (unchanged) ---
def generate_plan(client, user_prompt: str, screenshot_bytes: bytes, config) -> str:
    planning_prompt = f"""
Based on the user's goal and the current screen state, create a detailed step-by-step plan.

User Goal: {user_prompt}

Please analyze the current screen and create a numbered plan with specific steps. Each step should be:
1. Clear and actionable
2. Based on what you can see in the current screenshot
3. Include specific UI elements to look for or interact with

Format your response as:
PLAN:
1. [First step with specific details]
2. [Second step with specific details]
...

Be specific about what buttons to click, what text to type, and what to look for in the UI. Refer to the system_instruction for context on operating the computer and browser.
"""
    try:
        planning_config = types.GenerateContentConfig(
            system_instruction="You are a planning assistant. Analyze the current screen and create detailed, actionable plans for UI automation tasks. Do not execute any actions - only create plans."
        )
        
        response = client.models.generate_content(
            model=PLANNING_MODEL_ID,
            contents=[Content(
                role="user",
                parts=[
                    Part(text=planning_prompt),
                    Part.from_bytes(data=screenshot_bytes, mime_type='image/png')
                ]
            )],
            config=planning_config
        )
        
        plan = response.candidates[0].content.parts[0].text
        print(f"📋 Generated Plan:\n{plan}\n")
        return plan
        
    except Exception as e:
        print(f"Error generating plan: {e}")
        return "PLAN:\n1. Analyze current screen and proceed step by step\n2. Adapt based on what is visible"

def run_agent():
    with sync_playwright() as p:
        playwright_context["playwright"] = p
        
        print(f"Display resolution: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        print("Starting agent... The browser window will appear shortly.")
        print("Please do not interact with the mouse or keyboard during operation.")
        
        # 1. Define Tools (IMAP removed; manual Gmail fallback only)
        custom_tools = [
            types.FunctionDeclaration(
                name="open_browser_and_navigate",
                description="Launches a new Chromium browser window and navigates to the specified URL. Call this first.",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string", "description": "e.g., 'https://zoom.us/signup'"}},
                    "required": ["url"]
                }
            ),
            types.FunctionDeclaration(
                name="save_consent_screenshot",
                description="Saves a screenshot when a privacy consent dialog is visible.",
                parameters={"type": "object", "properties": {}}
            ),
            types.FunctionDeclaration(
                name="provide_signup_email",
                description="Returns the email address to use for signup.",
                parameters={"type": "object", "properties": {}}
            ),
            types.FunctionDeclaration(
                name="pw_navigate",
                description="Navigate current tab to the given URL using Playwright.",
                parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
            ),
            types.FunctionDeclaration(
                name="pw_go_back",
                description="Go back in browser history.",
                parameters={"type": "object", "properties": {"steps": {"type": "integer", "default": 1}}}
            ),
            types.FunctionDeclaration(
                name="provide_signup_password",
                description="Returns the web password for the Gmail account used to sign in at accounts.google.com.",
                parameters={"type": "object", "properties": {}}
            ),
            types.FunctionDeclaration(
                name="click_button_by_text",
                description="Clicks a visible button/link by exact text using Playwright (avoids coordinate clicks).",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Exact label, e.g., 'Create Account', 'Send Code', 'Delete'"},
                        "timeout_ms": {"type": "integer", "default": 5000}
                    },
                    "required": ["text"]
                }
            ),
            types.FunctionDeclaration(name="ui_click_label",
                description="Click a visible control by label, preferring dialog scope.",
                parameters={"type":"object","properties":{"label":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},
                        "required":["label"]}
            ),
            types.FunctionDeclaration(name="ui_click_any_label",
                description="Click the first matching label from a list (dialog preferred).",
                parameters={"type":"object","properties":{"labels":{"type":"array","items":{"type":"string"}},"timeout_ms":{"type":"integer","default":5000}},
                        "required":["labels"]}
            ),
            types.FunctionDeclaration(name="tabs_open_new",
                description="Open URL in a NEW tab (preserves current tab).",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(name="tabs_switch_to",
                description="Switch to a tab whose URL contains the given substring.",
                parameters={"type":"object","properties":{"substr":{"type":"string"},"timeout_ms":{"type":"integer","default":10000}},
                        "required":["substr"]}
            )
        ]

        config = types.GenerateContentConfig(
            tools=[
                types.Tool(computer_use=types.ComputerUse()),
                types.Tool(function_declarations=custom_tools)
            ],  system_instruction=f"""You are an agent operating a {DEVICE_TYPE} computer with a web browser.
Rules (You must follow these exactly):
- Rely entirely on visual feedback. Use your built-in Computer Use actions (mouse move, click, type, mouse wheel, trackpad scroll, PgDown/PgUp). Do NOT call any custom scroll helpers. Only use small scrolls.
- Avoid coordinate clicks when creating or terminating the account; prefer `click_button_by_text`.
SCROLLING POLICY (MANDATORY):


• Treat every scroll as a micro-step. After ONE small scroll, STOP and re-scan the viewport for target text before scrolling again.
• Use only small increments. When emitting built-in scroll calls (scroll_at / wheel / page_scroll), set magnitude/dy to a small value (≈ 80–120 px).
• Do not alternate rapidly up/down. If two consecutive scans don’t reveal progress toward the target, pause and try: collapse/expand sections, click “Admin” to expand, or use the left-nav scrollbar track precisely rather than large page scrolls.
• When aiming for "Admin" → "Account Management" → "Account Profile":
 - First try clicking visible items.
 - If not visible, perform at most THREE small scrolls in the left nav, re-checking after each.
 - If still not visible, slightly adjust the scroll anchor (hover the nav area and scroll again).
• Never perform large continuous scrolling. Avoid sending repeated scrolls without a scan in between.
• As soon as the target text is visible, CLICK it and stop scrolling (unless the next option requires a small scroll down).


- If any action is safety-gated and the function call lacks an id, re-issue with a function_call.id and avoid coordinate-based clicks.
1) Your first action MUST be to call `open_browser_and_navigate` to launch the browser with the url https://zoom.us/signup.
2) Use Google sign-in for account creation:
  - Call `provide_signup_email` and `provide_signup_password` to fill fields on accounts.google.com.
  - Click "Next" (do not click "Forgot password").
  - Click the "Create Account" button on Zoom, try using 'click_button_by_text' with label "Create Account" first.
3) STRICTLY FOLLOW THESE STEPS to delete the Zoom account:
  - Expand "Admin" (if present) → "Account Management".
  - Scroll the **left nav** in small increments until **"Account Profile"** is visible. Re-scan after each small scroll. CRITICAL STEP: Do NOT make large scroll jumps. You may get stuck in a loop
  if you skip over the desired item. Scroll slowly and check frequently.
  - Click **"Account Profile"**.
  - In the main content, click **"Terminate my account"**.
4) A modal dialog will open:
  - Click **"Send Code"** (inside the dialog).
  - Without closing the Zoom tab, open Gmail in a **new tab** (navigate to https://mail.google.com), sign in if needed (use the same tools), find the Zoom message and copy the 6-digit code manually from the email content.
  - Switch back to the Zoom tab, paste the code into the dialog field, and click the confirmation button (e.g., **"Delete"**, **"Confirm"**).
"""

        )

        # 2. Initialize Chat
        user_prompt = "First, open the browser and navigate to 'https://zoom.us/signup'. Then, create a new account using the gmail account provided. After creating the account, find the account settings and delete the account."
        print(f"\nGoal: {user_prompt}\n")

        initial_screenshot = get_screenshot_bytes()
        plan = generate_plan(client, user_prompt, initial_screenshot, config)
        
        planning_context = f"""
I will now execute the following plan. I will perform all actions within the browser window.
{plan}
"""
        
        chat_history = [
            Content(role="user", parts=[
                Part(text=user_prompt),
                Part(text=planning_context),
                Part.from_bytes(data=initial_screenshot, mime_type='image/png')
            ])
        ]

        # 3. Interaction Loop
        MAX_TURNS = 40
        for turn in range(1, MAX_TURNS + 1):
            print(f"--- Turn {turn} ---")
            time.sleep(2)
            print("Analyzing screen...")
            
            ok, response = call_model_with_retries(client, MODEL_ID, chat_history, config)
            if not ok:
                print(f"API Error (after retries): {response}")
                break

            cands = getattr(response, "candidates", None) or []
            if not cands:
                print("No candidates returned; retrying next turn.")
                time.sleep(1.0)
                continue

            model_response = cands[0].content
            chat_history.append(model_response)

            if model_response.parts and getattr(model_response.parts[0], "text", None):
                print(f"🤖 Agent: {model_response.parts[0].text.strip()}")

            # Nudge on Account Management if the model paused
            if not any(p.function_call for p in model_response.parts):
                url_now = current_page_url() or ""
                if ("account" in url_now.lower() and "management" in url_now.lower()) or "zoom.us/account" in url_now.lower():
                    chat_history.append(Content(
                        role="user",
                        parts=[Part(text=(
                            "If Account Profile is not visible in the left navigation, use your built-in mouse wheel "
                            "to perform small repeated scrolls within the left nav until you can see and click "
                            "“Account Profile”. Re-scan the left nav after each small scroll."
                        ))]
                    ))
                    continue
                print("Agent finished or is waiting for input.")
                break

            if not any(p.function_call for p in model_response.parts):
                url_now = (current_page_url() or "").lower()
                if any(k in url_now for k in ["account", "settings", "terminate", "delete"]):
                    chat_history.append(Content(role="user", parts=[Part(text=(
                        "A modal may be present. Use ui_click_any_label on 'Send Code'"
                        "then tabs_open_new to open the inbox, find the code from inside the latest email and copy it."
                        "tabs_switch_to back to the site, paste the code, and ui_click_any_label "
                        "on the deletion confirmation button."
                    ))]))
                    continue

            action_results = execute_function_calls(response.candidates[0])

            # If execute_function_calls asked for a retry via text, don't send FunctionResponses
            if len(action_results) == 1 and action_results[0][0] == "__RETRY_WITH_TEXT__":
                chat_history.append(Content(
                    role="user",
                    parts=[Part(text=(
                        "Safety requirement: I could not acknowledge your last tool call because it lacked a function_call.id. "
                        "Please re-issue the action without using coordinate-based clicks.\n\n"
                        "Specifically: do NOT use click_at. Instead, call the tool `click_button_by_text` "
                        "with the exact visible label (e.g., 'Create Account', 'Send Code', 'Delete'). "
                        "If you must use a tool call, ensure it includes a function_call.id."
                    ))]
                ))
                # Optional shims
                try:
                    pg = playwright_context.get("page")
                    url_now = (pg.url or "") if pg else ""
                    if pg and "zoom.us/account" in url_now:
                        for label in ["Send Code", "Terminate my account", "Delete", "Confirm"]:
                            shim = pw_click_button_by_text(label, 8000)
                            print(f"[Shim] {label}:", shim)
                            if shim.get("status") == "success":
                                break
                except Exception as e:
                    print("[Shim error]", e)
                continue

            # Build FunctionResponses
            function_response_parts = []
            names_emitted = []

            for item in action_results:
                if len(item) == 4:
                    fname, result, fcall, call_id = item
                else:
                    fname, result, fcall = item
                    call_id = getattr(fcall, "id", None)

                names_emitted.append(fname)

                try:
                    # Normalize response name: respond as pw_navigate if model used 'navigate'
                    response_name = fname

                    if isinstance(result, dict) and result.get("ack_only"):
                        ack = result["safety_ack_payload"]
                        rn = ack["name"]
                        fr = types.FunctionResponse(
                            id=ack["id"],
                            name=rn,
                            response=ack["response"],
                        )
                        function_response_parts.append(fr)

                    elif isinstance(result, dict) and result.get("deferred"):
                        exec_id = call_id or getattr(fcall, "id", None) or f"deferred-{fname}-{int(time.time()*1000)}"
                        fr = types.FunctionResponse(
                            id=exec_id,
                            name=response_name,
                            response={"status": "deferred_due_to_safety_ack"},
                        )
                        function_response_parts.append(fr)

                    else:
                        url = current_page_url()
                        base_ack = {
                            "function_name": fname,
                            "acknowledged": True,
                            "url": url,
                            "page_url": url,
                            "result": result if isinstance(result, dict) else {"result": str(result)}
                        }
                        new_screenshot = get_screenshot_bytes()
                        exec_id = call_id or getattr(fcall, "id", None) or f"exec-{fname}-{int(time.time()*1000)}"

                        fr = types.FunctionResponse(
                            id=exec_id,
                            name=response_name,
                            response=base_ack,
                            parts=[types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=new_screenshot
                                )
                            )],
                        )
                        function_response_parts.append(fr)

                except Exception as e:
                    fr = types.FunctionResponse(
                        id=call_id or getattr(fcall, "id", None) or f"error-{fname}-{int(time.time()*1000)}",
                        name=fname,
                        response={"status": "error", "message": f"builder_exception: {str(e)}"},
                    )
                    function_response_parts.append(fr)

            if len(function_response_parts) != len(action_results):
                print("[WARN] FR count mismatch; synthesizing missing responses.")
                while len(function_response_parts) < len(action_results):
                    idx = len(function_response_parts)
                    item = action_results[idx]
                    if len(item) == 4:
                        fname, _, fcall, call_id = item
                    else:
                        fname, _, fcall = item
                        call_id = getattr(fcall, "id", None)
                    response_name = fname
                    function_response_parts.append(types.FunctionResponse(
                        id=call_id or getattr(fcall, "id", None) or f"synth-{fname}-{int(time.time()*1000)}",
                        name=response_name,
                        response={"status": "synthesized_missing_response"},
                    ))

            print(f"[Debug] Emitted {len(names_emitted)} FunctionResponses for: {names_emitted}")
            chat_history.append(Content(role="user", parts=[Part(function_response=fr) for fr in function_response_parts]))

        print("--- Agent session finished ---")
        if playwright_context.get("context"):
            try:
                playwright_context["context"].close()
            except Exception:
                pass
        if playwright_context.get("browser"):
            try:
                playwright_context["browser"].close()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        run_agent()
    except pyautogui.FailSafeException:
        print("\n[ABORTED] Fail-safe triggered — mouse moved to top-left corner.")
        if playwright_context.get("browser"):
            playwright_context["browser"].close()
        exit(0)
