import json
from collections import defaultdict

def flag_duplicates():
    """Create a JSON file with flagged duplicate entries"""
    with open('data/all_platforms_classified.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Find duplicates by URL + Image (most reliable indicator)
    url_image_groups = defaultdict(list)
    for idx, entry in enumerate(data):
        key = (entry.get('url', ''), entry.get('image', ''))
        url_image_groups[key].append(idx)
    
    # Find duplicates by URL (same page, different screenshots)
    url_groups = defaultdict(list)
    for idx, entry in enumerate(data):
        url_groups[entry.get('url', '')].append(idx)
    
    # Find duplicates by settings content
    settings_groups = defaultdict(list)
    for idx, entry in enumerate(data):
        settings = entry.get('settings', [])
        setting_names = tuple(sorted([s.get('setting', '') for s in settings]))
        if len(setting_names) > 0:
            settings_groups[setting_names].append(idx)
    
    # Create flagged data with duplicate indicators
    flagged_data = []
    duplicate_indices = set()
    
    # Mark URL+Image duplicates
    for key, indices in url_image_groups.items():
        if len(indices) > 1:
            for idx in indices:
                duplicate_indices.add(idx)
    
    # Mark URL duplicates (same page)
    for url, indices in url_groups.items():
        if len(indices) > 1:
            for idx in indices:
                duplicate_indices.add(idx)
    
    # Mark settings duplicates
    for signature, indices in settings_groups.items():
        if len(indices) > 1:
            for idx in indices:
                duplicate_indices.add(idx)
    
    # Create summary
    summary = {
        'total_entries': len(data),
        'duplicate_entries_count': len(duplicate_indices),
        'unique_entries_count': len(data) - len(duplicate_indices),
        'duplicate_groups': {
            'by_url_image': {},
            'by_url': {},
            'by_settings': {}
        }
    }
    
    # Add URL+Image duplicates to summary
    for (url, image), indices in url_image_groups.items():
        if len(indices) > 1:
            summary['duplicate_groups']['by_url_image'][f"{url} | {image}"] = {
                'url': url,
                'image': image,
                'indices': indices,
                'count': len(indices)
            }
    
    # Add URL duplicates to summary
    for url, indices in url_groups.items():
        if len(indices) > 1:
            summary['duplicate_groups']['by_url'][url] = {
                'indices': indices,
                'count': len(indices),
                'entries': [{'index': idx, 'image': data[idx].get('image'), 'category': data[idx].get('category')} for idx in indices]
            }
    
    # Add settings duplicates to summary (top 10)
    settings_list = [(sig, indices) for sig, indices in settings_groups.items() if len(indices) > 1]
    settings_list.sort(key=lambda x: len(x[1]), reverse=True)
    for signature, indices in settings_list[:10]:
        summary['duplicate_groups']['by_settings'][f"Settings group ({len(indices)} entries)"] = {
            'indices': indices,
            'count': len(indices),
            'sample_settings': list(signature[:5]) if len(signature) > 0 else [],
            'entries': [{'index': idx, 'url': data[idx].get('url'), 'image': data[idx].get('image'), 'platform': data[idx].get('platform')} for idx in indices]
        }
    
    # Add flags to original data
    for idx, entry in enumerate(data):
        flagged_entry = entry.copy()
        flagged_entry['_is_duplicate'] = idx in duplicate_indices
        flagged_entry['_duplicate_reasons'] = []
        
        # Check why it's a duplicate
        url = entry.get('url', '')
        image = entry.get('image', '')
        settings = entry.get('settings', [])
        setting_names = tuple(sorted([s.get('setting', '') for s in settings]))
        
        if len(url_image_groups.get((url, image), [])) > 1:
            flagged_entry['_duplicate_reasons'].append('same_url_and_image')
        if len(url_groups.get(url, [])) > 1:
            flagged_entry['_duplicate_reasons'].append('same_url')
        if len(settings_groups.get(setting_names, [])) > 1 and len(setting_names) > 0:
            flagged_entry['_duplicate_reasons'].append('same_settings')
        
        flagged_data.append(flagged_entry)
    
    # Save flagged data
    with open('data/all_platforms_classified_flagged.json', 'w', encoding='utf-8') as f:
        json.dump(flagged_data, f, indent=2, ensure_ascii=False)
    
    # Save summary
    with open('duplicate_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"Flagged {len(duplicate_indices)} duplicate entries out of {len(data)} total entries")
    print(f"Created files:")
    print(f"  - data/all_platforms_classified_flagged.json (original data with _is_duplicate and _duplicate_reasons fields)")
    print(f"  - duplicate_summary.json (summary of duplicate groups)")

if __name__ == '__main__':
    flag_duplicates()


