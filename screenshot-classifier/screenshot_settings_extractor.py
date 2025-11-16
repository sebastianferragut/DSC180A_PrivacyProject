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

    def _slice_vertical(self, image_path: str, max_height: int = 2200) -> List[str]:
        """
        Automatically slices extremely tall images into smaller vertical segments.
        Returns a list of file paths to slice images (including the original if short).
        """
        from PIL import Image
        
        img = Image.open(image_path)
        w, h = img.size
        
        # If not tall enough, return original
        if h <= max_height:
            return [image_path]
        
        slices = []
        base = Path(image_path)
        
        for top in range(0, h, max_height):
            box = (0, top, w, min(top + max_height, h))
            slice_img = img.crop(box)
            slice_path = f"{base.parent}/{base.stem}_slice_{top}{base.suffix}"
            slice_img.save(slice_path)
            slices.append(slice_path)
        
        return slices
    
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
    
    def _retry_generate_content(self, parts, max_retries=5):
        import time, random
        
        for i in range(max_retries):
            try:
                return self.client.models.generate_content(
                    model=self.model_id,
                    contents=[Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=4096
                    )
                )
            except Exception as e:
                msg = str(e)
                if "503" in msg or "overloaded" in msg or "UNAVAILABLE" in msg:
                    wait = 1.0 * (2 ** i) + random.uniform(0, 0.4)
                    print(f"⚠️ Model overloaded — retrying in {wait:.2f}s...")
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError("Max retries exceeded while calling Gemini API")
    
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
            # 1. Slice extremely tall images
            slice_paths = self._slice_vertical(image_path)

            all_slice_settings = []

            for slice_path in slice_paths:
                # Load image
                with open(slice_path, 'rb') as f:
                    image_data = f.read()

                # Create prompt
                extraction_prompt = self._create_extraction_prompt()

                # Parts for Gemini API
                parts = [
                    Part(text=extraction_prompt),
                    Part.from_bytes(data=image_data, mime_type="image/png")
                ]

                # 2. Safe retry wrapper
                try:
                    response = self._retry_generate_content(parts)
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to extract settings: {str(e)}",
                        "image_path": image_path,
                        "timestamp": datetime.now().isoformat(),
                        "settings": []
                    }

                # 3. Null-safe extraction
                try:
                    text = (
                        response.candidates[0].content.parts[0].text
                        if response and response.candidates
                        and response.candidates[0].content
                        and response.candidates[0].content.parts
                        else ""
                    )
                except Exception:
                    text = ""

                if not text.strip():
                    continue

                parsed = self._parse_extraction_response(text, slice_path)
                all_slice_settings.extend(parsed.get("settings", []))

            # Combine slices output
            return {
                "status": "success",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "settings": all_slice_settings,
                "settings_count": len(all_slice_settings)
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to extract settings: {str(e)}",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "settings": []
            }

    def batch_extract(self, image_directory: str, output_file: Optional[str] = None) -> List[Dict]:
        
        """
        Processes all platform subdirectories, extracts settings from screenshots in each platform folder, and returns results organized by platform.
        Optionally saves results to a JSON file.
        
        Args:
            image_directory: Directory containing platform subdirectories with screenshot images
            output_file: Optional file to save results
            
        Returns:
            List of platform extraction results, each with status, total_images, platform, all_settings, summary, and timestamp
        """

        image_dir = Path(image_directory)
        if not image_dir.exists():
            return [{"status": "error", "message": f"Directory {image_directory} does not exist"}]
        
        # Find platform subdirectories (folders that contain images)
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
        platform_dirs = [d for d in image_dir.iterdir() if d.is_dir()]
        
        if not platform_dirs:
            return [{"status": "error", "message": "No platform subdirectories found in directory"}]
        
        all_platform_results = []
        
        # Process each platform directory
        for platform_dir in platform_dirs:
            platform_name = platform_dir.name
            print(f"\n📁 Processing platform: {platform_name}")
            
            # Find image files in this platform directory
            image_files = [f for f in platform_dir.iterdir() 
                          if f.is_file() and f.suffix.lower() in image_extensions]
            
            if not image_files:
                print(f"  ⚠️  No image files found in {platform_name}")
                all_platform_results.append({
                    "status": "success",
                    "total_images": 0,
                    "platform": platform_name,
                    "all_settings": [],
                    "summary": {
                        "total_settings_extracted": 0,
                        "successful_extractions": 0,
                        "failed_extractions": 0,
                        "failed image paths": [],
                        "average_settings_per_image": 0
                    },
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            # Initialize results for this platform
            platform_results = {
                "status": "success",
                "total_images": len(image_files),
                "platform": platform_name,
                "all_settings": [],
                "summary": {},
                "timestamp": datetime.now().isoformat()
            }
            
            # Process each image in this platform
            total_settings = 0
            successful_extractions = 0
            failed_image_paths = []
            
            for image_file in image_files:
                print(f"  Processing {image_file.name}...")
                extraction = self.extract_settings(str(image_file))
                
                # Flatten settings into all_settings
                if extraction.get("status") == "success":
                    successful_extractions += 1
                    settings = extraction.get("settings", [])
                    platform_results["all_settings"].extend(settings)
                    total_settings += len(settings)
                else:
                    failed_image_paths.append(str(image_file))
                    print(f"    ⚠️  Failed to extract from {image_file.name}: {extraction.get('message', 'Unknown error')}")
            
            # Generate summary for this platform
            platform_results["summary"] = {
                "total_settings_extracted": total_settings,
                "successful_extractions": successful_extractions,
                "failed_extractions": len(failed_image_paths),
                "failed image paths": failed_image_paths,
                "average_settings_per_image": round(total_settings / successful_extractions, 2) if successful_extractions > 0 else 0
            }
            
            all_platform_results.append(platform_results)
            print(f"  ✅ Extracted {total_settings} settings from {successful_extractions} images in {platform_name}")
        
        # Save results if output file specified
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_platform_results, f, indent=2, ensure_ascii=False)
            total_all_settings = sum(r["summary"]["total_settings_extracted"] for r in all_platform_results)
            total_all_images = sum(r["total_images"] for r in all_platform_results)
            print(f"\n✅ Results saved to {output_file}")
            print(f"📊 Total: {total_all_settings} settings from {total_all_images} images across {len(all_platform_results)} platforms")
        
        return all_platform_results


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
        platform_results = extractor.batch_extract(screenshots_dir, "extracted_settings.json")
        
        if platform_results and isinstance(platform_results, list):
            # Check if there are any errors
            if len(platform_results) == 1 and platform_results[0].get("status") == "error":
                print(f"❌ Error: {platform_results[0].get('message', 'Unknown error')}")
            else:
                print(f"\n📊 Summary by Platform:")
                total_all_images = 0
                total_all_settings = 0
                for result in platform_results:
                    if result.get("status") == "success":
                        print(f"\n  Platform: {result['platform']}")
                        print(f"    Total images: {result['total_images']}")
                        print(f"    Successful extractions: {result['summary']['successful_extractions']}")
                        failed_count = result['summary']['failed_extractions']
                        failed_paths = result['summary'].get('failed image paths', [])
                        print(f"    Failed extractions: {failed_count}")
                        if failed_paths:
                            print(f"    Failed image paths: {failed_paths}")
                        print(f"    Total settings extracted: {result['summary']['total_settings_extracted']}")
                        print(f"    Average settings per image: {result['summary']['average_settings_per_image']}")
                        total_all_images += result['total_images']
                        total_all_settings += result['summary']['total_settings_extracted']
                print(f"\n📊 Overall Summary:")
                print(f"  Total platforms processed: {len(platform_results)}")
                print(f"  Total images across all platforms: {total_all_images}")
                print(f"  Total settings extracted: {total_all_settings}")
        else:
            print(f"❌ Error: Unexpected results format")
    else:
        print(f"⚠️ Screenshots directory not found: {screenshots_dir}")
        print("Please create a directory with platform subdirectories containing your screenshot files")


if __name__ == "__main__":
    main()

