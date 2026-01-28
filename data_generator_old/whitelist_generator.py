"""
Whitelist Generator - Bidirectional BFS for Large Coverage

Generates pano whitelist using bidirectional BFS exploration.
"""

import os
import sys
import asyncio
from typing import Set, List, Tuple, Dict
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.metadata_fetcher import MetadataFetcher
from dotenv import load_dotenv

load_dotenv()


class WhitelistGenerator:
    """Generate panorama whitelists with large coverage area using BFS."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.metadata_fetcher = MetadataFetcher(self.api_key)
        self.cache = {}  # Cache for fetched metadata
        
        # Concurrency control
        self.max_concurrent = 4          # Max 4 parallel fetches
        self.semaphore = asyncio.Semaphore(4)
        self.min_delay = 0.2             # Min delay between requests
    
    async def generate_from_endpoints(
        self,
        spawn_pano_id: str,
        target_pano_id: str,
        coverage_multiplier: float = 2.0,
        max_panos: int = 200
    ) -> List[str]:
        """
        Generate whitelist using bidirectional BFS.
        
        Strategy:
        1. Calculate direct distance between spawn and target
        2. Set BFS range = distance * coverage_multiplier
        3. BFS from spawn_pano (up to range)
        4. BFS from target_pano (up to range)
        5. Merge and deduplicate
        
        Args:
            spawn_pano_id: Starting panorama ID
            target_pano_id: Target panorama ID
            coverage_multiplier: Coverage multiplier (default 2.0 = 2x distance)
            max_panos: Maximum number of panoramas
        
        Returns:
            List of panorama IDs
        """
        print(f"\n🔍 Generating whitelist (coverage: {coverage_multiplier}x)...")
        
        # Get metadata for both endpoints (parallel)
        spawn_meta, target_meta = await asyncio.gather(
            self._get_metadata(spawn_pano_id),
            self._get_metadata(target_pano_id)
        )
        
        if not spawn_meta or not target_meta:
            raise ValueError("Could not fetch metadata for spawn or target pano")
        
        # Calculate direct distance
        direct_distance = self._calculate_distance(
            spawn_meta["lat"], spawn_meta["lng"],
            target_meta["lat"], target_meta["lng"]
        )
        
        bfs_range = direct_distance * coverage_multiplier
        print(f"  Direct distance: {direct_distance:.0f}m")
        print(f"  BFS range: {bfs_range:.0f}m")
        
        # BFS from both ends (parallel execution)
        from_spawn_task = self._bfs_expand(
            spawn_pano_id,
            spawn_meta["lat"], spawn_meta["lng"],
            max_distance=bfs_range,
            max_nodes=max_panos // 2
        )
        
        from_target_task = self._bfs_expand(
            target_pano_id,
            target_meta["lat"], target_meta["lng"],
            max_distance=bfs_range,
            max_nodes=max_panos // 2
        )
        
        # Execute both BFS in parallel
        from_spawn, from_target = await asyncio.gather(from_spawn_task, from_target_task)
        
        # Merge and deduplicate
        whitelist = list(set(from_spawn) | set(from_target))
        
        print(f"[OK] Whitelist generated: {len(whitelist)} panoramas")
        return whitelist
    
    async def generate_from_target(
        self,
        target_pano_id: str,
        min_panos: int = 20,
        max_panos: int = 60,
        max_distance: float = 500,
        spawn_min_distance: float = 100,
        spawn_max_distance: float = 200
    ) -> Tuple[List[str], List[str], Dict[str, dict]]:
        """
        Generate whitelist by BFS from target, and return spawn candidates.
        
        This method ensures spawn-target connectivity by only selecting
        spawn points from the connected panorama network.
        
        Args:
            target_pano_id: Target panorama ID (destination)
            min_panos: Minimum required panoramas (raises error if not met)
            max_panos: Maximum panoramas to explore
            max_distance: Maximum distance from target (meters)
            spawn_min_distance: Minimum spawn-target distance (meters)
            spawn_max_distance: Maximum spawn-target distance (meters)
        
        Returns:
            Tuple of (whitelist, spawn_candidates, metadata_map)
            - whitelist: List of all explored panorama IDs
            - spawn_candidates: List of pano IDs suitable for spawn
            - metadata_map: Dict mapping pano_id to metadata (for link enhancement)
        """
        print(f"\n[*] Generating whitelist from target (BFS)...")
        
        # Get target metadata
        target_meta = await self._get_metadata(target_pano_id)
        if not target_meta:
            raise ValueError(f"Could not fetch metadata for target pano: {target_pano_id}")
        
        target_lat = target_meta["lat"]
        target_lng = target_meta["lng"]
        
        print(f"  Target: ({target_lat:.6f}, {target_lng:.6f})")
        print(f"  Max distance: {max_distance}m, Max panos: {max_panos}")
        
        # BFS from target
        visited = {}  # {pano_id: {"meta": ..., "distance": ..., "hops": ...}}
        queue = [(target_pano_id, 0)]  # (pano_id, hops)
        
        while queue and len(visited) < max_panos:
            # Process batch concurrently
            batch_size = min(self.max_concurrent, len(queue))
            batch = queue[:batch_size]
            queue = queue[batch_size:]
            
            # Fetch metadata for batch
            pano_ids = [item[0] for item in batch]
            hops_list = [item[1] for item in batch]
            
            tasks = [self._get_metadata_with_limit(pano_id) for pano_id in pano_ids]
            metadata_list = await asyncio.gather(*tasks, return_exceptions=True)
            
            for pano_id, hops, meta in zip(pano_ids, hops_list, metadata_list):
                if pano_id in visited:
                    continue
                
                if isinstance(meta, Exception) or not meta:
                    continue
                
                # Calculate distance from target
                distance = self._calculate_distance(
                    target_lat, target_lng,
                    meta["lat"], meta["lng"]
                )
                
                # Skip if too far
                if distance > max_distance:
                    continue
                
                visited[pano_id] = {
                    "meta": meta,
                    "distance": distance,
                    "hops": hops
                }
                
                # Add adjacent panoramas to queue
                for link in meta.get("links", []):
                    link_pano_id = link.get("panoId")
                    if link_pano_id and link_pano_id not in visited:
                        queue.append((link_pano_id, hops + 1))
            
            # Small delay between batches
            if queue:
                await asyncio.sleep(0.05)
        
        # Build results
        whitelist = list(visited.keys())
        
        # Check minimum panos requirement
        if len(whitelist) < min_panos:
            raise ValueError(
                f"Insufficient panoramas: found {len(whitelist)}, need {min_panos}. "
                f"Target may have poor Street View coverage."
            )
        
        # Filter spawn candidates by distance
        spawn_candidates = [
            pano_id for pano_id, data in visited.items()
            if spawn_min_distance <= data["distance"] <= spawn_max_distance
        ]
        
        # Build metadata map for link enhancement
        metadata_map = {
            pano_id: data["meta"] for pano_id, data in visited.items()
        }
        
        print(f"  [OK] Found {len(whitelist)} panoramas")
        print(f"  [OK] {len(spawn_candidates)} spawn candidates (distance: {spawn_min_distance}-{spawn_max_distance}m)")
        
        return whitelist, spawn_candidates, metadata_map
    
    async def _bfs_expand(
        self,
        start_pano: str,
        center_lat: float,
        center_lng: float,
        max_distance: float,
        max_nodes: int
    ) -> Set[str]:
        """
        BFS expansion from a starting point with distance constraint.
        
        Args:
            start_pano: Starting panorama ID
            center_lat: Center latitude for distance calculation
            center_lng: Center longitude for distance calculation
            max_distance: Maximum distance from center (meters)
            max_nodes: Maximum number of nodes to explore
        
        Returns:
            Set of panorama IDs
        """
        visited = set()
        result = set()
        queue = [start_pano]
        
        while queue and len(result) < max_nodes:
            # Process batch concurrently
            batch_size = min(self.max_concurrent, len(queue), max_nodes - len(result))
            batch = queue[:batch_size]
            queue = queue[batch_size:]
            
            # Fetch metadata for batch in parallel
            tasks = [self._get_metadata_with_limit(pano_id) for pano_id in batch]
            metadata_list = await asyncio.gather(*tasks, return_exceptions=True)
            
            #  Process results
            for pano_id, meta in zip(batch, metadata_list):
                if pano_id in visited:
                    continue
                
                visited.add(pano_id)
                
                # Skip if metadata fetch failed
                if isinstance(meta, Exception) or not meta:
                    continue
                
                # Check distance constraint
                distance = self._calculate_distance(
                    center_lat, center_lng,
                    meta["lat"], meta["lng"]
                )
                
                if distance > max_distance:
                    continue
                
                result.add(pano_id)
                
                # Add adjacent panoramas to queue
                for link in meta.get("links", []):
                    link_pano_id = link.get("panoId")
                    if link_pano_id and link_pano_id not in visited:
                        queue.append(link_pano_id)
            
            # Small delay between batches
            if queue:
                await asyncio.sleep(0.05)
        
        return result
    
    async def _get_metadata_with_limit(self, pano_id: str) -> dict:
        """
        Get metadata with concurrency control.
        
        Uses semaphore to limit simultaneous requests and adds delay.
        """
        async with self.semaphore:
            result = await self._get_metadata(pano_id)
            await asyncio.sleep(self.min_delay)
            return result
    
    async def _get_metadata(self, pano_id: str) -> dict:
        """
        Get metadata for a panorama (with caching).
        
        Args:
            pano_id: Panorama ID
        
        Returns:
            Metadata dict or None
        """
        if pano_id in self.cache:
            return self.cache[pano_id]
        
        try:
            # Use the global metadata_cache to check first
            from cache.metadata_cache import metadata_cache
            
            cached = metadata_cache.get(pano_id)
            if cached and cached.get("links"):
                # Already have complete cached data
                self.cache[pano_id] = cached
                return cached
            
            # Fetch and cache (synchronous operation)
            import asyncio
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, self.metadata_fetcher.fetch_and_cache_all, pano_id
            )
            
            if not success:
                return None
            
            # Retrieve from cache
            meta = metadata_cache.get(pano_id)
            if meta:
                self.cache[pano_id] = meta
            return meta
            
        except Exception as e:
            print(f"  Warning: Failed to fetch metadata for {pano_id}: {e}")
            return None
    
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
        from math import radians, cos, sin, asin, sqrt
        
        # Convert to radians
        lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        c = 2 * asin(sqrt(a))
        
        # Radius of Earth in meters
        r = 6371000
        
        return c * r


# Example usage
async def main():
    generator = WhitelistGenerator()
    
    # Generate whitelist between two points
    whitelist = await generator.generate_from_endpoints(
        spawn_pano_id="wwkpfmLCWlQ0vinOvd0TpQ",
        target_pano_id="eHuvoWBH4_2L-Qv445p-Eg",
        coverage_multiplier=2.0
    )
    
    print(f"\nGenerated whitelist: {len(whitelist)} panoramas")
    print(f"Sample: {list(whitelist)[:5]}")


if __name__ == "__main__":
    asyncio.run(main())
