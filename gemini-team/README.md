# Agentic AI: Browser-Based UI Scraping & Privacy Data Capture
## Overview

The code in this repo uses an agentic AI with Gemini API and Playwright to interact with a web platform and gather data on privacy design (so far, Zoom).
The code and outputs are located in the gemini-team folder.

The agent:

Signs in using Google OAuth (email/password provided via environment variables).

Crawls/navigates privacy, data, and security settings tabs.

Writes JSON outputs of relevant settings.

## 1. Accessing and Storing Data
### Output Data

All output is in JSON format.

Location: ./outputs/

Example file:

outputs/privacy_map_20251104_100756.json


These files are auto-generated when running the script and will be analyzed or uploaded to a data-collection repository.

### Input Data / Credentials

You must provide environment variables (see below in section 3) for:

Gemini API key 

Video platform URL (DO NOT CHANGE default : Zoom settings)

Email and password (test credentials only, provided)

## 2. Software Dependencies
Open a terminal window, ensure you are navigated to the gemini-team folder.

### Option A — Using Conda (recommended)

Activate provided Conda environment:
#### one-time setup
conda env create -f environment.yml

#### then for each new shell
conda activate agentic-ui

#### playwright runtime (once per machine / environment)
playwright install

### Option B — Manual Installation
pip install google-genai pyautogui pillow playwright beautifulsoup4 lxml
playwright install

### System Requirements

Python: 3.11+

OS: macOS or Windows 11

Browser: Chromium (installed by Playwright)

macOS Permissions

If using macOS, grant your terminal/IDE:

Accessibility → control the mouse

Screen Recording → allow pyautogui screenshots
(System Settings → Privacy & Security)

## 3. Environment Variables

You must export the following environment variables before running (be sure to change GEMINI_API_KEY to the one you get from https://aistudio.google.com/app/api-keys):
Open a terminal window, ensure you are navigated to the gemini-team folder, and execute:

macOS/Linux
export GEMINI_API_KEY="your_api_key_here" \
SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com" \
SIGNUP_EMAIL_PASSWORD="ZoomTestPass" \
SIGNUP_EMAIL_PASSWORD_WEB="$SIGNUP_EMAIL_PASSWORD" \
PROFILE_NAME="chrome" \
PLATFORM="https://zoom.us/profile/setting?tab=general"

Windows PowerShell
$env:GEMINI_API_KEY="your_api_key_here"
$env:SIGNUP_EMAIL_ADDRESS="zoomaitester10@gmail.com"
$env:SIGNUP_EMAIL_PASSWORD="ZoomTestPass"
$env:SIGNUP_EMAIL_PASSWORD_WEB=$env:SIGNUP_EMAIL_PASSWORD
$env:PLATFORM="https://zoom.us/profile/setting?tab=general"


Keep multi-line exports exactly as shown (no stray spaces).
Do not change the PLATFORM link (agent has been tested on Zoom, generalized support coming.)
Do not modify anything except for GEMINI_API_KEY. Free keys are provided at the link above. 

## 4. Running the Agent

In the terminal, ensure you are navigated to the gemini-team folder, and execute:

python uiagenthtml.py

The agent will:

Launch Chromium with Playwright and open the PLATFORM.

Sign in (using provided test credentials).

Crawl the site and write JSONs on relevant privacy design.

Save JSONs to ./outputs.

## 5. Behavior 

Move the mouse to the top-left corner to abort safely, close the Chromium tab, then exit out of the terminal that was running the script.

## 6. Folder Structure
gemini-team/

├── uiagenthtml.py        # Main script

├── environment.yml             # Conda environment definition

├── outputs/                # Output folder (auto-created)

└── README.md

## 7. Runtime Error Notes
If you get a 400 error, this happens with the API key at times due to a bug in the Gemini API. Simply re-run the script, ensuring all enviroment variables have been exported. 