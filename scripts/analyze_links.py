"""
Analyze panorama links to find direction issues.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.metadata_cache import metadata_cache
import json

def analyze_panorama(pano_id: str):
    """Analyze a panorama and its links."""
    meta = metadata_cache.get(pano_id)
    
    if not meta:
        print(f"Metadata not found for {pano_id}")
        return
    
    print(f"\n{'='*60}")
    print(f"=== Panorama: {pano_id} ===")
    print(f"{'='*60}")
    print(f"Location: ({meta['lat']:.6f}, {meta['lng']:.6f})")
    print(f"Center Heading: {meta.get('center_heading', 0)}")
    print(f"Source: {meta.get('source', 'unknown')}")
    
    links = meta.get('links', [])
    print(f"\nLinks ({len(links)} total):")
    
    issues = []
    
    for i, link in enumerate(links):
        link_pano = link.get('panoId', 'N/A')
        heading = link.get('heading', 'N/A')
        virtual = link.get('virtual', False)
        
        print(f"\n  [{i+1}] -> {link_pano}")
        print(f"      heading={heading}°, virtual={virtual}")
        
        # Check reverse link
        target_meta = metadata_cache.get(link_pano)
        if target_meta:
            reverse_link = None
            for tl in target_meta.get('links', []):
                if tl.get('panoId') == pano_id:
                    reverse_link = tl
                    break
            
            if reverse_link:
                rev_heading = reverse_link.get('heading', 'N/A')
                if heading != 'N/A' and rev_heading != 'N/A':
                    # Expected: reverse heading should be ~180° different
                    expected_reverse = (float(heading) + 180) % 360
                    actual_reverse = float(rev_heading)
                    diff = abs((actual_reverse - expected_reverse + 180) % 360 - 180)
                    
                    print(f"      <- REVERSE: heading={rev_heading}°")
                    print(f"         Expected reverse: {expected_reverse:.1f}°, Actual: {actual_reverse:.1f}°")
                    print(f"         Heading difference: {diff:.1f}° from expected")
                    
                    if diff > 20:  # More than 20° off
                        issues.append({
                            'from': pano_id,
                            'to': link_pano,
                            'forward_heading': heading,
                            'reverse_heading': rev_heading,
                            'diff': diff
                        })
                        print(f"         ** ISSUE: Heading mismatch!")
            else:
                issues.append({
                    'from': pano_id,
                    'to': link_pano,
                    'issue': 'NO_REVERSE_LINK'
                })
                print(f"      <- REVERSE: [X] NOT FOUND!")
        else:
            print(f"      <- REVERSE: Target not in cache")
    
    return issues


def analyze_geofence(geofence_name: str):
    """Analyze all panoramas in a geofence."""
    config_path = Path(__file__).parent.parent / "config" / "geofence_config.json"
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    pano_ids = config.get(geofence_name, [])
    print(f"\nAnalyzing geofence: {geofence_name}")
    print(f"Total panoramas: {len(pano_ids)}")
    
    all_issues = []
    
    for pano_id in pano_ids:
        issues = analyze_panorama(pano_id)
        if issues:
            all_issues.extend(issues)
    
    print(f"\n{'='*60}")
    print(f"=== SUMMARY ===")
    print(f"{'='*60}")
    print(f"Total issues found: {len(all_issues)}")
    
    for issue in all_issues:
        print(f"\n  {issue['from']} -> {issue['to']}")
        if 'issue' in issue:
            print(f"    Issue: {issue['issue']}")
        else:
            print(f"    Forward: {issue['forward_heading']}°")
            print(f"    Reverse: {issue['reverse_heading']}°")
            print(f"    Diff from 180°: {issue['diff']:.1f}°")


if __name__ == "__main__":
    # Analyze entire geofence
    analyze_geofence("list_nav_starbucks_20260118_164445")
