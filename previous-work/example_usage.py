#!/usr/bin/env python3
"""
Example usage of the Screenshot Summarizer

This script shows how to use the ScreenshotSummarizer class
to analyze individual screenshots or batch process multiple images.
"""

import os
from screenshot_summarizer import ScreenshotSummarizer


def example_single_screenshot():
    """Example: Summarize a single screenshot."""
    print("🔍 Example: Single Screenshot Summary")
    print("=" * 50)
    
    # Initialize summarizer
    summarizer = ScreenshotSummarizer()
    
    # Example screenshot path (replace with your actual screenshot)
    screenshot_path = "screenshots/general_20251022_102721.png"
    
    if os.path.exists(screenshot_path):
        print(f"Analyzing: {screenshot_path}")
        
        # Get summary
        result = summarizer.summarize_screenshot(screenshot_path)
        
        if result["status"] == "success":
            print("\n📊 Summary:")
            print("-" * 30)
            print(result["summary"])
        else:
            print(f"❌ Error: {result['message']}")
        
    else:
        print(f"⚠️  Screenshot not found: {screenshot_path}")
        print("Please add a screenshot to test with")


def example_batch_processing():
    """Example: Process multiple screenshots."""
    print("\n🔍 Example: Batch Processing")
    print("=" * 50)
    
    summarizer = ScreenshotSummarizer()
    
    # Directory containing screenshots
    screenshots_dir = "screenshots"
    
    if os.path.exists(screenshots_dir):
        print(f"Processing screenshots in: {screenshots_dir}")
        
        # Batch summarize with output file
        results = summarizer.batch_summarize(
            screenshots_dir, 
            "batch_summaries.json"
        )
        
        if results["status"] == "success":
            print(f"\n📊 Batch Results Summary:")
            print(f"Total images: {results['total_images']}")
            
            # Show first few summaries
            for i, summary in enumerate(results["summaries"][:3]):  # Show first 3
                if summary["status"] == "success":
                    filename = os.path.basename(summary["image_path"])
                    print(f"\n📸 {filename}:")
                    print("-" * 30)
                    # Show first 150 characters of summary
                    short_summary = summary["summary"][:150] + "..." if len(summary["summary"]) > 150 else summary["summary"]
                    print(short_summary)
            
            if len(results["summaries"]) > 3:
                print(f"\n... and {len(results['summaries']) - 3} more summaries")
                
        else:
            print(f"❌ Batch processing error: {results['message']}")
            
    else:
        print(f"⚠️  Directory not found: {screenshots_dir}")
        print("Please create a directory with your screenshots")


def example_custom_usage():
    """Example: Custom usage patterns."""
    print("\n🔍 Example: Custom Usage")
    print("=" * 50)
    
    summarizer = ScreenshotSummarizer()
    
    # You can also use it in a loop for specific files
    specific_files = [
        "screenshots/audio_conferencing_20251022_110156.png",
        "screenshots/security_menu_fullpage_20251022_110816.png"
    ]
    
    for file_path in specific_files:
        if os.path.exists(file_path):
            print(f"\n📸 Processing: {os.path.basename(file_path)}")
            result = summarizer.summarize_screenshot(file_path)
            
            if result["status"] == "success":
                print("✅ Summary generated successfully")
                # You could save individual results, process them, etc.
            else:
                print(f"❌ Failed: {result['message']}")
        else:
            print(f"⚠️  File not found: {file_path}")


def main():
    """Run all examples."""
    print("🚀 Screenshot Summarizer - Example Usage")
    print("=" * 60)
    
    # Check for API key
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY environment variable not set")
        print("Please run: source setup_env.sh")
        return
    
    try:
        # Run examples
        example_single_screenshot()
        example_batch_processing()
        example_custom_usage()
        
        print("\n✅ All examples completed!")
        print("\n📚 Next steps:")
        print("1. Try running the main summarizer: python screenshot_summarizer.py")
        print("2. Modify the code to suit your specific needs")
        print("3. Add your own screenshots to test with")
        
    except Exception as e:
        print(f"❌ Error running examples: {e}")
        print("Make sure you have the required dependencies installed")


if __name__ == "__main__":
    main()