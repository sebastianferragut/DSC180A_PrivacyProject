# Screenshot Summarizer - Setup Guide

## 📋 Setup Instructions

### 1. Get Your Google Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/app/api-keys)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the generated key

### 2. Set Up Your API Key

#### Option A: Temporary (for current session only)
```bash
export GEMINI_API_KEY="your_api_key_here"
```

#### Option B: Permanent (recommended)
Add to your shell configuration file:

**For zsh (default on macOS):**
```bash
echo 'export GEMINI_API_KEY="your_api_key_here"' >> ~/.zshrc
source ~/.zshrc
```

**For bash:**
```bash
echo 'export GEMINI_API_KEY="your_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

### 3. Activate the Environment

```bash
source setup_env.sh
```

### 4. Verify Setup

```bash
python -c "import os; print('API Key set:', 'Yes' if os.environ.get('GEMINI_API_KEY') else 'No')"
```

## 🚀 Usage

### Run the Summarizer
```bash
python screenshot_summarizer.py
```

### View Summaries
```bash
python view_summaries.py
```

### Run Examples
```bash
python example_usage.py
```

## 📝 Notes

- The API key is stored in your environment variables, not in the code files
- Never share your API key publicly
- The API key is used to make calls to Google's Gemini API
