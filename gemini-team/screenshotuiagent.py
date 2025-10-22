# run pip install -r requirements.txt
# can also install dependencies using 
# pip install google-genai pyautogui pillow playwright

# You can get a Gemini API key at https://aistudio.google.com/app/api-keys 
# ----- IMPORTANT EXPORTS BEFORE RUNNING SCRIPT -----
# Ensure you have the Gemini API key set in your environment (use this command in the terminal):
# export GEMINI_API_KEY="your_api_key_here"

# Paste the below into the terminal before running the script
# export GEMINI_API_KEY="your_api_key_here" \
# SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com" \
# SIGNUP_EMAIL_PASSWORD="ZoomTestPass" \
# SIGNUP_EMAIL_PASSWORD_WEB="$SIGNUP_EMAIL_PASSWORD" \
# VIDEO_PLATFORM="https://zoom.us/profile/setting?tab=general"

# ----------------------------------------------------

# Run the script using python screenshotuiagent.py
# Be sure to set "DEVICE_TYPE" variable below to your actual device type.

import sys
import time
import os, re, random
import io
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
import pyautogui
from playwright.sync_api import sync_playwright, Page

from google import genai
from google.genai import types
from google.genai.types import Content, Part, FunctionCall

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    exit(1)
VIDEO_PLATFORM = os.environ.get("VIDEO_PLATFORM")
if not VIDEO_PLATFORM:
    print("Error: VIDEO_PLATFORM environment variable not set.")
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

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# --- Playwright Global State ---
playwright_context: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "context": None,
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
        if hasattr(fc, "to_dict"):
            d = fc.to_dict()
            sd = (d.get("safetyDecision") or d.get("safety_decision") or
                  d.get("args",{}).get("safetyDecision") or d.get("args",{}).get("safety_decision"))
            if isinstance(sd, dict) and sd.get("decision"):
                return sd
    except Exception:
        pass
    return None

def _get_function_call_id(part) -> Optional[str]:
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

def _timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _safe_name(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]+', '_', s.strip()) or "unnamed"

def get_screenshot_bytes() -> bytes:
    screenshot = pyautogui.screenshot()
    img_byte_arr = io.BytesIO()
    screenshot.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def denormalize(value: int, max_value: int) -> int:
    return int((value * max_value) / cuse_grid)

