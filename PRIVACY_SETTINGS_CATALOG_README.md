# Privacy Settings Catalog

This document describes the two JSON catalog files that contain all privacy settings organized by category.

## 📁 Files

### 1. **Privacy Map Settings Catalog**
- **Location**: `gemini-team/privacy_settings_catalog.json`
- **Source**: Generated from `privacy_summary.json` (from web crawler)
- **Script**: `gemini-team/extract_privacy_settings.py`

### 2. **Screenshot Settings Catalog**
- **Location**: `screenshot-classifier/screenshot_privacy_settings_catalog.json`
- **Source**: Generated from `classification_summary.json` (from screenshot classifier)
- **Script**: `screenshot-classifier/extract_screenshot_settings.py`

## 🚀 Usage

### Generate Privacy Map Settings Catalog
```bash
cd gemini-team
python extract_privacy_settings.py
```

### Generate Screenshot Settings Catalog
```bash
cd screenshot-classifier
python extract_screenshot_settings.py
```

## 📊 JSON Structure

### Privacy Map Settings Catalog Structure

```json
{
  "metadata": {
    "generated_at": "2025-11-11T16:44:51.470529",
    "source_file": "privacy_summary.json",
    "total_settings": 364,
    "unique_settings": 24,
    "categories": 8,
    "total_pages": 38,
    "total_files": 3,
    "host": "zoom.us"
  },
  "categories": {
    "account_security": {
      "category": "account_security",
      "total_occurrences": 9,
      "unique_settings_count": 3,
      "settings": [
        {
          "setting": "Require that all meetings are secured with one security option",
          "type": "checkbox",
          "categories": ["communication_privacy", "account_security"],
          "pages": ["https://zoom.us/profile/setting?tab=meeting"],
          "files": ["privacy_map_20251029_131608.json", ...],
          "selectors": ["zoom-toggle__original"]
        }
      ]
    }
  },
  "all_settings": [...],
  "category_statistics": {...}
}
```

### Screenshot Settings Catalog Structure

```json
{
  "metadata": {
    "generated_at": "2025-11-11T16:45:06.612306",
    "source_file": "classification_summary.json",
    "total_settings": 30,
    "unique_settings": 15,
    "categories": 5,
    "total_screenshots": 8,
    "total_files": 2,
    "average_confidence": 1.0
  },
  "categories": {
    "access_to_device": {
      "category": "access_to_device",
      "total_occurrences": 26,
      "unique_settings_count": 13,
      "settings": [
        {
          "setting": "Banner prompt: 'Please enable access to your microphone and camera...'",
          "categories": ["access_to_device", "personal_information", ...],
          "images": ["security_menu_fullpage_20251022_110816.png"],
          "page_types": ["In-Meeting Security Settings Menu"],
          "files": ["classification_results.json"],
          "average_confidence": 1.0
        }
      ]
    }
  },
  "all_settings": [...],
  "category_statistics": {...}
}
```

## 📋 Fields Explained

### Privacy Map Settings Catalog

#### Metadata
- `generated_at`: Timestamp when catalog was generated
- `source_file`: Source summary file
- `total_settings`: Total number of setting occurrences
- `unique_settings`: Number of unique settings
- `categories`: Number of categories found
- `total_pages`: Total pages analyzed
- `total_files`: Number of privacy map files
- `host`: Website host (e.g., "zoom.us")

#### Category Settings
- `category`: Category name
- `total_occurrences`: Total times settings in this category appear
- `unique_settings_count`: Number of unique settings
- `settings`: Array of setting objects
  - `setting`: Setting label/text
  - `type`: Control type (checkbox, button, etc.)
  - `categories`: Categories this setting belongs to
  - `pages`: URLs where this setting appears
  - `files`: Files where this setting was found
  - `selectors`: CSS selectors for this control

### Screenshot Settings Catalog

#### Metadata
- `generated_at`: Timestamp when catalog was generated
- `source_file`: Source summary file
- `total_settings`: Total number of setting occurrences
- `unique_settings`: Number of unique settings
- `categories`: Number of categories found
- `total_screenshots`: Total screenshots analyzed
- `total_files`: Number of classification files
- `average_confidence`: Average confidence score

