"""
Link Enhancer - Distance-based Virtual Link Addition

Enhances panorama connections by adding virtual links between
nearby panoramas that don't have original API links.
"""

import math
from typing import Dict, List, Set, Tuple


class LinkEnhancer:
    """
    Enhances panorama link relationships based on distance.
    
    - Adds bidirectional virtual links between panoramas within threshold distance
    - Optionally removes (prunes) links that exceed the threshold distance
    """
    
    def __init__(self, threshold_meters: float = 15.0):
        """
        Initialize the link enhancer.
        
        Args:
            threshold_meters: Maximum distance (meters) for adding virtual links
                             and for pruning distant links. Default is 15 meters.
        """
        self.threshold = threshold_meters
    
    def enhance_links(
        self, 
        metadata_map: Dict[str, dict],
        prune_distant: bool = False
    ) -> Tuple[Dict[str, dict], int, int]:
        """
        Analyze all panoramas, add virtual links where needed, and optionally prune distant links.
        
        Args:
            metadata_map: Dictionary mapping pano_id to metadata.
                         Each metadata should have: lat, lng, links
            prune_distant: If True, also remove links that exceed the threshold distance
        
        Returns:
            Tuple of (enhanced metadata_map, virtual links added count, distant links removed count)
        """
        pano_ids = list(metadata_map.keys())
        n = len(pano_ids)
        
        if n < 2:
            return metadata_map, 0, 0
        
        # Step 1: Prune distant links if requested
        links_removed = 0
        if prune_distant:
            metadata_map, links_removed = self.prune_distant_links(metadata_map)
        
        # Build existing link sets for fast lookup
        existing_links = self._build_existing_links(metadata_map)
        
        virtual_links_added = 0
        
        # Step 2: Check all pairs of panoramas and add virtual links
        for i in range(n):
            for j in range(i + 1, n):
                pano_a = pano_ids[i]
                pano_b = pano_ids[j]
                
                # Skip if link already exists (either direction)
                if pano_b in existing_links.get(pano_a, set()):
                    continue
                if pano_a in existing_links.get(pano_b, set()):
                    continue
                
                meta_a = metadata_map.get(pano_a)
                meta_b = metadata_map.get(pano_b)
                
                if not meta_a or not meta_b:
                    continue
                
                if "lat" not in meta_a or "lat" not in meta_b:
                    continue
                
                # Calculate distance
                distance = self._calculate_distance(
                    meta_a["lat"], meta_a["lng"],
                    meta_b["lat"], meta_b["lng"]
                )
                
                if distance <= self.threshold:
                    # Add bidirectional virtual links
                    self._add_virtual_link(metadata_map, pano_a, pano_b, meta_a, meta_b, distance)
                    self._add_virtual_link(metadata_map, pano_b, pano_a, meta_b, meta_a, distance)
                    virtual_links_added += 2
                    
                    # Update existing links cache
                    existing_links.setdefault(pano_a, set()).add(pano_b)
                    existing_links.setdefault(pano_b, set()).add(pano_a)
        
        return metadata_map, virtual_links_added, links_removed
    
    def prune_distant_links(
        self,
        metadata_map: Dict[str, dict]
    ) -> Tuple[Dict[str, dict], int]:
        """
        Remove links between panoramas that exceed the threshold distance.
        
        Only removes links where BOTH endpoints are in the metadata_map
        (i.e., both panoramas are in the whitelist). This ensures we don't
        accidentally break connectivity to panoramas we don't have info about.
        
        Args:
            metadata_map: Dictionary mapping pano_id to metadata.
                         Each metadata should have: lat, lng, links
        
        Returns:
            Tuple of (pruned metadata_map, number of links removed)
        """
        links_removed = 0
        pano_ids_set = set(metadata_map.keys())
        
        for pano_id, meta in metadata_map.items():
            if "links" not in meta or not meta["links"]:
                continue
            
            if "lat" not in meta or "lng" not in meta:
                continue
            
            original_links = meta["links"]
            filtered_links = []
            
            for link in original_links:
                target_pano_id = link.get("panoId") or link.get("pano_id")
                
                if not target_pano_id:
                    filtered_links.append(link)
                    continue
                
                # Only check distance if target is also in our whitelist
                if target_pano_id not in pano_ids_set:
                    # Target not in whitelist, keep the link as-is
                    # (It will be filtered out by geofence anyway at runtime)
                    filtered_links.append(link)
                    continue
                
                target_meta = metadata_map.get(target_pano_id)
                if not target_meta or "lat" not in target_meta:
                    filtered_links.append(link)
                    continue
                
                # Calculate distance
                distance = self._calculate_distance(
                    meta["lat"], meta["lng"],
                    target_meta["lat"], target_meta["lng"]
                )
                
                if distance <= self.threshold:
                    # Keep the link
                    filtered_links.append(link)
                else:
                    # Remove the link (too far)
                    links_removed += 1
            
            # Update links
            metadata_map[pano_id]["links"] = filtered_links
        
        return metadata_map, links_removed
    
    def fix_reverse_headings(
        self, 
        metadata_map: Dict[str, dict]
    ) -> Tuple[Dict[str, dict], int]:
        """
        Ensure all links have correct bidirectional headings.
        
        For each link A->B with heading H, the reverse B->A should have heading (H+180)%360.
        This fixes direction description bugs caused by asymmetric Google API links.
        
        Args:
            metadata_map: Dictionary mapping pano_id to metadata
        
        Returns:
            Tuple of (fixed metadata_map, number of fixes applied)
        """
        pano_ids_set = set(metadata_map.keys())
        fixes_applied = 0
        
        for pano_id, meta in metadata_map.items():
            links = meta.get("links", [])
            if not links:
                continue
            
            for link in links:
                target_pano_id = link.get("panoId") or link.get("pano_id")
                forward_heading = link.get("heading")
                
                if not target_pano_id or forward_heading is None:
                    continue
                
                # Only process links within our whitelist
                if target_pano_id not in pano_ids_set:
                    continue
                
                # Calculate expected reverse heading
                expected_reverse = (float(forward_heading) + 180) % 360
                
                # Find reverse link in target
                target_meta = metadata_map.get(target_pano_id)
                if not target_meta:
                    continue
                
                target_links = target_meta.get("links", [])
                reverse_link = None
                reverse_idx = None
                
                for idx, tl in enumerate(target_links):
                    tl_pano = tl.get("panoId") or tl.get("pano_id")
                    if tl_pano == pano_id:
                        reverse_link = tl
                        reverse_idx = idx
                        break
                
                if reverse_link is None:
                    # No reverse link exists, add one
                    new_reverse_link = {
                        "panoId": pano_id,
                        "heading": round(expected_reverse, 2),
                        "text": "",
                        "heading_fixed": True  # Mark as auto-fixed
                    }
                    if "links" not in metadata_map[target_pano_id]:
                        metadata_map[target_pano_id]["links"] = []
                    metadata_map[target_pano_id]["links"].append(new_reverse_link)
                    fixes_applied += 1
                else:
                    # Reverse link exists, check if heading is correct
                    actual_reverse = float(reverse_link.get("heading", 0))
                    diff = abs((actual_reverse - expected_reverse + 180) % 360 - 180)
                    
                    if diff > 20:  # More than 20° off from expected
                        # Fix the heading
                        metadata_map[target_pano_id]["links"][reverse_idx]["heading"] = round(expected_reverse, 2)
                        metadata_map[target_pano_id]["links"][reverse_idx]["heading_fixed"] = True
                        fixes_applied += 1
        
        return metadata_map, fixes_applied
    
    def _build_existing_links(self, metadata_map: Dict[str, dict]) -> Dict[str, Set[str]]:
        """Build a lookup table of existing links (only tracking links within whitelist)."""
        pano_ids_set = set(metadata_map.keys())
        existing = {}
        for pano_id, meta in metadata_map.items():
            links = meta.get("links", [])
            # Only track links that point to nodes in our whitelist
            existing[pano_id] = set(
                link.get("panoId") for link in links 
                if link.get("panoId") and link.get("panoId") in pano_ids_set
            )
        return existing
    
    def _add_virtual_link(
        self,
        metadata_map: dict,
        from_pano: str,
        to_pano: str,
        from_meta: dict,
        to_meta: dict,
        distance: float
    ):
        """
        Add a virtual link from one panorama to another.
        
        The link format matches Google API format for consistency.
        """
        heading = self._calculate_heading(
            from_meta["lat"], from_meta["lng"],
            to_meta["lat"], to_meta["lng"]
        )
        
        virtual_link = {
            "panoId": to_pano,
            "heading": round(heading, 2),
            "text": "",  # Virtual links don't have street names
            "virtual": True,  # Mark as virtual link
            "distance": round(distance, 2)  # Extra info for debugging
        }
        
        # Ensure links list exists
        if "links" not in metadata_map[from_pano]:
            metadata_map[from_pano]["links"] = []
        
        # Check if link already exists (avoid duplicates)
        existing_pano_ids = {
            link.get("panoId") for link in metadata_map[from_pano]["links"]
        }
        
        if to_pano not in existing_pano_ids:
            metadata_map[from_pano]["links"].append(virtual_link)
    
    def _calculate_heading(
        self,
        lat1: float, lng1: float,
        lat2: float, lng2: float
    ) -> float:
        """
        Calculate heading (bearing) from point 1 to point 2.
        
        Args:
            lat1, lng1: Starting point coordinates
            lat2, lng2: Ending point coordinates
        
        Returns:
            Heading in degrees (0-360, where 0 is North)
        """
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlng_rad = math.radians(lng2 - lng1)
        
        x = math.sin(dlng_rad) * math.cos(lat2_rad)
        y = (math.cos(lat1_rad) * math.sin(lat2_rad) - 
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlng_rad))
        
        heading = math.degrees(math.atan2(x, y))
        
        # Normalize to 0-360
        return (heading + 360) % 360
    
    def _calculate_distance(
        self,
        lat1: float, lng1: float,
        lat2: float, lng2: float
    ) -> float:
        """
        Calculate distance between two points using Haversine formula.
        
        Args:
            lat1, lng1: First point coordinates
            lat2, lng2: Second point coordinates
        
        Returns:
            Distance in meters
        """
        R = 6371000  # Earth radius in meters
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        
        a = (math.sin(dlat / 2) ** 2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2)
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c