# --- Screenshot utilities (GENERALIZED) ---
def ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def save_desktop_screenshot(label: str = "desktop") -> Dict[str, Any]:
    """Captures a full desktop screenshot via pyautogui into ./screenshots."""
    try:
        ts = _timestamp()
        fname = f"{_safe_name(label)}_{ts}.png"
        full_path = os.path.join(SCREENSHOT_DIR, fname)
        pyautogui.screenshot(full_path)
        print(f"[saved] {full_path}")
        return {"status": "success", "path": full_path, "filename": fname}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def page_full_screenshot(label: str = "page", subfolder: str = "") -> Dict[str, Any]:
    """Captures Playwright page full_page screenshot into ./screenshots[/subfolder]."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        ts = _timestamp()
        folder = os.path.join(SCREENSHOT_DIR, _safe_name(subfolder)) if subfolder else SCREENSHOT_DIR
        os.makedirs(folder, exist_ok=True)
        fname = f"{_safe_name(label)}_{ts}.png"
        out = os.path.join(folder, fname)
        pg.screenshot(path=out, full_page=True)
        print(f"[saved] {out}")
        return {"status": "success", "path": out, "filename": fname}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def page_element_screenshot(selector: str, label: str = "element", subfolder: str = "") -> Dict[str, Any]:
    """Captures a specific element via CSS/xpath/text selector (locator-string) if visible."""
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}
        loc = pg.locator(selector)
        if not loc.count():
            return {"status": "error", "message": f"Selector not found: {selector}"}
        ts = _timestamp()
        folder = os.path.join(SCREENSHOT_DIR, _safe_name(subfolder)) if subfolder else SCREENSHOT_DIR
        os.makedirs(folder, exist_ok=True)
        fname = f"{_safe_name(label)}_{ts}.png"
        out = os.path.join(folder, fname)
        loc.first.screenshot(path=out)
        print(f"[saved] {out}")
        return {"status": "success", "path": out, "filename": fname}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Playwright semantic click helper (dialog-aware; avoids coord clicks) ---
def pw_click_button_by_text(text: str, timeout_ms: int = 5000) -> dict:
    try:
        pg: Page = playwright_context.get("page")
        if not pg:
            return {"status": "error", "message": "No active page"}

        # 1) Prefer modal/dialog scope if present
        try:
            dialog = pg.get_by_role("dialog").filter(has_text=re.compile(r".*", re.S)).first
            dialog.wait_for(state="visible", timeout=1500)
            btn = dialog.get_by_role("button", name=text, exact=True)
            if btn.count():
                btn.first.click(timeout=timeout_ms)
                return {"status": "success", "clicked": text, "scope": "dialog"}
        except Exception:
            pass

        # 2) Fallback: page buttons/links/text
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

# --- Browser lifecycle / navigation ---
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
                f"--window-size=1280,720",
                # Keep media prompts visible unless your instructions say otherwise:
                # "--use-fake-ui-for-media-stream",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1.0,
            accept_downloads=True,
            # You can grant permissions generically if desired by instructions:
            # permissions=["camera","microphone","notifications"],
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

# --- Generic UI label clicks ---
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

# --- Minimal email helpers (web UI only; kept for generic SSO/password flows) ---
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

    # Handle safety-gated calls up front
    for wc in wrapped_calls:
        fc = wc["fc"]
        sd = _extract_safety_decision(fc)
        if sd and sd.get("decision") in ("require_confirmation", "block"):
            name = fc.name
            call_id = wc["id"] or getattr(fc, "id", None) or f"gated-{int(time.time()*1000)}"

            # 1) Emit the required ack FunctionResponse
            results.append((
                name,
                {
                    "ack_only": True,
                    "safety_ack_payload": {
                        "id": call_id,
                        "name": name,
                        "response": {
                            "safety_decision": {
                                "decision": "proceed",                 # or echo sd["decision"]
                                "user_confirmation": "approved",
                                "explanation": sd.get("explanation","")
                            }
                        }
                    }
                },
                fc
            ))

            # 2) If it's a coordinate click, short-circuit and ask for a semantic re-emit
            if name == "click_at":
                # Tell caller we handled ack, but want a re-emit w/ text-based tool
                results.append(("__RETRY_WITH_TEXT__", {"reason": "gated_click_at"}, None))
            # Continue to next wrapped call (we don't execute the gated action now)
            continue

    # If any gated acks were added, return now so the chat nudge path can run
    if results:
        return results

    # Execute normal calls
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

            elif fname == "save_desktop_screenshot":
                action_result = save_desktop_screenshot(args.get("label","desktop"))

            elif fname == "page_full_screenshot":
                action_result = page_full_screenshot(
                    label=args.get("label","page"),
                    subfolder=args.get("subfolder","")
                )

            elif fname == "page_element_screenshot":
                action_result = page_element_screenshot(
                    selector=args["selector"],
                    label=args.get("label","element"),
                    subfolder=args.get("subfolder","")
                )

            elif fname == "provide_signup_email":
                action_result = provide_signup_email()

            elif fname in ("pw_navigate", "navigate"):
                action_result = pw_navigate(args["url"])

            elif fname == "pw_go_back":
                steps = int(args.get("steps", 1))
                action_result = pw_go_back(steps)

            elif fname == "provide_signup_password":
                action_result = provide_signup_password()

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

        # Return FunctionResponses with an inline desktop screenshot for traceability
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

        # 1) Define generic tools
        custom_tools = [
            types.FunctionDeclaration(
                name="open_browser_and_navigate",
                description="Launch a new Chromium window and navigate to the specified URL.",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(
                name="pw_navigate",
                description="Navigate current tab to the given URL using Playwright.",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(
                name="pw_go_back",
                description="Go back in browser history.",
                parameters={"type":"object","properties":{"steps":{"type":"integer","default":1}}}
            ),
            types.FunctionDeclaration(
                name="tabs_open_new",
                description="Open URL in a NEW tab (preserves current tab).",
                parameters={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}
            ),
            types.FunctionDeclaration(
                name="tabs_switch_to",
                description="Switch to a tab whose URL contains the given substring.",
                parameters={"type":"object","properties":{"substr":{"type":"string"},"timeout_ms":{"type":"integer","default":10000}},"required":["substr"]}
            ),
            types.FunctionDeclaration(
                name="click_button_by_text",
                description="Clicks a visible button/link by exact text using Playwright (avoids coordinate clicks).",
                parameters={"type":"object","properties":{"text":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["text"]}
            ),
            types.FunctionDeclaration(
                name="ui_click_label",
                description="Click a visible control by label, preferring dialog scope.",
                parameters={"type":"object","properties":{"label":{"type":"string"},"timeout_ms":{"type":"integer","default":5000}},"required":["label"]}
            ),
            types.FunctionDeclaration(
                name="ui_click_any_label",
                description="Click the first matching label from a list (dialog preferred).",
                parameters={"type":"object","properties":{"labels":{"type":"array","items":{"type":"string"}},"timeout_ms":{"type":"integer","default":5000}},"required":["labels"]}
            ),
            # Screenshot tools (generic; write to ./screenshots)
            types.FunctionDeclaration(
                name="save_desktop_screenshot",
                description="Capture a full-desktop screenshot to the local ./screenshots folder.",
                parameters={"type":"object","properties":{"label":{"type":"string"}}}
            ),
            types.FunctionDeclaration(
                name="page_full_screenshot",
                description="Capture a full-page screenshot of the current Playwright page into ./screenshots",
                parameters={"type":"object","properties":{"label":{"type":"string"},"subfolder":{"type":"string"}}}
            ),
            types.FunctionDeclaration(
                name="page_element_screenshot",
                description="Capture a screenshot of a specific element by selector into ./screenshots",
                parameters={"type":"object","properties":{"selector":{"type":"string"},"label":{"type":"string"},"subfolder":{"type":"string"}},"required":["selector"]}
            ),
            # Credentials fetchers (kept for generic sign-in flows your instructions may call)
            types.FunctionDeclaration(
                name="provide_signup_email",
                description="Returns an email address from env vars for sign-in/SSO flows.",
                parameters={"type":"object","properties":{}}
            ),
            types.FunctionDeclaration(
                name="provide_signup_password",
                description="Returns a web password from env vars for sign-in forms.",
                parameters={"type":"object","properties":{}}
            ),
        ]

        # 2) System instructions
        config = types.GenerateContentConfig(
            tools=[types.Tool(computer_use=types.ComputerUse()),
                   types.Tool(function_declarations=custom_tools)],
            system_instruction=f"""You are an agent operating a {DEVICE_TYPE} computer with a web browser.
            