#### Category Settings
- `category`: Category name
- `total_occurrences`: Total times settings in this category appear
- `unique_settings_count`: Number of unique settings
- `settings`: Array of setting objects
  - `setting`: Setting label/text
  - `categories`: Categories this setting belongs to
  - `images`: Screenshot images where this setting appears
  - `page_types`: Types of pages where this setting appears
  - `files`: Files where this setting was found
  - `average_confidence`: Average confidence score for this setting

## 🎯 Use Cases

### 1. **Privacy Settings Inventory**
- Complete list of all privacy settings found
- Organized by category for easy navigation
- Includes metadata about where settings appear

### 2. **Category Analysis**
- See which categories have the most settings
- Identify categories with few or no settings
- Analyze category coverage

### 3. **Setting Tracking**
- Track which settings appear in which pages/files
- Identify settings that appear across multiple files
- Find settings by category

### 4. **Comparison**
- Compare settings between web crawler and screenshot classifier
- Identify settings found in one method but not the other
- Analyze differences in detection

### 5. **Documentation**
- Generate documentation of all privacy settings
- Create reports with setting details
- Export for further analysis

## 📊 Example Queries

### Find all settings in a category
```python
import json

with open('privacy_settings_catalog.json') as f:
    catalog = json.load(f)

account_security_settings = catalog['categories']['account_security']['settings']
for setting in account_security_settings:
    print(setting['setting'])
```

### Find settings appearing in multiple files
```python
import json

with open('privacy_settings_catalog.json') as f:
    catalog = json.load(f)

for category_name, category_data in catalog['categories'].items():
    for setting in category_data['settings']:
        if len(setting['files']) > 1:
            print(f"{setting['setting']}: {len(setting['files'])} files")
```

### Find settings by page URL
```python
import json

with open('privacy_settings_catalog.json') as f:
    catalog = json.load(f)

target_url = "https://zoom.us/profile/setting?tab=meeting"
for category_name, category_data in catalog['categories'].items():
    for setting in category_data['settings']:
        if target_url in setting['pages']:
            print(setting['setting'])
```

## 🔄 Updating Catalogs

Catalogs should be regenerated whenever:
- New privacy map files are added
- New classification results are generated
- Summary files are updated

### Regeneration Workflow

1. **Update Privacy Map Catalog**:
   ```bash
   cd gemini-team
   python privacy_map_summarizer.py  # Generate summary
   python extract_privacy_settings.py  # Generate catalog
   ```

2. **Update Screenshot Catalog**:
   ```bash
   cd screenshot-classifier
   python screenshot_classification_summarizer.py  # Generate summary
   python extract_screenshot_settings.py  # Generate catalog
   ```

## 📝 Notes

- Catalogs are generated from summary files, not directly from source data
- Settings may appear in multiple categories
- Unique settings are determined by normalized setting text (lowercase, stripped)
- Catalogs include metadata for traceability
- All settings include references to source files/pages

## 🎓 Key Differences

### Privacy Map Catalog
- Based on web crawler data
- Includes CSS selectors
- Includes page URLs
- More detailed control information
- Based on HTML parsing

### Screenshot Catalog
- Based on screenshot analysis
- Includes confidence scores
- Includes image references
- Includes page type information
- Based on visual analysis

## 📚 Related Files

- `privacy_map_summarizer.py`: Generates privacy summary
- `screenshot_classification_summarizer.py`: Generates classification summary
- `privacy_summary.json`: Source for privacy map catalog
- `classification_summary.json`: Source for screenshot catalog

## ✅ Benefits

1. **Centralized Inventory**: All settings in one place
2. **Category Organization**: Easy to find settings by category
3. **Metadata Rich**: Includes source information
4. **Traceable**: Can track settings back to source files
5. **Analyzable**: JSON format allows for programmatic analysis
6. **Comparable**: Can compare between web crawler and screenshot methods

Enjoy exploring your privacy settings catalogs! 🔍

