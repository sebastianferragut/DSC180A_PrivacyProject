# navigate to gemini-team folder with ls, cd commands
# run pip install -r requirements.txt
# STILL WIP ^^
# can install dependencies using 
# pip install google-genai pyautogui pillow

# Ensure you have the Gemini API key set in your environment:
# export GEMINI_API_KEY="your_api_key_here"

import time
import os
import io
from typing import Any, Dict, List, Tuple
from datetime import datetime
import pyautogui
from PIL import Image

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

# --- Helper Functions ---

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

def generate_fake_user_credentials() -> Dict[str, str]:
    """Generates a fake user profile for account registration."""
    timestamp = int(time.time())
    username = f"testuser_{timestamp}"
    email = f"testuser_{timestamp}@example.com"
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
    """Parses Gemini response and executes actions via PyAutoGUI."""
    results = []
    
    # 1. Extract function calls
    function_calls: List[FunctionCall] = []
    for part in candidate.content.parts:
        if part.function_call:
            function_calls.append(part.function_call)
            
    # 2. Execute them
    for fc in function_calls:
        fname = fc.name
        args = fc.args
        action_result = {}
        
        # --- Safety Confirmation Check ---
        # If the model requires confirmation for a sensitive action, we
        # do NOT execute it. Instead, we send back a confirmation response.
        safety_decision = args.get('safety_decision')
        if safety_decision and safety_decision.get('decision') == 'require_confirmation':
            print(f"  Confirmation required for {fname}: {safety_decision.get('explanation')}")
            print("  Sending confirmation to proceed...")
            action_result = {"user_confirmation": "approved"}
            results.append((fname, action_result, fc))
            continue # Skip execution for this turn

        print(f"  Executing > {fname}({args})")
        
        try:
            # --- Standard Computer Use Tools ---
            if fname == "click_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                # Move first, then click, intended to be more human-like
                pyautogui.moveTo(x, y, duration=0.5) 
                pyautogui.click()
                
            elif fname == "type_text_at":
                x = denormalize(args["x"], SCREEN_WIDTH)
                y = denormalize(args["y"], SCREEN_HEIGHT)
                text = args["text"]
                press_enter = args.get("press_enter", False)
                
                pyautogui.click(x, y)
                # Select all and delete to ensure clean typing area
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('backspace')
                pyautogui.write(text, interval=0.05)
                if press_enter:
                    pyautogui.press('enter')
                    
            elif fname == "key_combination":
                keys = args["keys"].lower().split('+')
                # Map common key names if necessary (pyautogui handles most)
                key_map = {"control": "ctrl", "enter": "enter", "windows": "win"}
                mapped_keys = [key_map.get(k, k) for k in keys]
                pyautogui.hotkey(*mapped_keys)

            elif fname == "wait_5_seconds":
                # The loop naturally waits, but we can add explicit wait
                pass
                
            # --- Custom User-Defined Tool ---
            elif fname == "generate_fake_user_credentials":
                creds = generate_fake_user_credentials()
                generated_credentials.update(creds) # Store for later
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
    print(f"Display resolution: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
    print("Minimize this terminal window so the agent can see the desktop.")
    print("Starting in 5 seconds...")
    time.sleep(5)
    
    # 1. Define Tools
    custom_tools = [
        types.FunctionDeclaration(
            name="generate_fake_user_credentials",
            description="Generates a fake username, email, and secure password. Call this when you need to fill out a sign-up or registration form.",
            parameters={
                "type": "object",
                "properties": {} # No arguments needed
            }
        ),
        types.FunctionDeclaration(
            name="save_consent_screenshot",
            description="Call this function ONLY when you successfully see the Zoom recording consent prompt on screen. It saves the screenshot to the local disk.",
            parameters={
                "type": "object",
                "properties": {} # No arguments needed
            }
        )
    ]

    # Actions that don't make sense in a desktop context
    excluded_actions = ["open_web_browser", "navigate", "go_back", "go_forward"]

    config = types.GenerateContentConfig(
        tools=[
            # Standard Computer Use Tool
            types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER, # Acts as generic GUI
                    excluded_predefined_functions=excluded_actions
                )
            ),
            # Custom Tool for the final goal
            types.Tool(function_declarations=custom_tools)
        ],
        # Enhanced instructions for plan-based execution
        system_instruction="""You are an agent operating a Windows 11 PC. 
1. You must rely entirely on visual feedback from screenshots.
2. User interfaces may take time to load. If you click a button, you may need to wait for the next screen to appear.
3. Do not make up coordinates. Analyze the provided image carefully.
4. **Permissions**: If you encounter a permission dialog (e.g., "Allow this app to make changes?"), you are authorized to click "Yes" or "Allow" to proceed with the task.
5. **Account Registration**: If the task requires creating an account, use the `generate_fake_user_credentials` tool to get a username, email, and password. Then, type this information into the appropriate fields. Remember the credentials in case you need to log in later."""
    )

    # 2. Initialize Chat History
    user_prompt = "Join the meeting through link 'ucsd.zoom.us/my/qiyuli', start video recording, and save a local screenshot of the consent prompt."
    print(f"\nGoal: {user_prompt}\n")

    initial_screenshot = get_screenshot_bytes()
    
    # Generate detailed plan first
    plan = generate_plan(client, user_prompt, initial_screenshot, config)
    
    # Initialize chat history with plan
    planning_context = f"""
{user_prompt}

Here is the detailed plan to follow:
{plan}

Execute this plan step by step, adapting as needed based on what you see on screen.
"""
    
    chat_history = [
        Content(
            role="user",
            parts=[
                Part(text=planning_context),
                Part.from_bytes(data=initial_screenshot, mime_type='image/png')
            ]
        )
    ]

    # 3. Interaction Loop
    MAX_TURNS = 20
    # --- Credential Storage ---
    # This will hold any credentials generated during the session
    generated_credentials = {}
    last_action_results = []
    
    for turn in range(1, MAX_TURNS + 1):
        print(f"--- Turn {turn} ---")
        
        # --- Replanning Check ---
        # If the last action was clicking a link, wait for navigation
        if turn > 1 and last_action_results:
            prev_action = last_action_results[-1][0]
            if prev_action == "click_at":
                print("Detected link click - waiting for navigation...")
                time.sleep(10) # Wait longer for potential navigation
                
        print("Analyzing screen...")
        
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=chat_history,
                config=config
            )
        except Exception as e:
            print(f"API Error: {e}")
            break

        model_response = response.candidates[0].content
        chat_history.append(model_response)

        # Print model thoughts with plan context
        for part in model_response.parts:
            if part.text:
                agent_text = part.text.strip()
                print(f"🤖 Agent: {agent_text}")
                
                # Check if agent mentions plan completion or issues
                if "plan" in agent_text.lower() and ("complete" in agent_text.lower() or "finished" in agent_text.lower()):
                    print("🎉 Plan completed successfully!")
                    # We can optionally break here if the task is considered done
                    # break
                elif "cannot" in agent_text.lower() or "unable" in agent_text.lower() or "different" in agent_text.lower():
                    print("⚠️  Plan may need adjustment")
                    replanning_needed = True

        # Check if tools need to be executed
        if not any(part.function_call for part in model_response.parts):
            # No function calls -> model is done, asking a question
            break
        # Execute actions
        action_results = execute_function_calls(response.candidates[0])
        last_action_results = action_results

        # Capture new state after actions
        print("Capturing new state...")
        new_screenshot = get_screenshot_bytes()

        # Build function responses
        function_response_parts = []
        task_completed = False
        # Provide a dummy URL to satisfy browser environment URL requirement
        dummy_url = "https://example.local/desktop"
        for fname, result, fcall in action_results:
            if fname == "save_consent_screenshot" and result.get("status") == "success":
                task_completed = True
            
            resp_payload = dict(result or {})

            # If this is a confirmation response, use it directly.
            # Otherwise, create the acknowledgment payload for regular actions.
            if "user_confirmation" not in resp_payload:
                # For computer use tools, we must acknowledge the safety decision
                # by returning a specific payload structure.
                if fname in ("click_at", "type_text_at", "key_combination", "wait_5_seconds"):
                    resp_payload = {
                        "computer_use_tool_ack": {
                            "function_name": fname,
                            "acknowledged": True
                        }
                    }

            # Add dummy URL for browser environment compatibility
            resp_payload.setdefault("url", dummy_url)
            resp_payload.setdefault("page_url", dummy_url)

            function_response_parts.append(
                types.FunctionResponse(
                    name=fname,
                    response=resp_payload,
                    # IMPORTANT: We must send the new screenshot back with the function response
                    # so the model can see the result of its action.
                    parts=[types.FunctionResponsePart(
                        inline_data=types.FunctionResponseBlob(
                            mime_type="image/png",
                            data=new_screenshot
                        )
                    )]
                )
            )

        # Add function responses to history for next turn
        chat_history.append(
            Content(role="user", parts=[Part(function_response=fr) for fr in function_response_parts])
        )

        if task_completed:
            print("--- Task Goal Achieved ---")
            # We do one final generation to let the model acknowledge completion
            final_resp = client.models.generate_content(
                model=MODEL_ID,
                contents=chat_history,
                config=config
            )
            if final_resp.candidates and final_resp.candidates[0].content.parts:
                print(f"🤖 Agent: {final_resp.candidates[0].content.parts[0].text}")
            break

if __name__ == "__main__":
    # Ensure Zoom is installed and you are logged in before running.
    run_agent()