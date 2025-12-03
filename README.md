# Agentic AI: Generalized Privacy/Data Settings Scraping & Automation  
## Overview

This repository contains multiple components for a multi-agent system designed to:

1. **Capture privacy and data-related settings across multiple web platforms**  
   using a combined DOM-scraping + Gemini Computer Vision approach.
2. **Store cross-platform authenticated sessions**  
   to enable repeated scraping without re-authenticating.
3. **Provide a Chainlit-based agentic interface**  
   allowing users to automate changing their privacy/data settings across supported platforms.

The following are relevant scripts:

- `gemini-team/generalssagent.py`  
- `gemini-team/save_state.py`  
- `privacyagentapp/agenticapp.py`  

---

## 1. Accessing and Storing Data  

### 1.1 Output Data

#### **save_state.py**
Stores browser authentication state per platform:

gemini-team/profiles/storage/<hostname>.json

Each JSON file contains cookies, localStorage, and sessionStorage. These are reused by the scraping agent to avoid repeated logins.

---

#### **generalssagent.py**
Produces:

- `harvest_report.json` per platform  
- Full-page and section-level screenshots

Location:

gemini-team/generaloutput/<platform_name>/

│── harvest_report.json

└── screenshots/
└── sections/


---

### 1.2 Input Data / Credentials

Both scraping scripts require at least:

- A Gemini API key  
- A URL to begin scraping (`START_URL`)  
- A platform name (`PLATFORM_NAME`) to label output folders  

(Note: the Chainlit app requires only the Gemini API key.)

---

## 2. Software Dependencies  

Install via `gemini-team/environment.yml`:

conda env create -f environment.yml
conda activate agentic-ui

Install Playwright browser drivers:

playwright install

### System Requirements

- Python 3.11+  
- macOS (with Accessibility + Screen Recording permissions) or Windows 11 with permissions 
- Chromium (auto-installed via Playwright)

---

## 3. Script-Level Environment Variables  
Environment variables differ per script; therefore, they are documented **under the relevant sections**.

---

## 4. Running the Agents  

---

## 4.1 Authentication State Capture  
**File:** `gemini-team/save_state.py`

This script launches a visible Chromium window, navigates to the provided `START_URL`, and allows the user to manually complete login.  
After the user presses Enter in the terminal, the browser context’s storage state is saved to:

`profiles/storage/<hostname>.json`

### Run Command

python save_state.py <START_URL>


### Required Environment Variables (for save_state.py)

