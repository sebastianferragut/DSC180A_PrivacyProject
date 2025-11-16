# URL Navigation Script

This script allows you to navigate to URLs from `facebook.json` using Playwright. This is the first step in creating a tool to navigate to specific privacy settings pages.

## 🎯 Purpose

The `navigate_to_urls.py` script:
- Loads URLs from `facebook.json`
- Extracts different categories of URLs (visited, sections, actions)
- Uses Playwright to navigate to these URLs
- Can take screenshots of pages
- Provides a foundation for finding specific privacy settings

## 📋 URL Categories

The script extracts URLs from different parts of the JSON:

1. **visited_urls**: All pages visited during the crawl (from `state.visited_urls`)
2. **section_urls**: URLs where privacy sections were found (from `sections[].url`)
3. **action_urls**: URLs from action events (from `actions[].url`)
4. **all_unique**: All unique URLs combined and deduplicated

## 🚀 Usage

### Basic Usage

```bash
cd graphdata
python navigate_to_urls.py
```

This will:
1. Load `json_data/facebook.json`
2. Display available URL categories
3. Start a browser (non-headless by default)
4. Navigate to the first URL as an example
5. Give you options to navigate to more URLs

### Programmatic Usage

```python
from navigate_to_urls import URLNavigator

# Initialize navigator
navigator = URLNavigator("json_data/facebook.json", headless=False)

# Get all URLs
urls = navigator.get_all_urls()
print(f"Found {len(urls['all_unique'])} unique URLs")

# Start browser
navigator.start_browser()

# Navigate to a specific URL
result = navigator.navigate_to_url("https://accountscenter.facebook.com/password_and_security")
if result["status"] == "success":
    print(f"Successfully navigated to: {result['title']}")

# Take a screenshot
navigator.take_screenshot("screenshots/password_security.png")

# Navigate to all URLs in a category
results = navigator.navigate_all_urls("visited_urls", wait_between=3.0)

# Close browser
navigator.close_browser()
```

## 🔧 Features

### URL Extraction
- Extracts URLs from multiple sources in the JSON
- Deduplicates URLs
- Organizes URLs by category

### Navigation
- Navigates to URLs using Playwright
- Waits for page load
- Handles errors gracefully
- Returns navigation results with status

### Screenshots
- Takes full-page screenshots
- Auto-generates filenames from URLs
- Saves to `screenshots/` directory

### Browser Control
- Start/stop browser
- Configure headless mode
- Set viewport size
- Get current page info

## 📊 Example Output

```
🔍 Facebook URL Navigator
============================================================

📋 Available URLs:

  visited_urls: 6 URLs
    • https://accountscenter.facebook.com/password_and_security
    • https://accountscenter.facebook.com/info_and_permissions
    • https://accountscenter.facebook.com/ads
    ... and 3 more

  section_urls: 2 URLs
    • https://accountscenter.facebook.com/personal_info
    • https://accountscenter.facebook.com/personal_info/account_ownership_and_control

  all_unique: 6 URLs
    • https://accountscenter.facebook.com/password_and_security
    • https://accountscenter.facebook.com/info_and_permissions
    • https://accountscenter.facebook.com/ads
    ... and 3 more

🚀 Starting browser...
✅ Browser started

🌐 Navigating to first URL as example...
🌐 Navigating to: https://accountscenter.facebook.com/password_and_security
   ✅ Successfully navigated to: Facebook Account Center
   📍 Current URL: https://accountscenter.facebook.com/password_and_security
📸 Screenshot saved: screenshots/accountscenter.facebook.com_password_and_security.png
```

## 🎯 Next Steps

This script is the foundation for:
1. **Finding specific privacy settings**: Navigate to pages and search for settings
2. **Extracting settings data**: Parse page content to find privacy controls
3. **Automated navigation**: Build a system to navigate to specific settings
4. **Settings catalog**: Create a comprehensive map of privacy settings locations

## 🔗 Related Files

- `json_data/facebook.json`: Source data with URLs
- `ingest_run.py`: Neo4j ingestion script
- `queries/get_sections.py`: Example queries

## 💡 Tips

- Use `headless=False` to see the browser (useful for debugging)
- Use `headless=True` for automated runs
- Adjust `wait_between` time based on page load speed
- Screenshots are saved in `screenshots/` directory
- The script handles errors gracefully and continues

## 🐛 Troubleshooting

**Playwright not installed:**
```bash
pip install playwright
playwright install chromium
```

**URLs not loading:**
- Check that `json_data/facebook.json` exists
- Verify the JSON structure matches expected format
- Check network connectivity

**Browser not starting:**
- Ensure Playwright browsers are installed
- Check system permissions
- Try running with `headless=True`

Enjoy navigating to privacy settings! 🚀

