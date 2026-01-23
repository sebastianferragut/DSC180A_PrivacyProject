import json
from collections import defaultdict
from typing import List, Dict, Any

def find_duplicates(data: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """
    Find duplicate entries based on multiple criteria:
    1. Same URL
    2. Same image name
    3. Same settings content (normalized)
    """
    duplicates = defaultdict(list)
    
    # Group by URL
    by_url = defaultdict(list)
    for idx, entry in enumerate(data):
        by_url[entry.get('url', '')].append((idx, entry))
    
    # Group by image name
    by_image = defaultdict(list)
    for idx, entry in enumerate(data):
        by_image[entry.get('image', '')].append((idx, entry))
    
    # Find duplicates by URL
    url_duplicates = {}
    for url, entries in by_url.items():
        if len(entries) > 1:
            url_duplicates[url] = [idx for idx, _ in entries]
    
    # Find duplicates by image
    image_duplicates = {}
    for image, entries in by_image.items():
        if len(entries) > 1:
            image_duplicates[image] = [idx for idx, _ in entries]
    
    # Find duplicates by URL + image combination
    url_image_duplicates = {}
    url_image_key = defaultdict(list)
    for idx, entry in enumerate(data):
        key = (entry.get('url', ''), entry.get('image', ''))
        url_image_key[key].append(idx)
    
    for key, indices in url_image_key.items():
        if len(indices) > 1:
            url_image_duplicates[key] = indices
    
    # Find duplicates by settings content (normalized)
    settings_duplicates = {}
    settings_signatures = defaultdict(list)
    for idx, entry in enumerate(data):
        # Create a signature from settings
        settings = entry.get('settings', [])
        # Sort settings by setting name and create a signature
        setting_names = sorted([s.get('setting', '') for s in settings])
        signature = tuple(setting_names)
        settings_signatures[signature].append(idx)
    
    for signature, indices in settings_signatures.items():
        if len(indices) > 1 and len(signature) > 0:  # Only if there are actual settings
            settings_duplicates[signature] = indices
    
    return {
        'by_url': url_duplicates,
        'by_image': image_duplicates,
        'by_url_image': url_image_duplicates,
        'by_settings': settings_duplicates
    }

def format_duplicate_report(data: List[Dict[str, Any]], duplicates: Dict[str, Any]) -> str:
    """Format a human-readable report of duplicates"""
    report = []
    report.append("=" * 80)
    report.append("DUPLICATE ENTRIES REPORT")
    report.append("=" * 80)
    report.append("")
    
    # Report duplicates by URL + Image (most likely to be true duplicates)
    if duplicates['by_url_image']:
        report.append("DUPLICATES BY URL + IMAGE (Most Likely True Duplicates):")
        report.append("-" * 80)
        for (url, image), indices in sorted(duplicates['by_url_image'].items()):
            report.append(f"\nURL: {url}")
            report.append(f"Image: {image}")
            report.append(f"Found at indices: {indices}")
            for idx in indices:
                entry = data[idx]
                report.append(f"  [{idx}] Platform: {entry.get('platform')}, Category: {entry.get('category')}, Settings count: {len(entry.get('settings', []))}")
        report.append("")
    
    # Report duplicates by URL only
    if duplicates['by_url']:
        report.append("DUPLICATES BY URL (Same Page, Different Screenshots):")
        report.append("-" * 80)
        for url, indices in sorted(duplicates['by_url'].items()):
            if len(indices) > 1:
                report.append(f"\nURL: {url}")
                report.append(f"Found at indices: {indices}")
                for idx in indices:
                    entry = data[idx]
                    report.append(f"  [{idx}] Image: {entry.get('image')}, Category: {entry.get('category')}, Settings count: {len(entry.get('settings', []))}")
        report.append("")
    
    # Report duplicates by image only
    if duplicates['by_image']:
        report.append("DUPLICATES BY IMAGE NAME (Same Screenshot, Different URLs):")
        report.append("-" * 80)
        for image, indices in sorted(duplicates['by_image'].items()):
            if len(indices) > 1:
                report.append(f"\nImage: {image}")
                report.append(f"Found at indices: {indices}")
                for idx in indices:
                    entry = data[idx]
                    report.append(f"  [{idx}] URL: {entry.get('url')}, Platform: {entry.get('platform')}, Category: {entry.get('category')}")
        report.append("")
    
    # Report duplicates by settings content
    if duplicates['by_settings']:
        report.append("DUPLICATES BY SETTINGS CONTENT (Same Settings, Different Metadata):")
        report.append("-" * 80)
        # Only show first 10 to avoid overwhelming output
        count = 0
        for signature, indices in sorted(duplicates['by_settings'].items(), key=lambda x: len(x[1]), reverse=True):
            if count >= 10:
                report.append(f"\n... and {len(duplicates['by_settings']) - count} more groups of duplicates by settings")
                break
            if len(indices) > 1:
                report.append(f"\nSettings signature (first 5): {list(signature[:5])}")
                report.append(f"Found at indices: {indices}")
                for idx in indices:
                    entry = data[idx]
                    report.append(f"  [{idx}] URL: {entry.get('url')}, Image: {entry.get('image')}, Platform: {entry.get('platform')}")
                count += 1
        report.append("")
    
    return "\n".join(report)

def main():
    with open('data/all_platforms_classified.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"Total entries: {len(data)}")
    
    duplicates = find_duplicates(data)
    
    # Count duplicates
    url_image_count = sum(len(indices) for indices in duplicates['by_url_image'].values())
    url_count = sum(len(indices) for indices in duplicates['by_url'].values() if len(indices) > 1)
    image_count = sum(len(indices) for indices in duplicates['by_image'].values() if len(indices) > 1)
    settings_count = sum(len(indices) for indices in duplicates['by_settings'].values() if len(indices) > 1)
    
    print(f"\nDuplicate groups found:")
    print(f"  - By URL + Image: {len(duplicates['by_url_image'])} groups ({url_image_count} total entries)")
    print(f"  - By URL only: {len([k for k, v in duplicates['by_url'].items() if len(v) > 1])} groups")
    print(f"  - By Image only: {len([k for k, v in duplicates['by_image'].items() if len(v) > 1])} groups")
    print(f"  - By Settings: {len(duplicates['by_settings'])} groups")
    
    report = format_duplicate_report(data, duplicates)
    
    # Save report to file
    with open('duplicate_report.txt', 'w', encoding='utf-8') as f:
        f.write(report)
    
    print("\n" + report)
    print("\nFull report saved to: duplicate_report.txt")

if __name__ == '__main__':
    main()


