# Quick Start Guide

## Set Your API Key

Before running the summarizer, set your Google Gemini API key:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

## Run the Setup

```bash
source setup_env.sh
```

## Run the Summarizer

```bash
python screenshot_summarizer.py
```

## View Results

```bash
python view_summaries.py
```

---

**Note:** Your API key should never be committed to version control. Always use environment variables.
