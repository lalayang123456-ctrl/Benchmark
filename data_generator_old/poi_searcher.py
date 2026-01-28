"""
POI Searcher - Google Places API Integration

Searches for Points of Interest using Google Places API.
"""

import os
import json
import asyncio
import aiohttp
from typing import List, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class POI:
    """Represents a Point of Interest."""
    
    def __init__(self, place_id: str, name: str, lat: float, lng: float, 
                 address: str = "", nearest_pano_id: str = None):
        self.place_id = place_id
        self.name = name
        self.lat = lat
        self.lng = lng
        self.address = address
        self.nearest_pano_id = nearest_pano_id
    
    def __repr__(self):
        return f"POI(name='{self.name}', lat={self.lat}, lng={self.lng})"
    
    def to_dict(self):
        return {
            "place_id": self.place_id,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "address": self.address,
            "nearest_pano_id": self.nearest_pano_id
        }


class POISearcher:
    """Search for Points of Interest using Google Places API."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API Key not found. Set GOOGLE_API_KEY in .env")
        
        # Load POI configuration
        config_path = Path(__file__).parent / "poi_config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.poi_categories = self.config["poi_categories"]
        self.defaults = self.config["generation_defaults"]
    
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
        Without keyword, uses Places API (New) for type-based search.
        
        Args:
            lat: Latitude of search center
            lng: Longitude of search center
            poi_type: POI category ("restaurant", "transit", "landmark", "service")
            keyword: Optional specific keyword (e.g., "McDonald's") - enables name-based search
            radius_meters: Search radius in meters (default from config)
        
        Returns:
            List of POI objects
        """
        radius = radius_meters or self.defaults["search_radius"]
        
        # Get category configuration
        if poi_type not in self.poi_categories:
            raise ValueError(f"Unknown POI type: {poi_type}. Available: {list(self.poi_categories.keys())}")
        
        category = self.poi_categories[poi_type]
        
        # If keyword is provided, use Text Search API for accurate name matching
        # searchNearby does NOT support textQuery, only type-based filtering
        if keyword:
            print(f"[*] Searching for '{keyword}' using Text Search API...")
            return await self._search_with_text_search(lat, lng, radius, keyword)
        
        # Without keyword, use searchNearby with type filtering
        search_keyword = category["keywords"][0]
        try:
            return await self._search_with_places_api_new(lat, lng, radius, category, search_keyword)
        except Exception as e:
            if "has not been used" in str(e) or "not enabled" in str(e):
                print(f"[WARNING]  Places API (New) not enabled, falling back to Text Search...")
                return await self._search_with_text_search(lat, lng, radius, search_keyword)
            raise
    
    async def _search_with_places_api_new(
        self, lat: float, lng: float, radius: float, category: dict, search_keyword: str
    ) -> List[POI]:
        """Search using Places API (New) - requires POST request with FieldMask."""
        url = "https://places.googleapis.com/v1/places:searchNearby"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location"
        }
        
        # Get the places_type - can be a list or string
        places_type = category.get("places_type", "restaurant")
        if isinstance(places_type, str):
            included_types = [places_type]
        else:
            included_types = places_type if isinstance(places_type, list) else [places_type]
        
        body = {
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": lat,
                        "longitude": lng
                    },
                    "radius": float(radius)
                }
            },
            "includedTypes": included_types,
            "maxResultCount": 20
        }
        
        # Note: searchNearby does NOT support textQuery
        # It only supports type-based filtering
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as response:
                data = await response.json()
        
        if "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            raise Exception(f"Places API Error: {error_msg}")
        
        pois = []
        for place in data.get("places", []):
            name = place.get("displayName", {}).get("text", "Unknown")
            location = place.get("location", {})
            
            poi = POI(
                place_id=place.get("id", ""),
                name=name,
                lat=location.get("latitude", 0),
                lng=location.get("longitude", 0),
                address=place.get("formattedAddress", "")
            )
            pois.append(poi)
        
        print(f"[OK] Found {len(pois)} POIs for '{search_keyword}' (Places API New)")
        return pois
    
    async def _search_with_text_search(
        self, lat: float, lng: float, radius: float, search_keyword: str
    ) -> List[POI]:
        """Search using Text Search API - supports keyword-based search."""
        url = "https://places.googleapis.com/v1/places:searchText"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location"
        }
        
        # Improved textQuery format - simpler query often works better
        body = {
            "textQuery": search_keyword,
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": lat,
                        "longitude": lng
                    },
                    "radius": float(radius)
                }
            },
            "maxResultCount": 20
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as response:
                data = await response.json()
        
        # Debug: print response for troubleshooting
        if "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            error_code = data["error"].get("code", "")
            print(f"[DEBUG] Text Search API Error: {error_code} - {error_msg}")
            # Don't raise, just return empty list and let fallback happen
            return []
        
        pois = []
        for place in data.get("places", []):
            name = place.get("displayName", {}).get("text", "Unknown")
            location = place.get("location", {})
            
            poi = POI(
                place_id=place.get("id", ""),
                name=name,
                lat=location.get("latitude", 0),
                lng=location.get("longitude", 0),
                address=place.get("formattedAddress", "")
            )
            pois.append(poi)
        
        print(f"[OK] Found {len(pois)} POIs for '{search_keyword}' (Text Search)")
        return pois
    
    async def get_nearest_pano_id(self, lat: float, lng: float) -> Optional[str]:
        """
        Get nearest Street View panorama ID using Static API.
        
        Args:
            lat: Latitude
            lng: Longitude
        
        Returns:
            Panorama ID or None if not found
        """
        url = "https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {
            "location": f"{lat},{lng}",
            "key": self.api_key
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
        
        if data.get("status") == "OK":
            return data.get("pano_id")
        return None
    
    async def enrich_with_pano_ids(self, pois: List[POI]) -> List[POI]:
        """
        Enrich POIs with nearest panorama IDs.
        
        Args:
            pois: List of POI objects
        
        Returns:
            Same list with nearest_pano_id filled
        """
        tasks = []
        for poi in pois:
            tasks.append(self.get_nearest_pano_id(poi.lat, poi.lng))
        
        pano_ids = await asyncio.gather(*tasks)
        
        for poi, pano_id in zip(pois, pano_ids):
            poi.nearest_pano_id = pano_id
        
        valid_count = sum(1 for poi in pois if poi.nearest_pano_id)
        print(f"[OK] Enriched {valid_count}/{len(pois)} POIs with panorama IDs")
        
        return [poi for poi in pois if poi.nearest_pano_id]


# Example usage
async def main():
    searcher = POISearcher()
    
    # Search for McDonald's in Barcelona
    pois = await searcher.search_nearby(
        lat=41.4108,
        lng=2.1803,
        poi_type="restaurant",
        keyword="McDonald's"
    )
    
    # Enrich with panorama IDs
    pois = await searcher.enrich_with_pano_ids(pois)
    
    for poi in pois:
        print(f"  {poi.name}: {poi.nearest_pano_id}")


if __name__ == "__main__":
    asyncio.run(main())
