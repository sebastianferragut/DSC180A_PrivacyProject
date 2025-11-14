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
        # checks for an API key
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set or api_key not provided")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_id = 'gemini-2.5-pro'
        
        # Gemini API pricing (per 1M tokens) - unsure how accurate this is
        self.cost_input_per_1m = float(os.environ.get('GEMINI_COST_IN_PER_1M', '1.25'))
        self.cost_output_per_1m = float(os.environ.get('GEMINI_COST_OUT_PER_1M', '10.0'))
        
        # Privacy categories for classification (add to this as domain knowledge expands)
        self.privacy_categories = {
            # Device and Sensor Access
            "access_to_device": {
                "keywords": ["camera", "microphone", "video", "audio", "record", "recording", "permission", "device", "sensor"],
                "description": "Camera and microphone access settings"
            },

            # Profile and Personal Information
            "personal_information": {
                "keywords": ["personal", "profile", "name", "email", "phone number", "address", "contact"],
                "description": "Personal information and profile settings"
            },
            "sharing_settings": {
                "keywords": ["public", "private", "visibility", "audience", "organization-wide"],
                "description": "Content sharing and visibility settings"
            },

            # Location
            "location_privacy": {
                "keywords": ["location", "gps", "geolocation", "IP address", "position"],
                "description": "Location and geolocation privacy settings"
            },

            # Communication
            "communication_privacy": {
                "keywords": ["messages", "chat", "communication", "calls", "meeting", "conversation", "end-to-end encryption", "access controls"], # qiyu and haojian mentioned e2ee
                "description": "Communication and messaging privacy settings"
            },
            "notification_privacy": {
                "keywords": ["notifications", "alerts", "reminders", "email notifications", "participant consent/notification"], # qiyu and haojian also mentioned participant consent
                "description": "Notification and alert privacy settings"
            },

            # Third-party and connected services
            "third_party_sharing": {
                "keywords": ["third party", "partners", "integrations", "external", "api", "cookies", "advertising", "opt in/out"],
                "description": "Third-party data sharing and integration settings"
            },

            # Data Collection and Analytics
            "data_collection": {
                "keywords": ["data collection", "collect data", "analytics", "tracking", "telemetry"],
                "description": "Settings related to data collection and analytics"
            },

            # Data Management
            "data_retention": {
                "keywords": ["retention", "delete", "remove", "expire", "storage", "history", "logs", "archive"],
                "description": "Data retention and deletion settings"
            },

            # Security and Authentication
            "account_security": {
                "keywords": ["security", "password/passcode", "authentication", "login", "encryption", "two-factor authentication", "biometrics"],
                "description": "Account security and authentication settings"
            }
        }

    def _create_analysis_prompt(self) -> str:
        """Create the analysis prompt for Gemini."""
        categories_text = "\n".join([f"- {cat}: {info['description']}" for cat, info in self.privacy_categories.items()])
        
        return f"""
                You are a privacy settings expert analyzing a screenshot of a privacy settings page. 

                Analyze the screenshot and provide detailed information about:
                1. **Application/Service**: What application or service is this privacy settings page for?
                2. **Page Type**: What type of privacy settings page is this (e.g., main settings, specific category, etc.)?
                3. **Privacy Categories Present**: Which of the following privacy categories, if any, are visible or relevant in this screenshot?

                {categories_text}

                4. **Specific Settings**: List any specific privacy settings, toggles, or options visible in the screenshot.
                5. **User Actions Available**: What privacy-related actions can a user take on this page?
                6. **Privacy Level**: Rate the overall privacy-friendliness of the visible settings (1-10, where 10 is most privacy-friendly).
                7. **Key Concerns**: Identify any potential privacy concerns or red flags visible in the settings.
                8. **Recommendations**: Provide brief recommendations for privacy-conscious users.
                9. **Confidence**: Rate your confidence in the privacy categories identified (0-1, inclusive), where 1.0 indicates absolute certainty, and lower values indicate less certainty.

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
    
    
    ### Calculates token usage and costs

    def _extract_usage_metadata(self, response) -> Dict:
        """
        Extract token usage information from Gemini API response.
        
        Args:
            response: The response object from Gemini API
            
        Returns:
            Dictionary with input_tokens, output_tokens, and source information
        """
        usage_in, usage_out = 0, 0
        source = "estimate"
        
        try:
            # Try to get usage_metadata from response
            md = getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
            if md:
                usage_in = int(getattr(md, "prompt_token_count", 0) or getattr(md, "input_tokens", 0) or 0)
                usage_out = int(getattr(md, "candidates_token_count", 0) or getattr(md, "output_tokens", 0) or 0)
                if (usage_in + usage_out) > 0:
                    source = "api"
            
            # If not found, try from candidates
            if (usage_in + usage_out) == 0:
                c0 = (getattr(response, "candidates", None) or [None])[0]
                if c0:
                    md2 = getattr(c0, "usage_metadata", None)
                    if md2:
                        usage_in = int(getattr(md2, "prompt_token_count", 0) or getattr(md2, "input_tokens", 0) or 0)
                        usage_out = int(getattr(md2, "candidates_token_count", 0) or getattr(md2, "output_tokens", 0) or 0)
                        if (usage_in + usage_out) > 0:
                            source = "api"
        except Exception:
            pass
        
        return {
            "input_tokens": usage_in,
            "output_tokens": usage_out,
            "total_tokens": usage_in + usage_out,
            "source": source
        }
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost in USD based on token usage.
        
        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Cost in USD
        """
        cost = (input_tokens / 1_000_000 * self.cost_input_per_1m) + \
               (output_tokens / 1_000_000 * self.cost_output_per_1m)
        return round(cost, 8)
    
    ###


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
    
    
    def analyze_screenshot(self, image_path: str) -> Dict: # this function is the workhorse
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
                        role="user", # creates a user message
                        parts=[ # multimodal message
                            Part(text=analysis_prompt), # text instructions
                            Part.from_bytes(data=image_data, mime_type='image/png') # image data
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048
                )
            )
            
            # Extract usage metadata
            usage_info = self._extract_usage_metadata(response)
            
            # Parse response
            analysis_text = response.candidates[0].content.parts[0].text # would like to return this
            analysis_data = self._parse_analysis_response(analysis_text, image_path)
            
            # Add usage information to analysis data
            analysis_data["token_usage"] = usage_info
            analysis_data["cost_usd"] = self._calculate_cost(usage_info["input_tokens"], usage_info["output_tokens"])
            
            return analysis_data
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to analyze screenshot: {str(e)}",
                "image_path": image_path,
                "timestamp": datetime.now().isoformat()
            }
    

    def classify_screenshot(self, image_path: str) -> Dict:
        """
        Classify a screenshot into privacy categories.
        
        Args:
            image_path: Path to the screenshot image file
            
        Returns:
            Classification results
        """
        # response from gemini api
        analysis = self.analyze_screenshot(image_path) # calls the analyze_screenshot function and two helpers above
        
        if analysis.get("status") != "success":
            return analysis
        
        # Extract categories from analysis
        detected_categories = analysis.get("privacy_categories", []) # gets detected privacy categories from analyze_screenshot function
        
        # Map to our predefined categories
        classification = {
            "status": "success",
            "image_path": image_path,
            "detected_categories": detected_categories,
            "category_scores": {},
            "primary_category": None,
            "confidence": analysis.get("confidence", 0.0),
            "page_type": analysis.get("page_type", ""),
            "detected_settings": analysis.get("specific_settings", []) # list of specific settings visible in the screenshot (support confidence score)
        }
        
        # Calculate category scores based on detected categories

        #  "data_collection": { # from above ^
        #         "keywords": ["data collection", "collect data", "analytics", "tracking", "telemetry"],
        #         "description": "Settings related to data collection and analytics"
        #     },

        for category, info in self.privacy_categories.items(): # score: the number of keywords detected for each category
            score = 0
            for detected in detected_categories:
                if any(keyword in detected.lower() for keyword in info["keywords"]):
                    score += 1
            classification["category_scores"][category] = score / len(info["keywords"])
        
        # Determine primary category
        if classification["category_scores"]:
            primary = max(classification["category_scores"], key=classification["category_scores"].get) # iterates through scores using get method, returning max
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
        
        # Find image files (all supported image formats)
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'} # smart! haha
        image_files = [f for f in image_dir.iterdir() if f.suffix.lower() in image_extensions]
        
        if not image_files:
            return {"status": "error", "message": "No image files found in directory"}
        
        results = {
            "status": "success",
            "total_images": len(image_files),
            "classifications": [], # should have the path to image
            "summary": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Process each image
        for image_file in image_files:
            print(f"Processing {image_file.name}...")
            classification = self.classify_screenshot(str(image_file)) # batch_classify depends on classify_screenshot
            results["classifications"].append(classification) # appends dict
        
        # Generate summary
        category_counts = {} # is this really important?
        for classification in results["classifications"]: 
            if classification.get("primary_category"):
                cat = classification["primary_category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1
        
        results["summary"] = {
            "category_distribution": category_counts,
            "successful_classifications": len([c for c in results["classifications"] if c.get("status") == "success"]),
            "failed_classifications": len([c for c in results["classifications"] if c.get("status") != "success"])
        }
        
        # Save results if output file specified
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Results saved to {output_file}")
        
        return results
    
    # Called in main()
    def calculate_token_usage(self, image_path: str, output_file: Optional[str] = None) -> Dict:
        """
        Calculate token usage and costs for analyzing a single screenshot.
        
        Args:
            image_path: Path to the screenshot image file
            output_file: Optional file path to save the token usage information as JSON
            
        Returns:
            Dictionary containing token usage, costs, and image path
        """
        # Analyze the screenshot (this will capture usage information)
        analysis = self.analyze_screenshot(image_path)
        
        # Extract usage information
        usage_info = analysis.get("token_usage", {})
        cost = analysis.get("cost_usd", 0.0)
        
        # Create token usage report
        token_report = {
            "image_path": image_path,
            "model_used": self.model_id,
            "timestamp": datetime.now().isoformat(),
            "token_usage": {
                "input_tokens": usage_info.get("input_tokens", 0),
                "output_tokens": usage_info.get("output_tokens", 0),
                "total_tokens": usage_info.get("total_tokens", 0),
                "source": usage_info.get("source", "unknown")
            },
            "cost": {
                "cost_usd": cost,
                "pricing": {
                    "input_cost_per_1m_tokens": self.cost_input_per_1m,
                    "output_cost_per_1m_tokens": self.cost_output_per_1m
                }
            },
            "analysis_status": analysis.get("status", "unknown")
        }
        
        # Save to file if specified
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(token_report, f, indent=2)
            print(f"Token usage information saved to {output_file}")
        
        return token_report


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
    
    # Calculate token usage for all screenshots
    screenshots_dir = "screenshots"
    
    if os.path.exists(screenshots_dir):
        # Find all image files
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
        image_files = [f for f in Path(screenshots_dir).iterdir() if f.suffix.lower() in image_extensions]
        
        if image_files:
            print(f"\n💰 Calculating token usage for {len(image_files)} screenshot(s)...")
            all_token_reports = []
            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = 0.0
            
            for image_file in image_files:
                image_path = str(image_file)
                print(f"  Processing: {image_file.name}...")
                token_report = classifier.calculate_token_usage(image_path)
                all_token_reports.append(token_report)
                
                total_input_tokens += token_report['token_usage']['input_tokens']
                total_output_tokens += token_report['token_usage']['output_tokens']
                total_cost += token_report['cost']['cost_usd']
            
            # Create aggregated report
            aggregated_report = {
                "summary": {
                    "total_images": len(image_files),
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "total_cost_usd": round(total_cost, 8),
                    "average_cost_per_image": round(total_cost / len(image_files), 8) if image_files else 0.0,
                    "pricing": {
                        "input_cost_per_1m_tokens": classifier.cost_input_per_1m,
                        "output_cost_per_1m_tokens": classifier.cost_output_per_1m
                    }
                },
                "individual_reports": all_token_reports,
                "timestamp": datetime.now().isoformat()
            }
            
            # Save aggregated report
            output_file = "screenshot_classifier_token_usage.json"
            with open(output_file, 'w') as f:
                json.dump(aggregated_report, f, indent=2)
        
        # Batch classification
        print(f"\n🔍 Batch analyzing screenshots in: {screenshots_dir}")
        batch_results = classifier.batch_classify(screenshots_dir, "classification_results.json")
        print(f"📊 Batch Results:")
        print(json.dumps(batch_results["classifications"], indent=2))
        print(json.dumps(batch_results["summary"], indent=2))
    else:
        print(f"⚠️ Screenshots directory not found: {screenshots_dir}")
        print("Please create a directory with your screenshot files")


if __name__ == "__main__":
    main()
