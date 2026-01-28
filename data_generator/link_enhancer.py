"""
Link Enhancer - Virtual Link Addition and External Link Filtering

Enhances panorama connections by adding virtual links between
nearby panoramas that don't have original API links.

Per documentation:
- Virtual link threshold: 18 meters
- NO distance pruning
- NO fix_reverse_headings
- Filter links pointing outside whitelist
"""

import math
import logging
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


class LinkEnhancer:
    """
    Enhances panorama link relationships based on distance.
    
    - Adds bidirectional virtual links between panoramas within threshold distance
    - Filters out links pointing to panoramas outside the whitelist
    """
    
    def __init__(self, threshold_meters: float = 18.0):
        """
        Initialize the link enhancer.
        
        Args:
            threshold_meters: Maximum distance (meters) for adding virtual links.
                            Default is 18 meters per documentation.
        """
        self.threshold_meters = threshold_meters
    
    def enhance_links(
        self, 
        metadata_map: Dict[str, dict]
    ) -> Tuple[Dict[str, dict], int]:
        """
        Analyze all panoramas and add virtual links where needed.
        
        Args:
            metadata_map: Dictionary mapping pano_id to metadata.
                         Each metadata should have: lat, lng, links
        
        Returns:
            Tuple of (enhanced metadata_map, virtual links added count)
        """
        pano_ids = list(metadata_map.keys())
        virtual_links_added = 0
        
        # Build existing links lookup
        existing_links = self._build_existing_links(metadata_map)
        
        # Check all pairs for potential virtual links
        for i, pano_a in enumerate(pano_ids):
            meta_a = metadata_map.get(pano_a)
            if not meta_a:
                continue
            
            lat_a = meta_a.get("lat")
            lng_a = meta_a.get("lng")
            
            if lat_a is None or lng_a is None:
                continue
            
            for pano_b in pano_ids[i + 1:]:
                # Skip if link already exists
                if pano_b in existing_links.get(pano_a, set()):
                    continue
                
                meta_b = metadata_map.get(pano_b)
                if not meta_b:
                    continue
                
                lat_b = meta_b.get("lat")
                lng_b = meta_b.get("lng")
                
                if lat_b is None or lng_b is None:
                    continue
                
                # Calculate distance
                distance = self._calculate_distance(lat_a, lng_a, lat_b, lng_b)
                
                # Add virtual links if within threshold
                if distance <= self.threshold_meters:
                    # Add A -> B
                    self._add_virtual_link(
                        metadata_map, pano_a, pano_b,
                        meta_a, meta_b, distance
                    )
                    # Add B -> A
                    self._add_virtual_link(
                        metadata_map, pano_b, pano_a,
                        meta_b, meta_a, distance
                    )
                    virtual_links_added += 2
                    
                    # Update existing links lookup
                    existing_links.setdefault(pano_a, set()).add(pano_b)
                    existing_links.setdefault(pano_b, set()).add(pano_a)
        
        logger.info(f"Added {virtual_links_added} virtual links (threshold: {self.threshold_meters}m)")
        return metadata_map, virtual_links_added
    
    def filter_external_links(
        self, 
        metadata_map: Dict[str, dict],
        whitelist: Set[str]
    ) -> Tuple[Dict[str, dict], int]:
        """
        Remove links pointing to panoramas outside the whitelist.
        
        Args:
            metadata_map: Dictionary mapping pano_id to metadata
            whitelist: Set of valid panorama IDs
        
        Returns:
            Tuple of (filtered metadata_map, links removed count)
        """
        links_removed = 0
        
        for pano_id, meta in metadata_map.items():
            if pano_id not in whitelist:
                continue
            
            links = meta.get("links", [])
            if not links:
                continue
            
            # Filter links
            filtered_links = []
            for link in links:
                target_pano = link.get("pano_id")
                if target_pano in whitelist:
                    filtered_links.append(link)
                else:
                    links_removed += 1
            
            meta["links"] = filtered_links
        
        logger.info(f"Removed {links_removed} external links")
        return metadata_map, links_removed
    
    def _build_existing_links(self, metadata_map: Dict[str, dict]) -> Dict[str, Set[str]]:
        """Build a lookup table of existing links (only tracking links within whitelist)."""
        existing = {}
        whitelist = set(metadata_map.keys())
        
        for pano_id, meta in metadata_map.items():
            links = meta.get("links", [])
            targets = set()
            for link in links:
                target = link.get("pano_id")
                if target in whitelist:
                    targets.add(target)
            existing[pano_id] = targets
        
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
        # Calculate heading from 'from' to 'to'
        heading = self._calculate_heading(
            from_meta["lat"], from_meta["lng"],
            to_meta["lat"], to_meta["lng"]
        )
        
        # Create virtual link
        virtual_link = {
            "pano_id": to_pano,
            "heading": round(heading, 2),
            "distance": round(distance, 2),
            "virtual": True  # Mark as virtual link
        }
        
        # Add to links list
        if "links" not in from_meta:
            from_meta["links"] = []
        from_meta["links"].append(virtual_link)
        
        logger.debug(f"Added virtual link: {from_pano} -> {to_pano} (heading: {heading:.1f}°, dist: {distance:.1f}m)")
    
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
        delta_lng = math.radians(lng2 - lng1)
        
        x = math.sin(delta_lng) * math.cos(lat2_rad)
        y = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lng))
        
        heading = math.degrees(math.atan2(x, y))
        
        # Normalize to 0-360
        heading = (heading + 360) % 360
        
        return heading
    
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
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c


# Convenience function
def enhance_panorama_links(
    metadata_map: Dict[str, dict],
    threshold_meters: float = 18.0,
    whitelist: Set[str] = None
) -> Tuple[Dict[str, dict], int, int]:
    """
    Convenience function to enhance panorama links.
    
    Args:
        metadata_map: Dictionary of panorama metadata
        threshold_meters: Distance threshold for virtual links
        whitelist: Optional set of valid pano IDs for external link filtering
    
    Returns:
        Tuple of (enhanced metadata_map, virtual links added, external links removed)
    """
    enhancer = LinkEnhancer(threshold_meters)
    
    # Add virtual links
    metadata_map, virtual_added = enhancer.enhance_links(metadata_map)
    
    # Filter external links if whitelist provided
    external_removed = 0
    if whitelist:
        metadata_map, external_removed = enhancer.filter_external_links(metadata_map, whitelist)
    
    return metadata_map, virtual_added, external_removed


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    # Example metadata
    metadata = {
        "pano_1": {
            "lat": 47.5065,
            "lng": 19.0551,
            "links": []
        },
        "pano_2": {
            "lat": 47.5066,
            "lng": 19.0552,
            "links": []
        },
        "pano_3": {
            "lat": 47.5070,
            "lng": 19.0555,
            "links": []
        }
    }
    
    enhanced, virtual_count, external_count = enhance_panorama_links(
        metadata,
        threshold_meters=18.0,
        whitelist={"pano_1", "pano_2", "pano_3"}
    )
    
    print(f"Virtual links added: {virtual_count}")
    print(f"External links removed: {external_count}")
    
    for pano_id, meta in enhanced.items():
        print(f"{pano_id}: {len(meta.get('links', []))} links")
