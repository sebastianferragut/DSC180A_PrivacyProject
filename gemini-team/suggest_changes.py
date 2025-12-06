#!/usr/bin/env python3
"""
Script to generate privacy setting recommendations by comparing a user's privacy map
against the privacy settings catalog.

Usage:
    python suggest_changes.py <privacy_map_file> [--catalog <catalog_file>] [--output <output_file>]
    Example:
        python suggest_changes.py outputs/privacy_map_20251029_131608.json --catalog privacy_settings_catalog.json --format json --output suggestions/recommendations20251029_131608.json
        python suggest_changes.py outputs/privacy_map_20251029_131753.json --catalog privacy_settings_catalog.json --format json --output suggestions/recommendations20251029_131753.json
        python suggest_changes.py outputs/privacy_map_20251104_100756.json --catalog privacy_settings_catalog.json --format json --output suggestions/recommendations20251104_100756.json

"""

import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from datetime import datetime


class PrivacyRecommendationEngine:
    """Engine for generating privacy setting recommendations."""
    
    def __init__(self, catalog_path: str):
        """Initialize with the privacy settings catalog."""
        with open(catalog_path, 'r', encoding='utf-8') as f:
            self.catalog = json.load(f)
        
        # Build lookup structures for efficient matching
        self._build_lookups()
    
    def _build_lookups(self):
        """Build lookup structures for fast setting matching."""
        # Map setting names (normalized) to catalog entries
        self.setting_lookup: Dict[str, List[Dict]] = {}
        
        # Process all_settings from catalog
        for setting in self.catalog.get('all_settings', []):
            setting_name = self._normalize_setting_name(setting['setting'])
            if setting_name not in self.setting_lookup:
                self.setting_lookup[setting_name] = []
            self.setting_lookup[setting_name].append(setting)
        
        # Also process category settings
        for category_data in self.catalog.get('categories', {}).values():
            for setting in category_data.get('settings', []):
                setting_name = self._normalize_setting_name(setting['setting'])
                if setting_name not in self.setting_lookup:
                    self.setting_lookup[setting_name] = []
                if setting not in self.setting_lookup[setting_name]:
                    self.setting_lookup[setting_name].append(setting)
    
    def _normalize_setting_name(self, name: str) -> str:
        """Normalize setting name for comparison."""
        return name.lower().strip()
    
    def _find_catalog_entry(self, control_label: str, control_type: str) -> Optional[Dict]:
        """Find matching catalog entry for a control."""
        normalized = self._normalize_setting_name(control_label)
        
        # Direct match
        if normalized in self.setting_lookup:
            candidates = self.setting_lookup[normalized]
            # Prefer exact type match
            for candidate in candidates:
                if candidate.get('type') == control_type:
                    return candidate
            # Return first match if no type match
            if candidates:
                return candidates[0]
        
        # Fuzzy match - check if any catalog setting contains or is contained in the label
        for catalog_name, entries in self.setting_lookup.items():
            if catalog_name in normalized or normalized in catalog_name:
                for entry in entries:
                    if entry.get('type') == control_type:
                        return entry
                if entries:
                    return entries[0]
        
        return None
    
    def _is_privacy_enhancing(self, setting: Dict) -> bool:
        """Determine if a setting is privacy-enhancing (should be enabled)."""
        setting_name = self._normalize_setting_name(setting['setting'])
        categories = [c.lower() for c in setting.get('categories', [])]
        
        # Privacy-enhancing keywords
        privacy_keywords = [
            'require', 'secure', 'passcode', 'confirm', 'auto-delete',
            'disable', 'block', 'prevent', 'restrict', 'limit'
        ]
        
        # Privacy-reducing keywords
        privacy_reducing_keywords = [
            'accept all', 'targeting', 'tracking', 'share', 'sync',
            'allow', 'enable', 'automatic'
        ]
        
        # Check keywords
        has_privacy_keyword = any(kw in setting_name for kw in privacy_keywords)
        has_reducing_keyword = any(kw in setting_name for kw in privacy_reducing_keywords)
        
        # Category-based heuristics
        if 'account_security' in categories:
            return True  # Security settings are generally privacy-enhancing
        if 'data_retention' in categories and 'auto-delete' in setting_name:
            return True
        if 'cookie_consent' in categories or 'data_collection' in categories:
            return False  # Cookie/data collection settings are generally privacy-reducing
        
        # Default based on keywords
        if has_privacy_keyword and not has_reducing_keyword:
            return True
        if has_reducing_keyword and not has_privacy_keyword:
            return False
        
        # Default: be conservative - assume settings should be reviewed
        return None
    
    def _get_recommendation(self, control: Dict, catalog_entry: Optional[Dict]) -> Optional[Dict]:
        """Generate a recommendation for a single control."""
        control_label = control.get('label', '')
        control_type = control.get('type', '')
        
        if not catalog_entry:
            return {
                'setting': control_label,
                'type': control_type,
                'status': 'unknown',
                'recommendation': 'review',
                'reason': 'Setting not found in catalog - manual review recommended',
                'priority': 'low'
            }
        
        # Determine if this is privacy-enhancing
        is_enhancing = self._is_privacy_enhancing(catalog_entry)
        
        if is_enhancing is None:
            return {
                'setting': control_label,
                'type': control_type,
                'status': 'review_needed',
                'recommendation': 'review',
                'reason': 'Setting requires manual review to determine optimal configuration',
                'priority': 'medium',
                'categories': catalog_entry.get('categories', []),
                'page': catalog_entry.get('pages', [])[0] if catalog_entry.get('pages') else None
            }
        
        # For privacy-enhancing settings, recommend enabling
        # For privacy-reducing settings, recommend disabling
        if is_enhancing:
            return {
                'setting': control_label,
                'type': control_type,
                'status': 'should_enable',
                'recommendation': 'enable',
                'reason': f"Privacy-enhancing setting in categories: {', '.join(catalog_entry.get('categories', []))}",
                'priority': 'high' if 'account_security' in catalog_entry.get('categories', []) else 'medium',
                'categories': catalog_entry.get('categories', []),
                'page': catalog_entry.get('pages', [])[0] if catalog_entry.get('pages') else None
            }
        else:
            return {
                'setting': control_label,
                'type': control_type,
                'status': 'should_disable',
                'recommendation': 'disable',
                'reason': f"Privacy-reducing setting in categories: {', '.join(catalog_entry.get('categories', []))}",
                'priority': 'high' if 'data_collection' in catalog_entry.get('categories', []) or 
                              'cookie_consent' in catalog_entry.get('categories', []) else 'medium',
                'categories': catalog_entry.get('categories', []),
                'page': catalog_entry.get('pages', [])[0] if catalog_entry.get('pages') else None
            }
    
    def analyze_privacy_map(self, privacy_map_path: str) -> Dict[str, Any]:
        """Analyze a privacy map and generate recommendations."""
        with open(privacy_map_path, 'r', encoding='utf-8') as f:
            privacy_map = json.load(f)
        
        recommendations = []
        settings_found = set()
        
        # Process all discoveries in the privacy map
        for discovery in privacy_map.get('discoveries', []):
            page_url = discovery.get('path', [None])[0] if discovery.get('path') else None
            
            for control in discovery.get('controls', []):
                control_label = control.get('label', '')
                control_type = control.get('type', '')
                
                # Skip if we've already processed this setting on this page
                setting_key = f"{page_url}::{control_label}"
                if setting_key in settings_found:
                    continue
                settings_found.add(setting_key)
                
                # Find matching catalog entry
                catalog_entry = self._find_catalog_entry(control_label, control_type)
                
                # Generate recommendation
                recommendation = self._get_recommendation(control, catalog_entry)
                if recommendation:
                    recommendation['page'] = page_url
                    recommendations.append(recommendation)
        
        # Sort by priority (high -> medium -> low)
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        recommendations.sort(key=lambda x: (
            priority_order.get(x.get('priority', 'low'), 2),
            x.get('setting', '')
        ))
        
        # Generate summary statistics
        summary = {
            'total_recommendations': len(recommendations),
            'by_status': {},
            'by_priority': {},
            'by_category': {}
        }
        
        for rec in recommendations:
            status = rec.get('status', 'unknown')
            priority = rec.get('priority', 'low')
            categories = rec.get('categories', [])
            
            summary['by_status'][status] = summary['by_status'].get(status, 0) + 1
            summary['by_priority'][priority] = summary['by_priority'].get(priority, 0) + 1
            
            for cat in categories:
                summary['by_category'][cat] = summary['by_category'].get(cat, 0) + 1
        
        return {
            'privacy_map_file': Path(privacy_map_path).name,
            'host': privacy_map.get('host', 'unknown'),
            'generated_at': datetime.now().isoformat(),
            'summary': summary,
            'recommendations': recommendations
        }


