"""
Generalized visualization script for recommendation JSON files in gemini-team/suggestions.
Creates concise visualizations for any JSON file in the folder.
"""

import json
import os
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import Counter
import numpy as np

# Configuration
SUGGESTIONS_DIR = Path(__file__).parent.parent / "gemini-team" / "suggestions"
OUTPUT_DIR = Path(__file__).parent / "visualizations"


def load_json_file(filepath):
    """Load and parse a JSON recommendation file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_visualizations(data, filename):
    """Create concise visualizations for a recommendation file."""
    summary = data.get('summary', {})
    recommendations = data.get('recommendations', [])
    host = data.get('host', 'Unknown')
    generated_at = data.get('generated_at', 'Unknown')
    
    # Create figure with subplots
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
    
    # Title
    fig.suptitle(f'Privacy Recommendations: {host}\n{os.path.basename(filename)}', 
                 fontsize=16, fontweight='bold', y=0.98)
    
    # 1. Status Distribution (Pie Chart)
    ax1 = fig.add_subplot(gs[0, 0])
    status_data = summary.get('by_status', {})
    if status_data:
        colors_status = {
            'should_disable': '#d62728',
            'should_enable': '#2ca02c',
            'review_needed': '#ff7f0e',
            'unknown': '#7f7f7f'
        }
        labels = list(status_data.keys())
        sizes = list(status_data.values())
        colors = [colors_status.get(label, '#1f77b4') for label in labels]
        ax1.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
        ax1.set_title('Recommendations by Status', fontweight='bold')
    
    # 2. Priority Distribution (Bar Chart)
    ax2 = fig.add_subplot(gs[0, 2])
    priority_data = summary.get('by_priority', {})
    if priority_data:
        priority_order = ['high', 'medium', 'low']
        priorities = [p for p in priority_order if p in priority_data]
        counts = [priority_data[p] for p in priorities]
        colors_priority = {'high': '#d62728', 'medium': '#ff7f0e', 'low': '#2ca02c'}
        bars = ax2.bar(priorities, counts, color=[colors_priority[p] for p in priorities])
        ax2.set_title('Recommendations by Priority', fontweight='bold')
        ax2.set_ylabel('Count')
        ax2.set_xlabel('Priority')
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}', ha='center', va='bottom')
    
    # 3. Category Distribution (Horizontal Bar Chart)
    ax3 = fig.add_subplot(gs[1, 0])
    category_data = summary.get('by_category', {})
    if category_data:
        # Sort by value, descending
        sorted_categories = sorted(category_data.items(), key=lambda x: x[1], reverse=True)
        categories = [cat.replace('_', ' ').title() for cat, _ in sorted_categories]
        counts = [count for _, count in sorted_categories]
        bars = ax3.barh(categories, counts, color='#1f77b4')
        ax3.set_title('Recommendations by Category', fontweight='bold')
        ax3.set_xlabel('Count')
        # Add value labels
        for i, (bar, count) in enumerate(zip(bars, counts)):
            ax3.text(count, bar.get_y() + bar.get_height()/2.,
                    f' {int(count)}', va='center', ha='left')
    
    # 4. Status vs Priority Heatmap
    ax4 = fig.add_subplot(gs[2, 2])
    status_priority_counts = {}
    for rec in recommendations:
        status = rec.get('status', 'unknown')
        priority = rec.get('priority', 'unknown')
        key = (status, priority)
        status_priority_counts[key] = status_priority_counts.get(key, 0) + 1
    
    if status_priority_counts:
        statuses = sorted(set(s for s, _ in status_priority_counts.keys()))
        priorities = ['high', 'medium', 'low']
        heatmap_data = np.zeros((len(statuses), len(priorities)))
        for i, status in enumerate(statuses):
            for j, priority in enumerate(priorities):
                heatmap_data[i, j] = status_priority_counts.get((status, priority), 0)
        
        im = ax4.imshow(heatmap_data, cmap='YlOrRd', aspect='auto')
        ax4.set_xticks(np.arange(len(priorities)))
        ax4.set_yticks(np.arange(len(statuses)))
        ax4.set_xticklabels(priorities)
        ax4.set_yticklabels([s.replace('_', ' ').title() for s in statuses])
        ax4.set_xlabel('Priority')
        ax4.set_ylabel('Status')
        ax4.set_title('Status × Priority Distribution', fontweight='bold')
        
        # Add text annotations
        for i in range(len(statuses)):
            for j in range(len(priorities)):
                text = ax4.text(j, i, int(heatmap_data[i, j]),
                              ha="center", va="center", color="black", fontweight='bold')
        
        # Add colorbar
        plt.colorbar(im, ax=ax4, label='Count')
    
    # 5. Top Settings (Most Frequently Recommended)
    ax5 = fig.add_subplot(gs[1, 2])
    setting_counts = Counter(rec.get('setting', 'Unknown') for rec in recommendations)
    top_settings = setting_counts.most_common(10)
    if top_settings:
        settings = [s[:30] + '...' if len(s) > 30 else s for s, _ in top_settings]
        counts = [c for _, c in top_settings]
        bars = ax5.barh(range(len(settings)), counts, color='#9467bd')
        ax5.set_yticks(range(len(settings)))
        ax5.set_yticklabels(settings, fontsize=8)
        ax5.set_xlabel('Frequency')
        ax5.set_title('Top 10 Settings by Frequency', fontweight='bold')
        ax5.invert_yaxis()
        # Add value labels
        for i, (bar, count) in enumerate(zip(bars, counts)):
            ax5.text(count, bar.get_y() + bar.get_height()/2.,
                    f' {int(count)}', va='center', ha='left', fontsize=7)
    
    # 6. Summary Statistics Text
    ax6 = fig.add_subplot(gs[2, 0])
    ax6.axis('off')
    total = summary.get('total_recommendations', 0)
    stats_text = f"""
    Summary Statistics:
    • Total Recommendations: {total}
    • Host: {host}
    • Generated: {generated_at}
    • Should Disable: {status_data.get('should_disable', 0)} ({status_data.get('should_disable', 0)/total*100:.1f}%)
    • Should Enable: {status_data.get('should_enable', 0)} ({status_data.get('should_enable', 0)/total*100:.1f}%)
    • Review Needed: {status_data.get('review_needed', 0)} ({status_data.get('review_needed', 0)/total*100:.1f}%)
    • Unknown: {status_data.get('unknown', 0)} ({status_data.get('unknown', 0)/total*100:.1f}%)
    • High Priority: {priority_data.get('high', 0)} ({priority_data.get('high', 0)/total*100:.1f}%)
    • Medium Priority: {priority_data.get('medium', 0)} ({priority_data.get('medium', 0)/total*100:.1f}%)
    • Low Priority: {priority_data.get('low', 0)} ({priority_data.get('low', 0)/total*100:.1f}%)
    """
    ax6.text(0.1, 0.5, stats_text, fontsize=10, family='monospace',
            verticalalignment='center', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Save figure
    output_path = OUTPUT_DIR / f"{Path(filename).stem}_visualization.png"
    OUTPUT_DIR.mkdir(exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"✓ Created visualization: {output_path}")
    return output_path


def visualize_all_files():
    """Process all JSON files in the suggestions directory."""
    if not SUGGESTIONS_DIR.exists():
        print(f"Error: Directory not found: {SUGGESTIONS_DIR}")
        return
    
    json_files = list(SUGGESTIONS_DIR.glob("*.json"))
    
    if not json_files:
        print(f"No JSON files found in {SUGGESTIONS_DIR}")
        return
    
    print(f"Found {len(json_files)} JSON file(s) to visualize\n")
    
    for json_file in json_files:
        try:
            print(f"Processing: {json_file.name}...")
            data = load_json_file(json_file)
            create_visualizations(data, json_file)
        except Exception as e:
            print(f"✗ Error processing {json_file.name}: {e}")
    
    print(f"\n✓ All visualizations saved to: {OUTPUT_DIR}")


def visualize_single_file(filename):
    """Visualize a specific JSON file."""
    filepath = SUGGESTIONS_DIR / filename
    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return
    
    try:
        data = load_json_file(filepath)
        create_visualizations(data, filepath)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Visualize specific file
        visualize_single_file(sys.argv[1])
    else:
        # Visualize all files
        visualize_all_files()