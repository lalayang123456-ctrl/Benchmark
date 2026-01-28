"""
Spatial Orientation Task Generator

Generates tasks for evaluating spatial reasoning capabilities:
- Distance estimation to nearby POIs
- Bearing/direction estimation to POIs
"""

import os
import re
import json
import random
import math
import logging
import asyncio
import aiohttp
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
from collections import deque

from .generator_config import (
    TASKS_DIR, GEOFENCE_CONFIG_PATH, SEARCH_RADIUS, 
    MAX_PATH_STEPS, MIN_POI_COUNT, HIGH_VISIBILITY_TYPES,
    RESTAURANT_BRANDS, FOOD_TYPE_KEYWORDS
)

# Import MetadataFetcher for real panorama link fetching
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.metadata_fetcher import MetadataFetcher

logger = logging.getLogger(__name__)


class SpatialOrientationTaskGenerator:
    """Generate spatial orientation and distance estimation tasks."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is required")
        
        # Initialize MetadataFetcher for Selenium-based link fetching
        self.metadata_fetcher = MetadataFetcher(api_key=self.api_key, num_workers=2)
        
        # Ensure directories exist
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        GEOFENCE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Predefined cities for global sampling
        self.cities = [
            {"name": "New York, USA", "lat": 40.7580, "lng": -73.9855},
            {"name": "London, UK", "lat": 51.5074, "lng": -0.1278},
            {"name": "Tokyo, Japan", "lat": 35.6895, "lng": 139.6917},
            {"name": "Paris, France", "lat": 48.8566, "lng": 2.3522},
            {"name": "San Francisco, USA", "lat": 37.7749, "lng": -122.4194},
            {"name": "Sydney, Australia", "lat": -33.8688, "lng": 151.2093},
            {"name": "Berlin, Germany", "lat": 52.5200, "lng": 13.4050},
            {"name": "Singapore", "lat": 1.3521, "lng": 103.8198}
        ]

    async def generate_batch(
        self, 
        center_lat: float = None, 
        center_lng: float = None, 
        radius: float = 500,
        count: int = 1
    ) -> List[str]:
        """
        Generate a batch of spatial orientation tasks.
        
        Args:
            center_lat: Center latitude (random city if None)
            center_lng: Center longitude (random city if None)
            radius: Radius for random pano sampling (meters)
            count: Number of tasks to generate
            
        Returns:
            List of generated task IDs
        """
        generated_ids = []
        attempts = 0
        max_attempts = count * 20  # Higher retry count due to strict requirements
        
        # Determine center
        if center_lat is None or center_lng is None:
            city = random.choice(self.cities)
            center_lat, center_lng = city["lat"], city["lng"]
            print(f"[*] Randomly selected city: {city['name']}")
        
        print(f"[*] Starting generation: {count} tasks around {center_lat}, {center_lng}")
        
        try:
            async with aiohttp.ClientSession() as session:
                while len(generated_ids) < count and attempts < max_attempts:
                    attempts += 1
                    
                    # 1. Random point for pano search
                    lat, lng = self._random_point(center_lat, center_lng, radius)
                    print(f"  Attempt {attempts}: Sampling at {lat:.5f}, {lng:.5f}")
                    
                    # 2. Find nearest pano
                    pano_data = await self._find_nearest_pano(session, lat, lng)
                    if not pano_data:
                        print("    -> No Street View coverage")
                        continue
                    
                    pano_id = pano_data["pano_id"]
                    pano_lat = pano_data["lat"]
                    pano_lng = pano_data["lng"]
                    
                    # 3. Search for nearby POIs (within 30m)
                    pois = await self._search_nearby_pois(session, pano_lat, pano_lng, SEARCH_RADIUS)
                    
                    if len(pois) < MIN_POI_COUNT:
                        print(f"    -> Only {len(pois)} POIs found (need >= {MIN_POI_COUNT})")
                        continue
                    
                    print(f"    -> Found {len(pois)} POIs nearby")
                    
                    # 4. Select two POIs and check same-street
                    poi_pair = self._select_poi_pair(pois)
                    if not poi_pair:
                        print("    -> No valid POI pair (same-street check failed)")
                        continue
                    
                    poi_a, poi_b = poi_pair
                    print(f"    -> Selected: {poi_a['name']} & {poi_b['name']}")
                    
                    # 5. Get nearest panos for POIs
                    pano_a = await self._find_nearest_pano(session, poi_a["lat"], poi_a["lng"])
                    pano_b = await self._find_nearest_pano(session, poi_b["lat"], poi_b["lng"])
                    
                    if not pano_a or not pano_b:
                        print("    -> POIs have no Street View panos")
                        continue
                    
                    # 6. Check connectivity and build whitelist
                    whitelist, path = await self._build_connected_whitelist(
                        session, pano_a["pano_id"], pano_b["pano_id"]
                    )
                    
                    if not whitelist:
                        print("    -> POIs not connected or isolated")
                        continue
                    
                    print(f"    -> Whitelist size: {len(whitelist)} panos")

                    # --- NEW: Download Images for Whitelist ---

                    
                    # 7. Calculate ground truth
                    # Distance/Bearing from Spawn (Agent)
                    dist_a = self._haversine(pano_lat, pano_lng, poi_a["lat"], poi_a["lng"])
                    dist_b = self._haversine(pano_lat, pano_lng, poi_b["lat"], poi_b["lng"])
                    bearing_a = self._calculate_bearing(pano_lat, pano_lng, poi_a["lat"], poi_a["lng"])
                    bearing_b = self._calculate_bearing(pano_lat, pano_lng, poi_b["lat"], poi_b["lng"])
                    
                    # Distance/Bearing between POIs
                    dist_between_pois = self._haversine(poi_a["lat"], poi_a["lng"], poi_b["lat"], poi_b["lng"])
                    bearing_a_to_b = self._calculate_bearing(poi_a["lat"], poi_a["lng"], poi_b["lat"], poi_b["lng"])
                    bearing_b_to_a = self._calculate_bearing(poi_b["lat"], poi_b["lng"], poi_a["lat"], poi_a["lng"])
                    
                    # 8. Generate task
                    task_id = f"spatial_task_{len(generated_ids) + 1}_{int(datetime.now().timestamp())}"
                    
                    description = (
                        f"You are standing at a street location. Nearby, there is a {poi_a['name']} "
                        f"and a {poi_b['name']}. Estimate the distance between {poi_a['name']} and {poi_b['name']} "
                        f"in meters, and the relative direction of {poi_b['name']} from {poi_a['name']} "
                        f"(in degrees, 0°=North, 90°=East)."
                    )
                    
                    task_data = {
                        "task_id": task_id,
                        "task_type": "spatial_orientation",
                        "description": description,
                        "spawn_pano_id": pano_id,
                        "spawn_heading": bearing_a,  # Face towards POI A
                        "pois": [
                            {
                                "name": poi_a["name"],
                                "type": poi_a.get("type"),
                                "lat": poi_a["lat"],
                                "lng": poi_a["lng"],
                                "address": poi_a.get("address", "")
                            },
                            {
                                "name": poi_b["name"],
                                "type": poi_b.get("type"),
                                "lat": poi_b["lat"],
                                "lng": poi_b["lng"],
                                "address": poi_b.get("address", "")
                            }
                        ],
                        "geofence_id": f"list_spatial_{task_id}",
                        "ground_truth": {
                            "distance_a_meters": round(dist_a, 1),
                            "distance_b_meters": round(dist_b, 1),
                            # New fields used for relative estimation
                            "distance_between_pois_meters": round(dist_between_pois, 1),
                            "bearing_a_to_b_degrees": round(bearing_a_to_b, 1),
                            "bearing_b_to_a_degrees": round(bearing_b_to_a, 1),
                            # Reference
                            "bearing_a_degrees": round(bearing_a, 1),
                            "bearing_b_degrees": round(bearing_b, 1)
                        },
                        "answer": "",
                        "max_steps": None,
                        "max_time_seconds": 180,
                        "metadata": {
                            "created_at": datetime.now().isoformat(),
                            "spawn_location": {"lat": pano_lat, "lng": pano_lng}
                        }
                    }
                    
                    # 9. Save
                    self._save_task(task_data)
                    self._save_whitelist(f"list_spatial_{task_id}", whitelist)
                    
                    print(f"    [OK] Task Generated: {task_id}")
                    generated_ids.append(task_id)
        
        finally:
            # Cleanup MetadataFetcher workers
            await self.metadata_fetcher.cleanup()
        
        return generated_ids

    async def _find_nearest_pano(self, session: aiohttp.ClientSession, lat: float, lng: float) -> Optional[Dict]:
        """Find nearest Street View pano to coordinates."""
        url = "https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {
            "location": f"{lat},{lng}",
            "key": self.api_key,
            "source": "outdoor"
        }
        
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "OK":
                        return {
                            "pano_id": data["pano_id"],
                            "lat": data["location"]["lat"],
                            "lng": data["location"]["lng"]
                        }
        except Exception as e:
            logger.warning(f"Pano lookup error: {e}")
        return None

    async def _search_nearby_pois(
        self, session: aiohttp.ClientSession, lat: float, lng: float, radius: float
    ) -> List[Dict]:
        """Search for POIs near a location using Places API."""
        url = "https://places.googleapis.com/v1/places:searchNearby"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress,places.primaryType"
        }
        
        body = {
            "includedTypes": HIGH_VISIBILITY_TYPES,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius
                }
            },
            "maxResultCount": 10
        }
        
        try:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pois = []
                    for place in data.get("places", []):
                        loc = place.get("location", {})
                        display = place.get("displayName", {})
                        
                        name = display.get("text", "Unknown")
                        primary_type = place.get("primaryType", "")
                        
                        # Check if this type is food/restaurant related
                        is_food_place = any(kw in primary_type.lower() for kw in FOOD_TYPE_KEYWORDS)
                        
                        # If it is a food place, enforce brand filtering
                        if is_food_place:
                            if not any(brand.lower() in name.lower() for brand in RESTAURANT_BRANDS):
                                continue

                        pois.append({
                            "id": place.get("id"),
                            "name": name,
                            "type": primary_type,
                            "lat": loc.get("latitude"),
                            "lng": loc.get("longitude"),
                            "address": place.get("formattedAddress", "")
                        })
                    return pois
        except Exception as e:
            logger.warning(f"POI search error: {e}")
        return []

    def _select_poi_pair(self, pois: List[Dict]) -> Optional[Tuple[Dict, Dict]]:
        """Select a pair of POIs that are on the same street."""
        for i in range(len(pois)):
            for j in range(i + 1, len(pois)):
                poi_a, poi_b = pois[i], pois[j]
                
                # Same-street check
                street_a = self._extract_street(poi_a.get("address", ""))
                street_b = self._extract_street(poi_b.get("address", ""))
                
                if street_a and street_b and street_a.lower() == street_b.lower():
                    return (poi_a, poi_b)
        
        # Fallback: just pick first two if no same-street pair found
        if len(pois) >= 2:
            return (pois[0], pois[1])
        return None

    def _extract_street(self, address: str) -> Optional[str]:
        """Extract street name from address string."""
        if not address:
            return None
        
        # Common patterns for street names
        parts = address.split(",")
        if parts:
            # First part usually contains street
            street_part = parts[0].strip()
            # Remove building numbers
            street_cleaned = re.sub(r"^\d+\s*", "", street_part)
            return street_cleaned if street_cleaned else street_part
        return None

    async def _build_connected_whitelist(
        self, session: aiohttp.ClientSession, pano_a: str, pano_b: str
    ) -> Tuple[List[str], List[str]]:
        """
        Build whitelist with connected path between two panos.
        Returns (whitelist, path) or ([], []) if not connected.
        """
        # Simple BFS to find path and collect neighbors
        visited = {pano_a}
        queue = deque([(pano_a, [pano_a])])
        neighbors_a = set()
        neighbors_b = set()
        path_found = None
        
        # First, get links for pano_a
        links_a = await self._get_pano_links(session, pano_a)
        if not links_a:
            return [], []  # Isolated point
        neighbors_a.update(link["pano_id"] for link in links_a if "pano_id" in link)
        
        # Get links for pano_b
        links_b = await self._get_pano_links(session, pano_b)
        if not links_b:
            return [], []  # Isolated point
        neighbors_b.update(link["pano_id"] for link in links_b if "pano_id" in link)
        
        # BFS for path
        while queue and len(visited) < 50:  # Limit search
            current, path = queue.popleft()
            
            if current == pano_b:
                path_found = path
                break
            
            if len(path) > MAX_PATH_STEPS:
                continue
            
            links = await self._get_pano_links(session, current)
            for link in links:
                next_pano = link.get("pano_id")
                if next_pano and next_pano not in visited:
                    visited.add(next_pano)
                    queue.append((next_pano, path + [next_pano]))
        
        if not path_found:
            return [], []
        
        # Build whitelist: path + neighbors of endpoints
        whitelist = set(path_found)
        whitelist.update(neighbors_a)
        whitelist.update(neighbors_b)
        
        return list(whitelist), path_found

    async def _get_pano_links(self, session: aiohttp.ClientSession, pano_id: str) -> List[Dict]:
        """Get links for a panorama using MetadataFetcher (Selenium-based)."""
        try:
            # Use MetadataFetcher which uses Selenium + Google Maps JS API
            # to get real panorama links
            links_data = await self.metadata_fetcher.fetch_links(pano_id)
            
            if links_data and "links" in links_data:
                # Convert to our format: [{"pano_id": ..., "heading": ...}, ...]
                return [
                    {
                        "pano_id": link.get("panoId"),
                        "heading": link.get("heading", 0),
                        "description": link.get("description", "")
                    }
                    for link in links_data["links"]
                    if link.get("panoId")
                ]
        except Exception as e:
            logger.warning(f"Links fetch error for {pano_id}: {e}")
        
        return []

    def _random_point(self, lat: float, lng: float, radius_meters: float) -> Tuple[float, float]:
        """Generate random point within radius."""
        r = radius_meters / 111300.0
        u = random.random()
        v = random.random()
        w = r * math.sqrt(u)
        t = 2 * math.pi * v
        x = w * math.cos(t)
        y = w * math.sin(t)
        return (lat + x, lng + y / math.cos(math.radians(lat)))

    def _haversine(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance in meters using Haversine formula."""
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lng2 - lng1)
        
        a = math.sin(d_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c

    def _calculate_bearing(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate bearing from point 1 to point 2 in degrees (0-360)."""
        d_lon = math.radians(lng2 - lng1)
        lat1 = math.radians(lat1)
        lat2 = math.radians(lat2)
        
        y = math.sin(d_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
        bearing = math.degrees(math.atan2(y, x))
        
        return (bearing + 360) % 360

    def _save_task(self, task: Dict):
        """Save task to JSON file."""
        path = TASKS_DIR / f"{task['task_id']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2, ensure_ascii=False)

    def _save_whitelist(self, name: str, whitelist: List[str]):
        """Save whitelist to geofence config."""
        if GEOFENCE_CONFIG_PATH.exists():
            with open(GEOFENCE_CONFIG_PATH, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except:
                    config = {}
        else:
            config = {}
        
        config[name] = whitelist
        
        with open(GEOFENCE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
