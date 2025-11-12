#!/usr/bin/env python3
"""
Extract Privacy Settings from Screenshot Classification Summary

Creates a comprehensive JSON file listing all privacy settings
organized by category from the screenshot classification summary.
"""

import json
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
from datetime import datetime


class ScreenshotSettingsExtractor:
    """Extract and organize privacy settings from screenshot classification summary."""
    
    def __init__(self, summary_file: str = "classification_summary.json"):
        """Initialize extractor."""
        self.summary_file = Path(summary_file)
        self.summary = self.load_summary()
        
    def load_summary(self) -> Dict:
        """Load classification summary JSON."""
        if not self.summary_file.exists():
            raise FileNotFoundError(f"Summary file not found: {self.summary_file}")
        
        with open(self.summary_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
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
                            "files": [],
                            "confidence_scores": []
                        }
                    
                    # Add image and file info
                    if image_name not in setting_metadata[setting_key]["images"]:
                        setting_metadata[setting_key]["images"].append(image_name)
                    if page_type and page_type not in setting_metadata[setting_key]["page_types"]:
                        setting_metadata[setting_key]["page_types"].append(page_type)
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
                        "files": [],
                        "confidence_scores": []
                    }
                
                # Add image and file info
                if setting["image_name"] not in unique_settings[setting_key]["images"]:
                    unique_settings[setting_key]["images"].append(setting["image_name"])
                if setting["page_type"] and setting["page_type"] not in unique_settings[setting_key]["page_types"]:
                    unique_settings[setting_key]["page_types"].append(setting["page_type"])
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
        
        return {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "source_file": str(self.summary_file),
                "total_settings": len(all_settings),
                "unique_settings": len(setting_metadata),
                "categories": len(organized_settings),
                "total_screenshots": stats.get("total_screenshots", 0),
                "total_files": self.summary.get("files_analyzed", 0),
                "average_confidence": stats.get("confidence_stats", {}).get("average", 0.0)
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

