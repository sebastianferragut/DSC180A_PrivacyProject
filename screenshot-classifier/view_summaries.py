#!/usr/bin/env python3
"""
Simple script to view screenshot summaries in a readable format
"""

import json
import os
from pathlib import Path

def view_summaries(json_file="summaries.json"):
    """Display summaries in a readable format."""
    
    if not os.path.exists(json_file):
        print(f"❌ File not found: {json_file}")
        return
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    print("📸 Screenshot Summaries")
    print("=" * 50)
    print(f"Total images processed: {data['total_images']}")
    print(f"Timestamp: {data['timestamp']}")
    print()
    
    for i, summary in enumerate(data['summaries'], 1):
        filename = Path(summary['image_path']).name
        
        if summary['status'] == 'success':
            print(f"📸 {i}. {filename}")
            print("-" * 40)
            print(summary['summary'])
            print()
        else:
            print(f"❌ {i}. {filename} - Error: {summary['message']}")
            print()

def view_single_summary(json_file="summaries.json", image_name=None):
    """View a single summary by image name."""
    
    if not os.path.exists(json_file):
        print(f"❌ File not found: {json_file}")
        return
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    if image_name:
        for summary in data['summaries']:
            if image_name in summary['image_path']:
                filename = Path(summary['image_path']).name
                print(f"📸 {filename}")
                print("=" * 50)
                
                if summary['status'] == 'success':
                    print(summary['summary'])
                else:
                    print(f"❌ Error: {summary['message']}")
                return
        
        print(f"❌ No summary found for: {image_name}")
    else:
        print("Available screenshots:")
        for i, summary in enumerate(data['summaries'], 1):
            filename = Path(summary['image_path']).name
            status = "✅" if summary['status'] == 'success' else "❌"
            print(f"{i:2d}. {status} {filename}")

def main():
    """Main function to view summaries."""
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            view_single_summary()
        elif sys.argv[1] == "--single":
            if len(sys.argv) > 2:
                view_single_summary(image_name=sys.argv[2])
            else:
                print("Usage: python view_summaries.py --single <image_name>")
        else:
            view_single_summary(image_name=sys.argv[1])
    else:
        view_summaries()

if __name__ == "__main__":
    main()
