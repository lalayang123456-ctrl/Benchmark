import json
import glob
import os
import re
from collections import Counter

def analyze_by_geofence(directory):
    files = glob.glob(os.path.join(directory, 'nav_*.json'))
    
    # Raw POI type counts from geofence
    raw_poi_counts = Counter()
    
    # Category mapping
    category_mapping = {
        # Restaurant category
        'kfc': 'restaurant',
        'burger_king': 'restaurant',
        'starbucks': 'restaurant',
        'pizza_hut': 'restaurant',
        'mcdonalds': 'restaurant',
        'subway': 'restaurant',
        'restaurant': 'restaurant',
        
        # Transit category
        'transit': 'transit',
        'bus_station': 'transit',
        'transit_station': 'transit',
        
        # Landmark category
        'landmark': 'landmark',
        'church': 'landmark',
        
        # Service category
        'service': 'service',
        'bank': 'service',
        'pharmacy': 'service',
        'hospital': 'service',
        'post_office': 'service',
        'parking': 'service',
        
        # Gas station category
        'gas_station': 'gas_station',
        
        # Supermarket category
        'supermarket': 'supermarket',
    }
    
    category_counts = Counter()
    total_files = 0
    
    # Regex to extract POI type from geofence
    pattern = re.compile(r"list_nav_(.+)_\d{8}_\d{4,6}")
    
    print(f"Found {len(files)} nav task files in {directory}")

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                geofence = data.get('geofence', '')
                
                match = pattern.match(geofence)
                if match:
                    raw_type = match.group(1)
                    raw_poi_counts[raw_type] += 1
                    
                    # Map to category
                    category = category_mapping.get(raw_type, 'other')
                    category_counts[category] += 1
                    total_files += 1
                        
        except Exception as e:
            print(f"Error reading {file_path}: {e}")

    # Print category distribution
    print("\n=== POI Category Distribution ===")
    print(f"{'Category':<20} | {'Count':>10} | {'Percentage':>12}")
    print("-" * 48)

    for category, count in category_counts.most_common():
        percentage = (count / total_files) * 100 if total_files > 0 else 0
        print(f"{category:<20} | {count:>10} | {percentage:>11.2f}%")

    print("-" * 48)
    print(f"{'Total':<20} | {total_files:>10} | {'100.00%':>12}")
    
    # Print detailed breakdown
    print("\n=== Detailed POI Type Distribution ===")
    print(f"{'POI Type':<20} | {'Category':<15} | {'Count':>8} | {'Percentage':>10}")
    print("-" * 62)
    
    for poi_type, count in raw_poi_counts.most_common():
        category = category_mapping.get(poi_type, 'other')
        percentage = (count / total_files) * 100 if total_files > 0 else 0
        print(f"{poi_type:<20} | {category:<15} | {count:>8} | {percentage:>9.2f}%")
    
    print("-" * 62)
    print(f"{'Total':<20} | {'':<15} | {total_files:>8} | {'100.00%':>10}")

if __name__ == "__main__":
    tasks_dir = r"c:\GitHub\StreetView\VLN_BENCHMARK\tasks"
    analyze_by_geofence(tasks_dir)
