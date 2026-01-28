"""
Verify if link.heading is relative to true north or to centerHeading.

This script:
1. Gets a panorama's metadata including links and centerHeading
2. Gets coordinates for the current and linked panoramas
3. Calculates the actual geographic bearing using coordinates
4. Compares with link.heading to determine if centerHeading correction is needed
"""
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.metadata_cache import metadata_cache


def calculate_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the bearing (compass direction) from point 1 to point 2.
    Returns degrees clockwise from true north (0-360).
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lng = math.radians(lng2 - lng1)
    
    x = math.sin(delta_lng) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lng)
    
    bearing = math.atan2(x, y)
    bearing_deg = math.degrees(bearing)
    
    # Normalize to 0-360
    return (bearing_deg + 360) % 360


def verify_heading(pano_id: str):
    """Verify link.heading for a panorama."""
    # Get metadata
    metadata = metadata_cache.get(pano_id)
    if not metadata:
        print(f"ERROR: No metadata for {pano_id}")
        return
    
    center_heading = metadata.get('center_heading', 0.0) or 0.0
    current_lat = metadata['lat']
    current_lng = metadata['lng']
    links = metadata.get('links', [])
    
    print(f"Panorama: {pano_id}")
    print(f"Location: ({current_lat:.6f}, {current_lng:.6f})")
    print(f"centerHeading: {center_heading:.1f}°")
    print(f"Links: {len(links)}")
    print()
    print("=" * 80)
    print(f"{'Link':<5} {'link.heading':<15} {'Calc Bearing':<15} {'Diff (no corr)':<18} {'Diff (with corr)':<18}")
    print("=" * 80)
    
    for i, link in enumerate(links, 1):
        link_pano_id = link.get('panoId') or link.get('pano_id')
        link_heading = float(link.get('heading', 0))
        
        # Get linked panorama location
        link_location = metadata_cache.get_location(link_pano_id)
        
        if link_location:
            link_lat, link_lng = link_location
            
            # Calculate actual geographic bearing
            actual_bearing = calculate_bearing(current_lat, current_lng, link_lat, link_lng)
            
            # Difference without centerHeading correction
            diff_no_corr = (link_heading - actual_bearing + 180) % 360 - 180
            
            # Difference with centerHeading correction
            corrected_heading = (link_heading + center_heading) % 360
            diff_with_corr = (corrected_heading - actual_bearing + 180) % 360 - 180
            
            print(f"{i:<5} {link_heading:<15.1f} {actual_bearing:<15.1f} {diff_no_corr:<18.1f} {diff_with_corr:<18.1f}")
        else:
            print(f"{i:<5} {link_heading:<15.1f} {'N/A':<15} {'N/A':<18} {'N/A':<18}")
    
    print()
    print("Interpretation:")
    print("  - If 'Diff (no corr)' is close to 0: link.heading is TRUE NORTH reference")
    print("  - If 'Diff (with corr)' is close to 0: link.heading needs centerHeading correction")


def main():
    # Try to find a panorama with metadata
    from cache.cache_manager import cache_manager
    
    with cache_manager.get_connection() as conn:
        cursor = conn.execute('''
            SELECT pano_id FROM metadata 
            WHERE links IS NOT NULL AND center_heading IS NOT NULL
            LIMIT 1
        ''')
        row = cursor.fetchone()
    
    if row:
        verify_heading(row['pano_id'])
    else:
        print("No panoramas with complete metadata found in cache.")
        print("Please run the center_heading update script first, or provide a pano_id manually.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        verify_heading(sys.argv[1])
    else:
        main()
