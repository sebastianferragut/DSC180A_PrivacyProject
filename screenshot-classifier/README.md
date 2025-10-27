# Privacy Screenshot Classification System

A comprehensive system for analyzing and classifying privacy settings screenshots using Google's Gemini API. This tool can automatically categorize privacy settings pages, identify privacy concerns, and provide recommendations for privacy-conscious users.

## Features

- 🔍 **Screenshot Analysis**: Analyze individual privacy settings screenshots
- 🏷️ **Automatic Classification**: Categorize screenshots into privacy categories
- 📊 **Batch Processing**: Process multiple screenshots at once
- 🔒 **Privacy Audit**: Conduct comprehensive privacy audits
- 🎯 **Custom Categories**: Define custom privacy categories
- 📈 **Detailed Reports**: Generate detailed analysis reports

## Privacy Categories

The system recognizes the following privacy categories:

- **Data Collection**: Analytics, tracking, telemetry settings
- **Camera & Microphone**: Video/audio access permissions
- **Location Privacy**: GPS and geolocation settings
- **Personal Information**: Profile and contact information
- **Communication Privacy**: Messages, calls, meeting settings
- **Account Security**: Authentication and access controls
- **Sharing Settings**: Content visibility and audience controls
- **Notification Privacy**: Alert and notification preferences
- **Data Retention**: Data deletion and storage policies
- **Third-Party Sharing**: External integrations and partnerships

## Installation

### Using Conda (Recommended)

1. **Create the environment:**
   ```bash
   conda env create -f environment.yml
   ```

2. **Activate the environment:**
   ```bash
   conda activate privacy-project
   ```

3. **Install Playwright browsers:**
   ```bash
   playwright install
   ```

### Using Pip

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install Playwright browsers:**
   ```bash
   playwright install
   ```

## Setup

