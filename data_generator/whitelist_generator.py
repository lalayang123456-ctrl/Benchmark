"""
Whitelist Generator - BFS Exploration from Target

Generates pano whitelist using BFS exploration from target panorama.
Ensures spawn-target connectivity by exploring outward from target.

Optimized for parallel fetching with detailed logging.
"""

import os
import sys
import asyncio
import logging
import math
from typing import Set, List, Tuple, Dict, Optional
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.metadata_fetcher import MetadataFetcher
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class WhitelistGenerator:
    """Generate panorama whitelists with BFS exploration from target."""
    
    def __init__(self, api_key: str = None, parallel_workers: int = 4):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        # Initialize fetcher with worker pool
        self.metadata_fetcher = MetadataFetcher(
            api_key=self.api_key, 
            num_workers=parallel_workers
        )
        self.metadata_cache: Dict[str, dict] = {}
        self.parallel_workers = parallel_workers
        # Note: semaphore and request_delay are now handled by MetadataFetcher
    
    async def enter_session(self):
        """Start a persistent session (keep workers alive)."""
        if not self.metadata_fetcher.is_initialized:
            await self.metadata_fetcher.initialize()
            
    async def exit_session(self):
        """End persistent session (cleanup workers)."""
        await self.metadata_fetcher.cleanup()

    async def generate_from_target(
        self,
        target_pano_id: str,
        min_panos: int = 20,
        max_panos: int = 60,
        max_distance: float = 500,
        spawn_min_distance: float = 100,
        spawn_max_distance: float = 200,
        keep_session: bool = False
    ) -> Tuple[List[str], List[str], Dict[str, dict]]:
        """
        Generate whitelist by BFS from target, and return spawn candidates.
        
        This method ensures spawn-target connectivity by only selecting
        spawn points from the connected panorama network.
        
        Args:
            target_pano_id: Target panorama ID (BFS starting point)
            min_panos: Minimum panoramas required
            max_panos: Maximum panoramas to explore
            max_distance: Maximum distance from target (meters)
            spawn_min_distance: Minimum spawn distance from target (meters)
            spawn_max_distance: Maximum spawn distance from target (meters)
            keep_session: If True, assumes session is managed externally and won't init/cleanup here.
        
        Returns:
            Tuple of (whitelist, spawn_candidates, metadata_map)
        """
        print(f"  [*] Starting BFS from target: {target_pano_id[:20]}...")
        print(f"      Constraints: min={min_panos}, max={max_panos}, distance={max_distance}m")
        # print(f"      Parallel workers: {self.parallel_workers}")
        
        # Clear cache for new generation (optional)
        self.metadata_cache = {}
        
        # Initialize workers if not already running
        managed_internally = False
        if not self.metadata_fetcher.is_initialized and not keep_session:
             await self.metadata_fetcher.initialize()
             managed_internally = True
        
        try:
            # Get target metadata first
            target_meta = await self._get_metadata_with_retry(target_pano_id)
            if not target_meta:
                print(f"  [!] Failed to get metadata for target")
                return [], [], {}
            
            target_lat = target_meta.get("lat")
            target_lng = target_meta.get("lng")
            
            if target_lat is None or target_lng is None:
                print(f"  [!] Target metadata missing coordinates")
                return [], [], {}
            
            print(f"      Target coords: ({target_lat:.6f}, {target_lng:.6f})")

            # Check target date
            target_date = target_meta.get("date", "")
            if target_date:
                try:
                    target_year = int(target_date.split("-")[0])
                    if target_year < 2020:
                        print(f"  [!] Target is too old: {target_date} < 2020")
                        # Depending on requirements, we might want to convert this target 
                        # to a newer nearby pano, or just abort. 
                        # For now, let's just warn but proceed (or abort?).
                        # The user said "fail" effectively if point is old.
                        # "不考虑这个全景图点了" -> Do not consider this pano point.
                        # If the TARGET is old, we probably shouldn't generate a whitelist from it.
                        return [], [], {}
                except ValueError:
                    pass
            
            # BFS exploration with parallel fetching
            whitelist_set = await self._bfs_expand_parallel(
                start_pano=target_pano_id,
                center_lat=target_lat,
                center_lng=target_lng,
                max_distance=max_distance,
                max_nodes=max_panos
            )
            
            # Convert to list
            whitelist = list(whitelist_set)
            print(f"  [*] BFS complete: {len(whitelist)} panoramas found")
            
        finally:
            # Cleanup workers ONLY if we managed them internally
            if managed_internally:
                await self.metadata_fetcher.cleanup()

        # Check minimum requirement
        if len(whitelist) < min_panos:
            print(f"  [!] Insufficient coverage: {len(whitelist)} < {min_panos}")
            return [], [], {}
        
        # Find spawn candidates (panos within spawn distance range)
        spawn_candidates = []
        for pano_id in whitelist:
            if pano_id == target_pano_id:
                continue
            
            meta = self.metadata_cache.get(pano_id)
            if not meta:
                continue
            
            pano_lat = meta.get("lat")
            pano_lng = meta.get("lng")
            if pano_lat is None or pano_lng is None:
                continue
            
            distance = self._calculate_distance(target_lat, target_lng, pano_lat, pano_lng)
            
            if spawn_min_distance <= distance <= spawn_max_distance:
                spawn_candidates.append(pano_id)
        
        print(f"      Spawn candidates: {len(spawn_candidates)} in range [{spawn_min_distance}, {spawn_max_distance}]m")
        
        return whitelist, spawn_candidates, self.metadata_cache.copy()
    
    async def _bfs_expand_parallel(
        self,
        start_pano: str,
        center_lat: float,
        center_lng: float,
        max_distance: float,
        max_nodes: int
    ) -> Set[str]:
        """
        BFS expansion with parallel fetching and radial/directional diversity.
        
        Uses direction-aware queue sorting to ensure expansion in all directions,
        not just along a single street.
        """
        visited = set()
        result = set()
        
        # Queue entries: (pano_id, direction_from_center)
        # direction_from_center is the heading from center to this pano (0-360)
        queue = [(start_pano, 0)]  # Start point has no direction
        
        # Add start pano to result (already fetched)
        result.add(start_pano)
        visited.add(start_pano)
        
        # Get neighbors from start
        start_meta = self.metadata_cache.get(start_pano)
        if start_meta:
            for link in start_meta.get("links", []):
                neighbor_id = link.get("pano_id")
                if neighbor_id and neighbor_id not in visited:
                    # Use link heading as direction
                    direction = link.get("heading", 0)
                    queue.append((neighbor_id, direction))
        
        batch_num = 0
        while queue and len(result) < max_nodes:
            batch_num += 1
            
            # Sort queue by direction to maximize coverage of different directions
            # Group by 45-degree sectors (8 sectors total)
            queue = self._sort_queue_by_direction_diversity(queue)
            
            # Take a batch of nodes to process in parallel
            batch_size = min(self.parallel_workers, len(queue), max_nodes - len(result))
            batch = []
            batch_directions = []
            
            for _ in range(batch_size):
                if queue:
                    pano_id, direction = queue.pop(0)
                    if pano_id not in visited:
                        batch.append(pano_id)
                        batch_directions.append(direction)
                        visited.add(pano_id)
            
            if not batch:
                continue
            
            print(f"      [Batch {batch_num}] Fetching {len(batch)} panos in parallel...")
            
            # Fetch all in parallel
            tasks = [self._get_metadata_with_retry(pano_id) for pano_id in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            success_count = 0
            new_neighbors = []
            
            for pano_id, meta in zip(batch, results):
                if isinstance(meta, Exception):
                    print(f"        [!] {pano_id[:20]}... Exception: {meta}")
                    continue
                
                if not meta:
                    continue
                
                pano_lat = meta.get("lat")
                pano_lng = meta.get("lng")
                
                if pano_lat is None or pano_lng is None:
                    continue
                
                # Check distance constraint
                distance = self._calculate_distance(center_lat, center_lng, pano_lat, pano_lng)
                
                if distance > max_distance:
                    print(f"        [-] {pano_id[:20]}... distance {distance:.0f}m > {max_distance}m (skipped)")
                    continue

                # NEW: Date filtering (Gen 4 camera check)
                # Skip panoramas older than 2020 (Gen 4 rollout complete by 2020)
                capture_date = meta.get("date", "")
                if capture_date:
                    try:
                        # Format is usually "YYYY-MM"
                        year = int(capture_date.split("-")[0])
                        if year < 2020:
                            print(f"        [-] {pano_id[:20]}... Old pano {capture_date} < 2020 (skipped)")
                            continue
                    except ValueError:
                        print(f"DEBUG: Date parse error for {pano_id}: {capture_date}")
                        pass  # Keep if date format is unknown
                else:
                    print(f"DEBUG: No date for {pano_id}")
                
                # Add to result
                result.add(pano_id)
                success_count += 1
                
                links = meta.get("links", [])
                
                # Calculate direction from center for logging
                direction = self._calculate_heading(center_lat, center_lng, pano_lat, pano_lng)
                sector = self._get_direction_name(direction)
                
                print(f"        [+] {pano_id[:20]}... {len(links)} links, {distance:.0f}m {sector}")
                
                # Add neighbors to queue with their directions
                for link in links:
                    neighbor_id = link.get("pano_id")
                    if neighbor_id and neighbor_id not in visited:
                        neighbor_direction = link.get("heading", 0)
                        new_neighbors.append((neighbor_id, neighbor_direction))
            
            # Add new neighbors to queue
            queue.extend(new_neighbors)
            
            print(f"      [Batch {batch_num}] Added {success_count}/{len(batch)} panos, queue size: {len(queue)}, total: {len(result)}")
            
            # Check if we have enough
            if len(result) >= max_nodes:
                print(f"      [*] Reached max_nodes limit ({max_nodes})")
                break
        
        return result
    
    def _sort_queue_by_direction_diversity(
        self, 
        queue: List[Tuple[str, float]]
    ) -> List[Tuple[str, float]]:
        """
        Sort queue to prioritize direction diversity.
        
        Divides 360 degrees into 8 sectors (45 degrees each) and
        round-robin selects from each sector to ensure radial expansion.
        """
        if len(queue) <= 1:
            return queue
        
        # Group by 45-degree sectors
        sectors = [[] for _ in range(8)]
        for pano_id, direction in queue:
            sector_idx = int(direction / 45) % 8
            sectors[sector_idx].append((pano_id, direction))
        
        # Round-robin from each sector
        result = []
        max_sector_len = max(len(s) for s in sectors) if sectors else 0
        
        for i in range(max_sector_len):
            for sector in sectors:
                if i < len(sector):
                    result.append(sector[i])
        
        return result
    
    def _get_direction_name(self, heading: float) -> str:
        """Convert heading to cardinal direction name."""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = int((heading + 22.5) / 45) % 8
        return directions[idx]
    
    def _calculate_heading(
        self,
        lat1: float, lng1: float,
        lat2: float, lng2: float
    ) -> float:
        """Calculate heading from point 1 to point 2."""
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lng = math.radians(lng2 - lng1)
        
        x = math.sin(delta_lng) * math.cos(lat2_rad)
        y = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lng))
        
        heading = math.degrees(math.atan2(x, y))
        return (heading + 360) % 360
    
    async def _get_metadata_with_retry(
        self, 
        pano_id: str, 
        max_retries: int = 2
    ) -> Optional[dict]:
        """
        Get metadata for a panorama with retry logic.
        
        Shows detailed logs for pano ID, links count, and retry attempts.
        """
        # Check cache first
        if pano_id in self.metadata_cache:
            return self.metadata_cache[pano_id]
        
        last_error = None
        
        # Note: We don't need a semaphore here because fetch_links
        # uses the worker queue to manage concurrency.
        
        # Fetch basic metadata (lat, lng, date)
        # This is fast and synchronous (using requests), run in thread
        basic = await asyncio.to_thread(
            self.metadata_fetcher.fetch_basic_metadata, pano_id
        )
        
        if not basic:
            print(f"        [!] {pano_id[:20]}... No basic metadata")
            return None
        
        # Fetch links (async, uses worker pool)
        links_result = await self.metadata_fetcher.fetch_links(pano_id, max_retries=max_retries)
        
        links = []
        center_heading = 0.0
        
        if links_result:
            raw_links = links_result.get("links", [])
            center_heading = links_result.get("centerHeading", 0.0)
            
            # Normalize link format: panoId -> pano_id
            for link in raw_links:
                links.append({
                    "pano_id": link.get("panoId") or link.get("pano_id"),
                    "heading": link.get("heading", 0),
                    "description": link.get("description", "")
                })
        else:
            print(f"        [!] {pano_id[:20]}... No links data")
            return None
        
        # Combine into metadata dict
        meta = {
            "pano_id": pano_id,
            "lat": basic.get("lat"),
            "lng": basic.get("lng"),
            "date": basic.get("capture_date"),
            "center_heading": center_heading,
            "links": links
        }
        
        self.metadata_cache[pano_id] = meta
        return meta
    
    def _calculate_distance(
        self,
        lat1: float, lng1: float,
        lat2: float, lng2: float
    ) -> float:
        """
        Calculate distance between two points using Haversine formula.
        
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