(be sure to change GEMINI_API_KEY to the one you get from https://aistudio.google.com/app/api-keys)

macOS/Linux:
export GEMINI_API_KEY="your_api_key_here"
export START_URL="https://example.com/path/to/settings"



Windows PowerShell:
$env:GEMINI_API_KEY="your_api_key_here"
$env:START_URL="https://example.com/path/to/settings"


Behavior:

- Opens Chromium  
- User signs in manually  
- Press Enter in terminal  
- Storage state is saved  
- Must be run **once per site** before using `generalssagent.py` and `agenticapp.py`

---

## 4.2 Generalized Scraping Agent  
**File:** `gemini-team/generalssagent.py`

python generalssagent.py


This agent:

- Loads saved storage state (created via `save_state.py`)  
- Uses Gemini Planner to determine navigation/capture steps  
- Clicks through privacy/data settings  
- Captures full-page and element-level screenshots  
- Writes `harvest_report.json`

This script **does not** perform login.  
`save_state.py` must be run first.

### Required Environment Variables (for generalssagent.py)
(be sure to change GEMINI_API_KEY to the one you get from https://aistudio.google.com/app/api-keys)

Example exports for macOS/Linux :
export GEMINI_API_KEY="your_api_key_here"
export START_URL="https://zoom.us/profile/setting?tab=general"
export PLATFORM_NAME="zoom"


Example exports for Windows PowerShell:
$env:GEMINI_API_KEY="your_api_key_here"
$env:START_URL="https://zoom.us/profile/setting?tab=general"
$env:PLATFORM_NAME="zoom"


### Example START_URLs

- https://zoom.us/profile/setting?tab=general  
- https://www.linkedin.com/mypreferences/d/categories/account  
- https://accountscenter.facebook.com/password_and_security  

---

## 4.3 Generalized Privacy Setting Classification

This stage extracts structured text from screenshots, merges it with harvesting metadata, and classifies each screenshot into a privacy-setting category.

---

## 4.3.1 Screenshot Settings Extraction  
**File:** `screenshot-classifier/screenshot_settings_extractor.py`

This script processes all screenshots captured by the scraping agent and uses Gemini to extract:  
- setting names  
- descriptions  
- current states (if visible)

The extracted output is saved to:  
`screenshot-classifier/extracted_settings.json`

### Run Command
```bash
python screenshot-classifier/screenshot_settings_extractor.py
```

**Behavior:**
- Loads all screenshots from the platform folders  
- Sends each image to Gemini for OCR + semantic parsing  
- Saves structured setting objects

---

## 4.3.2 Merge Harvest Metadata + Extracted Text  
**File:** `database/merge_harvest_text.py`

This script merges:  
- `harvest_report.json` (from each platform’s crawling run)  
- `screenshot-classifier/extracted_settings.json`

It links each screenshot to:  
- the URL where it was captured  
- extracted setting text  
- metadata recorded during navigation (DOM node, screenshot type, etc.)

### Run Command
```bash
python database/merge_harvest_text.py
```

**Output:**  
`database/data/all_platforms_images.json`

**Behavior:**  
Produces a unified mapping of each screenshot → URL → extracted text.

---

## 4.3.3 Category Classification  
**File:** `database/classify_categories.py`

This script classifies each screenshot entry into a high-level privacy-setting category (e.g., Account Security, Data Sharing, Visibility, Ads/Personalization, Location, etc.).  
A `category` field is added to each screenshot entry.

### Run Command
```bash
python database/classify_categories.py
```

**Input:**  
`database/data/all_platforms_images.json`

**Output:**  
`database/data/all_platforms_classified.json`

**Behavior:**  
Each screenshot entry now contains:  
- platform  
- image
- full_image_path
- url  
- **category**

---

## 4.3 Chainlit Privacy Automation App  
**File:** `privacyagentapp/agenticapp.py`

Run with (be sure to change GEMINI_API_KEY to the one you get from https://aistudio.google.com/app/api-keys):

export GEMINI_API_KEY="your_key_here"
chainlit run privacyagentapp/agenticapp.py -w


Capabilities:

- Loads the curated multi-platform privacy settings database  
- Automates changing privacy settings on supported platforms  
- Verifies operations with Playwright + Gemini  
- Reports on changes

### Required Environment Variables (for agenticapp.py)

Only (be sure to change GEMINI_API_KEY to the one you get from https://aistudio.google.com/app/api-keys):

export GEMINI_API_KEY="your_key_here"

### Example Supported Commands

- `change twitterX audience__media_and_tagging::Protect your posts to on`
- `change instagram account_privacy::Private account to on`
- `change reddit allow_people_to_follow_you to on`

---

## 5. Folder Structure 

DSC180A_PrivacyProject/
├── gemini-team/
│   ├── generalssagent.py
│   ├── save_state.py
│   ├── generaloutput/
│   ├── profiles/
│   │   └── storage/
│   └── environment.yml
│
├── screenshot-classifier/
│   ├── screenshot_settings_extractor.py
│   └── extracted_settings.json
│
├── database/
│   ├── merge_harvest_text.py
│   ├── classify_categories.py
│   └── data/
│       ├── all_platforms_images.json
│       └── all_platforms_classified.json
│
├── privacyagentapp/
│   ├── agenticapp.py
│   └── database/
│
└── ANY OTHER FILES/FOLDERS

---

## 6. Runtime Behavior Notes

- If you encounter a Gemini 400 error, re-run the script.  
- macOS may require re-granting screen recording permissions.  
- Ensure a storageState JSON exists before running `generalssagent.py`.
- If encountering many Gemini 503 errors, run the script at a later time.
---
