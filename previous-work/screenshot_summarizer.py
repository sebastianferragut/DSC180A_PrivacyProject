#!/usr/bin/env python3
"""
Screenshot Summarizer

A simple and effective tool for analyzing screenshots and providing
clear summaries of what they show.
"""

import os
import json
from typing import Dict, Optional
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from google.genai.types import Content, Part


class ScreenshotSummarizer:
    """
    A simple screenshot summarizer using Google's Gemini API.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the summarizer with Gemini API key.
        
        Args:
            api_key: Google Gemini API key. If None, will try to get from environment.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set or api_key not provided")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_id = 'gemini-2.5-pro'
    
    def summarize_screenshot(self, image_path: str) -> Dict:
        """
        Summarize what's shown in a screenshot.
        
        Args:
            image_path: Path to the screenshot image file
            
        Returns:
            Dictionary containing summary results
        """
        try:
            # Check if file exists
            if not os.path.exists(image_path):
                return {
                    "status": "error",
                    "message": f"Screenshot file not found: {image_path}",
                    "timestamp": datetime.now().isoformat()
                }
            
            # Load and prepare image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create summarization prompt
            prompt = self._create_summarization_prompt()
            
            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[
                    Content(
                        role="user",
                        parts=[
                            Part(text=prompt),
                            Part.from_bytes(data=image_data, mime_type='image/png')
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1024
                )
            )
            
            # Parse response
            summary_text = response.candidates[0].content.parts[0].text
            return self._parse_summary_response(summary_text, image_path)
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to summarize screenshot: {str(e)}",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat()
            }
    
    def _create_summarization_prompt(self) -> str:
        """Create the summarization prompt for Gemini."""
        return """
        Analyze this screenshot and provide a clear, concise summary of what it shows.
        
        Please describe:
        1. **Application/Website**: What application, website, or program is this from?
        2. **Main Content**: What is the main purpose or content of this screen?
        3. **Key Elements**: What are the most important buttons, menus, text, or visual elements visible?
        4. **User Actions**: What can a user do on this screen? What actions are available?
        5. **Context**: Any additional context that would help someone understand what this screenshot shows?
        
        Provide a clear, informative summary that would help someone understand what this screenshot 
        contains without needing to see the actual image. Be specific and detailed but concise.
        
        Format your response as a well-structured summary with clear sections.
        """
    
    def _parse_summary_response(self, response_text: str, image_path: str) -> Dict:
        """Parse the Gemini response and structure the data."""
        try:
            return {
                "status": "success",
                "image_path": image_path,
                "summary": response_text,
                "timestamp": datetime.now().isoformat(),
                "model_used": self.model_id
            }
        except Exception as e:
            return {
                "status": "partial_success",
                "image_path": image_path,
                "raw_response": response_text,
                "timestamp": datetime.now().isoformat(),
                "message": f"Could not fully parse response: {str(e)}"
            }
    
    def batch_summarize(self, image_directory: str, output_file: Optional[str] = None) -> Dict:
        """
        Summarize multiple screenshots in a directory.
        
        Args:
            image_directory: Directory containing screenshot images
            output_file: Optional file to save results
            
        Returns:
            Batch summarization results
        """
        image_dir = Path(image_directory)
        if not image_dir.exists():
            return {"status": "error", "message": f"Directory {image_directory} does not exist"}
        
        # Find image files
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
        image_files = [
            f for f in image_dir.iterdir() 
            if f.suffix.lower() in image_extensions
        ]
        
        if not image_files:
            return {"status": "error", "message": "No image files found in directory"}
        
        results = {
            "status": "success",
            "total_images": len(image_files),
            "summaries": [],
            "timestamp": datetime.now().isoformat()
        }
        
        # Process each image
        for image_file in image_files:
            print(f"📸 Summarizing {image_file.name}...")
            summary = self.summarize_screenshot(str(image_file))
            results["summaries"].append(summary)
        
        # Save results if output file specified
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"💾 Results saved to {output_file}")
        
        return results


def main():
    """Example usage of the ScreenshotSummarizer."""
    print("🚀 Screenshot Summarizer")
    print("=" * 40)
    
    # Initialize summarizer
    try:
        summarizer = ScreenshotSummarizer()
        print("✅ Screenshot Summarizer initialized successfully")
    except ValueError as e:
        print(f"❌ Error: {e}")
        print("Please set your GEMINI_API_KEY environment variable")
        return
    
    # Example: Summarize a single screenshot
    # Replace with your actual screenshot path
    screenshot_path = "screenshots/general_20251022_102721.png"
    
    if os.path.exists(screenshot_path):
        print(f"\n📸 Analyzing screenshot: {screenshot_path}")
        result = summarizer.summarize_screenshot(screenshot_path)
        
        if result["status"] == "success":
            print("📊 Summary:")
            print("-" * 40)
            print(result["summary"])
        else:
            print(f"❌ Error: {result['message']}")
    else:
        print(f"⚠️  Screenshot file not found: {screenshot_path}")
        print("Please provide a valid screenshot path")
    
    # Example: Batch summarization
    screenshots_dir = "screenshots"
    
    if os.path.exists(screenshots_dir):
        print(f"\n📸 Batch summarizing screenshots in: {screenshots_dir}")
        batch_results = summarizer.batch_summarize(screenshots_dir, "summaries.json")
        
        if batch_results["status"] == "success":
            print(f"✅ Processed {batch_results['total_images']} screenshots")
            print("📊 Individual summaries:")
            for summary in batch_results["summaries"]:
                if summary["status"] == "success":
                    print(f"\n📸 {Path(summary['image_path']).name}:")
                    print("-" * 30)
                    print(summary["summary"][:200] + "..." if len(summary["summary"]) > 200 else summary["summary"])
        else:
            print(f"❌ Batch processing error: {batch_results['message']}")
    else:
        print(f"⚠️  Screenshots directory not found: {screenshots_dir}")


if __name__ == "__main__":
    main()
