import sys
sys.path.insert(0, '.')
from cache.cache_manager import cache_manager

with cache_manager.get_connection() as conn:
    cursor = conn.execute('SELECT pano_id, center_heading FROM metadata WHERE center_heading IS NOT NULL LIMIT 10')
    print("Panorama ID              | centerHeading")
    print("-" * 50)
    for row in cursor.fetchall():
        print(f"{row['pano_id'][:24]:<24} | {row['center_heading']:.1f}°")
