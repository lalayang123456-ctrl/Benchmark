"""
Task Assembler - Main Orchestrator

Combines all modules to generate complete navigation tasks.
"""

import os
import sys
import json
import random
import asyncio
from typing import Tuple, Optional, List
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from .poi_searcher import POISearcher, POI
from .directions_fetcher import DirectionsFetcher, Route
from .whitelist_generator import WhitelistGenerator
from .link_enhancer import enhance_panorama_links
from dotenv import load_dotenv

load_dotenv()


class TaskAssembler:
    """Orchestrate the full task generation pipeline."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.poi_searcher = POISearcher(self.api_key)
        self.directions_fetcher = DirectionsFetcher(self.api_key)
        self.whitelist_generator = WhitelistGenerator(self.api_key)
        
        self.tasks_dir = Path(__file__).parent.parent / "tasks"
        self.config_dir = Path(__file__).parent.parent / "config"
        
        # Validation settings
        self.max_target_retries = 5   # Max attempts to find a valid target POI
        self.max_spawn_retries = 5    # Max attempts to find a valid spawn point
    
    async def generate_navigation_task(
        self,
        center_lat: float,
        center_lng: float,
        poi_type: str,
        poi_keyword: str = None,
        spawn_distance_range: Tuple[int, int] = (50, 120),  # Reduced from (100, 300)
        task_id: str = None
    ) -> dict:
        """
        Full pipeline for POI navigation task generation.
        
        Steps:
        1. Search for target POI
        2. Select spawn point at specified distance
        3. Get navigation route
        4. Simplify instructions
        5. Generate whitelist (large coverage)
        6. Assemble and save task.json
        7. Update geofence_config.json
        
        Args:
            center_lat: Search center latitude
            center_lng: Search center longitude
            poi_type: POI category
            poi_keyword: Specific POI keyword (optional)
            spawn_distance_range: (min, max) distance from target in meters
            task_id: Custom task ID (optional, auto-generated if not provided)
        
        Returns:
            Generated task dictionary
        """
        print(f"\n{'='*60}")
        print(f"*** Starting Task Generation Pipeline")
        print(f"{'='*60}\n")
        
        # Step 1: Search for POI
        print("[*] Step 1: Searching for POI...")
        pois = await self.poi_searcher.search_nearby(
            lat=center_lat,
            lng=center_lng,
            poi_type=poi_type,
            keyword=poi_keyword
        )
        
        if not pois:
            raise ValueError(f"No POIs found for type '{poi_type}' with keyword '{poi_keyword}'")
        
        # Enrich with panorama IDs
        pois = await self.poi_searcher.enrich_with_pano_ids(pois)
        
        if not pois:
            raise ValueError("No POIs have nearby Street View coverage")
        
        # Randomly select target with valid links
        target_poi = await self._select_valid_target(pois)
        print(f"  Selected target: {target_poi.name} (pano: {target_poi.nearest_pano_id})")
        
        # Step 2: Select spawn point with valid links
        print("\n[*] Step 2: Selecting spawn point...")
        spawn_poi = await self._select_spawn_point(
            target_poi,
            distance_range=spawn_distance_range
        )
        print(f"  Spawn point: {spawn_poi.lat:.6f}, {spawn_poi.lng:.6f}")
        
        # Step 3: Get navigation route
        print("\n[*]  Step 3: Planning navigation route...")
        route = await self.directions_fetcher.get_route(
            origin_lat=spawn_poi.lat,
            origin_lng=spawn_poi.lng,
            dest_lat=target_poi.lat,
            dest_lng=target_poi.lng
        )
        
        # Step 4: Generate task description
        print("\n[*] Step 4: Generating task description...")
        description = self.directions_fetcher.generate_task_description(
            route, target_poi.name
        )
        print(f"  Description: {description[:100]}...")
        
        # Step 5: Generate whitelist
        print("\n[*] Step 5: Generating whitelist...")
        whitelist = await self.whitelist_generator.generate_from_endpoints(
            spawn_pano_id=spawn_poi.nearest_pano_id,
            target_pano_id=target_poi.nearest_pano_id,
            coverage_multiplier=1.0  # Reduced from 2.0 for faster generation
        )
        
        # Step 6: Assemble task
        print("\n[*] Step 6: Assembling task...")
        task_id = task_id or self._generate_task_id(poi_type, poi_keyword)
        list_id = f"list_{task_id}"
        
        task = {
            "task_id": task_id,
            "task_type": "navigation_to_poi",
            "geofence": list_id,
            "spawn_point": spawn_poi.nearest_pano_id,
            "spawn_heading": self._calculate_initial_heading(spawn_poi, target_poi),
            "description": description,
            "ground_truth": {
                "target_name": target_poi.name,
                "target_pano_id": target_poi.nearest_pano_id,
                "optimal_path_length": len(route.steps),
                "optimal_distance_meters": route.total_distance_meters,
                "route_description": self._summarize_route(route)
            },
            "answer": "",
            "target_pano_ids": [target_poi.nearest_pano_id],
            "max_steps": max(30, len(route.steps) * 3),
            "max_time_seconds": 300
        }
        
        # Step 7: Save files
        print("\n[*] Step 7: Saving files...")
        self._save_task(task)
        self._save_whitelist(list_id, whitelist)
        
        print(f"\n{'='*60}")
        print(f"[OK] Task Generation Complete!")
        print(f"{'='*60}")
        print(f"  Task ID: {task_id}")
        print(f"  Task file: tasks/{task_id}.json")
        print(f"  Whitelist: {len(whitelist)} panoramas")
        print(f"  Route: {route.total_distance_text}, {len(route.steps)} steps")
        print(f"{'='*60}\n")
        
        return task
    
    async def _select_spawn_point(
        self,
        target_poi: POI,
        distance_range: Tuple[int, int]
    ) -> POI:
        """
        Select a spawn point at specified distance from target.
        Validates that spawn point has adjacent panoramas.
        
        Args:
            target_poi: Target POI
            distance_range: (min, max) distance in meters
        
        Returns:
            POI object for spawn point with valid adjacent links
        """
        import math
        
        for attempt in range(self.max_spawn_retries):
            # Random direction and distance
            heading = random.uniform(0, 360)
            distance = random.uniform(*distance_range)
            
            # Calculate offset coordinates
            # 1 degree lat ≈ 111,111 meters
            # 1 degree lng ≈ 111,111 * cos(lat) meters
            lat_offset = (distance * math.cos(math.radians(heading))) / 111111
            lng_offset = (distance * math.sin(math.radians(heading))) / (111111 * math.cos(math.radians(target_poi.lat)))
            
            spawn_lat = target_poi.lat + lat_offset
            spawn_lng = target_poi.lng + lng_offset
            
            # Get nearest pano at spawn location
            spawn_pano_id = await self.poi_searcher.get_nearest_pano_id(spawn_lat, spawn_lng)
            
            if not spawn_pano_id:
                print(f"  [!] Attempt {attempt+1}: No Street View at ({spawn_lat:.4f}, {spawn_lng:.4f}), retrying...")
                continue
            
            # Validate spawn point has adjacent links
            if not await self._has_adjacent_links(spawn_pano_id):
                print(f"  [!] Attempt {attempt+1}: Spawn pano has no adjacent links, retrying...")
                continue
            
            return POI(
                place_id="spawn_point",
                name="Spawn Point",
                lat=spawn_lat,
                lng=spawn_lng,
                nearest_pano_id=spawn_pano_id
            )
        
        raise ValueError(f"Could not find valid spawn point after {self.max_spawn_retries} attempts")
    
    async def _select_valid_target(self, pois: list) -> POI:
        """
        Select a target POI that has adjacent panorama links.
        
        Args:
            pois: List of candidate POIs
        
        Returns:
            POI with valid adjacent links
        """
        random.shuffle(pois)  # Randomize order
        
        for i, poi in enumerate(pois[:self.max_target_retries]):
            if await self._has_adjacent_links(poi.nearest_pano_id):
                return poi
            print(f"  [!] POI '{poi.name}' has no adjacent links, trying next...")
        
        raise ValueError(f"No POIs with valid adjacent panoramas found (checked {min(len(pois), self.max_target_retries)})")
    
    async def _has_adjacent_links(self, pano_id: str) -> bool:
        """
        Check if a panorama has adjacent links (can navigate to other panos).
        
        Args:
            pano_id: Panorama ID to check
        
        Returns:
            True if has at least one adjacent link
        """
        from cache.metadata_cache import metadata_cache
        from engine.metadata_fetcher import MetadataFetcher
        
        # Check cache first
        cached = metadata_cache.get(pano_id)
        if cached and "links" in cached:
            return len(cached.get("links", [])) > 0
        
        # Fetch metadata
        fetcher = MetadataFetcher(self.api_key)
        success = fetcher.fetch_and_cache_all(pano_id)
        
        if not success:
            return False
        
        meta = metadata_cache.get(pano_id)
        return len(meta.get("links", [])) > 0 if meta else False
    
    def _calculate_initial_heading(self, spawn: POI, target: POI) -> int:
        """Calculate initial heading from spawn to target."""
        import math
        
        dlng = target.lng - spawn.lng
        y = math.sin(math.radians(dlng)) * math.cos(math.radians(target.lat))
        x = math.cos(math.radians(spawn.lat)) * math.sin(math.radians(target.lat)) - \
            math.sin(math.radians(spawn.lat)) * math.cos(math.radians(target.lat)) * math.cos(math.radians(dlng))
        
        heading = math.degrees(math.atan2(y, x))
        return int((heading + 360) % 360)
    
    def _summarize_route(self, route: Route) -> str:
        """Create a simple route summary."""
        directions = []
        for step in route.steps:
            if "left" in step.instruction.lower():
                directions.append("left")
            elif "right" in step.instruction.lower():
                directions.append("right")
            else:
                directions.append("straight")
        
        return "→".join(directions[:5])  # First 5 turns only
    
    def _generate_task_id(self, poi_type: str, keyword: str = None) -> str:
        """Generate a task ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        poi_name = keyword.lower().replace("'", "").replace(" ", "_") if keyword else poi_type
        return f"nav_{poi_name}_{timestamp}"
    
    def _save_task(self, task: dict):
        """Save task to JSON file."""
        self.tasks_dir.mkdir(exist_ok=True)
        
        task_file = self.tasks_dir / f"{task['task_id']}.json"
        with open(task_file, 'w', encoding='utf-8') as f:
            json.dump(task, f, indent=4, ensure_ascii=False)
        
        print(f"  [OK] Saved task: {task_file}")
    
    def _save_whitelist(self, list_id: str, whitelist: list):
        """Save whitelist to geofence_config.json."""
        config_file = self.config_dir / "geofence_config.json"
        
        # Load existing config
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = {}
        
        # Add new whitelist
        config[list_id] = whitelist
        
        # Save
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        print(f"  [OK] Updated whitelist: {list_id} ({len(whitelist)} panos)")
    
    async def generate_batch_tasks_v2(
        self,
        center_lat: float,
        center_lng: float,
        poi_type: str,
        poi_keyword: str = None,
        spawn_count: int = 2,
        min_panos: int = 20,
        max_panos: int = 60,
        max_distance: float = 500,
        spawn_min_distance: float = 100,
        spawn_max_distance: float = 200,
        virtual_link_threshold: float = 20.0
    ) -> List[dict]:
        """
        Generate multiple tasks for the same target using V2 algorithm.
        
        V2 features:
        - BFS from target ensures spawn-target connectivity
        - Distance-based virtual links enhance panorama connections
        - Multiple spawn points generate multiple tasks
        
        Args:
            center_lat: Search center latitude
            center_lng: Search center longitude
            poi_type: POI category
            poi_keyword: Specific POI keyword
            spawn_count: Number of tasks to generate
            min_panos: Minimum panoramas required
            max_panos: Maximum panoramas to explore
            max_distance: Maximum distance from target (meters)
            spawn_min_distance: Minimum spawn-target distance (meters)
            spawn_max_distance: Maximum spawn-target distance (meters)
            virtual_link_threshold: Distance for virtual links (meters)
        
        Returns:
            List of generated task dicts
        """
        print("\n" + "="*60)
        print("*** Task Generation V2 Pipeline")
        print("="*60)
        
        # Step 1: Search for POIs
        print("\n[*] Step 1: Searching for POI...")
        pois = await self.poi_searcher.search_nearby(
            lat=center_lat,
            lng=center_lng,
            poi_type=poi_type,
            keyword=poi_keyword
        )
        
        if not pois:
            raise ValueError(f"No POIs found for type '{poi_type}' with keyword '{poi_keyword}'")
        
        # Enrich with panorama IDs
        pois = await self.poi_searcher.enrich_with_pano_ids(pois)
        
        if not pois:
            raise ValueError("No POIs have nearby Street View coverage")
        
        print(f"  Found {len(pois)} POIs with Street View coverage")
        
        # Step 2: Try each POI until we find one with sufficient coverage
        print("\n[*] Step 2: Finding target with sufficient coverage...")
        
        random.shuffle(pois)  # Randomize order
        
        target_poi = None
        whitelist = None
        spawn_candidates = None
        metadata_map = None
        
        for i, poi in enumerate(pois):
            print(f"  Trying POI {i+1}/{len(pois)}: {poi.name}")
            
            try:
                whitelist, spawn_candidates, metadata_map = await self.whitelist_generator.generate_from_target(
                    target_pano_id=poi.nearest_pano_id,
                    min_panos=min_panos,
                    max_panos=max_panos,
                    max_distance=max_distance,
                    spawn_min_distance=spawn_min_distance,
                    spawn_max_distance=spawn_max_distance
                )
                
                # Check if we have enough spawn candidates
                if len(spawn_candidates) < spawn_count:
                    print(f"    [!] Not enough spawn candidates: {len(spawn_candidates)} < {spawn_count}")
                    continue
                
                target_poi = poi
                break
                
            except ValueError as e:
                print(f"    [!] Skipping: {e}")
                continue
        
        if not target_poi:
            raise ValueError(f"No POIs with sufficient panorama coverage. Need {min_panos} panos and {spawn_count} spawn candidates.")
        
        print(f"\n  [OK] Selected target: {target_poi.name}")
        
        # Step 3: Enhance links (add virtual links for nearby panos, prune distant links)
        print("\n[*] Step 3: Enhancing panorama links...")
        enhanced_metadata, virtual_count, pruned_count = enhance_panorama_links(
            metadata_map,
            threshold_meters=virtual_link_threshold,
            prune_distant=True  # Enable pruning of links > threshold distance
        )
        print(f"  [OK] Added {virtual_count} virtual links, pruned {pruned_count} distant links")
        
        # Step 3b: Fix reverse heading consistency
        # Ensures all links have correct bidirectional headings (180° offset)
        from .link_enhancer import LinkEnhancer
        enhancer = LinkEnhancer(virtual_link_threshold)
        enhanced_metadata, fixed_count = enhancer.fix_reverse_headings(enhanced_metadata)
        print(f"  [OK] Fixed {fixed_count} reverse heading mismatches")
        
        # Step 3c: Save enhanced links back to cache for runtime use
        from cache.metadata_cache import metadata_cache
        saved_count = 0
        for pano_id, meta in enhanced_metadata.items():
            if 'links' in meta and 'lat' in meta:
                metadata_cache.save(
                    pano_id=pano_id,
                    lat=meta['lat'],
                    lng=meta['lng'],
                    capture_date=meta.get('capture_date', ''),
                    links=meta['links'],
                    center_heading=meta.get('center_heading', 0.0),
                    source='enhanced'
                )
                saved_count += 1
        print(f"  [OK] Saved enhanced links for {saved_count} panoramas to cache")
        
        # Step 4: Select spawn points
        print(f"\n[*] Step 4: Selecting {spawn_count} spawn points...")
        selected_spawns = random.sample(spawn_candidates, spawn_count)
        
        for i, spawn_id in enumerate(selected_spawns):
            spawn_meta = metadata_map.get(spawn_id, {})
            print(f"  Spawn {i+1}: {spawn_id[:20]}... (distance: {spawn_meta.get('distance', 'N/A')}m)")
        
        # Step 5: Generate tasks for each spawn
        print(f"\n[*] Step 5: Generating {spawn_count} tasks...")
        
        base_task_id = self._generate_task_id(poi_type, poi_keyword)
        list_id = f"list_{base_task_id}"
        
        tasks = []
        for i, spawn_pano_id in enumerate(selected_spawns):
            task_id = f"{base_task_id}_{i+1}" if spawn_count > 1 else base_task_id
            
            # Get spawn metadata for heading calculation
            spawn_meta = enhanced_metadata.get(spawn_pano_id, {})
            spawn_poi = POI(
                place_id="spawn_point",
                name="Spawn Point",
                lat=spawn_meta.get("lat", center_lat),
                lng=spawn_meta.get("lng", center_lng),
                nearest_pano_id=spawn_pano_id
            )
            
            # Calculate initial heading towards target
            initial_heading = self._calculate_initial_heading(spawn_poi, target_poi)
            
            # Get route for description
            route = await self.directions_fetcher.get_route(
                origin_lat=spawn_poi.lat,
                origin_lng=spawn_poi.lng,
                dest_lat=target_poi.lat,
                dest_lng=target_poi.lng
            )
            
            description = self.directions_fetcher.generate_task_description(
                route, target_poi.name
            )
            
            task = {
                "task_id": task_id,
                "task_type": "navigation_to_poi",
                "geofence": list_id,
                "spawn_point": spawn_pano_id,
                "spawn_heading": initial_heading,
                "description": description,
                "ground_truth": {
                    "target_name": target_poi.name,
                    "target_pano_id": target_poi.nearest_pano_id,
                    "optimal_path_length": len(route.steps),
                    "optimal_distance_meters": route.total_distance_meters,
                    "route_description": self._summarize_route(route)
                },
                "answer": "",
                "target_pano_ids": [target_poi.nearest_pano_id],
                "max_steps": max(30, len(route.steps) * 3),
                "max_time_seconds": 300
            }
            
            tasks.append(task)
            self._save_task(task)
        
        # Step 6: Save shared whitelist
        print("\n[*] Step 6: Saving whitelist...")
        self._save_whitelist(list_id, whitelist)
        
        # Summary
        print(f"\n{'='*60}")
        print(f"[OK] Task Generation V2 Complete!")
        print(f"{'='*60}")
        print(f"  Target: {target_poi.name}")
        print(f"  Tasks generated: {len(tasks)}")
        print(f"  Whitelist: {len(whitelist)} panoramas")
        print(f"  Virtual links: {virtual_count}")
        for task in tasks:
            print(f"  - {task['task_id']}")
        print(f"{'='*60}\n")
        
        return tasks


# Example usage
async def main():
    assembler = TaskAssembler()
    
    task = await assembler.generate_navigation_task(
        center_lat=41.4108,
        center_lng=2.1803,
        poi_type="restaurant",
        poi_keyword="McDonald's"
    )
    
    print(f"\nGenerated task: {json.dumps(task, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    asyncio.run(main())
