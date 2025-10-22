"""
Screenshot Classification System for Privacy Settings Pages

This system uses Google's Gemini API to analyze screenshots of privacy settings pages
and categorize them based on privacy-related content and settings.
"""

import os
import json
import base64
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import io
from PIL import Image

from google import genai
from google.genai import types
from google.genai.types import Content, Part


class PrivacyScreenshotClassifier:
    """
    A classifier for privacy settings screenshots using Google's Gemini API.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the classifier with Gemini API key.
        
        Args:
            api_key: Google Gemini API key. If None, will try to get from environment.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set or api_key not provided")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_id = 'gemini-2.5-pro'
        
        # Privacy categories for classification
        self.privacy_categories = {
            "data_collection": {
                "keywords": ["data collection", "collect data", "analytics", "tracking", "telemetry"],
                "description": "Settings related to data collection and analytics"
            },
            "camera_microphone": {
                "keywords": ["camera", "microphone", "video", "audio", "recording", "permissions"],
                "description": "Camera and microphone access settings"
            },
            "location_privacy": {
                "keywords": ["location", "gps", "geolocation", "where you are", "position"],
                "description": "Location and geolocation privacy settings"
            },
            "personal_information": {
                "keywords": ["personal info", "profile", "name", "email", "phone", "address", "contact"],
                "description": "Personal information and profile settings"
            },
            "communication_privacy": {
                "keywords": ["messages", "chat", "communication", "calls", "meeting", "conversation"],
                "description": "Communication and messaging privacy settings"
            },
            "account_security": {
                "keywords": ["security", "password", "authentication", "login", "account", "access"],
                "description": "Account security and authentication settings"
            },
            "sharing_settings": {
                "keywords": ["share", "public", "private", "visibility", "who can see", "audience"],
                "description": "Content sharing and visibility settings"
            },
            "notification_privacy": {
                "keywords": ["notifications", "alerts", "reminders", "email notifications"],
                "description": "Notification and alert privacy settings"
            },
            "data_retention": {
                "keywords": ["retention", "delete", "remove", "expire", "storage", "history"],
                "description": "Data retention and deletion settings"
            },
            "third_party_sharing": {
                "keywords": ["third party", "partners", "integrations", "external", "api"],
                "description": "Third-party data sharing and integration settings"
            }
        }
    
    def analyze_screenshot(self, image_path: str) -> Dict:
        """
        Analyze a screenshot and return privacy-related information.
        
        Args:
            image_path: Path to the screenshot image file
            
        Returns:
            Dictionary containing analysis results
        """
        try:
            # Load and prepare image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create analysis prompt
            analysis_prompt = self._create_analysis_prompt()
            
            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[
                    Content(
                        role="user",
                        parts=[
                            Part(text=analysis_prompt),
                            Part.from_bytes(data=image_data, mime_type='image/png')
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048
                )
            )
            
            # Parse response
            analysis_text = response.candidates[0].content.parts[0].text
            return self._parse_analysis_response(analysis_text, image_path)
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to analyze screenshot: {str(e)}",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat()
            }
    
    def _create_analysis_prompt(self) -> str:
        """Create the analysis prompt for Gemini."""
        categories_text = "\n".join([
            f"- {cat}: {info['description']}" 
            for cat, info in self.privacy_categories.items()
        ])
        
        return f"""
You are a privacy settings expert analyzing a screenshot of a privacy settings page. 

Analyze the screenshot and provide detailed information about:

1. **Application/Service**: What application or service is this privacy settings page for?
2. **Page Type**: What type of privacy settings page is this (e.g., main settings, specific category, etc.)?
3. **Privacy Categories Present**: Which of the following privacy categories are visible or relevant in this screenshot?

{categories_text}

4. **Specific Settings**: List any specific privacy settings, toggles, or options visible in the screenshot.
5. **User Actions Available**: What privacy-related actions can a user take on this page?
6. **Privacy Level**: Rate the overall privacy-friendliness of the visible settings (1-10, where 10 is most privacy-friendly).
7. **Key Concerns**: Identify any potential privacy concerns or red flags visible in the settings.
8. **Recommendations**: Provide brief recommendations for privacy-conscious users.

Please respond in JSON format with the following structure:
{{
    "application": "string",
    "page_type": "string", 
    "privacy_categories": ["list", "of", "categories"],
    "specific_settings": ["list", "of", "visible", "settings"],
    "user_actions": ["list", "of", "available", "actions"],
    "privacy_level": number,
    "key_concerns": ["list", "of", "concerns"],
    "recommendations": ["list", "of", "recommendations"],
    "confidence": number
}}

