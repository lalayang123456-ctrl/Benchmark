"""
Task Assembler - Main Orchestrator

Combines all modules to generate complete navigation and exploration tasks.
Implements V2 algorithm with BFS from target and Greedy Farthest Point Sampling.
"""

import os
import sys
import math
import json
import heapq
import copy
import random
import asyncio
import logging
from typing import List, Dict, Optional, Set, Tuple
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from .poi_searcher import POISearcher, POI
from .directions_fetcher import DirectionsFetcher, Route
from .whitelist_generator import WhitelistGenerator
from .link_enhancer import LinkEnhancer, enhance_panorama_links
from .visualization import generate_network_html
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class TaskAssembler:
    """Orchestrate the full task generation pipeline."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.poi_searcher = POISearcher(self.api_key)
        self.directions_fetcher = DirectionsFetcher(self.api_key)
        self.whitelist_generator = WhitelistGenerator(self.api_key, parallel_workers=8)
        
        # Load config defaults
        config_path = Path(__file__).parent / "poi_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            self.config = {"generation_defaults": {}}
        
        self.defaults = self.config.get("generation_defaults", {})
        
        # Output directories
        self.base_dir = Path(__file__).parent.parent
        self.tasks_dir = self.base_dir / "tasks"
        self.config_dir = self.base_dir / "config"
        self.vis_dir = self.base_dir / "vis"
        self.cache_dir = self.base_dir / "cache"

    def _dijkstra_shortest_path(
        self,
        start_pano: str,
        end_pano: str,
        graph: Dict[str, dict]
    ) -> List[str]:
        """
        Find shortest path using Dijkstra algorithm on panorama graph.
        
        Args:
            start_pano: Starting panorama ID
            end_pano: Target panorama ID
            graph: Metadata map representing the graph
            
        Returns:
            List of panorama IDs representing the path [start, ..., end]
        """
        if start_pano not in graph or end_pano not in graph:
            return []
            
        # Priority queue: (distance, pano_id)
        pq = [(0, start_pano)]
        
        # Distances to each node
        distances = {start_pano: 0}
        
        # Predecessors for path reconstruction
        previous = {start_pano: None}
        
        visited = set()
        
        while pq:
            current_dist, current_pano = heapq.heappop(pq)
            
            if current_pano == end_pano:
                break
            
            if current_pano in visited:
                continue
            
            visited.add(current_pano)
            
            # Get neighbors
            meta = graph.get(current_pano, {})
            current_lat = meta.get("lat")
            current_lng = meta.get("lng")
            
            if current_lat is None or current_lng is None:
                continue
                
            for link in meta.get("links", []):
                neighbor_id = link.get("pano_id")
                if not neighbor_id or neighbor_id not in graph:
                    continue
                
                # Calculate edge weight (distance)
                neighbor_meta = graph.get(neighbor_id, {})
                neighbor_lat = neighbor_meta.get("lat")
                neighbor_lng = neighbor_meta.get("lng")
                
                if neighbor_lat is None or neighbor_lng is None:
                    continue
                    
                edge_dist = self._calculate_distance(
                    current_lat, current_lng, neighbor_lat, neighbor_lng
                )
                
                new_dist = current_dist + edge_dist
                
                if new_dist < distances.get(neighbor_id, float('inf')):
                    distances[neighbor_id] = new_dist
                    previous[neighbor_id] = current_pano
                    heapq.heappush(pq, (new_dist, neighbor_id))
        
        # Reconstruct path
        path = []
        current = end_pano
        if current in previous: # Only if reachable
            while current:
                path.append(current)
                current = previous[current]
            path.reverse()
        
        return path

    def _calculate_visual_path(
        self,
        path_ids: List[str],
        graph: Dict[str, dict]
    ) -> List[dict]:
        """
        Calculate visual path with headings for each step.
        
        Args:
            path_ids: List of panorama IDs in path
            graph: Metadata map
            
        Returns:
            List of step dictionaries with pano_id and heading
        """
        visual_path = []
        
        for i in range(len(path_ids)):
            current_id = path_ids[i]
            
            # Determine heading
            if i == 0:
                # Start Point: Look ahead to next node
                if len(path_ids) > 1:
                    next_id = path_ids[i+1]
                    curr_meta = graph.get(current_id, {})
                    next_meta = graph.get(next_id, {})
                    
                    heading = self._calculate_initial_heading(
                        curr_meta.get("lat", 0), curr_meta.get("lng", 0),
                        next_meta.get("lat", 0), next_meta.get("lng", 0)
                    )
                else:
                    heading = 0.0
            else:
                # Intermediate/End Point: Look from previous node (Movement Direction)
                # Heading = Bearing(Prev -> Current)
                prev_id = path_ids[i-1]
                prev_meta = graph.get(prev_id, {})
                curr_meta = graph.get(current_id, {})
                
                heading = self._calculate_initial_heading(
                    prev_meta.get("lat", 0), prev_meta.get("lng", 0),
                    curr_meta.get("lat", 0), curr_meta.get("lng", 0)
                )
            
            visual_path.append({
                "step_index": i,
                "pano_id": current_id,
                "heading": round(heading, 1)
            })
            
        return visual_path
    
    async def generate_batch_tasks_v2(
        self,
        center_lat: float,
        center_lng: float,
        poi_type: str,
        poi_keyword: str = None,
        spawn_count: int = None,
        min_panos: int = None,
        max_panos: int = None,
        max_distance: float = None,
        spawn_min_distance: float = None,
        spawn_max_distance: float = None,
        virtual_link_threshold: float = None,
        secondary_keywords: List[str] = None,
        generate_exploration: bool = True
    ) -> List[dict]:
        """
        Generate multiple tasks for the same target using V2 algorithm.
        
        V2 features:
        - BFS from target ensures spawn-target connectivity
        - Distance-based virtual links enhance panorama connections
        - Greedy Farthest Point Sampling for dispersed spawn selection
        - Multi-target POI support
        - Exploration tasks generated alongside navigation tasks
        - POI uniqueness pre-check before BFS
        
        Args:
            center_lat: Search center latitude
            center_lng: Search center longitude
            poi_type: POI category
            poi_keyword: Specific POI keyword (uses Text Search if provided)
            spawn_count: Number of spawn points per target
            min_panos: Minimum panoramas required
            max_panos: Maximum panoramas to explore
            max_distance: Maximum BFS exploration distance (meters)
            spawn_min_distance: Minimum spawn distance from target (meters)
            spawn_max_distance: Maximum spawn distance from target (meters)
            virtual_link_threshold: Distance threshold for virtual links (meters)
            secondary_keywords: Optional list of secondary POI keywords
            generate_exploration: Also generate exploration tasks (default: True)
        
        Returns:
            Tuple[List[dict], List[str]]: (List of generated task dictionaries, List of whitelist pano IDs)
        """
        print("=" * 60)
        print("*** Task Generation V2 Pipeline")
        print("=" * 60)
        
        # Load defaults if not provided
        spawn_count = spawn_count if spawn_count is not None else self.defaults.get("spawn_count", 2)
        min_panos = min_panos if min_panos is not None else self.defaults.get("min_panos", 20)
        max_panos = max_panos if max_panos is not None else self.defaults.get("max_panos", 60)
        max_distance = max_distance if max_distance is not None else self.defaults.get("max_distance", 500)
        spawn_min_distance = spawn_min_distance if spawn_min_distance is not None else self.defaults.get("spawn_distance_min", 100)
        spawn_max_distance = spawn_max_distance if spawn_max_distance is not None else self.defaults.get("spawn_distance_max", 200)
        virtual_link_threshold = virtual_link_threshold if virtual_link_threshold is not None else self.defaults.get("virtual_link_threshold", 18.0)
        
        all_tasks = []
        
        # Step 1: Search for primary POI
        print("\n[*] Step 1: Searching for POI...")
        pois = await self.poi_searcher.search_nearby(
            lat=center_lat,
            lng=center_lng,
            poi_type=poi_type,
            keyword=poi_keyword
        )
        
        if not pois:
            print("  [!] No POIs found")
            return [], []
        
        # Enrich with panorama IDs
        pois = await self.poi_searcher.enrich_with_pano_ids(pois)
        
        if not pois:
            print("  [!] No POIs with Street View coverage")
            return [], []
        
        print(f"  Found {len(pois)} POIs with Street View coverage")
        
        # Shuffle for randomness
        random.shuffle(pois)
        
        # Step 2: Find target with sufficient coverage
        # Note: Uniqueness check is done later for exploration tasks only,
        # checking if target is unique within the whitelist (not the wider area)
        print("\n[*] Step 2: Finding target with sufficient coverage...")
        
        target_poi = None
        whitelist = None
        spawn_candidates = None
        metadata_map = None
        
        try:
            for i, poi in enumerate(pois):
                print(f"  Trying POI {i + 1}/{len(pois)}: {poi.name}")
                
                # BFS exploration (no uniqueness pre-check for navigation tasks)
                # Global session is assumed active, so keep_session=True
                result = await self.whitelist_generator.generate_from_target(
                    target_pano_id=poi.nearest_pano_id,
                    min_panos=min_panos,
                    max_panos=max_panos,
                    max_distance=max_distance,
                    spawn_min_distance=spawn_min_distance,
                    spawn_max_distance=spawn_max_distance,
                    keep_session=True  # Reuse global workers
                )
                
                whitelist, spawn_candidates, metadata_map = result
                
                if len(whitelist) >= min_panos and len(spawn_candidates) >= spawn_count:
                    target_poi = poi
                    print(f"  [OK] Selected target: {poi.name}")
                    break
                else:
                    print(f"      Insufficient: {len(whitelist)} panos, {len(spawn_candidates)} spawn candidates")
        
        finally:
            # We do NOT exit session here, as it is managed globally.
            pass
        
        if not target_poi:
            print("  [!] No unique POI has sufficient coverage")
            return [], []
        
        # Step 3: Enhance panorama links
        print("\n[*] Step 3: Enhancing panorama links...")
        
        # Keep raw metadata for visual path generation (to avoid virtual links)
        raw_metadata_map = copy.deepcopy(metadata_map)
        
        whitelist_set = set(whitelist)
        metadata_map, virtual_added, external_removed = enhance_panorama_links(
            metadata_map,
            threshold_meters=virtual_link_threshold,
            whitelist=whitelist_set
        )
        
        print(f"  [OK] Added {virtual_added} virtual links")
        print(f"  [OK] Removed {external_removed} external links")
        
        # Save enhanced metadata to cache
        await self._save_metadata_cache(metadata_map)
        print(f"  [OK] Saved enhanced links for {len(metadata_map)} panoramas to cache")
        
        # Step 4: Select spawn points using Greedy Farthest Point Sampling
        print(f"\n[*] Step 4: Selecting {spawn_count} spawn points...")
        
        selected_spawns = self.select_spawn_points_dispersed(
            candidates=spawn_candidates,
            metadata_map=metadata_map,
            count=spawn_count
        )
        
        for i, spawn_id in enumerate(selected_spawns):
            spawn_meta = metadata_map.get(spawn_id, {})
            target_meta = metadata_map.get(target_poi.nearest_pano_id, {})
            
            if spawn_meta and target_meta:
                distance = self._calculate_distance(
                    spawn_meta.get("lat", 0), spawn_meta.get("lng", 0),
                    target_meta.get("lat", 0), target_meta.get("lng", 0)
                )
                print(f"  Spawn {i + 1}: {spawn_id[:30]}... (distance: {distance:.0f}m)")
            else:
                print(f"  Spawn {i + 1}: {spawn_id[:30]}...")
        
        geofence_name = self._generate_geofence_name(poi_keyword or poi_type)
        
        # Step 5a: Generate navigation tasks for primary target
        print(f"\n[*] Step 5a: Generating {spawn_count} navigation tasks...")
        
        for i, spawn_id in enumerate(selected_spawns):
            # Calculate visual path using raw graph (no virtual links)
            path_ids = self._dijkstra_shortest_path(spawn_id, target_poi.nearest_pano_id, raw_metadata_map)
            
            if not path_ids:
                print(f"      [!] No path found for spawn {spawn_id[:10]}... (skipping)")
                continue
                
            visual_path = self._calculate_visual_path(path_ids, raw_metadata_map)
            
            task = await self._generate_task(
                task_index=i + 1,
                spawn_pano_id=spawn_id,
                target_poi=target_poi,
                metadata_map=metadata_map,
                geofence_name=geofence_name,
                n_panos=len(whitelist),
                visual_path=visual_path
            )
            if task:
                all_tasks.append(task)
        
        # Step 5b: Generate exploration tasks for primary target (if enabled)
        if generate_exploration:
            print(f"\n[*] Step 5b: Generating {spawn_count} exploration tasks...")
            
            # NOTE: Uniqueness check is disabled for now. To enable, uncomment:
            # is_unique = await self._check_uniqueness_in_whitelist(
            #     poi=target_poi, whitelist_set=whitelist_set, max_distance=max_distance
            # )
            # if not is_unique:
            #     print("      [!] Skipping: target not unique within whitelist")
            
            # Use different spawn points for exploration (re-sample for variety)
            exploration_spawns = self.select_spawn_points_dispersed(
                candidates=spawn_candidates,
                metadata_map=metadata_map,
                count=spawn_count
            )
            
            for i, spawn_id in enumerate(exploration_spawns):
                task = await self._generate_exploration_task(
                    task_index=i + 1,
                    spawn_pano_id=spawn_id,
                    target_poi=target_poi,
                    metadata_map=metadata_map,
                    geofence_name=geofence_name,
                    is_positive=True,
                    n_panos=len(whitelist)
                )
                if task:
                    all_tasks.append(task)
        
        # Step 5c: Generate tasks for secondary targets (if provided)
        if secondary_keywords:
            print(f"\n[*] Step 5c: Searching for secondary targets...")
            
            for keyword in secondary_keywords:
                secondary_tasks = await self._generate_secondary_target_tasks(
                    primary_poi=target_poi,
                    keyword=keyword,
                    whitelist_set=whitelist_set,
                    metadata_map=metadata_map,
                    spawn_candidates=spawn_candidates,
                    spawn_count=spawn_count,
                    geofence_name=geofence_name,
                    max_distance=max_distance,
                    generate_exploration=generate_exploration,
                    raw_metadata_map=raw_metadata_map
                )
                all_tasks.extend(secondary_tasks)
        
        # Step 6: Save whitelist
        print(f"\n[*] Step 6: Saving whitelist...")
        self._save_whitelist(geofence_name, whitelist)
        print(f"  [OK] Updated whitelist: {geofence_name} ({len(whitelist)} panos)")
        
        # Prepare visualization data
        all_spawn_points = list(set(t['spawn_point'] for t in all_tasks))
        all_target_panos = list(set(pid for t in all_tasks for pid in t.get('target_pano_ids', [])))
        
        # Ensure primary target is included even if no tasks generated (unlikely)
        if target_poi.nearest_pano_id not in all_target_panos:
            all_target_panos.append(target_poi.nearest_pano_id)
        
        # Generate visualization
        vis_path = generate_network_html(
            geofence_name=geofence_name,
            metadata_map=metadata_map,
            spawn_points=all_spawn_points,
            target_pano_ids=all_target_panos,
            output_dir=str(self.vis_dir)
        )
        print(f"  [OK] Generated visualization: {vis_path}")
        
        # Summary
        nav_count = len([t for t in all_tasks if t['task_type'] == 'navigation_to_poi'])
        exp_count = len([t for t in all_tasks if t['task_type'] == 'exploration_find_poi'])
        
        print("\n" + "=" * 60)
        print("[OK] Task Generation V2 Complete!")
        print("=" * 60)
        print(f"  Target: {target_poi.name}")
        print(f"  Navigation tasks: {nav_count}")
        print(f"  Exploration tasks: {exp_count}")
        print(f"  Total tasks: {len(all_tasks)}")
        print(f"  Whitelist: {len(whitelist)} panoramas")
        print(f"  Virtual links: {virtual_added}")
        for task in all_tasks:
            print(f"  - [{task['task_type'][:3]}] {task['task_id']}")
        print("=" * 60)
        
        return all_tasks, whitelist
    
    async def generate_exploration_tasks(
        self,
        center_lat: float,
        center_lng: float,
        poi_type: str,
        poi_keyword: str,
        negative_keywords: List[str] = None,
        spawn_count: int = None,
        min_panos: int = None,
        max_panos: int = None,
        max_distance: float = None,
        spawn_min_distance: float = None,
        spawn_max_distance: float = None,
        virtual_link_threshold: float = None
    ) -> List[dict]:
        """
        Generate exploration tasks (find POI in area).
        
        Generates both positive examples (target exists) and negative examples
        (target not in whitelist).
        
        Args:
            center_lat: Search center latitude
            center_lng: Search center longitude
            poi_type: POI category
            poi_keyword: Primary POI keyword for positive examples
            negative_keywords: Keywords for negative examples
            spawn_count: Number of spawn points per task type
            ... (other args same as generate_batch_tasks_v2)
        
        Returns:
            List of exploration task dictionaries
        """
        print("=" * 60)
        print("*** Exploration Task Generation")
        print("=" * 60)
        
        # Load defaults if not provided
        spawn_count = spawn_count if spawn_count is not None else self.defaults.get("spawn_count", 2)
        min_panos = min_panos if min_panos is not None else self.defaults.get("min_panos", 20)
        max_panos = max_panos if max_panos is not None else self.defaults.get("max_panos", 60)
        max_distance = max_distance if max_distance is not None else self.defaults.get("max_distance", 500)
        spawn_min_distance = spawn_min_distance if spawn_min_distance is not None else self.defaults.get("spawn_distance_min", 100)
        spawn_max_distance = spawn_max_distance if spawn_max_distance is not None else self.defaults.get("spawn_distance_max", 200)
        virtual_link_threshold = virtual_link_threshold if virtual_link_threshold is not None else self.defaults.get("virtual_link_threshold", 18.0)
        
        all_tasks = []
        
        # Step 1: Search for primary POI
        print("\n[*] Step 1: Searching for primary POI...")
        pois = await self.poi_searcher.search_nearby(
            lat=center_lat,
            lng=center_lng,
            poi_type=poi_type,
            keyword=poi_keyword
        )
        
        if not pois:
            print("  [!] No POIs found")
            return []
        
        pois = await self.poi_searcher.enrich_with_pano_ids(pois)
        
        if not pois:
            print("  [!] No POIs with Street View coverage")
            return []
        
        print(f"  Found {len(pois)} POIs with Street View coverage")
        random.shuffle(pois)
        
        # Step 2: Find unique target (pre-check before BFS)
        print("\n[*] Step 2: Finding unique target (pre-check)...")
        
        target_poi = None
        whitelist = None
        spawn_candidates = None
        metadata_map = None
        
        for poi in pois:
            # Pre-check uniqueness
            is_unique, count = await self.pre_check_unique_target(poi, max_distance)
            
            if not is_unique:
                print(f"  Skipping {poi.name}: {count} '{poi.keyword}' found within {max_distance}m")
                continue
            
            print(f"  [OK] {poi.name} is unique within {max_distance}m")
            
            # Try to generate whitelist
            result = await self.whitelist_generator.generate_from_target(
                target_pano_id=poi.nearest_pano_id,
                min_panos=min_panos,
                max_panos=max_panos,
                max_distance=max_distance,
                spawn_min_distance=spawn_min_distance,
                spawn_max_distance=spawn_max_distance
            )
            
            whitelist, spawn_candidates, metadata_map = result
            
            if len(whitelist) >= min_panos and len(spawn_candidates) >= spawn_count:
                target_poi = poi
                print(f"  [OK] Selected target: {poi.name}")
                break
        
        if not target_poi:
            print("  [!] No unique POI with sufficient coverage found")
            return []
        
        # Step 3: Enhance links
        print("\n[*] Step 3: Enhancing panorama links...")
        whitelist_set = set(whitelist)
        metadata_map, virtual_added, external_removed = enhance_panorama_links(
            metadata_map,
            threshold_meters=virtual_link_threshold,
            whitelist=whitelist_set
        )
        print(f"  [OK] Added {virtual_added} virtual links, removed {external_removed} external")
        
        await self._save_metadata_cache(metadata_map)
        
        # Step 4: Generate positive examples
        print(f"\n[*] Step 4: Generating {spawn_count} positive exploration tasks...")
        
        geofence_name = self._generate_geofence_name(f"exp_{poi_keyword or poi_type}")
        
        selected_spawns = self.select_spawn_points_dispersed(
            candidates=spawn_candidates,
            metadata_map=metadata_map,
            count=spawn_count
        )
        
        for i, spawn_id in enumerate(selected_spawns):
            task = await self._generate_exploration_task(
                task_index=i + 1,
                spawn_pano_id=spawn_id,
                target_poi=target_poi,
                metadata_map=metadata_map,
                geofence_name=geofence_name,
                is_positive=True,
                n_panos=len(whitelist)
            )
            if task:
                all_tasks.append(task)
        
        # Step 5: Generate negative examples
        if negative_keywords:
            print(f"\n[*] Step 5: Generating negative exploration tasks...")
            
            for keyword in negative_keywords:
                # Search for negative keyword
                neg_pois = await self.poi_searcher.search_nearby(
                    lat=target_poi.lat,
                    lng=target_poi.lng,
                    poi_type=poi_type,
                    keyword=keyword,
                    radius_meters=int(max_distance)
                )
                
                neg_pois = await self.poi_searcher.enrich_with_pano_ids(neg_pois)
                
                # Check if any are in whitelist
                in_whitelist = [p for p in neg_pois if p.nearest_pano_id in whitelist_set]
                
                if not in_whitelist:
                    print(f"  [OK] '{keyword}' not in whitelist - generating negative tasks")
                    
                    # Generate negative tasks with independent spawn selection
                    neg_spawns = self.select_spawn_points_dispersed(
                        candidates=spawn_candidates,
                        metadata_map=metadata_map,
                        count=spawn_count
                    )
                    
                    for i, spawn_id in enumerate(neg_spawns):
                        task = await self._generate_exploration_task(
                            task_index=i + 1,
                            spawn_pano_id=spawn_id,
                            target_poi=POI(
                                place_id="",
                                name=keyword,
                                lat=0, lng=0,
                                keyword=keyword
                            ),
                            metadata_map=metadata_map,
                            geofence_name=geofence_name,
                            is_positive=False,
                            n_panos=len(whitelist)
                        )
                        if task:
                            all_tasks.append(task)
                else:
                    print(f"  [!] '{keyword}' found in whitelist - skipping")
        
        # Step 6: Save whitelist and visualization
        print(f"\n[*] Step 6: Saving whitelist...")
        self._save_whitelist(geofence_name, whitelist)
        
        # Prepare visualization data
        all_spawn_points = list(set(t['spawn_point'] for t in all_tasks))
        all_target_panos = list(set(pid for t in all_tasks for pid in t.get('target_pano_ids', [])))
        
        if target_poi.nearest_pano_id not in all_target_panos:
             all_target_panos.append(target_poi.nearest_pano_id)

        generate_network_html(
            geofence_name=geofence_name,
            metadata_map=metadata_map,
            spawn_points=all_spawn_points,
            target_pano_ids=all_target_panos,
            output_dir=str(self.vis_dir)
        )
        
        print("\n" + "=" * 60)
        print("[OK] Exploration Task Generation Complete!")
        print("=" * 60)
        print(f"  Tasks generated: {len(all_tasks)}")
        print("=" * 60)
        
        return all_tasks
    
    async def pre_check_unique_target(
        self, poi: POI, max_distance: float
    ) -> Tuple[bool, int]:
        """
        Pre-check if target POI is unique within BFS radius.
        
        Args:
            poi: Primary POI to check
            max_distance: BFS exploration radius (meters)
        
        Returns:
            Tuple of (is_unique, count_in_range)
        """
        # Search for same keyword around the POI
        same_keyword_pois = await self.poi_searcher.search_nearby(
            lat=poi.lat,
            lng=poi.lng,
            poi_type="",  # Use keyword search
            keyword=poi.keyword,
            radius_meters=int(max_distance)
        )
        
        count = len(same_keyword_pois)
        is_unique = (count <= 1)
        
        return is_unique, count
    
    async def _check_uniqueness_in_whitelist(
        self,
        poi: POI,
        whitelist_set: Set[str],
        max_distance: float
    ) -> bool:
        """
        Check if target POI is unique within the whitelist.
        
        This is less strict than checking the entire area - we only check
        if there are other POIs of the same type whose nearest pano is in the whitelist.
        
        Args:
            poi: Primary POI to check
            whitelist_set: Set of panorama IDs in the whitelist
            max_distance: Search radius (meters)
        
        Returns:
            True if POI is unique within whitelist
        """
        # Search for same keyword around the POI
        same_keyword_pois = await self.poi_searcher.search_nearby(
            lat=poi.lat,
            lng=poi.lng,
            poi_type="",
            keyword=poi.keyword,
            radius_meters=int(max_distance)
        )
        
        # Enrich with pano IDs
        same_keyword_pois = await self.poi_searcher.enrich_with_pano_ids(same_keyword_pois)
        
        # Count POIs whose nearest pano is in whitelist (excluding the target itself)
        in_whitelist = [
            p for p in same_keyword_pois 
            if p.nearest_pano_id in whitelist_set and p.place_id != poi.place_id
        ]
        
        # If no other same-type POIs in whitelist, target is unique
        return len(in_whitelist) == 0
    
    def select_spawn_points_dispersed(
        self,
        candidates: List[str],
        metadata_map: Dict[str, dict],
        count: int
    ) -> List[str]:
        """
        Select spawn points using Greedy Farthest Point Sampling.
        
        Ensures spawn points are spatially dispersed.
        
        Args:
            candidates: List of candidate panorama IDs
            metadata_map: Metadata for each panorama
            count: Number of spawn points to select
        
        Returns:
            List of selected spawn point panorama IDs
        """
        if len(candidates) <= count:
            return candidates.copy()
        
        selected = []
        remaining = set(candidates)
        
        # First point: random selection
        first = random.choice(list(remaining))
        selected.append(first)
        remaining.remove(first)
        
        # Subsequent points: furthest from already selected
        while len(selected) < count and remaining:
            best_candidate = None
            best_min_distance = -1
            
            for candidate in remaining:
                cand_meta = metadata_map.get(candidate, {})
                if not cand_meta:
                    continue
                
                cand_lat = cand_meta.get("lat")
                cand_lng = cand_meta.get("lng")
                
                if cand_lat is None or cand_lng is None:
                    continue
                
                # Find minimum distance to any selected point
                min_dist = float('inf')
                for sel in selected:
                    sel_meta = metadata_map.get(sel, {})
                    if not sel_meta:
                        continue
                    
                    sel_lat = sel_meta.get("lat")
                    sel_lng = sel_meta.get("lng")
                    
                    if sel_lat is None or sel_lng is None:
                        continue
                    
                    dist = self._calculate_distance(cand_lat, cand_lng, sel_lat, sel_lng)
                    min_dist = min(min_dist, dist)
                
                # Choose candidate with largest minimum distance
                if min_dist > best_min_distance:
                    best_min_distance = min_dist
                    best_candidate = candidate
            
            if best_candidate:
                selected.append(best_candidate)
                remaining.remove(best_candidate)
            else:
                break
        
        return selected
    
    async def _generate_task(
        self,
        task_index: int,
        spawn_pano_id: str,
        target_poi: POI,
        metadata_map: Dict[str, dict],
        geofence_name: str,
        n_panos: int = 0,
        visual_path: List[dict] = None
    ) -> Optional[dict]:
        """Generate a single navigation task."""
        spawn_meta = metadata_map.get(spawn_pano_id, {})
        target_meta = metadata_map.get(target_poi.nearest_pano_id, {})
        
        if not spawn_meta or not target_meta:
            logger.warning(f"Missing metadata for spawn or target")
            return None
        
        # Calculate initial heading
        if visual_path and len(visual_path) > 0:
            # Use the heading from the first step of the visual path
            # This ensures start orientation matches the "Head [Direction]" instruction
            heading = visual_path[0]["heading"]
        else:
            heading = self._calculate_initial_heading(
                spawn_meta.get("lat"), spawn_meta.get("lng"),
                target_meta.get("lat"), target_meta.get("lng")
            )
        
        # Get route and description
        route = await self.directions_fetcher.get_route(
            origin_lat=spawn_meta.get("lat"),
            origin_lng=spawn_meta.get("lng"),
            dest_lat=target_poi.lat,
            dest_lng=target_poi.lng
        )
        
        description = self.directions_fetcher.generate_task_description(
            route, target_poi.name
        ) if route else f"Navigate to {target_poi.name}."
        
        # Calculate distance and path length
        # Use route distance if available (more accurate for SPL), otherwise fallback to Haversine
        if route and route.total_distance_meters > 0:
            optimal_distance = route.total_distance_meters
        else:
            optimal_distance = self._calculate_distance(
                spawn_meta.get("lat"), spawn_meta.get("lng"),
                target_meta.get("lat"), target_meta.get("lng")
            )
        
        task_id = self._generate_task_id(f"nav_{target_poi.keyword or 'poi'}", task_index)
        
        # Calculate constraints
        max_steps = len(visual_path) * 2 if visual_path else None
        
        task = {
            "task_id": task_id,
            "task_type": "navigation_to_poi",
            "geofence": geofence_name,
            "spawn_point": spawn_pano_id,
            "spawn_heading": round(heading, 1),
            "description": description,
            "ground_truth": {
                "target_name": target_poi.name,
                "target_pano_id": target_poi.nearest_pano_id,
                "optimal_distance_meters": round(optimal_distance, 1),
                "route_description": self._summarize_route(route) if route else ""
            },
            "answer": "",
            "target_pano_ids": [target_poi.nearest_pano_id],
            "max_steps": max_steps,
            "max_time_seconds": None
        }
        
        if visual_path:
            task["visual_path"] = visual_path
        
        # Save task (default)
        self._save_task(task)
        
        return task
    
    async def _generate_exploration_task(
        self,
        task_index: int,
        spawn_pano_id: str,
        target_poi: POI,
        metadata_map: Dict[str, dict],
        geofence_name: str,
        is_positive: bool,
        n_panos: int = 0
    ) -> Optional[dict]:
        """Generate a single exploration task."""
        spawn_meta = metadata_map.get(spawn_pano_id, {})
        
        if not spawn_meta:
            logger.warning(f"Missing metadata for spawn")
            return None
        
        # Random initial heading for exploration
        heading = random.uniform(0, 360)
        
        # Generate exploration description
        description = self.directions_fetcher.generate_exploration_description(
            target_poi.name, language="en"
        )
        
        task_id = self._generate_task_id(f"exp_{target_poi.keyword or 'poi'}", task_index)
        
        task = {
            "task_id": task_id,
            "task_type": "exploration_find_poi",
            "geofence": geofence_name,
            "spawn_point": spawn_pano_id,
            "spawn_heading": round(heading, 1),
            "description": description,
            "ground_truth": {
                "target_name": target_poi.name,
                "target_pano_id": target_poi.nearest_pano_id if is_positive else None,
                "answer": "yes" if is_positive else "no"
            },
            "answer": "",
            "target_pano_ids": [target_poi.nearest_pano_id] if is_positive else [],
            "max_steps": None,
            "max_time_seconds": max(300, 3 * n_panos)
        }
        
        # Save task
        self._save_task(task)
        
        return task
    
    async def _generate_secondary_target_tasks(
        self,
        primary_poi: POI,
        keyword: str,
        whitelist_set: Set[str],
        metadata_map: Dict[str, dict],
        spawn_candidates: List[str],
        spawn_count: int,
        geofence_name: str,
        max_distance: float,
        generate_exploration: bool = True,
        raw_metadata_map: Dict[str, dict] = None
    ) -> List[dict]:
        """Generate tasks for secondary POI targets."""
        tasks = []
        
        # Ensure we have raw map (fallback to enhanced map if not provided, though less ideal for SPL)
        if raw_metadata_map is None:
            raw_metadata_map = metadata_map
        
        # Search for secondary POI using Text Search
        secondary_pois = await self.poi_searcher.search_nearby(
            lat=primary_poi.lat,
            lng=primary_poi.lng,
            poi_type="",
            keyword=keyword,
            radius_meters=int(max_distance)
        )
        
        secondary_pois = await self.poi_searcher.enrich_with_pano_ids(secondary_pois)
        
        # Filter: only keep POIs whose nearest_pano_id is in whitelist
        valid_pois = [p for p in secondary_pois if p.nearest_pano_id in whitelist_set]
        
        # Check valid POIs
        if not valid_pois:
            print(f"    No valid '{keyword}' found in whitelist")
            return []
            
        print(f"    [OK] Found {len(valid_pois)} valid '{keyword}' targets in whitelist")
        
        # Iterate over ALL valid POIs
        for poi_idx, target_poi in enumerate(valid_pois):
            print(f"    -> Processing secondary target {poi_idx+1}/{len(valid_pois)}: {target_poi.name}")
            
            # Select spawn points (independent selection for each target)
            selected_spawns = self.select_spawn_points_dispersed(
                candidates=spawn_candidates,
                metadata_map=metadata_map,
                count=spawn_count
            )
            
            # Generate navigation tasks
            for i, spawn_id in enumerate(selected_spawns):
                # Calculate visual path using raw graph (no virtual links)
                path_ids = self._dijkstra_shortest_path(spawn_id, target_poi.nearest_pano_id, raw_metadata_map)
                
                if not path_ids:
                    print(f"      [!] No path found for spawn {spawn_id[:10]}... (skipping)")
                    continue
                    
                visual_path = self._calculate_visual_path(path_ids, raw_metadata_map)
                
                # Ensure unique task ID by including secondary index if multiple
                # _generate_task uses task_index, but we need to ensure global uniqueness for this run
                # actually _generate_task calls _generate_task_id -> "nav_{name}_{index}"
                # If name is same (e.g. 2 Starbucks), we might get collision if we reset index.
                # So let's pass a modified index or rely on timestamp in ID.
                # Just using i+1 is fine if names are different or we accept they are different files.
                # But if names are identical (e.g. "Starbucks" and "Starbucks"), we need differentiation.
                
                # Let's rely on _generate_task logic but maybe we should append something if needed.
                # However, target_poi.name usually differs (e.g. "Starbucks - Main St" vs "Starbucks").
                # If names are identical, we might have issues. 
                # Let's hope POI names are distinct enough or timestamp helps.
                
                # Use a combined index to ensure uniqueness if multiple targets have same name
                task_idx = i + 1 + (poi_idx * 10) 
                
                task = await self._generate_task(
                    task_index=task_idx, 
                    spawn_pano_id=spawn_id,
                    target_poi=target_poi,
                    metadata_map=metadata_map,
                    geofence_name=geofence_name,
                    n_panos=len(whitelist_set),
                    visual_path=visual_path
                )
                if task:
                    tasks.append(task)
            
            # Generate exploration tasks (if enabled)
            if generate_exploration:
                exploration_spawns = self.select_spawn_points_dispersed(
                    candidates=spawn_candidates,
                    metadata_map=metadata_map,
                    count=spawn_count
                )
                
                for i, spawn_id in enumerate(exploration_spawns):
                    task = await self._generate_exploration_task(
                        task_index=i + 1,
                        spawn_pano_id=spawn_id,
                        target_poi=target_poi,
                        metadata_map=metadata_map,
                        geofence_name=geofence_name,
                        is_positive=True,
                        n_panos=len(whitelist_set)
                    )
                    if task:
                        tasks.append(task)
        
        return tasks
    
    def _calculate_initial_heading(
        self,
        spawn_lat: float, spawn_lng: float,
        target_lat: float, target_lng: float
    ) -> float:
        """Calculate initial heading from spawn to target."""
        lat1_rad = math.radians(spawn_lat)
        lat2_rad = math.radians(target_lat)
        delta_lng = math.radians(target_lng - spawn_lng)
        
        x = math.sin(delta_lng) * math.cos(lat2_rad)
        y = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lng))
        
        heading = math.degrees(math.atan2(x, y))
        return (heading + 360) % 360
    
    def _calculate_distance(
        self,
        lat1: float, lng1: float,
        lat2: float, lng2: float
    ) -> float:
        """Calculate distance between two points using Haversine formula."""
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
    
    def _summarize_route(self, route: Route) -> str:
        """Create a simple route summary."""
        if not route or not route.steps:
            return ""
        
        directions = []
        for step in route.steps:
            inst = step.instruction.lower()
            if "left" in inst:
                directions.append("left")
            elif "right" in inst:
                directions.append("right")
            elif "straight" in inst or "continue" in inst:
                directions.append("straight")
        
        return "→".join(directions) if directions else "straight"
    
    def _generate_task_id(self, poi_name: str, index: int) -> str:
        """Generate a task ID."""
        # Clean POI name
        clean_name = poi_name.lower().replace("'", "").replace(" ", "_")
        clean_name = "".join(c for c in clean_name if c.isalnum() or c == "_")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{clean_name}_{timestamp}_{index}"
    
    def _generate_geofence_name(self, poi_name: str) -> str:
        """Generate a geofence name."""
        clean_name = poi_name.lower().replace("'", "").replace(" ", "_")
        clean_name = "".join(c for c in clean_name if c.isalnum() or c == "_")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"list_nav_{clean_name}_{timestamp}"
    
    def _save_task(self, task: dict, subfolder: str = ""):
        """Save task to JSON file."""
        if subfolder:
            target_dir = self.base_dir / subfolder
        else:
            target_dir = self.tasks_dir
            
        target_dir.mkdir(parents=True, exist_ok=True)
        
        task_file = target_dir / f"{task['task_id']}.json"
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2, ensure_ascii=False)
        
        logger.debug(f"Saved task: {task_file}")
    
    def _save_whitelist(self, geofence_name: str, whitelist: List[str]):
        """Save whitelist to geofence_config.json."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        config_file = self.config_dir / "geofence_config.json"
        
        # Load existing config
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}
        
        # Update with new whitelist
        config[geofence_name] = whitelist
        
        # Save
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        
        logger.debug(f"Saved whitelist: {geofence_name}")
    
    async def _save_metadata_cache(self, metadata_map: Dict[str, dict]):
        """Save enhanced metadata to cache (both JSON file and SQLite database)."""
        from cache.metadata_cache import metadata_cache as sqlite_cache
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_file = self.cache_dir / "pano_metadata.json"
        
        # Load existing cache
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
        else:
            cache = {}
        
        # Update cache
        cache.update(metadata_map)
        
        # Save to JSON file
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        
        # Also save to SQLite database for Human Evaluation
        for pano_id, meta in metadata_map.items():
            lat = meta.get("lat")
            lng = meta.get("lng")
            if lat is not None and lng is not None:
                sqlite_cache.save(
                    pano_id=pano_id,
                    lat=lat,
                    lng=lng,
                    capture_date=meta.get("date") or meta.get("capture_date"),
                    links=meta.get("links"),
                    center_heading=meta.get("center_heading"),
                    source="task_generation"
                )
        
        logger.debug(f"Updated metadata cache: {len(metadata_map)} entries (JSON + SQLite)")


# Example usage
async def main():
    assembler = TaskAssembler()
    
    # Generate navigation tasks
    tasks = await assembler.generate_batch_tasks_v2(
        center_lat=47.5065,
        center_lng=19.0551,
        poi_type="restaurant",
        poi_keyword="McDonald's",
        spawn_count=2
    )
    
    print(f"\nGenerated {len(tasks)} tasks")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
