"""
Privacy Settings Extractor for Screenshots

This system uses Google's Gemini API to extract individual privacy settings
from screenshots of privacy settings pages, including setting names, descriptions,
and their current states.
"""

import os
import json
import re
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from google.genai.types import Content, Part


class PrivacySettingsExtractor:
    """
    Extracts individual privacy settings from screenshots using Google's Gemini API.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the extractor with Gemini API key. Sets up the Gemini client for API calls.
        
        Args:
            api_key: Google Gemini API key. If None, will try to get from environment.
        """

        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set or API key not provided")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_id = 'gemini-2.5-pro'

    def _create_extraction_prompt(self) -> str:
        """Creates the prompt that instructs Gemini to extract all individual privacy settings with their names, descriptions, and states from a screenshot."""
        return """
                You are analyzing a screenshot of a privacy settings page. Your task is to extract ALL individual privacy settings visible in the screenshot.

                For each setting, identify:
                1. **Application/Service**: What application or service is this privacy settings page for?
                2. **Page Type**: What type of privacy settings page is this (e.g., main settings, specific category, etc.)?
                3. **Setting Name**: The exact name or label of the setting (e.g., "Camera Access", "Location Services", "Share Analytics Data")
                4. **Description**: A brief description of what the setting controls or what it does (e.g. "Show the link for Zoom International Dial-in Numbers on email invitations")
                5. **State**: The current state/value of the setting if applicable. This could be:
                    - "enabled" or "disabled" (for toggles/switches)
                    - "on" or "off"
                    - A specific value (e.g., "Public", "Private", "Friends Only")
                    - A selected option from a dropdown or list
                    - Any other state indicator visible in the UI

                    Extract ALL settings visible in the screenshot, including:
                    - Toggles and switches
                    - Dropdown menus and selectors
                    - Radio buttons
                    - Checkboxes
                    - Sliders
                    - Any other privacy-related controls

                Please respond in JSON format with the following structure:
                {
                    "application": "string - name of the application/service",
                    "page_type": "string - type of privacy settings page",
                    "settings": [
                        {
                            "setting": "string - name of the setting",
                            "description": "string - what this setting controls",
                            "state": "string - current state/value of the setting"
                        }
                    ]
                }

                Be thorough and extract every privacy setting visible in the screenshot. If no settings are visible, return an empty settings array.
                """

    def _parse_extraction_response(self, response_text: str, image_path: str) -> Dict:

        """Parses the JSON response from Gemini, adds image_path to each setting, and includes metadata like timestamp and settings count."""

        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                extraction_data = json.loads(json_match.group())
            else:
                # Fallback: create structured response from text
                extraction_data = {
                    "application": "unknown",
                    "settings": [],
                    "raw_response": response_text,
                    "parsed": False
                }
            
            # Ensure settings array exists
            if "settings" not in extraction_data:
                extraction_data["settings"] = []
            
            # Add image_path to each setting
            for setting in extraction_data["settings"]:
                setting["image_path"] = image_path
            
            # Add metadata
            extraction_data.update({
                "status": "success",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "model_used": self.model_id,
                "settings_count": len(extraction_data["settings"])
            })
            
            return extraction_data
            
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "message": f"Could not parse JSON response: {str(e)}",
                "raw_response": response_text,
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "settings": []
            }
    
    def extract_settings(self, image_path: str) -> Dict:

        """
        Extracts all privacy settings from a single screenshot by sending it to Gemini API and parsing the response.
        Returns a dictionary with the application name, list of settings (each with name, description, state, and image_path), and metadata.
        
        Args:
            image_path: Path to the screenshot image file
            
        Returns:
            Dictionary containing extracted settings with image_path for each setting
        """

        try:
            # Load and prepare image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create extraction prompt
            extraction_prompt = self._create_extraction_prompt()
            
            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[
                    Content(
                        role="user",
                        parts=[
                            Part(text=extraction_prompt),
                            Part.from_bytes(data=image_data, mime_type='image/png')
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=4096  # Increased for potentially many settings
                )
            )
            
            # Parse response
            extraction_text = response.candidates[0].content.parts[0].text
            extraction_data = self._parse_extraction_response(extraction_text, image_path)
            
            return extraction_data
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to extract settings: {str(e)}",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "settings": []
            }

    def batch_extract(self, image_directory: str, output_file: Optional[str] = None) -> Dict:
        
        """
        Processes all screenshots in a directory, extracts settings from each, and returns a flattened list of all settings plus per-image results.
        Optionally saves results to a JSON file.
        
        Args:
            image_directory: Directory containing screenshot images
            output_file: Optional file to save results
            
        Returns:
            Batch extraction results with all settings flattened
        """

        image_dir = Path(image_directory)
        if not image_dir.exists():
            return {"status": "error", "message": f"Directory {image_directory} does not exist"}
        
        # Find image files
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
        image_files = [f for f in image_dir.iterdir() if f.suffix.lower() in image_extensions]
        
        if not image_files:
            return {"status": "error", "message": "No image files found in directory"}
        
        results = {
            "status": "success",
            "total_images": len(image_files),
            "all_settings": [],  # Flattened list of all settings
            "by_image": [],  # Per-image extraction results
            "summary": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Process each image
        total_settings = 0
        successful_extractions = 0
        failed_extractions = 0
        
        for image_file in image_files:
            print(f"Processing {image_file.name}...")
            extraction = self.extract_settings(str(image_file))
            
            # Add to per-image results
            results["by_image"].append({
                "image_path": str(image_file),
                "status": extraction.get("status", "unknown"),
                "application": extraction.get("application", "unknown"),
                "settings_count": extraction.get("settings_count", 0),
                "settings": extraction.get("settings", [])
            })
            
            # Flatten settings into all_settings
            if extraction.get("status") == "success":
                successful_extractions += 1
                settings = extraction.get("settings", [])
                results["all_settings"].extend(settings)
                total_settings += len(settings)
            else:
                failed_extractions += 1
                print(f"  ⚠️  Failed to extract from {image_file.name}: {extraction.get('message', 'Unknown error')}")
        
        # Generate summary
        results["summary"] = {
            "total_settings_extracted": total_settings,
            "successful_extractions": successful_extractions,
            "failed_extractions": failed_extractions,
            "average_settings_per_image": round(total_settings / successful_extractions, 2) if successful_extractions > 0 else 0
        }
        
        # Save results if output file specified
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\n✅ Results saved to {output_file}")
            print(f"📊 Extracted {total_settings} settings from {successful_extractions} images")
        
        return results


def main():
    
    """Main entry point that initializes the extractor and processes all screenshots in the 'screenshots' directory, saving results to 'extracted_settings.json'."""
    
    # Initialize extractor
    try:
        extractor = PrivacySettingsExtractor()
        print("✅ Privacy Settings Extractor initialized successfully")
    except ValueError as e:
        print(f"❌ Error: {e}")
        print("Please set your GEMINI_API_KEY environment variable")
        return
    
    # Batch extract settings from screenshots
    screenshots_dir = "screenshots"
    
    if os.path.exists(screenshots_dir):
        print(f"\n🔍 Extracting settings from screenshots in: {screenshots_dir}")
        results = extractor.batch_extract(screenshots_dir, "extracted_settings.json")
        
        if results.get("status") == "success":
            print(f"\n📊 Summary:")
            print(f"  Total images processed: {results['total_images']}")
            print(f"  Successful extractions: {results['summary']['successful_extractions']}")
            print(f"  Failed extractions: {results['summary']['failed_extractions']}")
            print(f"  Total settings extracted: {results['summary']['total_settings_extracted']}")
            print(f"  Average settings per image: {results['summary']['average_settings_per_image']}")
        else:
            print(f"❌ Error: {results.get('message', 'Unknown error')}")
    else:
        print(f"⚠️ Screenshots directory not found: {screenshots_dir}")
        print("Please create a directory with your screenshot files")


if __name__ == "__main__":
    main()

