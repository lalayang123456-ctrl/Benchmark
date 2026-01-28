"""
POI Searcher - Google Places API Integration

Searches for Points of Interest using Google Places API.
Supports both Text Search (for keyword-based) and Nearby Search (for type-based) queries.
"""

import os
import json
import asyncio
import aiohttp
import logging
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class POI:
    """Represents a Point of Interest."""
    place_id: str
    name: str
    lat: float
    lng: float
    address: str = ""
    nearest_pano_id: Optional[str] = None
    keyword: Optional[str] = None  # Store the search keyword for uniqueness check
    
    def __repr__(self):
        return f"POI({self.name}, {self.lat:.4f}, {self.lng:.4f}, pano={self.nearest_pano_id})"
    
    def to_dict(self) -> dict:
        return {
            "place_id": self.place_id,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "address": self.address,
            "nearest_pano_id": self.nearest_pano_id,
            "keyword": self.keyword
        }


class POISearcher:
    """Search for Points of Interest using Google Places API."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API key is required. Set GOOGLE_API_KEY environment variable.")
        
        # Load POI config
        config_path = Path(__file__).parent / "poi_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            self.config = {"poi_categories": {}, "generation_defaults": {}}
        
        self.default_radius = self.config.get("generation_defaults", {}).get("search_radius", 1500)
        self.max_retries = 3
        self.retry_delay = 2.0  # seconds
    
    async def search_nearby(
        self,
        lat: float,
        lng: float,
        poi_type: str,
        keyword: str = None,
        radius_meters: int = None
    ) -> List[POI]:
        """
        Search for POIs near a location.
        
        When a keyword is provided, uses Text Search API for accurate name matching.
        Without keyword, uses Nearby Search API for type-based search.
        
        Args:
            lat: Latitude of search center
            lng: Longitude of search center
            poi_type: POI category (e.g., 'restaurant', 'transit')
            keyword: Specific keyword to search (e.g., "McDonald's")
            radius_meters: Search radius in meters
        
        Returns:
            List of POI objects
        """
        radius = radius_meters or self.default_radius
        
        # Get category config
        category = self.config.get("poi_categories", {}).get(poi_type, {})
        
        if keyword:
            # Use Text Search API for keyword-based search
            pois = await self._search_with_text_search(lat, lng, radius, keyword)
        else:
            # Use Nearby Search API for type-based search
            pois = await self._search_with_nearby_search(lat, lng, radius, category)
        
        # Store the keyword for each POI
        for poi in pois:
            poi.keyword = keyword or poi_type
        
        return pois
    
    async def _search_with_text_search(
        self, lat: float, lng: float, radius: float, search_keyword: str
    ) -> List[POI]:
        """
        Search using Text Search API - supports keyword-based search.
        Uses locationBias (preference, not strict limit).
        """
        url = "https://places.googleapis.com/v1/places:searchText"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress"
        }
        
        body = {
            "textQuery": search_keyword,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius
                }
            },
            "maxResultCount": 20
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=body) as response:
                        if response.status == 200:
                            data = await response.json()
                            return self._parse_places_response(data)
                        else:
                            error_text = await response.text()
                            logger.warning(f"Text Search API error (attempt {attempt + 1}): {response.status} - {error_text}")
            except Exception as e:
                logger.warning(f"Text Search API exception (attempt {attempt + 1}): {e}")
            
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)
        
        logger.error(f"Text Search API failed after {self.max_retries + 1} attempts")
        return []
    
    async def _search_with_nearby_search(
        self, lat: float, lng: float, radius: float, category: dict
    ) -> List[POI]:
        """
        Search using Nearby Search API - for type-based search.
        Uses locationRestriction (strict limit).
        Does NOT support keyword parameter.
        """
        url = "https://places.googleapis.com/v1/places:searchNearby"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress"
        }
        
        # Get places_type from category
        places_type = category.get("places_type", [])
        if isinstance(places_type, str):
            places_type = [places_type]
        
        if not places_type:
            logger.warning("No places_type specified for Nearby Search")
            return []
        
        body = {
            "includedTypes": places_type,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius
                }
            },
            "maxResultCount": 20
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=body) as response:
                        if response.status == 200:
                            data = await response.json()
                            return self._parse_places_response(data)
                        else:
                            error_text = await response.text()
                            logger.warning(f"Nearby Search API error (attempt {attempt + 1}): {response.status} - {error_text}")
            except Exception as e:
                logger.warning(f"Nearby Search API exception (attempt {attempt + 1}): {e}")
            
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)
        
        logger.error(f"Nearby Search API failed after {self.max_retries + 1} attempts")
        return []
    
    def _parse_places_response(self, data: dict) -> List[POI]:
        """Parse Places API response into POI objects."""
        pois = []
        places = data.get("places", [])
        
        for place in places:
            try:
                location = place.get("location", {})
                display_name = place.get("displayName", {})
                
                poi = POI(
                    place_id=place.get("id", ""),
                    name=display_name.get("text", "Unknown"),
                    lat=location.get("latitude", 0),
                    lng=location.get("longitude", 0),
                    address=place.get("formattedAddress", "")
                )
                pois.append(poi)
            except Exception as e:
                logger.warning(f"Error parsing place: {e}")
        
        return pois
    
    async def get_nearest_pano_id(self, lat: float, lng: float) -> Optional[str]:
        """
        Get nearest Street View panorama ID using Static API metadata.
        
        Args:
            lat: Latitude
            lng: Longitude
        
        Returns:
            Panorama ID or None if not found
        """
        url = f"https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {
            "location": f"{lat},{lng}",
            "key": self.api_key,
            "source": "outdoor"
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
                                logger.debug(f"No Street View coverage at {lat}, {lng}")
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
        Enrich POIs with nearest panorama IDs (Concurrent).
        Filters out POIs without Street View coverage.
        
        Args:
            pois: List of POI objects
        
        Returns:
            List of POIs with nearest_pano_id filled (only those with coverage)
        """
        enriched = []
        
        async def _enrich_single(poi):
            pano_id = await self.get_nearest_pano_id(poi.lat, poi.lng)
            if pano_id:
                poi.nearest_pano_id = pano_id
                return poi
            return None

        tasks = [_enrich_single(poi) for poi in pois]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res:
                enriched.append(res)
                logger.debug(f"Found pano {res.nearest_pano_id} for {res.name}")
        
        logger.info(f"Enriched {len(enriched)}/{len(pois)} POIs with Street View coverage")
        return enriched


# Example usage
async def main():
    searcher = POISearcher()
    
    # Search for McDonald's near Budapest
    pois = await searcher.search_nearby(
        lat=47.5065,
        lng=19.0551,
        poi_type="restaurant",
        keyword="McDonald's"
    )
    
    print(f"Found {len(pois)} POIs")
    for poi in pois:
        print(f"  - {poi}")
    
    # Enrich with panorama IDs
    enriched = await searcher.enrich_with_pano_ids(pois)
    print(f"\nWith Street View coverage: {len(enriched)}")
    for poi in enriched:
        print(f"  - {poi}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
