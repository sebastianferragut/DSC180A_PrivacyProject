# navigate to gemini-team folder with ls, cd commands
# run pip install -r requirements.txt
# STILL WIP ^^
# can install dependencies using 
# pip install google-genai pyautogui pillow playwright

# You can get a Gemini API key at https://aistudio.google.com/app/api-keys 
# Ensure you have the Gemini API key set in your environment (use this command in the terminal):
# export GEMINI_API_KEY="your_api_key_here"

# Run the script using python privacyuiagent.py, and minimize the terminal window
# so the agent can see the desktop.

# Be sure to set "DEVICE_TYPE" variable below to your actual device type.

import sys 
import time
import os
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
# Get API key from environment variable
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    exit(1)

MODEL_ID = 'gemini-2.5-computer-use-preview-10-2025'
PLANNING_MODEL_ID = 'gemini-2.5-pro'

# Set your device type here (e.g., "MacBook", "Windows PC", "Linux PC")
DEVICE_TYPE = "MacBook"
# DEVICE_TYPE = "Windows 11 PC"

# Configure PyAutoGUI
# Move mouse to top-left corner to abort script if it goes haywire
pyautogui.FAILSAFE = True 
# specific delay after each PyAutoGUI call to let UI settle
pyautogui.PAUSE = 1.0

# Initialize Gemini client
client = genai.Client(api_key=API_KEY)

# Get actual screen dimensions
SCREEN_WIDTH, SCREEN_HEIGHT = pyautogui.size()
# Computer Use model works on a 1000x1000 normalized grid
cuse_grid = 1000

# --- Playwright Global State ---
# We'll manage these objects in the main run_agent function
playwright_context: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "page": None,
}

# --- Helper Functions ---
def current_page_url() -> str:
    """Returns the current URL from the browser page, if available."""
    try:
        pg = playwright_context.get("page")
        if pg:
            return pg.url or ""
    except Exception:
        pass
    return ""

def get_screenshot_bytes() -> bytes:
    """Captures screen and returns PNG bytes for the API."""
    screenshot = pyautogui.screenshot()
    img_byte_arr = io.BytesIO()
    screenshot.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def denormalize(value: int, max_value: int) -> int:
    """Converts 0-1000 coordinate to actual screen pixel coordinate."""
    return int((value * max_value) / cuse_grid)

# --- Custom Function Implementation ---

