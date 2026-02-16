# Agentic Privacy Control Center: Generalized Privacy/Data Settings Scraping & Automation

## Overview
This repository builds an end-to-end pipeline that captures privacy/data settings from web platforms, normalizes them into a settings database, and drives an agentic UI that can change settings on a user's behalf. It solves the "every platform has a different UI" problem by combining Playwright automation with Gemini planning/verification and a reusable authenticated profile cache.

## Script Overview
- Authenticated profile cache capture via `gemini-team/save_state.py`.
- Screenshot extraction and classification pipeline that produces `database/data/extracted_settings_with_urls_and_layers_classified.json` used by the app and dashboard.
- Chainlit app `privacyagentapp/agenticapp.py` that loads the settings DB and safely attempts setting changes with a planner -> executor -> verifier loop.

---

## Getting Started

### Prerequisites
- Python 3.11 (conda recommended)
- Playwright browsers installed
- macOS or Windows with Accessibility/Screen Recording permissions (for UI automation)
- Gemini API key from [AI Studio API keys](https://aistudio.google.com/app/api-keys)

### API Credentials and Environment
Core variable (can be set either in environment before running Chainlit or in-app as prompted):
- `GEMINI_API_KEY`

macOS/Linux:
```bash
# Optional for Chainlit app (otherwise will be prompted for it in-app)
export GEMINI_API_KEY="your_api_key_here" 

# For save_state.py
export START_URL="https://example.com/path/to/settings"
export PLATFORM_NAME="example"
```

Windows PowerShell:
```powershell
$env:GEMINI_API_KEY="your_api_key_here"
$env:START_URL="https://example.com/path/to/settings"
$env:PLATFORM_NAME="example"
```

### Install Dependencies
```bash
conda env create -f gemini-team/environment.yml
conda activate agentic-ui
playwright install
```

---

## Profile Cache and save_state.py

### What the profile cache is
The profile cache is a Playwright storage state file (cookies, localStorage, sessionStorage) saved per hostname. It lets the crawler and agent reuse authenticated sessions without repeated logins.

Location:
- `gemini-team/profiles/storage/<hostname>.json`

### How save_state.py works
`gemini-team/save_state.py` launches a visible Chromium window, navigates to the URL you provide, and waits for you to log in. When you press Enter in the terminal, it saves the browser context storage state to the cache path above.

### Generate a profile cache
```bash
python gemini-team/save_state.py "https://www.linkedin.com/mypreferences/d/categories/account"
```

### Load and use a profile cache
`agenticapp.py` derives the hostname from the target URL and load the matching cache file.

Example: run the agent (must have a cache and have run the scraping/categorization for the target host)
```bash
# Optional export, can be done in the terminal or in-app as prompted
export GEMINI_API_KEY="your_api_key_here"

chainlit run privacyagentapp/agenticapp.py -w
```

If a site logs you out or changes sessions, re-run `save_state.py` for that hostname.

---
## Running Web Crawler

### What it does
`gemini-team/settingsPageAgent.py` contains a script that crawls a site's settings page to find pages that contain user-configurable toggles (privacy/data/security controls). It leverages Playwright for browser automation and Google Gemini to steer the discovery process. Along the navigation process, the script captures a full-page screenshot for each unique UI state encountered and records the traversal path.

Flow:
- Opens provided URL
- Lets user log in and go to settings page
- Iterate until queue is empty or iteration limit is hit:
    - Finds and queue hyperlinks in DOM
    - Dequeue link, ask Gemini if link is relevant
        - If relevant, navigate to page
        - If irrelevant, omit
    - Take screenshot and log page link
 
```bash
cd gemini-team
python settingsPageAgent.py
cd picasso                  # to view captured screenshots and click counts
```

The captured screenshots are saved in `gemini-team/picasso` based on platform and click counts JSON, which contain page links organized by depth from starting page. These results are subsequently processed below! 

---
## Running screenshot processing

### What it does
This process is to process the screenshots captured by the web crawler and build into json and csv file for supporting the Chainlit app and the dashboard view.

Flow:
- Extract text from screenshots
- Parse and map url to the respective screenshots
- Classify screenshot settings

### Run command
```bash
cd screenshot-classifier
python screenshot_settings_extractor.py
cd ../database
python map_url.py
python classify_categories.py
```

The json files produced after each step are ```screenshot-classifier/extracted_settings.json```, ```/database/data/extracted_settings_with_urls_and_layers.json``` and the final file ```database/data/extracted_settings_with_urls_and_layers_classified```.



## Running the Agent (agenticapp.py)

### What it does
`privacyagentapp/agenticapp.py` is a Chainlit app that loads the settings database and attempts setting changes on real sites.

Flow:
- Planner: Gemini proposes selectors and intent (`change_value`, `confirm`, `scroll`, etc.).
- Executor: Playwright applies selectors and navigates the UI.
- Verifier: deterministic checks when possible, otherwise Gemini visual verification.

### Run command
```bash
# # Optional export, can be done in the terminal or in-app as prompted
export GEMINI_API_KEY="your_api_key_here"

chainlit run privacyagentapp/agenticapp.py -w
```

### Example in-app commands
```text
settings <platform>
change <platform> <setting_id_or_name> to <value>
change <platform> <section_id_or_name>::<leaf_setting_name> to <value>
report
```
Mainly, the user is expected to navigate the agent with the provided UI to understand the categories of settings for each platform and select a setting and target value. The advanced commands as shown above are also available. 
```

### Log meanings
- `TURN N`: executor attempt number (max 6 per change).
- `[planner_setting_change]` and `[planner_confirm_only]`: Gemini planner calls.
- `selectors`: actions returned by the planner; `[apply_selector]` shows how they were matched.
- `done=true`: planner claims it completed the change; executor still verifies.
- `status=success|uncertain|error`: final outcome reported to the UI.
- `notes=...`: short planner notes or error tags like `model_bad_json` or `confirm_only_no_selectors`.
```
---


## Repo Structure
```
DSC180A_PrivacyProject/
|-- gemini-team/
|   |-- save_state.py
|   |-- profiles/
|   |   `-- storage/
|   `-- environment.yml
|-- database/
`-- privacyagentapp/
    `-- agenticapp.py
```
