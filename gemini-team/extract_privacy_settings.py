#!/usr/bin/env python3
"""
Extract Privacy Settings from Privacy Map Summary

Creates a comprehensive JSON file listing all privacy settings
organized by category from the privacy map summary.
"""

import json
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
from datetime import datetime


class PrivacySettingsExtractor:
    """Extract and organize privacy settings from summary."""
    
    def __init__(self, summary_file: str = "privacy_summary.json"):
        """Initialize extractor."""
        self.summary_file = Path(summary_file)
        self.summary = self.load_summary()
        
    def load_summary(self) -> Dict:
        """Load privacy summary JSON."""
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
            host = file_stats.get("host", "unknown")
            
            # Process each page
            for page in file_stats.get("pages", []):
                page_url = page.get("url", "")
                
                # Process each control
                for control in page.get("privacy_controls", []):
                    label = control.get("label", "").strip()
                    control_type = control.get("type", "")
                    selector = control.get("selector", "")
                    categories = control.get("categories", [])
                    
                    if not label:
                        continue
                    
                    # Create setting entry
                    setting_entry = {
                        "setting": label,
                        "type": control_type,
                        "selector": selector,
                        "page_url": page_url,
                        "file": file_name,
                        "host": host,
                        "categories": categories
                    }
                    
                    # Add to category lists
                    for category in categories:
                        settings_by_category[category].append(setting_entry)
                    
                    # Track unique settings
                    setting_key = label.lower().strip()
                    if setting_key not in setting_metadata:
                        setting_metadata[setting_key] = {
                            "setting": label,
                            "type": control_type,
                            "categories": categories,
                            "pages": [],
                            "files": []
                        }
                    
                    # Add page and file info
                    if page_url not in setting_metadata[setting_key]["pages"]:
                        setting_metadata[setting_key]["pages"].append(page_url)
                    if file_name not in setting_metadata[setting_key]["files"]:
                        setting_metadata[setting_key]["files"].append(file_name)
                    
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
                        "type": setting["type"],
                        "categories": setting["categories"],
                        "pages": [],
                        "files": [],
                        "selectors": []
                    }
                
                # Add page and file info
                if setting["page_url"] not in unique_settings[setting_key]["pages"]:
                    unique_settings[setting_key]["pages"].append(setting["page_url"])
                if setting["file"] not in unique_settings[setting_key]["files"]:
                    unique_settings[setting_key]["files"].append(setting["file"])
                if setting["selector"] not in unique_settings[setting_key]["selectors"]:
                    unique_settings[setting_key]["selectors"].append(setting["selector"])
            
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
                "total_pages": stats.get("total_pages_analyzed", 0),
                "total_files": self.summary.get("files_analyzed", 0),
                "host": file_stats.get("host", "unknown") if detailed_stats else "unknown"
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
    
    def save_settings_json(self, output_file: str = "privacy_settings_catalog.json"):
        """Save settings to JSON file."""
        settings_data = self.extract_settings_by_category()
        
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Privacy settings catalog saved to: {output_path}")
        print(f"   Total unique settings: {settings_data['metadata']['unique_settings']}")
        print(f"   Categories: {settings_data['metadata']['categories']}")
        print(f"   Total pages: {settings_data['metadata']['total_pages']}")
        
        return output_path


def main():
    """Main function."""
    print("🔍 Extracting Privacy Settings from Privacy Map Summary")
    print("=" * 60)
    
    try:
        extractor = PrivacySettingsExtractor("privacy_summary.json")
        extractor.save_settings_json("privacy_settings_catalog.json")
        print("\n✅ Extraction complete!")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("   Please run privacy_map_summarizer.py first to generate privacy_summary.json")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

