"""
Example Usage of Privacy Screenshot Classifier

This script demonstrates how to use the PrivacyScreenshotClassifier
to analyze privacy settings screenshots.

Not used.
"""

import os
import json
from screenshot_classification import PrivacyScreenshotClassifier


def example_single_screenshot():
    """Example: Analyze a single screenshot."""
    print("🔍 Example: Single Screenshot Analysis")
    print("=" * 50)
    
    # Initialize classifier
    classifier = PrivacyScreenshotClassifier()
    
    # Example screenshot path (replace with your actual screenshot)
    screenshot_path = "zoom_privacy_settings.png"
    
    if os.path.exists(screenshot_path):
        print(f"Analyzing: {screenshot_path}")
        
        # Get detailed analysis
        analysis = classifier.analyze_screenshot(screenshot_path)
        print("\n📊 Detailed Analysis:")
        print(json.dumps(analysis, indent=2))
        
        # Get classification
        classification = classifier.classify_screenshot(screenshot_path)
        print("\n🏷️  Classification:")
        print(json.dumps(classification, indent=2))
        
    else:
        print(f"⚠️  Screenshot not found: {screenshot_path}")
        print("Please add a privacy settings screenshot to test with")


def example_batch_processing():
    """Example: Process multiple screenshots."""
    print("\n🔍 Example: Batch Processing")
    print("=" * 50)
    
    classifier = PrivacyScreenshotClassifier()
    
    # Directory containing screenshots
    screenshots_dir = "privacy_screenshots"
    
    if os.path.exists(screenshots_dir):
        print(f"Processing screenshots in: {screenshots_dir}")
        
        # Batch classify with output file
        results = classifier.batch_classify(
            screenshots_dir, 
            "batch_results.json"
        )
        
        print("\n📊 Batch Results Summary:")
        print(f"Total images: {results['total_images']}")
        print(f"Successful: {results['summary']['successful_classifications']}")
        print(f"Failed: {results['summary']['failed_classifications']}")
        
        print("\n📈 Category Distribution:")
        for category, count in results['summary']['category_distribution'].items():
            print(f"  {category}: {count}")
            
    else:
        print(f"⚠️  Directory not found: {screenshots_dir}")
        print("Please create a directory with your privacy screenshots")


def example_custom_categories():
    """Example: Using custom privacy categories."""
    print("\n🔍 Example: Custom Categories")
    print("=" * 50)
    
    classifier = PrivacyScreenshotClassifier()
    
    # Add custom categories
    classifier.privacy_categories.update({
        "zoom_specific": {
            "keywords": ["zoom", "meeting", "webinar", "recording", "cloud recording"],
            "description": "Zoom-specific privacy settings"
        },
        "social_media": {
            "keywords": ["social", "facebook", "twitter", "instagram", "linkedin", "post"],
            "description": "Social media privacy settings"
        }
    })
    
    print("Added custom categories:")
    for cat, info in classifier.privacy_categories.items():
        if cat in ["zoom_specific", "social_media"]:
            print(f"  {cat}: {info['description']}")


def example_privacy_audit():
    """Example: Conduct a privacy audit of screenshots."""
    print("\n🔍 Example: Privacy Audit")
    print("=" * 50)
    
    classifier = PrivacyScreenshotClassifier()
    
    # Simulate audit results
    audit_results = {
        "total_screenshots": 5,
        "privacy_levels": [7, 4, 8, 6, 3],  # 1-10 scale
        "common_concerns": [
            "Data collection enabled by default",
            "Location tracking not clearly disclosed",
            "Third-party sharing options unclear"
        ],
        "recommendations": [
            "Disable analytics and tracking",
            "Review data retention settings",
            "Limit third-party integrations"
        ]
    }
    
    print("🔒 Privacy Audit Results:")
    print(f"Average privacy level: {sum(audit_results['privacy_levels'])/len(audit_results['privacy_levels']):.1f}/10")
    print(f"Total screenshots analyzed: {audit_results['total_screenshots']}")
    
    print("\n⚠️  Common Privacy Concerns:")
    for concern in audit_results['common_concerns']:
        print(f"  • {concern}")
    
    print("\n💡 Recommendations:")
    for rec in audit_results['recommendations']:
        print(f"  • {rec}")


def create_sample_directory():
    """Create a sample directory structure for testing."""
    print("\n📁 Creating Sample Directory Structure")
    print("=" * 50)
    
    # Create directories
    os.makedirs("privacy_screenshots", exist_ok=True)
    os.makedirs("results", exist_ok=True)
    
    # Create sample files
    sample_files = [
        "privacy_screenshots/zoom_settings.png",
        "privacy_screenshots/facebook_privacy.png", 
        "privacy_screenshots/google_account.png",
        "privacy_screenshots/instagram_settings.png"
    ]
    
    for file_path in sample_files:
        if not os.path.exists(file_path):
            # Create empty placeholder files
            with open(file_path, 'w') as f:
                f.write("# Placeholder for screenshot file")
            print(f"Created placeholder: {file_path}")
    
    print("\n📂 Directory structure created:")
    print("privacy_screenshots/")
    print("├── zoom_settings.png")
    print("├── facebook_privacy.png")
    print("├── google_account.png")
    print("└── instagram_settings.png")
    print("results/")
    print("└── (for output files)")


def main():
    """Run all examples."""
    print("🚀 Privacy Screenshot Classifier - Example Usage")
    print("=" * 60)
    
    # Check for API key
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY environment variable not set")
        print("Please set your Google Gemini API key:")
        print("export GEMINI_API_KEY='your_api_key_here'")
        return
    
    try:
        # Create sample directory structure
        create_sample_directory()
        
        # Run examples
        example_single_screenshot()
        example_batch_processing()
        example_custom_categories()
        example_privacy_audit()
        
        print("\n✅ All examples completed!")
        print("\n📚 Next steps:")
        print("1. Add your actual privacy screenshots to the 'privacy_screenshots/' directory")
        print("2. Run the classifier on your screenshots")
        print("3. Review the results in the generated JSON files")
        
    except Exception as e:
        print(f"❌ Error running examples: {e}")
        print("Make sure you have the required dependencies installed")


if __name__ == "__main__":
    main()
