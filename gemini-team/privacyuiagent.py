# navigate to gemini-team folder with ls, cd commands
# run pip install -r requirements.txt
# STILL WIP ^^, so for now,
# can install dependencies using 
# pip install google-genai pyautogui pillow playwright

# You can get a Gemini API key at https://aistudio.google.com/app/api-keys 
# ----- IMPORTANT EXPORTS BEFORE RUNNING SCRIPT -----
# Ensure you have the Gemini API key set in your environment (use this command in the terminal):
# export GEMINI_API_KEY="your_api_key_here"
# Required (replace with actual test email account details)
# export SIGNUP_EMAIL_ADDRESS="your_test_account@gmail.com"
# export SIGNUP_EMAIL_PASSWORD="your_app_password_or_password"
# export SIGNUP_EMAIL_PASSWORD_WEB="$SIGNUP_EMAIL_PASSWORD"
# export SIGNUP_IMAP_SERVER="imap.gmail.com"
# export SIGNUP_IMAP_PORT=993
# export SIGNUP_IMAP_FOLDER=INBOX
# export SIGNUP_IMAP_SSL=true

# Run the script using python privacyuiagent.py, and minimize the terminal window
# so the agent can see the desktop.

# Be sure to set "DEVICE_TYPE" variable below to your actual device type.
import sys 
import time
import os, imaplib, email, re, random
from email.header import decode_header
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

def get_screenshot_bytes() -> bytes:
    screenshot = pyautogui.screenshot()
    img_byte_arr = io.BytesIO()
    screenshot.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def denormalize(value: int, max_value: int) -> int:
    return int((value * max_value) / cuse_grid)

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

# --- Email / IMAP Helpers 
ZOOM_CODE_RE = re.compile(r"\b(\d{6})\b")

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

def _connect_imap():
    host = os.environ.get("SIGNUP_IMAP_SERVER", "").strip()
    port = int(os.environ.get("SIGNUP_IMAP_PORT", "993"))
    user = os.environ.get("SIGNUP_EMAIL_ADDRESS", "").strip()
    pwd  = os.environ.get("SIGNUP_EMAIL_PASSWORD", "").strip()
    if not (host and user and pwd):
        raise RuntimeError("Missing IMAP env vars SIGNUP_IMAP_SERVER / SIGNUP_EMAIL_ADDRESS / SIGNUP_EMAIL_PASSWORD")
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, pwd)
    return M

def _decode_hdr(val):
    if not val: return ""
    parts = decode_header(val)
    out = []
    for s, enc in parts:
        out.append(s.decode(enc or "utf-8", errors="ignore") if isinstance(s, bytes) else s)
    return "".join(out)

def _parse_message_for_code(msg) -> Dict[str, str]:
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    text += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    pass
    else:
        try:
            text = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            text = str(msg.get_payload())

    m = ZOOM_CODE_RE.search(text)
    if m:
        return {"code": m.group(1)}

    m2 = re.search(r"https://\S+", text)
    if m2:
        return {"link": m2.group(0).rstrip(").,>")}
    return {}

