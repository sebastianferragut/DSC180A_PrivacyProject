# Privacy Agent

A privacy-focused automation tool that uses AI vision to interact with Zoom application.

## Features

- Automatically opens Zoom application
- Takes screenshots of the current screen
- Uses Google Gemini AI to analyze screenshots and determine click locations
- Performs automated clicking based on AI analysis

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure Zoom is installed on your macOS system

3. Run the agent:
```bash
python privacy_agent.py
```

## Usage

The agent will:
1. Check if Zoom is running, and open it if not
2. Take a screenshot of the current screen
3. Use Gemini AI to analyze the screenshot
4. Automatically click on the appropriate locations

## Safety Features

- Failsafe enabled: Move mouse to corner of screen to stop automation
- Process checking to avoid duplicate Zoom instances
- Error handling for robust operation

## Requirements

- macOS (uses `open` command)
- Python 3.7+
- Zoom application installed
- Google Gemini API key (for AI analysis)

