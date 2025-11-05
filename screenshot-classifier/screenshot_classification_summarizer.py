#!/usr/bin/env python3
"""
Screenshot Classification Summarizer

Analyzes screenshot classification JSON files and generates comprehensive summaries
of privacy-related settings found in the analyzed screenshots.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict
from datetime import datetime
import re


# Privacy categories with descriptions (matching screenshot_classification.py)
PRIVACY_CATEGORIES = {
    "access_to_device": {
        "description": "Camera and microphone access settings",
        "priority": "high"
    },
    "personal_information": {
        "description": "Personal information and profile settings",
        "priority": "medium"
    },
    "sharing_settings": {
        "description": "Content sharing and visibility settings",
        "priority": "medium"
    },
    "location_privacy": {
        "description": "Location and geolocation privacy settings",
        "priority": "high"
    },
    "communication_privacy": {
        "description": "Communication and messaging privacy settings",
        "priority": "medium"
    },
    "notification_privacy": {
        "description": "Notification and alert privacy settings",
        "priority": "low"
    },
    "third_party_sharing": {
        "description": "Third-party data sharing and integration settings",
        "priority": "high"
    },
    "data_collection": {
        "description": "Settings related to data collection and analytics",
        "priority": "high"
    },
    "data_retention": {
        "description": "Data retention and deletion settings",
        "priority": "high"
    },
    "account_security": {
        "description": "Account security and authentication settings",
        "priority": "high"
    }
}


class ScreenshotClassificationSummarizer:
    """Summarizes screenshot classification JSON files."""
    
    def __init__(self, results_dir: str = "."):
        """
        Initialize the summarizer.
        
        Args:
            results_dir: Directory containing classification result JSON files
        """
        self.results_dir = Path(results_dir)
        self.privacy_categories = PRIVACY_CATEGORIES
        
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
        Analyze a single classification results JSON file.
        
        Returns:
            Dictionary with analysis results
        """
        data = self.load_json_file(file_path)
        if not data:
            return None
        
        # Initialize statistics
        stats = {
            "file_name": file_path.name,
            "timestamp": data.get("timestamp", ""),
            "total_images": data.get("total_images", 0),
            "successful_classifications": data.get("summary", {}).get("successful_classifications", 0),
            "failed_classifications": data.get("summary", {}).get("failed_classifications", 0),
            "classifications": [],
            "category_totals": defaultdict(int),
            "category_details": defaultdict(list),
            "page_types": [],
            "all_detected_settings": [],
            "confidence_stats": {
                "total": 0,
                "sum": 0.0,
                "min": 1.0,
                "max": 0.0
            },
            "high_confidence_classifications": 0,
            "screenshots_with_privacy": 0
        }
        
        classifications = data.get("classifications", [])
        
        for classification in classifications:
            status = classification.get("status", "unknown")
            image_path = classification.get("image_path", "")
            image_name = Path(image_path).name if image_path else "unknown"
            
            detected_categories = classification.get("detected_categories", [])
            category_scores = classification.get("category_scores", {})
            primary_category = classification.get("primary_category")
            confidence = classification.get("confidence", 0.0)
            page_type = classification.get("page_type", "")
            detected_settings = classification.get("detected_settings", [])
            
            classification_info = {
                "image_name": image_name,
                "image_path": image_path,
                "status": status,
                "detected_categories": detected_categories,
                "primary_category": primary_category,
                "confidence": confidence,
                "page_type": page_type,
                "detected_settings": detected_settings,
                "category_scores": category_scores
            }
            
            stats["classifications"].append(classification_info)
            
            # Track categories
            for cat in detected_categories:
                stats["category_totals"][cat] += 1
                stats["category_details"][cat].append({
                    "image": image_name,
                    "confidence": confidence,
                    "page_type": page_type
                })
            
            # Track page types
            if page_type:
                stats["page_types"].append(page_type)
            
            # Track detected settings
            stats["all_detected_settings"].extend(detected_settings)
            
            # Track confidence statistics
            if confidence > 0:
                stats["confidence_stats"]["total"] += 1
                stats["confidence_stats"]["sum"] += confidence
                stats["confidence_stats"]["min"] = min(stats["confidence_stats"]["min"], confidence)
                stats["confidence_stats"]["max"] = max(stats["confidence_stats"]["max"], confidence)
                
                if confidence >= 0.8:
                    stats["high_confidence_classifications"] += 1
            
            # Count screenshots with privacy settings
            if detected_categories:
                stats["screenshots_with_privacy"] += 1
        
        # Calculate average confidence
        if stats["confidence_stats"]["total"] > 0:
            stats["confidence_stats"]["average"] = stats["confidence_stats"]["sum"] / stats["confidence_stats"]["total"]
        else:
            stats["confidence_stats"]["average"] = 0.0
        
        # Convert defaultdicts to regular dicts
        stats["category_totals"] = dict(stats["category_totals"])
        
        return stats
    
    def summarize_all_files(self) -> Dict:
        """
        Analyze all classification JSON files in the results directory.
        
        Returns:
            Comprehensive summary of all files
        """
        # Look for classification*.json files (including classification_results.json)
        json_files_list = list(self.results_dir.glob("classification*.json"))
        
        # Remove duplicates by converting to set of string paths
        seen = set()
        json_files = []
        for f in json_files_list:
            if str(f) not in seen:
                seen.add(str(f))
                json_files.append(f)
        
        if not json_files:
            return {"error": f"No classification JSON files found in {self.results_dir}"}
        
        all_stats = []
        combined_summary = {
            "summary_generated_at": datetime.now().isoformat(),
            "files_analyzed": len(json_files),
            "file_details": [],
            "combined_statistics": {
                "total_screenshots": 0,
                "successful_classifications": 0,
                "failed_classifications": 0,
                "screenshots_with_privacy": 0,
                "category_totals": defaultdict(int),
                "all_page_types": [],
                "unique_settings_count": 0,
                "confidence_stats": {
                    "total": 0,
                    "sum": 0.0,
                    "average": 0.0,
                    "min": 1.0,
                    "max": 0.0
                },
                "high_confidence_count": 0
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
                    "screenshots": stats["total_images"],
                    "successful": stats["successful_classifications"],
                    "failed": stats["failed_classifications"],
                    "with_privacy": stats["screenshots_with_privacy"],
                    "categories_found": list(stats["category_totals"].keys())
                })
        
        # Combine statistics
        for stats in all_stats:
            combined_summary["combined_statistics"]["total_screenshots"] += stats["total_images"]
            combined_summary["combined_statistics"]["successful_classifications"] += stats["successful_classifications"]
            combined_summary["combined_statistics"]["failed_classifications"] += stats["failed_classifications"]
            combined_summary["combined_statistics"]["screenshots_with_privacy"] += stats["screenshots_with_privacy"]
            combined_summary["combined_statistics"]["high_confidence_count"] += stats["high_confidence_classifications"]
            
            for cat, count in stats["category_totals"].items():
                combined_summary["combined_statistics"]["category_totals"][cat] += count
            
            combined_summary["combined_statistics"]["all_page_types"].extend(stats["page_types"])
            
            # Combine confidence stats
            if stats["confidence_stats"]["total"] > 0:
                cs = combined_summary["combined_statistics"]["confidence_stats"]
                cs["total"] += stats["confidence_stats"]["total"]
                cs["sum"] += stats["confidence_stats"]["sum"]
                cs["min"] = min(cs["min"], stats["confidence_stats"]["min"])
                cs["max"] = max(cs["max"], stats["confidence_stats"]["max"])
        
        # Calculate overall average confidence
        cs = combined_summary["combined_statistics"]["confidence_stats"]
        if cs["total"] > 0:
            cs["average"] = cs["sum"] / cs["total"]
        
        # Get unique page types
        combined_summary["combined_statistics"]["unique_page_types"] = list(set(
            combined_summary["combined_statistics"]["all_page_types"]
        ))
        
        # Count unique settings across all files
        all_settings = set()
        for stats in all_stats:
            for setting in stats["all_detected_settings"]:
                all_settings.add(setting.lower().strip())
        combined_summary["combined_statistics"]["unique_settings_count"] = len(all_settings)
        
        # Convert defaultdict to regular dict
        combined_summary["combined_statistics"]["category_totals"] = dict(
            combined_summary["combined_statistics"]["category_totals"]
        )
        
        # Add detailed file stats
        combined_summary["detailed_file_stats"] = all_stats
        
        return combined_summary
    
    def generate_text_report(self, summary: Dict) -> str:
        """Generate a human-readable text report."""
        if "error" in summary:
            return f"Error: {summary['error']}"
        
        report = []
        report.append("=" * 80)
        report.append("SCREENSHOT CLASSIFICATION SUMMARY REPORT")
        report.append("=" * 80)
        report.append(f"Generated: {summary['summary_generated_at']}")
        report.append(f"Files Analyzed: {summary['files_analyzed']}")
        report.append("")
        
        # Combined statistics
        stats = summary["combined_statistics"]
        report.append("COMBINED STATISTICS")
        report.append("-" * 80)
        report.append(f"Total Screenshots Analyzed: {stats['total_screenshots']}")
        report.append(f"Successful Classifications: {stats['successful_classifications']}")
        report.append(f"Failed Classifications: {stats['failed_classifications']}")
        report.append(f"Screenshots with Privacy Settings: {stats['screenshots_with_privacy']}")
        report.append(f"Unique Settings Detected: {stats['unique_settings_count']}")
        report.append(f"High Confidence Classifications (≥0.8): {stats['high_confidence_count']}")
        report.append("")
        
        # Confidence statistics
        if stats["confidence_stats"]["total"] > 0:
            cs = stats["confidence_stats"]
            report.append("CONFIDENCE STATISTICS")
            report.append("-" * 80)
            report.append(f"Average Confidence: {cs['average']:.2f}")
            report.append(f"Min Confidence: {cs['min']:.2f}")
            report.append(f"Max Confidence: {cs['max']:.2f}")
            report.append(f"Total Classifications with Confidence: {cs['total']}")
            report.append("")
        
        # Category breakdown
        report.append("PRIVACY CATEGORIES")
        report.append("-" * 80)
        if stats['category_totals']:
            for category, count in sorted(stats['category_totals'].items(), 
                                         key=lambda x: x[1], reverse=True):
                cat_info = self.privacy_categories.get(category, {})
                description = cat_info.get("description", category)
                priority = cat_info.get("priority", "unknown")
                report.append(f"  {category}: {count} screenshots ({priority} priority)")
                report.append(f"    {description}")
        else:
            report.append("  No privacy categories detected")
        report.append("")
        
        # Page types
        if stats.get("unique_page_types"):
            report.append("PAGE TYPES DETECTED")
            report.append("-" * 80)
            for page_type in sorted(stats["unique_page_types"]):
                if page_type:  # Skip empty strings
                    report.append(f"  • {page_type}")
            report.append("")
        
        # File-by-file breakdown
        report.append("FILE-BY-FILE BREAKDOWN")
        report.append("-" * 80)
        for file_detail in summary["file_details"]:
            report.append(f"\nFile: {file_detail['file']}")
            report.append(f"  Screenshots: {file_detail['screenshots']}")
            report.append(f"  Successful: {file_detail['successful']}")
            report.append(f"  Failed: {file_detail['failed']}")
            report.append(f"  With Privacy Settings: {file_detail['with_privacy']}")
            if file_detail['categories_found']:
                report.append(f"  Categories Found: {', '.join(file_detail['categories_found'])}")
            else:
                report.append(f"  Categories Found: None")
        
        # Detailed classifications by category
        report.append("\n")
        report.append("DETAILED CLASSIFICATIONS BY CATEGORY")
        report.append("-" * 80)
        
        # Group classifications by category
        category_classifications = defaultdict(list)
        for file_stats in summary["detailed_file_stats"]:
            for classification in file_stats["classifications"]:
                for cat in classification["detected_categories"]:
                    category_classifications[cat].append({
                        "image": classification["image_name"],
                        "page_type": classification["page_type"],
                        "confidence": classification["confidence"],
                        "settings": classification["detected_settings"]
                    })
        
        for category in sorted(category_classifications.keys()):
            cat_info = self.privacy_categories.get(category, {})
            description = cat_info.get("description", category)
            report.append(f"\n{category.upper().replace('_', ' ')}")
            report.append(f"  {description}")
            report.append(f"  Total Screenshots: {len(category_classifications[category])}")
            
            # Show screenshots in this category
            for item in category_classifications[category][:10]:  # Show first 10
                report.append(f"    • {item['image']}")
                if item['page_type']:
                    report.append(f"      Page Type: {item['page_type']}")
                if item['confidence'] > 0:
                    report.append(f"      Confidence: {item['confidence']:.2f}")
                if item['settings']:
                    report.append(f"      Settings Found: {len(item['settings'])}")
                    # Show first 2 settings as examples
                    for setting in item['settings'][:2]:
                        setting_short = setting[:60] + "..." if len(setting) > 60 else setting
                        report.append(f"        - {setting_short}")
            
            if len(category_classifications[category]) > 10:
                report.append(f"    ... and {len(category_classifications[category]) - 10} more screenshots")
        
        # Screenshots with highest confidence
        report.append("\n")
        report.append("HIGH CONFIDENCE CLASSIFICATIONS")
        report.append("-" * 80)
        
        high_conf_classifications = []
        for file_stats in summary["detailed_file_stats"]:
            for classification in file_stats["classifications"]:
                if classification.get("confidence", 0) >= 0.8:
                    high_conf_classifications.append({
                        "image": classification["image_name"],
                        "confidence": classification["confidence"],
                        "categories": classification["detected_categories"],
                        "page_type": classification["page_type"]
                    })
        
        high_conf_classifications.sort(key=lambda x: x["confidence"], reverse=True)
        
        for item in high_conf_classifications[:10]:  # Show top 10
            report.append(f"  • {item['image']}")
            report.append(f"    Confidence: {item['confidence']:.2f}")
            report.append(f"    Categories: {', '.join(item['categories']) if item['categories'] else 'None'}")
            if item['page_type']:
                report.append(f"    Page Type: {item['page_type']}")
        
        if len(high_conf_classifications) > 10:
            report.append(f"  ... and {len(high_conf_classifications) - 10} more high confidence classifications")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def save_summary(self, summary: Dict, output_file: str = "classification_summary.json"):
        """Save summary to JSON file."""
        output_path = self.results_dir / output_file
        
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
    print("🔍 Screenshot Classification Summarizer")
    print("=" * 60)
    
    # Initialize summarizer
    summarizer = ScreenshotClassificationSummarizer(results_dir=".")
    
    # Generate summary
    print("\nAnalyzing classification result files...")
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
    summarizer.save_summary(summary, "classification_summary.json")
    
    # Save text report
    text_report_path = summarizer.results_dir / "classification_summary.txt"
    with open(text_report_path, 'w', encoding='utf-8') as f:
        f.write(text_report)
    print(f"Text report saved to {text_report_path}")
    
    print("\n✅ Summary complete!")


if __name__ == "__main__":
    main()

