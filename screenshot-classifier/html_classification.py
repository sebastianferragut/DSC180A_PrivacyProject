"""
HTML Classification System for Privacy Settings Pages

This system uses Google's Gemini API to analyze HTML files of privacy settings pages
and categorize them based on privacy-related content and settings.
"""

import os
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import re

from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from google.genai.types import Content, Part


class PrivacyHTMLClassifier:
    """
    A classifier for privacy settings HTML pages using Google's Gemini API.
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
                "keywords": ["messages", "chat", "communication", "calls", "meeting", "conversation", "end-to-end encryption", "access controls"],
                "description": "Communication and messaging privacy settings"
            },
            "notification_privacy": {
                "keywords": ["notifications", "alerts", "reminders", "email notifications", "participant consent/notification"],
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
                You are a privacy settings expert analyzing an HTML page of a privacy settings interface. 

                Analyze the text content from the HTML page, focusing on the text content that is visible to the user, and provide detailed information about:

                1. **Application/Service**: What application or service is this privacy settings page for?
                2. **Page Type**: What type of privacy settings page is this (e.g., main settings, specific category, etc.)?
                3. **Privacy Categories Present**: Which of the following privacy categories, if any, are visible or relevant in this HTML page?

                {categories_text}

                4. **Specific Settings**: List any specific privacy settings, toggles, or options visible in the HTML.
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
    
    def _extract_visible_text(self, html_content: str, max_length: int = 80000) -> str:
        """
        Extract only visible text content from HTML, ignoring all CSS, styling, scripts, and non-visible elements.
        
        Args:
            html_content: Raw HTML content
            max_length: Maximum length of extracted text (in characters)
            
        Returns:
            Extracted visible text content
        """
        try:
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove all non-visible and styling elements
            # Remove scripts, styles, and other non-content elements
            for element in soup(["script", "style", "noscript", "meta", "link", "head"]):
                element.decompose()
            
            # Try to find main content areas first
            main_content = None
            for selector in ['main', '[role="main"]', '.main-content', '#main', 'body']:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            if not main_content:
                main_content = soup.body if soup.body else soup
            
            # Extract only visible text content
            # This preserves text structure but removes all HTML tags and styling
            text = main_content.get_text(separator='\n', strip=True)
            
            # Clean up excessive whitespace while preserving line breaks
            # Remove multiple spaces but keep line breaks for structure
            lines = text.split('\n')
            cleaned_lines = []
            for line in lines:
                # Clean up each line: remove extra spaces
                cleaned_line = re.sub(r'[ \t]+', ' ', line.strip())
                if cleaned_line:  # Only keep non-empty lines
                    cleaned_lines.append(cleaned_line)
            
            # Join lines back together
            result = '\n'.join(cleaned_lines)
            
            # Remove excessive blank lines
            result = re.sub(r'\n{3,}', '\n\n', result)
            
            # Truncate if too long
            if len(result) > max_length:
                result = result[:max_length] + "\n\n[Content truncated due to size]"
            
            return result
            
        except Exception as e:
            # Fallback: simple text extraction using regex
            # Remove all HTML tags
            text = re.sub(r'<[^>]+>', '\n', html_content)
            # Clean up whitespace
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            if len(text) > max_length:
                text = text[:max_length] + "\n\n[Content truncated due to size]"
            return text
    
    def _parse_analysis_response(self, response_text: str, html_path: str) -> Dict:
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
                "html_path": html_path,
                "timestamp": datetime.now().isoformat(),
                "model_used": self.model_id
            })
            
            return analysis_data
            
        except json.JSONDecodeError:
            return {
                "status": "partial_success",
                "raw_response": response_text,
                "html_path": html_path,
                "timestamp": datetime.now().isoformat(),
                "message": "Could not parse JSON response, returning raw text"
            }
    
    
    def analyze_html(self, html_path: str) -> Dict:
        """
        Analyze an HTML file and return privacy-related information.
        
        Args:
            html_path: Path to the HTML file
            
        Returns:
            Dictionary containing analysis results
        """
        try:
            # Load HTML content
            with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
            
            # Extract only visible text content (ignores CSS, styling, scripts)
            # Limit to ~80K characters (~20K tokens) to stay well within Gemini limits
            visible_text = self._extract_visible_text(html_content, max_length=80000)
            
            # Create analysis prompt
            analysis_prompt = self._create_analysis_prompt()
            
            # Combine prompt with extracted visible text
            full_prompt = f"{analysis_prompt}\n\nHere is the visible text content extracted from the HTML page (all CSS, styling, and scripts have been removed):\n\n{visible_text}"
            
            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[
                    Content(
                        role="user",
                        parts=[
                            Part(text=full_prompt)
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048
                )
            )
            
            # Check for empty response
            if not response.candidates or not response.candidates[0].content:
                raise ValueError("No response from Gemini API - possibly blocked by safety filters")
            
            # Parse response
            analysis_text = response.candidates[0].content.parts[0].text
            return self._parse_analysis_response(analysis_text, html_path)
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to analyze HTML: {str(e)}",
                "html_path": html_path,
                "timestamp": datetime.now().isoformat()
            }
    

    def classify_html(self, html_path: str) -> Dict:
        """
        Classify an HTML file into privacy categories.
        
        Args:
            html_path: Path to the HTML file
            
        Returns:
            Classification results
        """
        # response from gemini api
        analysis = self.analyze_html(html_path)
        
        if analysis.get("status") != "success":
            return analysis
        
        # Extract categories from analysis
        detected_categories = analysis.get("privacy_categories", [])
        
        # Map to our predefined categories
        classification = {
            "status": "success",
            "html_path": html_path,
            "detected_categories": detected_categories,
            "category_scores": {},
            "primary_category": None,
            "confidence": analysis.get("confidence", 0.0),
            "page_type": analysis.get("page_type", ""),
            "detected_settings": analysis.get("specific_settings", [])
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
            primary = max(classification["category_scores"], key=classification["category_scores"].get)
            if classification["category_scores"][primary] > 0:
                classification["primary_category"] = primary
        
        return classification
    

    def batch_classify(self, html_directory: str, output_file: Optional[str] = None) -> Dict:
        """
        Classify multiple HTML files in a directory.
        
        Args:
            html_directory: Directory containing HTML files
            output_file: Optional file to save results
            
        Returns:
            Batch classification results
        """
        html_dir = Path(html_directory)
        if not html_dir.exists():
            return {"status": "error", "message": f"Directory {html_directory} does not exist"}
        
        # Find HTML files
        html_extensions = {'.html', '.htm'}
        html_files = [f for f in html_dir.iterdir() if f.suffix.lower() in html_extensions]
        
        if not html_files:
            return {"status": "error", "message": "No HTML files found in directory"}
        
        results = {
            "status": "success",
            "total_html_files": len(html_files),
            "classifications": [],
            "summary": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Process each HTML file
        for html_file in html_files:
            print(f"Processing {html_file.name}...")
            classification = self.classify_html(str(html_file))
            results["classifications"].append(classification)
        
        # Generate summary
        category_counts = {}
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


def main():
    """Example usage of the PrivacyHTMLClassifier."""

    # Initialize classifier
    try:
        classifier = PrivacyHTMLClassifier()
        print("✅ Privacy HTML Classifier initialized successfully")
    except ValueError as e:
        print(f"❌ Error: {e}")
        print("Please set your GEMINI_API_KEY environment variable")
        return
    
    # Batch classification
    html_dir = "scraped_html"
    
    if os.path.exists(html_dir):
        print(f"\n🔍 Batch analyzing HTML files in: {html_dir}")
        batch_results = classifier.batch_classify(html_dir, "html_classification_results.json")
        print(f"📊 Batch Results:")
        print(json.dumps(batch_results["classifications"], indent=2))
        print(json.dumps(batch_results["summary"], indent=2))
    else:
        print(f"⚠️ HTML directory not found: {html_dir}")
        print("Please create a directory with your HTML files")


if __name__ == "__main__":
    main()