# Convenience function
def enhance_panorama_links(
    metadata_map: Dict[str, dict],
    threshold_meters: float = 15.0,
    prune_distant: bool = False
) -> Tuple[Dict[str, dict], int, int]:
    """
    Convenience function to enhance panorama links.
    
    Args:
        metadata_map: Dictionary of panorama metadata
        threshold_meters: Distance threshold for virtual links and pruning
        prune_distant: If True, also remove links that exceed the threshold
    
    Returns:
        Tuple of (enhanced metadata_map, virtual links added, distant links removed)
    """
    enhancer = LinkEnhancer(threshold_meters)
    return enhancer.enhance_links(metadata_map, prune_distant=prune_distant)


# Convenience function for pruning only
def prune_distant_links(
    metadata_map: Dict[str, dict],
    threshold_meters: float = 15.0
) -> Tuple[Dict[str, dict], int]:
    """
    Convenience function to only prune distant links without adding virtual ones.
    
    Args:
        metadata_map: Dictionary of panorama metadata
        threshold_meters: Distance threshold - links exceeding this will be removed
    
    Returns:
        Tuple of (pruned metadata_map, links removed count)
    """
    enhancer = LinkEnhancer(threshold_meters)
    return enhancer.prune_distant_links(metadata_map)


# Test code
if __name__ == "__main__":
    # Test with sample data
    test_metadata = {
        "pano_a": {
            "lat": 47.5065,
            "lng": 19.0550,
            "links": [
                {"panoId": "pano_c", "heading": 0}  # Link to far-away pano (should be pruned)
            ]
        },
        "pano_b": {
            "lat": 47.5066,  # ~11m away from pano_a
            "lng": 19.0550,
            "links": []
        },
        "pano_c": {
            "lat": 47.5070,  # ~55m away from pano_a
            "lng": 19.0550,
            "links": [
                {"panoId": "pano_a", "heading": 180}  # Link to far-away pano (should be pruned)
            ]
        }
    }
    
    print("=" * 50)
    print("Test 1: Add virtual links only (prune_distant=False)")
    print("=" * 50)
    enhanced1, added1, removed1 = enhance_panorama_links(
        {k: {**v, "links": list(v["links"])} for k, v in test_metadata.items()},
        threshold_meters=15.0,
        prune_distant=False
    )
    print(f"Virtual links added: {added1}")
    print(f"Distant links removed: {removed1}")
    for pano_id, meta in enhanced1.items():
        print(f"\n{pano_id}: {len(meta.get('links', []))} links")
        for link in meta.get("links", []):
            print(f"  -> {link['panoId']}: heading={link['heading']}°, virtual={link.get('virtual', False)}")
    
    print("\n" + "=" * 50)
    print("Test 2: Add virtual links AND prune distant (prune_distant=True)")
    print("=" * 50)
    enhanced2, added2, removed2 = enhance_panorama_links(
        {k: {**v, "links": list(v["links"])} for k, v in test_metadata.items()},
        threshold_meters=15.0,
        prune_distant=True
    )
    print(f"Virtual links added: {added2}")
    print(f"Distant links removed: {removed2}")
    for pano_id, meta in enhanced2.items():
        print(f"\n{pano_id}: {len(meta.get('links', []))} links")
        for link in meta.get("links", []):
            print(f"  -> {link['panoId']}: heading={link['heading']}°, virtual={link.get('virtual', False)}")

