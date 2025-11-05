#!/usr/bin/env python3
"""
Privacy Map Summarizer

Analyzes privacy map JSON files from the outputs directory and generates
comprehensive summaries of privacy-related settings found across different pages.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict
from datetime import datetime
import re


# Privacy categories with keywords for classification
PRIVACY_CATEGORIES = {
    "data_collection": {
        "keywords": [
            "data collection", "collect data", "analytics", "tracking", "telemetry",
            "usage data", "performance data", "crash reports", "cookies", "cookie"
        ],
        "description": "Data collection and analytics settings",
        "priority": "high"
    },
    "camera_microphone": {
        "keywords": [
            "camera", "microphone", "video", "audio", "recording", "record",
            "permissions", "access", "capture", "stream", "mic", "cam"
        ],
        "description": "Camera and microphone access settings",
        "priority": "high"
    },
    "location_privacy": {
        "keywords": [
            "location", "gps", "geolocation", "where you are", "position",
            "coordinates", "address", "nearby"
        ],
        "description": "Location and geolocation privacy settings",
        "priority": "high"
    },
    "personal_information": {
        "keywords": [
            "personal info", "profile", "name", "email", "phone", "address",
            "contact", "identity", "demographics", "personal information"
        ],
        "description": "Personal information and profile settings",
        "priority": "medium"
    },
    "communication_privacy": {
        "keywords": [
            "messages", "chat", "communication", "calls", "meeting", "conversation",
            "dialogue", "discussion", "correspondence", "chat history"
        ],
        "description": "Communication and messaging privacy settings",
        "priority": "medium"
    },
    "account_security": {
        "keywords": [
            "security", "password", "authentication", "login", "account", "access",
            "verification", "two-factor", "2fa", "mfa", "passcode"
        ],
        "description": "Account security and authentication settings",
        "priority": "high"
    },
    "sharing_settings": {
        "keywords": [
            "share", "public", "private", "visibility", "who can see", "audience",
            "followers", "friends", "connections", "sharing"
        ],
        "description": "Content sharing and visibility settings",
        "priority": "medium"
    },
    "notification_privacy": {
        "keywords": [
            "notifications", "alerts", "reminders", "email notifications",
            "push notifications", "updates", "announcements"
        ],
        "description": "Notification and alert privacy settings",
        "priority": "low"
    },
    "data_retention": {
        "keywords": [
            "retention", "delete", "remove", "expire", "storage", "history",
            "archive", "backup", "cleanup", "download data", "export data"
        ],
        "description": "Data retention and deletion settings",
        "priority": "high"
    },
    "third_party_sharing": {
        "keywords": [
            "third party", "third-party", "partners", "integrations", "external",
            "api", "affiliates", "vendors", "service providers"
        ],
        "description": "Third-party data sharing and integration settings",
        "priority": "high"
    },
    "cookie_consent": {
        "keywords": [
            "cookie", "cookies", "accept all cookies", "targeting cookies",
            "functional cookies", "performance cookies", "cookie consent"
        ],
        "description": "Cookie consent and management settings",
        "priority": "high"
    }
}


class PrivacyMapSummarizer:
    """Summarizes privacy map JSON files and categorizes privacy settings."""
    
    def __init__(self, outputs_dir: str = "outputs"):
        """
        Initialize the summarizer.
        
        Args:
            outputs_dir: Directory containing privacy map JSON files
        """
        self.outputs_dir = Path(outputs_dir)
        self.privacy_categories = PRIVACY_CATEGORIES
        
    def classify_control(self, control_label: str) -> List[str]:
        """
        Classify a control into privacy categories based on its label.
        
        Args:
            control_label: The label text of the control
            
        Returns:
            List of category names that match this control
        """
        if not control_label:
            return []
        
        label_lower = control_label.lower()
        matches = []
        
        for category, info in self.privacy_categories.items():
            for keyword in info["keywords"]:
                if keyword.lower() in label_lower:
                    if category not in matches:
                        matches.append(category)
                    break
        
        return matches
    
    def load_json_file(self, file_path: Path) -> Dict:
        """Load and parse a JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return None
    
    def analyze_file(self, file_path: Path) -> Dict:
        """
        Analyze a single privacy map JSON file.
        
        Returns:
            Dictionary with analysis results
        """
        data = self.load_json_file(file_path)
        if not data:
            return None
        
        # Initialize statistics
        stats = {
            "file_name": file_path.name,
            "host": data.get("host", "unknown"),
            "start_url": data.get("start_url", ""),
            "total_pages": len(data.get("discoveries", [])),
            "total_controls": data.get("summary", {}).get("controls_found", 0),
            "pages_with_privacy": 0,
            "privacy_controls_by_category": defaultdict(int),
            "privacy_controls": [],
            "pages": [],
            "category_distribution": defaultdict(int),
            "unique_privacy_settings": set()
        }
        
        discoveries = data.get("discoveries", [])
        
        for discovery in discoveries:
            path = discovery.get("path", [])
            controls = discovery.get("controls", [])
            page_url = path[0] if path else "unknown"
            
            page_info = {
                "url": page_url,
                "total_controls": len(controls),
                "privacy_controls": [],
                "categories_found": set()
            }
            
            privacy_found = False
            
            for control in controls:
                label = control.get("label", "")
                control_type = control.get("type", "")
                selector = control.get("selector", "")
                
                # Classify the control
                categories = self.classify_control(label)
                
                if categories:
                    privacy_found = True
                    privacy_control = {
                        "label": label,
                        "type": control_type,
                        "selector": selector,
                        "categories": categories,
                        "url": page_url
                    }
                    
                    page_info["privacy_controls"].append(privacy_control)
                    stats["privacy_controls"].append(privacy_control)
                    stats["unique_privacy_settings"].add(label.lower().strip())
                    
                    for cat in categories:
                        stats["privacy_controls_by_category"][cat] += 1
                        page_info["categories_found"].add(cat)
            
            if privacy_found:
                stats["pages_with_privacy"] += 1
                page_info["categories_found"] = list(page_info["categories_found"])
                stats["pages"].append(page_info)
        
        # Convert set to list for JSON serialization
        stats["unique_privacy_settings"] = list(stats["unique_privacy_settings"])
        stats["category_distribution"] = dict(stats["privacy_controls_by_category"])
        
        return stats
    
    def summarize_all_files(self) -> Dict:
        """
        Analyze all JSON files in the outputs directory.
        
        Returns:
            Comprehensive summary of all files
        """
        if not self.outputs_dir.exists():
            return {"error": f"Directory {self.outputs_dir} does not exist"}
        
        json_files = list(self.outputs_dir.glob("privacy_map_*.json"))
        
        if not json_files:
            return {"error": f"No privacy map JSON files found in {self.outputs_dir}"}
        
        all_stats = []
        combined_summary = {
            "summary_generated_at": datetime.now().isoformat(),
            "files_analyzed": len(json_files),
            "file_details": [],
            "combined_statistics": {
                "total_pages_analyzed": 0,
                "total_privacy_controls": 0,
                "pages_with_privacy": 0,
                "category_totals": defaultdict(int),
                "all_unique_settings": set(),
                "most_common_settings": []
            }
        }
        
        # Analyze each file
        for json_file in sorted(json_files):
            print(f"Analyzing {json_file.name}...")
            stats = self.analyze_file(json_file)
            if stats:
                all_stats.append(stats)
                combined_summary["file_details"].append({
                    "file": json_file.name,
                    "host": stats["host"],
                    "pages": stats["total_pages"],
                    "privacy_controls": len(stats["privacy_controls"]),
                    "categories": stats["category_distribution"]
                })
        
        # Combine statistics
        for stats in all_stats:
            combined_summary["combined_statistics"]["total_pages_analyzed"] += stats["total_pages"]
            combined_summary["combined_statistics"]["total_privacy_controls"] += len(stats["privacy_controls"])
            combined_summary["combined_statistics"]["pages_with_privacy"] += stats["pages_with_privacy"]
            
            for cat, count in stats["category_distribution"].items():
                combined_summary["combined_statistics"]["category_totals"][cat] += count
            
            combined_summary["combined_statistics"]["all_unique_settings"].update(
                stats["unique_privacy_settings"]
            )
        
        # Convert to regular dict for JSON serialization
        combined_summary["combined_statistics"]["category_totals"] = dict(
            combined_summary["combined_statistics"]["category_totals"]
        )
        combined_summary["combined_statistics"]["all_unique_settings"] = list(
            combined_summary["combined_statistics"]["all_unique_settings"]
        )
        
        # Find most common settings (appearing in multiple files)
        setting_counts = defaultdict(int)
        for stats in all_stats:
            for setting in stats["unique_privacy_settings"]:
                setting_counts[setting] += 1
        
        most_common = sorted(setting_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        combined_summary["combined_statistics"]["most_common_settings"] = [
            {"setting": setting, "files_found_in": count} 
            for setting, count in most_common
        ]
        
        # Add detailed file stats
        combined_summary["detailed_file_stats"] = all_stats
        
        return combined_summary
    
    def generate_text_report(self, summary: Dict) -> str:
        """Generate a human-readable text report."""
        if "error" in summary:
            return f"Error: {summary['error']}"
        
        report = []
        report.append("=" * 80)
        report.append("PRIVACY MAP SUMMARY REPORT")
        report.append("=" * 80)
        report.append(f"Generated: {summary['summary_generated_at']}")
        report.append(f"Files Analyzed: {summary['files_analyzed']}")
        report.append("")
        
        # Combined statistics
        stats = summary["combined_statistics"]
        report.append("COMBINED STATISTICS")
        report.append("-" * 80)
        report.append(f"Total Pages Analyzed: {stats['total_pages_analyzed']}")
        report.append(f"Pages with Privacy Controls: {stats['pages_with_privacy']}")
        report.append(f"Total Privacy Controls Found: {stats['total_privacy_controls']}")
        report.append(f"Unique Privacy Settings: {len(stats['all_unique_settings'])}")
        report.append("")
        
        # Category breakdown
        report.append("PRIVACY CATEGORIES")
        report.append("-" * 80)
        for category, count in sorted(stats['category_totals'].items(), 
                                     key=lambda x: x[1], reverse=True):
            cat_info = self.privacy_categories.get(category, {})
            description = cat_info.get("description", category)
            priority = cat_info.get("priority", "unknown")
            report.append(f"  {category}: {count} controls ({priority} priority)")
            report.append(f"    {description}")
        report.append("")
        
        # Most common settings
        report.append("MOST COMMON PRIVACY SETTINGS")
        report.append("-" * 80)
        for item in stats['most_common_settings'][:15]:
            report.append(f"  • {item['setting']} (found in {item['files_found_in']} file(s))")
        report.append("")
        
        # File-by-file breakdown
        report.append("FILE-BY-FILE BREAKDOWN")
        report.append("-" * 80)
        for file_detail in summary["file_details"]:
            report.append(f"\nFile: {file_detail['file']}")
            report.append(f"  Host: {file_detail['host']}")
            report.append(f"  Pages: {file_detail['pages']}")
            report.append(f"  Privacy Controls: {file_detail['privacy_controls']}")
            report.append(f"  Categories Found: {', '.join(file_detail['categories'].keys())}")
        
        # Detailed privacy controls by category
        report.append("\n")
        report.append("DETAILED PRIVACY CONTROLS BY CATEGORY")
        report.append("-" * 80)
        
        # Group controls by category
        category_controls = defaultdict(list)
        for file_stats in summary["detailed_file_stats"]:
            for control in file_stats["privacy_controls"]:
                for cat in control["categories"]:
                    category_controls[cat].append({
                        "label": control["label"],
                        "type": control["type"],
                        "url": control["url"],
                        "file": file_stats["file_name"]
                    })
        
        for category in sorted(category_controls.keys()):
            cat_info = self.privacy_categories.get(category, {})
            description = cat_info.get("description", category)
            report.append(f"\n{category.upper().replace('_', ' ')}")
            report.append(f"  {description}")
            report.append(f"  Total Controls: {len(category_controls[category])}")
            
            # Show unique controls
            unique_labels = set()
            for control in category_controls[category]:
                unique_labels.add(control["label"])
            
            report.append(f"  Unique Settings: {len(unique_labels)}")
            for label in sorted(unique_labels)[:10]:  # Show first 10
                report.append(f"    • {label}")
            if len(unique_labels) > 10:
                report.append(f"    ... and {len(unique_labels) - 10} more")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def save_summary(self, summary: Dict, output_file: str = "privacy_summary.json"):
        """Save summary to JSON file."""
        output_path = self.outputs_dir.parent / output_file
        
        # Convert sets to lists for JSON serialization
        def convert_sets(obj):
            if isinstance(obj, set):
                return list(obj)
            elif isinstance(obj, dict):
                return {k: convert_sets(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_sets(item) for item in obj]
            return obj
        
        summary_serializable = convert_sets(summary)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary_serializable, f, indent=2, ensure_ascii=False)
        
        print(f"Summary saved to {output_path}")
        return output_path


def main():
    """Main function to run the summarizer."""
    print("🔍 Privacy Map Summarizer")
    print("=" * 60)
    
    # Initialize summarizer
    summarizer = PrivacyMapSummarizer(outputs_dir="outputs")
    
    # Generate summary
    print("\nAnalyzing privacy map files...")
    summary = summarizer.summarize_all_files()
    
    if "error" in summary:
        print(f"❌ Error: {summary['error']}")
        return
    
    # Generate text report
    print("\nGenerating text report...")
    text_report = summarizer.generate_text_report(summary)
    
    # Print report
    print("\n")
    print(text_report)
    
    # Save JSON summary
    print("\nSaving summary...")
    summarizer.save_summary(summary, "privacy_summary.json")
    
    # Save text report
    text_report_path = summarizer.outputs_dir.parent / "privacy_summary.txt"
    with open(text_report_path, 'w', encoding='utf-8') as f:
        f.write(text_report)
    print(f"Text report saved to {text_report_path}")
    
    print("\n✅ Summary complete!")


if __name__ == "__main__":
    main()