1. **Get a Gemini API Key:**
   - Visit [Google AI Studio](https://aistudio.google.com/app/api-keys)
   - Create a new API key
   - Copy the key for use in the next step

2. **Set Environment Variable:**
   ```bash
   export GEMINI_API_KEY="your_api_key_here"
   ```

   On Windows:
   ```cmd
   set GEMINI_API_KEY=your_api_key_here
   ```

## Usage

### Basic Usage

```python
from screenshot_classification import PrivacyScreenshotClassifier

# Initialize classifier
classifier = PrivacyScreenshotClassifier()

# Analyze a single screenshot
result = classifier.analyze_screenshot("privacy_settings.png")
print(result)

# Classify screenshot into categories
classification = classifier.classify_screenshot("privacy_settings.png")
print(classification)
```

### Batch Processing

```python
# Process multiple screenshots
results = classifier.batch_classify(
    "screenshots_directory/", 
    "results.json"
)
print(f"Processed {results['total_images']} images")
```

### Command Line Usage

```bash
# Run the main script
python screenshot-classification.py

# Run example usage
python example_usage.py
```

## Example Output

### Analysis Result
```json
{
  "application": "Zoom",
  "page_type": "Privacy Settings",
  "privacy_categories": ["data_collection", "camera_microphone", "communication_privacy"],
  "specific_settings": [
    "Allow Zoom to collect usage data",
    "Camera access permissions",
    "Meeting recording settings"
  ],
  "user_actions": [
    "Toggle data collection",
    "Change camera permissions",
    "Configure recording settings"
  ],
  "privacy_level": 6,
  "key_concerns": [
    "Data collection enabled by default",
    "Recording permissions unclear"
  ],
  "recommendations": [
    "Disable data collection",
    "Review recording permissions"
  ],
  "confidence": 0.85
}
```

### Classification Result
```json
{
  "image_path": "zoom_privacy_settings.png",
  "detected_categories": ["data_collection", "camera_microphone"],
  "category_scores": {
    "data_collection": 0.8,
    "camera_microphone": 0.9,
    "communication_privacy": 0.6
  },
  "primary_category": "camera_microphone",
  "confidence": 0.85
}
```

## File Structure

```
screenshot-classifier/
│
├── screenshot_classification.py    # ⭐ Main classifier module
│   ├── PrivacyScreenshotClassifier class
│   ├── analyze_screenshot()        # Analyze individual screenshots
│   ├── classify_screenshot()       # Classify into categories
│   └── batch_classify()            # Process multiple screenshots
│
├── requirements_simple.txt         # Essential dependencies
│   ├── google-genai>=1.44.0        # Gemini API client
│   ├── pillow>=11.0.0              # Image processing
│   └── requests>=2.31.0            # HTTP requests
│
├── screenshots/                    # Input directory
│   ├── *.png, *.jpg, etc.          # Screenshot images
│
└── Environment:
    └── GEMINI_API_KEY              # API key environment variable
```

### Supporting Files (Optional/Additional Tools)

```
screenshot-classifier/
│
├── 📚 Documentation
│   ├── README.md                  # Main documentation file
│   ├── README_SETUP.md            # Setup instructions
│   ├── QUICK_START.md             # Quick start guide
│   └── File-Tree.png              # Visual file tree
│
├── 🧪 Testing & Examples
│   ├── test_classifier.py         # Unit tests for classifier
│   └── example_usage.py           # Usage examples
│
├── 🔧 Configuration & Setup
│   ├── requirements_clean.txt     # Full dependency list
│   ├── environment.yml            # Conda environment config
│   ├── setup.py                   # Package installation script
│   └── setup_env.sh               # Environment setup script
│
├── 📊 Alternative Tools
│   ├── screenshot_summarizer.py   # Separate summarization tool
│   ├── view_summaries.py          # View summary results
│   └── config.py                  # Configuration file (unused)
│
└── 📁 Generated Outputs
    ├── classification_results.json # Batch results
    └── summaries.json              # Summary data
```


## API Reference

### PrivacyScreenshotClassifier

#### `__init__(api_key=None)`
Initialize the classifier with a Gemini API key.

#### `analyze_screenshot(image_path)`
Analyze a screenshot and return detailed privacy information.

**Parameters:**
- `image_path` (str): Path to the screenshot image

**Returns:**
- `dict`: Analysis results with privacy information

#### `classify_screenshot(image_path)`
Classify a screenshot into privacy categories.

**Parameters:**
- `image_path` (str): Path to the screenshot image

**Returns:**
- `dict`: Classification results with category scores

#### `batch_classify(image_directory, output_file=None)`
Process multiple screenshots in a directory.

**Parameters:**
- `image_directory` (str): Directory containing screenshots
- `output_file` (str, optional): File to save results

**Returns:**
- `dict`: Batch processing results

## Customization

### Adding Custom Categories

```python
classifier = PrivacyScreenshotClassifier()

# Add custom privacy categories
classifier.privacy_categories.update({
    "zoom_specific": {
        "keywords": ["zoom", "meeting", "webinar", "recording"],
        "description": "Zoom-specific privacy settings"
    },
    "social_media": {
        "keywords": ["social", "facebook", "twitter", "post"],
        "description": "Social media privacy settings"
    }
})
```

### Custom Analysis Prompts

You can modify the analysis prompt by overriding the `_create_analysis_prompt()` method:

```python
def _create_analysis_prompt(self):
    return """
    Your custom analysis prompt here...
    """
```

## Troubleshooting

### Common Issues

1. **API Key Not Set**
   ```
   ValueError: GEMINI_API_KEY environment variable not set
   ```
   **Solution:** Set your Gemini API key as an environment variable.

2. **Image Not Found**
   ```
   FileNotFoundError: Screenshot file not found
   ```
   **Solution:** Ensure the image file exists and the path is correct.

3. **API Rate Limits**
   ```
   Rate limit exceeded
   ```
   **Solution:** Add delays between API calls or use batch processing.

### Performance Tips

- Use batch processing for multiple screenshots
- Compress images before analysis to reduce API costs
- Cache results to avoid re-analyzing the same screenshots

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the example usage scripts

## Changelog

### v1.0.0
- Initial release
- Basic screenshot analysis
- Privacy category classification
- Batch processing support
- Example usage scripts
