#!/usr/bin/env python
"""
Migrate metadata from JSON cache to SQLite database.

This script is needed if you generated tasks before the fix that added SQLite saving.
It reads the pano_metadata.json file and imports all entries into the SQLite database.

Usage:
    python scripts/migrate_metadata_to_sqlite.py
"""

import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.metadata_cache import metadata_cache


def main():
    cache_file = Path(__file__).parent.parent / "cache" / "pano_metadata.json"
    
    if not cache_file.exists():
        print(f"[!] Cache file not found: {cache_file}")
        return
    
    print(f"[*] Loading metadata from: {cache_file}")
    
    with open(cache_file, "r", encoding="utf-8") as f:
        metadata_map = json.load(f)
    
    print(f"[*] Found {len(metadata_map)} entries")
    
    imported = 0
    skipped = 0
    
    for pano_id, meta in metadata_map.items():
        lat = meta.get("lat")
        lng = meta.get("lng")
        
        if lat is None or lng is None:
            skipped += 1
            continue
        
        metadata_cache.save(
            pano_id=pano_id,
            lat=lat,
            lng=lng,
            capture_date=meta.get("date") or meta.get("capture_date"),
            links=meta.get("links"),
            center_heading=meta.get("center_heading"),
            source="migrated_from_json"
        )
        imported += 1
    
    print(f"[OK] Imported {imported} entries to SQLite")
    if skipped:
        print(f"     Skipped {skipped} entries (missing lat/lng)")
    
    # Verify
    stats = metadata_cache.get_stats()
    print(f"[*] SQLite cache now has {stats['total_metadata']} entries")


if __name__ == "__main__":
    main()
