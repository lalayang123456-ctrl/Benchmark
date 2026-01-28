"""
Script to analyze panorama network for Starbucks tasks.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cache.metadata_cache import metadata_cache

# Load geofence config
config_path = Path(__file__).parent / "config" / "geofence_config.json"
with open(config_path, 'r', encoding='utf-8') as f:
    geofence = json.load(f)

whitelist = geofence.get('list_nav_starbucks_20260118_164445', [])
whitelist_set = set(whitelist)
print(f'Total panoramas in whitelist: {len(whitelist)}')

# Haversine distance calculation
def calc_distance(lat1, lng1, lat2, lng2):
    R = 6371000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Gather metadata
pano_data = {}
for pano_id in whitelist:
    meta = metadata_cache.get(pano_id)
    if meta:
        links = meta.get('links', [])
        link_targets = [l.get('panoId', '') for l in links]
        links_in_wl = [t for t in link_targets if t in whitelist_set]
        pano_data[pano_id] = {
            'lat': meta.get('lat'),
            'lng': meta.get('lng'),
            'links': links_in_wl
        }

# Print table header
print('\n=== PANORAMA CONNECTIONS ===')
print(f'{"From Pano":<25} {"To Pano":<25} {"Distance(m)":<12} {"Connected":<10}')
print('='*75)

# Build distance matrix for all pairs
all_pairs = []
for i, pano_a in enumerate(whitelist):
    for pano_b in whitelist[i+1:]:
        data_a = pano_data.get(pano_a, {})
        data_b = pano_data.get(pano_b, {})
        if data_a.get('lat') and data_b.get('lat'):
            dist = calc_distance(data_a['lat'], data_a['lng'], data_b['lat'], data_b['lng'])
            connected = pano_b in data_a.get('links', []) or pano_a in data_b.get('links', [])
            all_pairs.append((pano_a[:22], pano_b[:22], dist, connected))

# Sort by distance
all_pairs.sort(key=lambda x: x[2])

for a, b, dist, conn in all_pairs:
    conn_str = 'YES' if conn else 'NO'
    print(f'{a:<25} {b:<25} {dist:>10.1f}m  {conn_str:<10}')

print('\n=== SUMMARY ===')
connected_count = sum(1 for _, _, _, c in all_pairs if c)
print(f'Total pairs: {len(all_pairs)}')
print(f'Connected pairs: {connected_count}')
print(f'Unconnected pairs: {len(all_pairs) - connected_count}')

# Show pairs under 15m that are NOT connected (potential issues)
print('\n=== PAIRS < 15m NOT CONNECTED (potential issues) ===')
for a, b, dist, conn in all_pairs:
    if dist <= 15 and not conn:
        print(f'{a} <-> {b}: {dist:.1f}m')

# Show pairs > 15m that ARE connected (should have been pruned)
print('\n=== PAIRS > 15m STILL CONNECTED (should have been pruned) ===')
for a, b, dist, conn in all_pairs:
    if dist > 15 and conn:
        print(f'{a} <-> {b}: {dist:.1f}m')