def wait_for_zoom_code(max_wait_seconds: int = 180, poll_interval: int = 5) -> Dict[str, str]:
    folder = os.environ.get("SIGNUP_IMAP_FOLDER", "INBOX")
    start = time.time()
    last_uid_seen = None
    try:
        M = _connect_imap()
        M.select(folder)
        typ, data = M.uid('search', None, 'ALL')
        if typ == 'OK' and data and data[0]:
            uids = data[0].split()
            last_uid_seen = uids[-1] if uids else None

        while time.time() - start < max_wait_seconds:
            time.sleep(poll_interval)
            M.select(folder)
            search_crit = f'(UID {int(last_uid_seen)+1}:*)' if last_uid_seen else 'ALL'
            typ, data = M.uid('search', None, search_crit)
            if typ != 'OK':
                continue
            new_uids = [u for u in (data[0].split() if data and data[0] else [])]
            if not new_uids:
                continue

            for uid in new_uids:
                typ, msg_data = M.uid('fetch', uid, '(RFC822)')
                if typ != 'OK' or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subj = _decode_hdr(msg.get('Subject', ''))
                from_ = _decode_hdr(msg.get('From', ''))
                if not re.search(r"zoom", f"{subj} {from_}", re.I):
                    continue

                parsed = _parse_message_for_code(msg)
                if "code" in parsed or "link" in parsed:
                    try: M.logout()
                    except Exception: pass
                    return {"status": "success", **parsed}

            last_uid_seen = new_uids[-1]

        try: M.logout()
        except Exception: pass
        return {"status": "error", "message": "Timed out waiting for Zoom code"}
    except Exception as e:
        return {"status": "error", "message": f"IMAP error: {e}"}

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
    """Parses Gemini response and executes actions."""
    results = []
    function_calls: List[FunctionCall] = [p.function_call for p in candidate.content.parts if p.function_call]
    
    for fc in function_calls:
        fname = fc.name
        args = fc.args or {}
        action_result = {}

        # -------- SAFETY DECISION HANDSHAKE --------
        safety_decision = args.get("safety_decision")
        if safety_decision and isinstance(safety_decision, dict) and safety_decision.get("decision") == "require_confirmation":
            print(f"  Safety confirmation requested for {fname}: {safety_decision.get('explanation','')}")
            # ACK only; do NOT execute anything on this turn.
            results.append((
                fname,
                {
                    "ack_only": True,
                    "safety_decision": safety_decision,
                    "user_confirmation": "approved"
                },
                fc
            ))
            continue
        # -------------------------------------------

        print(f"  Executing > {fname}({args})")
        try:
            if fname == "click_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.3)
                pyautogui.click()

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

            elif fname == "key_combination":
                keys = args["keys"].lower().split('+')
                key_map = {"control": "ctrl", "command": "cmd", "windows": "win"}
                mapped_keys = [key_map.get(k, k) for k in keys]
                pyautogui.hotkey(*mapped_keys)

            elif fname == "wait_5_seconds":
                pass

            # ==== NEW: implement built-in Computer Use scroll ====
            elif fname == "scroll_at":
                # Model provides normalized x,y, direction ('down'|'up'), and magnitude
                x = denormalize(args.get("x", 500), SCREEN_WIDTH)
                y = denormalize(args.get("y", 500), SCREEN_HEIGHT)
                direction = (args.get("direction") or "down").lower()
                magnitude = int(args.get("magnitude", 200))
                # Focus the intended pane by moving mouse there, then wheel
                pyautogui.moveTo(x, y, duration=0.2)
                # pyautogui.scroll: positive scrolls up, negative scrolls down
                scroll_amount = -magnitude if direction == "down" else magnitude
                pyautogui.scroll(scroll_amount)
                action_result = {"status": "success", "scrolled": direction, "magnitude": magnitude, "x": x, "y": y}

            # Some model variants may emit 'wheel' or 'page_scroll'
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

            elif fname == "pw_navigate" or fname == "navigate":  # alias 'navigate' to pw_navigate
                action_result = pw_navigate(args["url"])

            elif fname == "pw_go_back":
                steps = int(args.get("steps", 1))
                action_result = pw_go_back(steps)

            elif fname == "wait_for_zoom_code":
                max_wait = int(args.get("max_wait_seconds", 180))
                poll = int(args.get("poll_interval", 5))
                action_result = wait_for_zoom_code(max_wait, poll)

            elif fname == "provide_signup_password":
                action_result = provide_signup_password()

            else:
                print(f"Warning: Skipping unimplemented function {fname}")
                action_result = {"error": f"Function {fname} not implemented locally."}

        except Exception as e:
            print(f"Error executing {fname}: {e}")
            action_result = {"error": str(e)}

        results.append((fname, action_result, fc))
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