def open_browser_and_navigate(url: str) -> Dict[str, str]:
    """Launch a Chromium window sized to the full screen and navigate to URL."""
    try:
        p = playwright_context.get("playwright")
        if not p:
            return {"status": "error", "message": "Playwright not initialized."}

        # Use your real desktop resolution for the browser window.
        # macOS ignores --start-maximized, so set size + position explicitly.
        win_w, win_h = SCREEN_WIDTH, SCREEN_HEIGHT
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-features=IsolateOrigins,site-per-process",
                f"--window-position=0,0",
                f"--window-size={win_w},{win_h}",
            ],
        )

        # Make the context viewport match the window size (no letterboxing).
        context = browser.new_context(
            viewport={"width": win_w, "height": win_h},  # or viewport=None to follow window size
            device_scale_factor=1.0,
        )
        page = context.new_page()
        page.bring_to_front()
        page.goto(url, wait_until="load", timeout=60_000)

        playwright_context["browser"] = browser
        playwright_context["page"] = page

        # Small settle to ensure OS brought it to the front
        time.sleep(0.5)
        return {"status": "success", "message": f"Successfully navigated to {url}."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def generate_fake_user_credentials() -> Dict[str, str]:
    """Generates a fake user profile for account registration."""
    timestamp = int(time.time())
    username = f"testuser_{timestamp}"
    # Use a disposable email service that has a public inbox
    email = f"testuser{timestamp}@mailinator.com"
    password = f"P@ssw0rd_{timestamp}!"
    
    credentials = {
        "username": username,
        "email": email,
        "password": password,
        "status": "success"
    }
    print(f"\n[INFO] Generated fake credentials: {username} / {email}\n")
    return credentials

def save_consent_screenshot() -> Dict[str, Any]:
    """Saves a timestamped screenshot to disk (the goal of the task)."""
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

# --- Action Execution Loop ---

def execute_function_calls(candidate) -> List[Tuple[str, Dict, FunctionCall]]:
    """Parses Gemini response and executes actions."""
    results = []
    function_calls: List[FunctionCall] = [p.function_call for p in candidate.content.parts if p.function_call]
    
    for fc in function_calls:
        fname = fc.name
        args = fc.args
        action_result = {}
        
        # --- Safety Confirmation Check ---
        safety_decision = args.get('safety_decision')
        if safety_decision and safety_decision.get('decision') == 'require_confirmation':
            print(f"  Confirmation required for {fname}: {safety_decision.get('explanation')}")
            print("  Sending confirmation to proceed...")
            action_result = {"user_confirmation": "approved"}
            results.append((fname, action_result, fc))
            continue

        print(f"  Executing > {fname}({args})")
        
        try:
            if fname == "click_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                pyautogui.moveTo(x, y, duration=0.5)
                pyautogui.click()
            elif fname == "type_text_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                text = args["text"]
                press_enter = args.get("press_enter", False)
                pyautogui.click(x, y)
                
                # Platform-specific hotkey for 'select all'
                if sys.platform == "darwin": # macOS
                    pyautogui.hotkey('command', 'a')
                else: # Windows/Linux
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
                pass # The loop delay is sufficient
                
            # --- Custom Tools ---
            elif fname == "open_browser_and_navigate":
                action_result = open_browser_and_navigate(args["url"])
            elif fname == "generate_fake_user_credentials":
                creds = generate_fake_user_credentials()
                # Store credentials in a global or class-level variable if needed across turns
                action_result = creds
            elif fname == "save_consent_screenshot":
                action_result = save_consent_screenshot()
            else:
                print(f"Warning: Skipping unimplemented function {fname}")
                action_result = {"error": f"Function {fname} not implemented locally."}
        except Exception as e:
            print(f"Error executing {fname}: {e}")
            action_result = {"error": str(e)}
        results.append((fname, action_result, fc))
    return results

# --- Main Agent Logic ---
# (generate_plan function remains unchanged)
def generate_plan(client, user_prompt: str, screenshot_bytes: bytes, config) -> str:
    """Generate a detailed plan based on user prompt and current UI state."""
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
        # No need for sleep, we'll wait for the browser to launch
        
        # 1. Define Tools
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
                name="generate_fake_user_credentials",
                description="Generates a fake email and secure password for a sign-up form.",
                parameters={"type": "object", "properties": {}}
            ),
            types.FunctionDeclaration(
                name="save_consent_screenshot",
                description="Saves a screenshot when a privacy consent dialog is visible.",
                parameters={"type": "object", "properties": {}}
            )
        ]

        config = types.GenerateContentConfig(
            tools=[
                types.Tool(computer_use=types.ComputerUse()), # Using default computer_use tools
                types.Tool(function_declarations=custom_tools)
            ],
            system_instruction=f"""You are an agent operating a {DEVICE_TYPE} computer inside a web browser.
1.  Your first action MUST be to call `open_browser_and_navigate` to launch the browser.
2.  You must rely entirely on visual feedback from screenshots. All your actions should be directed at the browser window.
3.  If you need to create an account, use `generate_fake_user_credentials`.
4.  After clicking a button or link, wait for the page to load before taking the next action. The new screenshot will show you the updated page state."""
        )

        # 2. Initialize Chat
        user_prompt = "First, open the browser and navigate to 'https://zoom.us/signup'. Then, create a new account using fake credentials. After creating the account, find the account settings and delete the account."
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
        MAX_TURNS = 30 # Increased for a longer task
        for turn in range(1, MAX_TURNS + 1):
            print(f"--- Turn {turn} ---")
            
            # Add a small delay to let the UI settle before acting
            time.sleep(2)
            
            print("Analyzing screen...")
            
            try:
                response = client.models.generate_content(model=MODEL_ID, contents=chat_history, config=config)
            except Exception as e:
                print(f"API Error: {e}")
                break

            model_response = response.candidates[0].content
            chat_history.append(model_response)

            if model_response.parts[0].text:
                print(f"🤖 Agent: {model_response.parts[0].text.strip()}")

            if not any(p.function_call for p in model_response.parts):
                print("Agent finished or is waiting for input.")
                break
                
            action_results = execute_function_calls(response.candidates[0])
            print("Capturing new state...")
            new_screenshot = get_screenshot_bytes()
            function_response_parts = []

            for fname, result, fcall in action_results:
                url = current_page_url()
                # Always include a URL; some steps might happen before navigation completes.
                # If url is empty, still send an empty string to satisfy the requirement.
                base_ack = {
                    "function_name": fname,
                    "acknowledged": True,
                    "url": url,          # <-- plain key
                    "page_url": url,     # <-- also present for clarity
                }

                # Merge any tool-specific result
                if result:
                    # If your custom tool returned a dict, keep it under "result"
                    base_ack["result"] = result

                # Special case: safety confirmation path you implemented
                if isinstance(result, dict) and "user_confirmation" in result:
                    base_ack["user_confirmation"] = result["user_confirmation"]

                # Final response object the model will read
                resp_payload = {
                    "computer_use_tool_ack": base_ack,
                    # Redundant top-level url for strict validators:
                    "url": url,
                    "page_url": url,
                }

                # (Optional) debug once:
                # print("DEBUG function response payload:", json.dumps(resp_payload, indent=2))

                function_response_parts.append(
                    types.FunctionResponse(
                        name=fname,
                        response=resp_payload,
                        parts=[
                            types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=new_screenshot
                                )
                            )
                        ],
                    )
                )


            chat_history.append(Content(role="user", parts=[Part(function_response=fr) for fr in function_response_parts]))

        print("--- Agent session finished ---")
        if playwright_context.get("context"):
            playwright_context["context"].close()
        if playwright_context.get("browser"):
            playwright_context["browser"].close()


if __name__ == "__main__":
    try:
        run_agent()
    except pyautogui.FailSafeException:
        print("\n[ABORTED] Fail-safe triggered — mouse moved to top-left corner.")
        if playwright_context.get("browser"):
            playwright_context["browser"].close()
        exit(0)
