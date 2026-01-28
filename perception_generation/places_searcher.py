"""
Places Searcher - Google Places API Integration for Perception Tasks

Searches for specific places by name using Google Places API Text Search.
Uses locationRestriction for strict radius enforcement.
"""

import os
import asyncio
import aiohttp
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env from VLN_BENCHMARK directory
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)


@dataclass
class POI:
    """Represents a Point of Interest."""
    place_id: str
    name: str
    lat: float
    lng: float
    address: str = ""
    place_type: str = ""
    pano_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.place_type,
            "lat": self.lat,
            "lng": self.lng,
            "address": self.address,
            "pano_id": self.pano_id
        }


class PlacesSearcher:
    """Search for specific places by name using Google Places API."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API key is required. Set GOOGLE_API_KEY environment variable.")
        
        self.max_retries = 3
        self.retry_delay = 2.0
    
    async def search_by_name(
        self,
        lat: float,
        lng: float,
        radius: float,
        name: str
    ) -> Optional[POI]:
        """
        Search for a specific place by name within strict radius.
        
        Uses Text Search API with locationRestriction for strict boundary.
        
        Args:
            lat: Center latitude
            lng: Center longitude
            radius: Search radius in meters (strict limit)
            name: Place name to search for
        
        Returns:
            POI object if found within radius, None otherwise
        """
        url = "https://places.googleapis.com/v1/places:searchText"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress,places.primaryType"
        }
        
        body = {
            "textQuery": name,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius
                }
            },
            "maxResultCount": 5
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=body) as response:
                        if response.status == 200:
                            data = await response.json()
                            places = data.get("places", [])
                            
                            if not places:
                                logger.info(f"  [-] '{name}' not found within {radius}m")
                                return None
                            
                            # Return first (most relevant) result
                            place = places[0]
                            location = place.get("location", {})
                            display_name = place.get("displayName", {})
                            
                            poi = POI(
                                place_id=place.get("id", ""),
                                name=display_name.get("text", name),
                                lat=location.get("latitude", 0),
                                lng=location.get("longitude", 0),
                                address=place.get("formattedAddress", ""),
                                place_type=place.get("primaryType", "")
                            )
                            
                            logger.info(f"  [+] Found '{poi.name}' at ({poi.lat:.6f}, {poi.lng:.6f})")
                            return poi
                        else:
                            error_text = await response.text()
                            logger.warning(f"Places API error (attempt {attempt + 1}): {response.status} - {error_text}")
            except Exception as e:
                logger.warning(f"Places API exception (attempt {attempt + 1}): {e}")
            
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)
        
        logger.error(f"Places API failed after {self.max_retries + 1} attempts for '{name}'")
        return None
    
    async def search_multiple_names(
        self,
        lat: float,
        lng: float,
        radius: float,
        names: List[str]
    ) -> List[POI]:
        """
        Search for multiple places by name, return only those found.
        
        Args:
            lat: Center latitude
            lng: Center longitude
            radius: Search radius in meters
            names: List of place names to search for
        
        Returns:
            List of POI objects for places found within radius
        """
        logger.info(f"[*] Searching for {len(names)} places within {radius}m radius...")
        
        # Search sequentially to avoid rate limiting
        found_pois = []
        for name in names:
            poi = await self.search_by_name(lat, lng, radius, name)
            if poi:
                found_pois.append(poi)
            await asyncio.sleep(0.3)  # Small delay between requests
        
        logger.info(f"[*] Found {len(found_pois)}/{len(names)} places within radius")
        return found_pois
    
    async def get_nearest_pano_id(self, lat: float, lng: float, radius: int = 50) -> Optional[str]:
        """
        Get nearest Street View panorama ID.
        
        Args:
            lat: Latitude
            lng: Longitude
            radius: Search radius in meters
        
        Returns:
            Panorama ID or None if not found
        """
        url = "https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {
            "location": f"{lat},{lng}",
            "key": self.api_key,
            "source": "outdoor",
            "radius": radius
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == "OK":
                                return data.get("pano_id")
                            else:
                                return None
                        else:
                            logger.warning(f"Street View metadata error (attempt {attempt + 1}): {response.status}")
            except Exception as e:
                logger.warning(f"Street View metadata exception (attempt {attempt + 1}): {e}")
            
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)
        
        return None
    
    async def enrich_with_pano_ids(self, pois: List[POI]) -> List[POI]:
        """
        Enrich POIs with nearest panorama IDs.
        Filters out POIs without Street View coverage.
        
        Args:
            pois: List of POI objects
        
        Returns:
            List of POIs with pano_id filled (only those with coverage)
        """
        enriched = []
        
        for poi in pois:
            pano_id = await self.get_nearest_pano_id(poi.lat, poi.lng)
            if pano_id:
                poi.pano_id = pano_id
                enriched.append(poi)
                logger.info(f"  [+] {poi.name} -> pano {pano_id[:20]}...")
            else:
                logger.warning(f"  [-] {poi.name} has no Street View coverage")
            await asyncio.sleep(0.2)
        
        logger.info(f"[*] Enriched {len(enriched)}/{len(pois)} POIs with Street View coverage")
        return enriched