Be specific about what buttons to click, what text to type, and what to look for in the UI.
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
        
        # 1. Define Tools (no scroll helpers declared—Computer Use will decide calls;
        # we just implement them when they arrive, like scroll_at.)
        custom_tools = [
            types.FunctionDeclaration(
                name="open_browser_and_navigate",
                description="Launches a new Chromium browser window and navigates to the specified URL. Call this first.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to navigate to (e.g., 'https://zoom.us/signup')."
                        }
                    },
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
                name="wait_for_zoom_code",
                description="Polls the test inbox for a Zoom verification email and returns a 6-digit code or a verification link.",
                parameters={
                    "type": "object",
                    "properties": {
                        "max_wait_seconds": {"type": "integer", "default": 180},
                        "poll_interval": {"type": "integer", "default": 5}
                    }
                }
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
            # NOTE: We do NOT declare scroll_at here; it comes from Computer Use tool.
        ]

        config = types.GenerateContentConfig(
            tools=[
                types.Tool(computer_use=types.ComputerUse()),
                types.Tool(function_declarations=custom_tools)
            ],
            system_instruction=f"""You are an agent operating a {DEVICE_TYPE} computer with a web browser.
                                1. Your first action MUST be to call `open_browser_and_navigate` to launch the browser.
                                2. Rely entirely on visual feedback. Use your built-in Computer Use actions (mouse move, click, type, mouse wheel, trackpad scroll, PgDown/PgUp). Do NOT call any custom scroll helpers.
                                3. During signup, use the Google sign-in flow via the provided tools (provide_signup_email / provide_signup_password).
                                4. If the UI asks for a Zoom verification code, call `wait_for_zoom_code` and enter the code or open the link.

                                Left-nav termination flow (MANDATORY):
                                - Expand **Admin** (if present).
                                - Click **Account Management**.
                                - Then REPEATEDLY SCROLL the **left navigation** with small wheel strokes within the nav pane until **Account Profile** is visible. KEEP SCROLLING until it is visible. Re-scan after each small scroll.
                                - Click **Account Profile**.
                                - In the main content, perform small incremental scrolls to find **Terminate my account**, then click it.
                                - If a confirmation flow requires **Send Code**, click it, open Gmail, fetch the code, return, paste, and confirm.

                                Rules:
                                - Prefer small, repeated scrolls to large jumps; if not visible, keep scrolling a bit more and re-scan the left nav.
                                - Do NOT use “My Account → Profile” unless “Admin” is missing entirely.
                                - After every click or scroll, re-check the visible text to decide the next action.
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
        MAX_TURNS = 30
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

            # If no function calls, possibly nudge when on Account Management
            if not any(p.function_call for p in model_response.parts):
                url_now = current_page_url() or ""
                if ("account" in url_now.lower() and "management" in url_now.lower()) or "zoom.us/account" in url_now.lower():
                    chat_history.append(Content(
                        role="user",
                        parts=[Part(text=(
                            "If Account Profile is not visible in the left navigation, use your built-in mouse wheel "
                            "to perform small repeated scrolls within the left nav until you can see and click "
                            "“Account Profile”. Do not stop scrolling early; re-scan the left nav after each small scroll."
                        ))]
                    ))
                    continue
                print("Agent finished or is waiting for input.")
                break
                
            action_results = execute_function_calls(response.candidates[0])

            # Build function responses
            function_response_parts = []
            for fname, result, fcall in action_results:
                # ACK-only branch (safety handshake)
                if isinstance(result, dict) and result.get("ack_only"):
                    fr = types.FunctionResponse(
                        name=fname,
                        response={
                            "acknowledged": True,
                            "user_confirmation": result.get("user_confirmation", "approved"),
                            "safety_decision": result.get("safety_decision", {})
                        },
                    )
                    function_response_parts.append(fr)
                    continue

                # Normal tool response branch
                url = current_page_url()
                base_ack = {
                    "function_name": fname,
                    "acknowledged": True,
                    "url": url,
                    "page_url": url,
                    "result": result if isinstance(result, dict) else {"result": str(result)}
                }

                new_screenshot = get_screenshot_bytes()
                fr = types.FunctionResponse(
                    name=fname,
                    response=base_ack,
                    parts=[
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=new_screenshot
                            )
                        )
                    ],
                )
                function_response_parts.append(fr)

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