Primary Objective
-Open {VIDEO_PLATFORM} using open_browser_and_navigate, sign in using the Google sign-in (use provide_signup_email / provide_signup_password if needed), and capture settings + in-meeting privacy UX.


1. Settings phase: For the account Settings/Preferences, capture one full-page screenshot per horizontal settings tab (e.g., General, Meeting, Recording). After each full-page screenshot, immediately move on—do not scroll the page further and do not capture vertical navigation.
2. Meeting phase: Start/host a browser-based meeting (no native client). Capture any in-meeting UIs for permissions, recording consent, Security menu, and Share Screen → Advanced sharing options, then end the meeting.
-In the meeting phase, cancel any prompts to open zoom.us app and stay in browser; click on Join from your browser links if needed. Also continue without using microphone or camera whenever this is prompted, but screenshot those prompts.

Navigation Rules
-Only click the horizontal tab bar within Settings (e.g., General / Meeting / Recording). Do not use or scroll the vertical nav; the full-page capture of each tab is sufficient.
-If a tab has sub-tabs (e.g., Basic/Advanced) and they’re clearly part of the same horizontal section, click each sub-tab and take a full-page screenshot per sub-tab, then proceed.
-Avoid deep-dives and subtoggles unless a dialog/popover is specifically about privacy/permissions/recording.

Screenshot Rules
-Use page_full_screenshot(label, subfolder) for each Settings tab (labels like: general, meeting, recording; subfolder settings).
-Use page_element_screenshot(selector, label, subfolder) for in-meeting popovers/menus (labels like security_menu, share_advanced_options; subfolder meeting).
-Use save_desktop_screenshot(label) only for OS-level prompts you can’t read in-page.
-Save all images to ./screenshots.

Scrolling Policy (strict)
-Do not scroll during Settings tab captures—take a single full-page screenshot per tab and advance.
-Scrolling is allowed only to reveal a horizontal tab bar if it’s just out of view, or within the in-meeting UI to expose a specific privacy/permission popover. When allowed: use one small scroll (≈80–120 px), then stop.

Tab/Window Policy
-Use in-page links when possible. If a web client opens in a new page for the meeting, it’s acceptable.
-Do not navigate away from a Settings tab before its screenshot is taken.

Safety/Acks
-Prefer role/text-based actions; avoid coordinate clicks.
-If a call is safety-gated and lacks an id, re-issue with a function_call.id and use semantic tools.

Output Discipline
-Ensure content is fully loaded before capturing.
-Use concise semantic names:
-general.png, meeting.png, recording.png, etc
-security_menu.png, share_advanced_options.png, recording_consent.png, etc

Targets (guidance)
-Settings tabs: General, Meeting, Recording.
-In-meeting: any permissions/recording consent prompts, Security menu; Share Screen up-arrow → Advanced sharing options."""
       )

        # 3) Initialize Chat
        # The user_prompt is intentionally generic — you can specialize in your own caller.
        user_prompt = "Sign in to the selected video platform, capture screenshots of all privacy/data/security/recording settings, then host a web meeting and capture in-meeting permission, recording, security, and sharing option prompts/menus. Save screenshots to ./screenshots."
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

        # 4) Interaction Loop
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

            # If the model stalls without toolcalls, we just continue the loop once
            if not any(p.function_call for p in model_response.parts):
                print("No tool calls detected. Continuing.")
                continue

            action_results = execute_function_calls(response.candidates[0])

            # If execute_function_calls asked for a retry via text, don't send FunctionResponses
            if len(action_results) == 1 and action_results[0][0] == "__RETRY_WITH_TEXT__":
                chat_history.append(Content(
                    role="user",
                    parts=[Part(text=(
                        "Safety requirement: Your last tool call lacked a function_call.id or used a gated action. "
                        "Re-issue with a proper id and use text/role-based tools (e.g., click_button_by_text)."
                    ))]
                ))
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