def format_recommendations_report(results: Dict[str, Any], output_format: str = 'text') -> str:
    """Format recommendations as a readable report."""
    if output_format == 'json':
        return json.dumps(results, indent=2, ensure_ascii=False)
    
    # Text format
    lines = []
    lines.append("=" * 80)
    lines.append("PRIVACY SETTINGS RECOMMENDATIONS")
    lines.append("=" * 80)
    lines.append(f"Privacy Map: {results['privacy_map_file']}")
    lines.append(f"Host: {results['host']}")
    lines.append(f"Generated: {results['generated_at']}")
    lines.append("")
    
    # Summary
    summary = results['summary']
    lines.append("SUMMARY")
    lines.append("-" * 80)
    lines.append(f"Total Recommendations: {summary['total_recommendations']}")
    lines.append("")
    
    lines.append("By Status:")
    for status, count in sorted(summary['by_status'].items()):
        lines.append(f"  {status}: {count}")
    lines.append("")
    
    lines.append("By Priority:")
    for priority, count in sorted(summary['by_priority'].items(), 
                                  key=lambda x: {'high': 0, 'medium': 1, 'low': 2}.get(x[0], 3)):
        lines.append(f"  {priority}: {count}")
    lines.append("")
    
    lines.append("By Category:")
    for category, count in sorted(summary['by_category'].items(), key=lambda x: -x[1]):
        lines.append(f"  {category}: {count}")
    lines.append("")
    
    # Detailed recommendations
    lines.append("=" * 80)
    lines.append("DETAILED RECOMMENDATIONS")
    lines.append("=" * 80)
    lines.append("")
    
    # Group by priority
    for priority in ['high', 'medium', 'low']:
        priority_recs = [r for r in results['recommendations'] if r.get('priority') == priority]
        if not priority_recs:
            continue
        
        lines.append(f"\n{priority.upper()} PRIORITY ({len(priority_recs)} recommendations)")
        lines.append("-" * 80)
        
        for i, rec in enumerate(priority_recs, 1):
            lines.append(f"\n{i}. {rec['setting']}")
            lines.append(f"   Type: {rec['type']}")
            lines.append(f"   Status: {rec['status']}")
            lines.append(f"   Recommendation: {rec['recommendation'].upper()}")
            lines.append(f"   Reason: {rec['reason']}")
            if rec.get('page'):
                lines.append(f"   Page: {rec['page']}")
            if rec.get('categories'):
                lines.append(f"   Categories: {', '.join(rec['categories'])}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate privacy setting recommendations from a privacy map'
    )
    parser.add_argument(
        'privacy_map',
        help='Path to the privacy map JSON file to analyze'
    )
    parser.add_argument(
        '--catalog',
        default='privacy_settings_catalog.json',
        help='Path to the privacy settings catalog JSON file (default: privacy_settings_catalog.json)'
    )
    parser.add_argument(
        '--output',
        help='Output file path (default: print to stdout)'
    )
    parser.add_argument(
        '--format',
        choices=['text', 'json'],
        default='text',
        help='Output format (default: text)'
    )
    
    args = parser.parse_args()
    
    # Validate files exist
    if not Path(args.privacy_map).exists():
        print(f"Error: Privacy map file not found: {args.privacy_map}", file=sys.stderr)
        sys.exit(1)
    
    if not Path(args.catalog).exists():
        print(f"Error: Catalog file not found: {args.catalog}", file=sys.stderr)
        sys.exit(1)
    
    # Generate recommendations
    try:
        engine = PrivacyRecommendationEngine(args.catalog)
        results = engine.analyze_privacy_map(args.privacy_map)
        
        # Format output
        output = format_recommendations_report(results, args.format)
        
        # Write output
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"Recommendations written to: {args.output}", file=sys.stderr)
        else:
            print(output)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()