Be thorough and accurate in your analysis. Focus on privacy-related content and settings.
"""
    
    def _parse_analysis_response(self, response_text: str, image_path: str) -> Dict:
        """Parse the Gemini response and structure the data."""
        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                analysis_data = json.loads(json_match.group())
            else:
                # Fallback: create structured response from text
                analysis_data = {
                    "raw_response": response_text,
                    "parsed": False
                }
            
            # Add metadata
            analysis_data.update({
                "status": "success",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "model_used": self.model_id
            })
            
            return analysis_data
            
        except json.JSONDecodeError:
            return {
                "status": "partial_success",
                "raw_response": response_text,
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "message": "Could not parse JSON response, returning raw text"
            }
    
    def classify_screenshot(self, image_path: str) -> Dict:
        """
        Classify a screenshot into privacy categories.
        
        Args:
            image_path: Path to the screenshot image file
            
        Returns:
            Classification results
        """
        analysis = self.analyze_screenshot(image_path)
        
        if analysis.get("status") != "success":
            return analysis
        
        # Extract categories from analysis
        detected_categories = analysis.get("privacy_categories", [])
        
        # Map to our predefined categories
        classification = {
            "image_path": image_path,
            "detected_categories": detected_categories,
            "category_scores": {},
            "primary_category": None,
            "confidence": analysis.get("confidence", 0.5) # TODO: fix confidence
        }
        
        # Calculate category scores based on detected categories
        for category, info in self.privacy_categories.items():
            score = 0
            for detected in detected_categories:
                if any(keyword in detected.lower() for keyword in info["keywords"]):
                    score += 1
            classification["category_scores"][category] = score / len(info["keywords"])
        
        # Determine primary category
        if classification["category_scores"]:
            primary = max(classification["category_scores"], 
                         key=classification["category_scores"].get)
            if classification["category_scores"][primary] > 0:
                classification["primary_category"] = primary
        
        return classification
    
    def batch_classify(self, image_directory: str, output_file: Optional[str] = None) -> Dict:
        """
        Classify multiple screenshots in a directory.
        
        Args:
            image_directory: Directory containing screenshot images
            output_file: Optional file to save results
            
        Returns:
            Batch classification results
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
            "classifications": [],
            "summary": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Process each image
        for image_file in image_files:
            print(f"Processing {image_file.name}...")
            classification = self.classify_screenshot(str(image_file))
            results["classifications"].append(classification)
        
        # Generate summary
        category_counts = {}
        for classification in results["classifications"]:
            if classification.get("primary_category"):
                cat = classification["primary_category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1
        
        results["summary"] = {
            "category_distribution": category_counts,
            "successful_classifications": len([c for c in results["classifications"] 
                                              if c.get("status") == "success"]),
            "failed_classifications": len([c for c in results["classifications"] 
                                         if c.get("status") != "success"])
        }
        
        # Save results if output file specified
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Results saved to {output_file}")
        
        return results


def main():
    """Example usage of the PrivacyScreenshotClassifier."""
    # Initialize classifier
    try:
        classifier = PrivacyScreenshotClassifier()
        print("✅ Privacy Screenshot Classifier initialized successfully")
    except ValueError as e:
        print(f"❌ Error: {e}")
        print("Please set your GEMINI_API_KEY environment variable")
        return
    
    # Example: Classify a single screenshot
    # Replace with your actual screenshot path
    # screenshot_path = "screenshots\general_20251022_102721.png"
    
    # if os.path.exists(screenshot_path):
    #     print(f"\n🔍 Analyzing screenshot: {screenshot_path}")
    #     result = classifier.classify_screenshot(screenshot_path)
    #     print(f"📊 Classification Result:")
    #     print(json.dumps(result, indent=2))
    # else:
    #     print(f"⚠️  Screenshot file not found: {screenshot_path}")
    #     print("Please provide a valid screenshot path")
    
    # Example: Batch classification
    # Replace with your directory containing screenshots
    screenshots_dir = "screenshots"
    
    if os.path.exists(screenshots_dir):
        print(f"\n🔍 Batch analyzing screenshots in: {screenshots_dir}")
        batch_results = classifier.batch_classify(screenshots_dir, "classification_results.json")
        print(f"📊 Batch Results:")
        print(json.dumps(batch_results["classifications"], indent=2))
    else:
        print(f"⚠️  Screenshots directory not found: {screenshots_dir}")
        print("Please create a directory with your screenshot files")


if __name__ == "__main__":
    main()
