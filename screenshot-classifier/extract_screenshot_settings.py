#!/usr/bin/env python3
"""
Extract Privacy Settings from Screenshot Classification Summary

Creates a comprehensive JSON file listing all privacy settings
organized by category from the screenshot classification summary.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from datetime import datetime


class ScreenshotSettingsExtractor:
    """Extract and organize privacy settings from screenshot classification summary."""
    
    def __init__(self, summary_file: str = "classification_summary.json", 
                 results_file: str = "classification_results.json",
                 summaries_file: str = "summaries.json"):
        """Initialize extractor."""
        self.summary_file = Path(summary_file)
        self.results_file = Path(results_file)
        self.summaries_file = Path(summaries_file)
        self.summary = self.load_summary()
        self.results_data = self.load_results()
        self.summaries_data = self.load_summaries()
        self.application_map = self.build_application_map()
        
    def load_summary(self) -> Dict:
        """Load classification summary JSON."""
        if not self.summary_file.exists():
            raise FileNotFoundError(f"Summary file not found: {self.summary_file}")
        
        with open(self.summary_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_results(self) -> Optional[Dict]:
        """Load original classification results JSON."""
        if not self.results_file.exists():
            return None
        
        try:
            with open(self.results_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    
    def load_summaries(self) -> Optional[Dict]:
        """Load summaries JSON."""
        if not self.summaries_file.exists():
            return None
        
        try:
            with open(self.summaries_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    
    def extract_application_from_raw_response(self, raw_response: str) -> Optional[str]:
        """Extract application name from raw_response JSON."""
        if not raw_response:
            return None
        
        try:
            # Try to find JSON in raw_response
            json_match = re.search(r'\{.*?"application"\s*:\s*"([^"]+)"', raw_response, re.DOTALL)
            if json_match:
                return json_match.group(1)
            
            # Try to parse as JSON
            json_match = re.search(r'\{.*?\}', raw_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("application")
        except:
            pass
        
        return None
    
    def extract_application_from_summary(self, image_path: str) -> Optional[str]:
        """Extract application from summaries.json."""
        if not self.summaries_data:
            return None
        
        summaries = self.summaries_data.get("summaries", [])
        for summary in summaries:
            if summary.get("image_path") == image_path:
                summary_text = summary.get("summary", "")
                # Look for "Application/Website" section
                if "Application/Website" in summary_text:
                    # Try to extract application name from bold text after Application/Website
                    # Pattern: Application/Website\n...**App Name**...
                    match = re.search(r'Application/Website[^\n]*\n[^\n]*?\*\*([^*]+?)\*\*', summary_text)
                    if match:
                        app_name = match.group(1).strip()
                        # Normalize common variations
                        if "Zoom Workplace" in app_name or "Zoom" in app_name:
                            return "Zoom"
                        elif "LinkedIn" in app_name:
                            return "LinkedIn"
                        elif "Facebook" in app_name:
                            return "Facebook"
                        elif "Twitter" in app_name or "X" in app_name:
                            return "Twitter/X"
                        elif "Instagram" in app_name:
                            return "Instagram"
                        elif "Google" in app_name:
                            return "Google"
                        elif "Microsoft" in app_name:
                            return "Microsoft"
                        # If it's a short name (likely an app name), return it
                        if len(app_name) < 30 and not any(word in app_name.lower() for word in ['screenshot', 'this is', 'website', 'application']):
                            return app_name
                
                # Fallback: look for common app names in Application/Website section
                app_section_match = re.search(r'Application/Website[^\n]*\n([^\n#]+)', summary_text, re.IGNORECASE)
                if app_section_match:
                    section_text = app_section_match.group(1)
                    # Check for specific app mentions
                    if "zoom" in section_text.lower() and ("workplace" in section_text.lower() or "website" in section_text.lower() or "zoom.us" in section_text.lower()):
                        return "Zoom"
                    for app in ["LinkedIn", "Facebook", "Twitter", "Instagram", "Google", "Microsoft"]:
                        if app.lower() in section_text.lower():
                            return app
                
                # Last resort: look anywhere in summary for app names
                if "zoom" in summary_text.lower():
                    return "Zoom"
                for app in ["LinkedIn", "Facebook", "Twitter", "Instagram", "Google", "Microsoft"]:
                    if app.lower() in summary_text.lower():
                        return app
        
        return None
    
    def infer_application_from_path(self, image_path: str) -> Optional[str]:
        """Infer application from image path/filename."""
        if not image_path:
            return None
        
        path_lower = image_path.lower()
        
        # Check for common patterns
        if "zoom" in path_lower:
            return "Zoom"
        elif "linkedin" in path_lower:
            return "LinkedIn"
        elif "facebook" in path_lower:
            return "Facebook"
        elif "twitter" in path_lower or "x.com" in path_lower:
            return "Twitter/X"
        elif "instagram" in path_lower:
            return "Instagram"
        elif "google" in path_lower:
            return "Google"
        elif "microsoft" in path_lower or "msft" in path_lower:
            return "Microsoft"
        
        return None
    
    def build_application_map(self) -> Dict[str, str]:
        """Build a map of image_path -> application."""
        app_map = {}
        
        # First, try to get from classification results
        if self.results_data:
            classifications = self.results_data.get("classifications", [])
            for classification in classifications:
                image_path = classification.get("image_path", "")
                raw_response = classification.get("raw_response", "")
                
                # Try to extract from raw_response
                app = self.extract_application_from_raw_response(raw_response)
                if app:
                    app_map[image_path] = app
        
        # Then, try to get from summaries
        if self.summaries_data:
            summaries = self.summaries_data.get("summaries", [])
            for summary in summaries:
                image_path = summary.get("image_path", "")
                if image_path and image_path not in app_map:
                    app = self.extract_application_from_summary(image_path)
                    if app:
                        app_map[image_path] = app
        
        # Finally, infer from paths
        all_image_paths = set()
        if self.results_data:
            for classification in self.results_data.get("classifications", []):
                all_image_paths.add(classification.get("image_path", ""))
        if self.summaries_data:
            for summary in self.summaries_data.get("summaries", []):
                all_image_paths.add(summary.get("image_path", ""))
        
        for image_path in all_image_paths:
            if image_path and image_path not in app_map:
                app = self.infer_application_from_path(image_path)
                if app:
                    app_map[image_path] = app
        
        return app_map
    
    def get_application(self, image_path: str) -> str:
        """Get application name for an image path."""
        return self.application_map.get(image_path, "Unknown")
    
    def extract_settings_by_category(self) -> Dict:
        """Extract all privacy settings organized by category."""
        detailed_stats = self.summary.get("detailed_file_stats", [])
        
        # Organize settings by category
        settings_by_category = defaultdict(list)
        all_settings = []
        setting_metadata = {}
        
        # Process each file
        for file_stats in detailed_stats:
            file_name = file_stats.get("file_name", "unknown")
            
            # Process each classification
            for classification in file_stats.get("classifications", []):
                image_name = classification.get("image_name", "")
                image_path = classification.get("image_path", "")
                page_type = classification.get("page_type", "")
                detected_categories = classification.get("detected_categories", [])
                detected_settings = classification.get("detected_settings", [])
                confidence = classification.get("confidence", 0.0)
                category_scores = classification.get("category_scores", {})
                
                # Get application/website for this image
                application = self.get_application(image_path)
                
                # Process each detected setting
                for setting_text in detected_settings:
                    if not setting_text or not setting_text.strip():
                        continue
                    
                    setting_label = setting_text.strip()
                    setting_key = setting_label.lower().strip()
                    
                    # Create setting entry
                    setting_entry = {
                        "setting": setting_label,
                        "image_name": image_name,
                        "image_path": image_path,
                        "page_type": page_type,
                        "application": application,
                        "categories": detected_categories,
                        "confidence": confidence,
                        "file": file_name
                    }
                    
                    # Add to category lists
                    for category in detected_categories:
                        settings_by_category[category].append(setting_entry)
                    
                    # Track unique settings
                    if setting_key not in setting_metadata:
                        setting_metadata[setting_key] = {
                            "setting": setting_label,
                            "categories": detected_categories,
                            "images": [],
                            "page_types": [],
                            "applications": [],
                            "files": [],
                            "confidence_scores": []
                        }
                    
                    # Add image and file info
                    if image_name not in setting_metadata[setting_key]["images"]:
                        setting_metadata[setting_key]["images"].append(image_name)
                    if page_type and page_type not in setting_metadata[setting_key]["page_types"]:
                        setting_metadata[setting_key]["page_types"].append(page_type)
                    if application and application not in setting_metadata[setting_key]["applications"]:
                        setting_metadata[setting_key]["applications"].append(application)
                    if file_name not in setting_metadata[setting_key]["files"]:
                        setting_metadata[setting_key]["files"].append(file_name)
                    if confidence > 0:
                        setting_metadata[setting_key]["confidence_scores"].append(confidence)
                    
                    all_settings.append(setting_entry)
        
        # Organize by category with metadata
        organized_settings = {}
        stats = self.summary.get("combined_statistics", {})
        category_totals = stats.get("category_totals", {})
        
        for category in sorted(settings_by_category.keys()):
            settings = settings_by_category[category]
            
            # Get unique settings
            unique_settings = {}
            for setting in settings:
                setting_key = setting["setting"].lower().strip()
                if setting_key not in unique_settings:
                    unique_settings[setting_key] = {
                        "setting": setting["setting"],
                        "categories": setting["categories"],
                        "images": [],
                        "page_types": [],
                        "applications": [],
                        "files": [],
                        "confidence_scores": []
                    }
                
                # Add image and file info
                if setting["image_name"] not in unique_settings[setting_key]["images"]:
                    unique_settings[setting_key]["images"].append(setting["image_name"])
                if setting["page_type"] and setting["page_type"] not in unique_settings[setting_key]["page_types"]:
                    unique_settings[setting_key]["page_types"].append(setting["page_type"])
                if setting.get("application") and setting["application"] not in unique_settings[setting_key]["applications"]:
                    unique_settings[setting_key]["applications"].append(setting["application"])
                if setting["file"] not in unique_settings[setting_key]["files"]:
                    unique_settings[setting_key]["files"].append(setting["file"])
                if setting["confidence"] > 0:
                    unique_settings[setting_key]["confidence_scores"].append(setting["confidence"])
            
            # Calculate average confidence for each setting
            for setting_key, setting_data in unique_settings.items():
                if setting_data["confidence_scores"]:
                    setting_data["average_confidence"] = sum(setting_data["confidence_scores"]) / len(setting_data["confidence_scores"])
                else:
                    setting_data["average_confidence"] = 0.0
                # Remove individual scores, keep only average
                del setting_data["confidence_scores"]
            
            organized_settings[category] = {
                "category": category,
                "total_occurrences": len(settings),
                "unique_settings_count": len(unique_settings),
                "settings": list(unique_settings.values())
            }
        
        # Get unique applications
        all_applications = set()
        for setting_data in setting_metadata.values():
            all_applications.update(setting_data.get("applications", []))
        
        return {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "source_file": str(self.summary_file),
                "total_settings": len(all_settings),
                "unique_settings": len(setting_metadata),
                "categories": len(organized_settings),
                "total_screenshots": stats.get("total_screenshots", 0),
                "total_files": self.summary.get("files_analyzed", 0),
                "average_confidence": stats.get("confidence_stats", {}).get("average", 0.0),
                "applications": sorted(list(all_applications)) if all_applications else ["Unknown"]
            },
            "categories": organized_settings,
            "all_settings": list(setting_metadata.values()),
            "category_statistics": {
                category: {
                    "total_occurrences": category_totals.get(category, 0),
                    "unique_settings": len(organized_settings[category]["settings"]) if category in organized_settings else 0
                }
                for category in category_totals.keys()
            }
        }
    
    def save_settings_json(self, output_file: str = "screenshot_privacy_settings_catalog.json"):
        """Save settings to JSON file."""
        settings_data = self.extract_settings_by_category()
        
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Screenshot privacy settings catalog saved to: {output_path}")
        print(f"   Total unique settings: {settings_data['metadata']['unique_settings']}")
        print(f"   Categories: {settings_data['metadata']['categories']}")
        print(f"   Total screenshots: {settings_data['metadata']['total_screenshots']}")
        print(f"   Average confidence: {settings_data['metadata']['average_confidence']:.2f}")
        print(f"   Applications: {', '.join(settings_data['metadata']['applications'])}")
        
        return output_path


def main():
    """Main function."""
    print("🔍 Extracting Privacy Settings from Screenshot Classification Summary")
    print("=" * 60)
    
    try:
        extractor = ScreenshotSettingsExtractor("classification_summary.json")
        extractor.save_settings_json("screenshot_privacy_settings_catalog.json")
        print("\n✅ Extraction complete!")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("   Please run screenshot_classification_summarizer.py first to generate classification_summary.json")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

