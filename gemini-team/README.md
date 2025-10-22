# Overview
Agentic UI automation that signs into a video platform using Google sign-in (e.g., Zoom web), captures full-page screenshots of privacy/data/security/recording settings, then launches a browser-based meeting and captures in-meeting privacy/permission UIs. Screenshots are saved to ./screenshots.

# Prerequisites

## 1) General permissions

Python 3.11.1

Playwright browsers installed

macOS or Windows (set DEVICE_TYPE in code)

For macOS (because we use pyautogui):

System Settings → Privacy & Security → grant your terminal/IDE:

Accessibility

Screen Recording

## 2) Install (in the terminal)

Environment
conda env create -f environment.yml

Install dependencies
pip install google-genai pyautogui pillow playwright

playwright install

## 3) Environment variables

You need a Gemini API key. Also provide the entry URL for the video platform’s settings.

Get an API key: https://aistudio.google.com/app/api-keys

Set exports (Linux/macOS):

export GEMINI_API_KEY="your_key_here" \
SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com" \
SIGNUP_EMAIL_PASSWORD="ZoomTestPass" \
SIGNUP_EMAIL_PASSWORD_WEB="$SIGNUP_EMAIL_PASSWORD" \
VIDEO_PLATFORM="https://zoom.us/profile/setting?tab=general"


On Windows (PowerShell):

$env:GEMINI_API_KEY="your_api_key_here"
$env:SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com"
$env:SIGNUP_EMAIL_PASSWORD="ZoomTestPass"
$env:SIGNUP_EMAIL_PASSWORD_WEB=$env:SIGNUP_EMAIL_PASSWORD
$env:VIDEO_PLATFORM="https://zoom.us/profile/setting?tab=general"


Keep the multi-line export exactly as shown (no stray spaces before backslashes).
VIDEO_PLATFORM can be any target site entry (we use Zoom Settings → General as an example).

## 4) Run
python screenshotuiagent.py


The agent will:

Open {VIDEO_PLATFORM} in Chromium (Playwright).

Sign in if required (using provide_signup_email / provide_signup_password).

Settings phase: Click each horizontal settings tab (General, Meeting, Recording) and take one full-page screenshot per tab (no vertical-nav scrolling).

Meeting phase: Start a browser-based meeting (stay in web client), capture:

Permissions prompts (mic/camera/notifications/screenshare)

Recording consent banners/dialogs

Security menu

Share Screen up-arrow → Advanced sharing options

End the meeting and finish.

All images save to ./screenshots (e.g., settings/general_YYYYMMDD_HHMMSS.png, meeting/share_advanced_options_*.png).

## 5) Important behaviors & knobs
Viewport / “Zoomed UI” fix

The script sets:

Browser window: --window-size=1280,720

Context viewport: 1280×720, device_scale_factor=1.0

This normalizes Zoom’s web client so toolbars fit on screen. If UI is still too large/small, tweak in open_browser_and_navigate:

viewport={"width": 1280, "height": 720}, device_scale_factor=1.0


Optionally inject page zoom post-load:

page.evaluate("document.body.style.zoom='80%'")

Screenshots

Full page (settings tabs): page_full_screenshot(label="general", subfolder="settings")

Element/Popover (in meeting menus): page_element_screenshot(selector, label="security_menu", subfolder="meeting")

Desktop/OS prompts: save_desktop_screenshot(label="os_prompt")

Scrolling policy

No scrolling for settings tab captures (one full-page shot per tab).

Minimal scrolling only to reveal the horizontal tab bar or in-meeting popovers; use a single small scroll (~80–120px), then stop.

Coordinate clicks

The agent prefers semantic/role-based actions (e.g., click_button_by_text, ui_click_label).

If the model attempts a click_at (coordinates), the runtime acknowledges safety and nudges it to retry with semantic tools.

Fail-safe

Moving the mouse to the top-left corner triggers pyautogui fail-safe. The script will close the browser context and exit.

## 6) Folder structure

gemini-team/

├── screenshotuiagent.py

├── environment.yml

├── screenshots/                # auto-created, output images live here

└── README.md


## 7) Customization

Device type: set DEVICE_TYPE = "MacBook" or "Windows 11 PC".

Labels & subfolders: keep them semantic (e.g., settings/meeting, meeting/security_menu).

VIDEO_PLATFORM: set export of VIDEO_PLATFORM to desired url. 

system_instruction: Large prompt to guide the creation of the plan and execution of actions. 