import os
import logging
import aiohttp
from typing import Optional, Dict
from dotenv import load_dotenv
from .config import SOLAR_API_BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)

class GroundTruthFetcher:
    """
    Fetches ground truth building data using Google Maps Solar API.
    """
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API Key is required")
            
    async def fetch_building_data(self, lat: float, lng: float) -> Optional[Dict]:
        """
        Fetch building insights for a specific location.
        
        Args:
            lat: Latitude
            lng: Longitude
            
        Returns:
            Dictionary with building data or None if no building found/error.
            Structure:
            {
                "lat": float,
                "lng": float,
                "height_meters": float, # Max height
                "segment_heights": list, # Heights of different roof segments
                "date": str, # Imagery date YYYY-MM-DD
                "name": str, # Resource name
                "confidence": str # e.g. HIGH
            }
        """
        params = {
            "location.latitude": lat,
            "location.longitude": lng,
            "requiredQuality": "HIGH",
            "key": self.api_key
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                # Solar API: buildingInsights:findClosest
                async with session.get(SOLAR_API_BASE_URL, params=params) as response:
                    if response.status != 200:
                        logger.warning(f"Solar API Error {response.status}: {await response.text()}")
                        return None
                        
                    data = await response.json()
                    
                    # Extract relevant fields
                    # Response format: https://developers.google.com/maps/documentation/solar/building-insights
                    
                    if "name" not in data:
                        return None
                        
                    center = data.get("center", {})
                    imagery_date = data.get("imageryDate", {})
                    
                    # Date formatting
                    date_str = ""
                    if imagery_date:
                        date_str = f"{imagery_date.get('year')}-{imagery_date.get('month'):02d}-{imagery_date.get('day'):02d}"
                    
                    # Height Logic
                    # Solar API doesn't give a single "height" field directly in the root.
                    # It gives 'boundingBox' (lat/lng/z) or assumes you use the DSM.
                    # BUT checking documentation: 
                    # "Solar API data layers" -> DSM (Digital Surface Model).
                    # 'buildingInsights' returns 'boundingBox' which has sw and ne with elevation?
                    # No, actually 'buildingInsights' returns summary.
                    
                    # Correction: buildingInsights returns 'solarPotential', 'center', 'boundingBox', 'imageryDate', 'postalCode', etc.
                    # It DOES NOT explicitly return "Height in Meters" as a top level attribute in the JSON based on standard overview.
                    # Wait, looking at documentation deeply:
                    # The Solar API is primarily for solar potential. 
                    # However, "Open Buildings" has height.
                    # User requested Solar API -> buildingInsights.
                    # Let me check if I can derive height or if I made a mistake in the plan assuming Solar API gives direct height.
                    
                    # Re-reading Plan/Knowledge:
                    # Google Maps Platform Solar API -> BuildingInsights
                    # Returns `boundingBox`.
                    # Does it return height?
                    # "The Building Insights endpoint returns the bounding box, center, and date."
                    # It also returns `solarPotential` -> `roofSegmentStats` -> `pitchDegrees`, `azimuthDegrees`, `boundingBox` of segment.
                    # It does NOT appear to provide "Height from ground" explicitly in simple JSON.
                    # The "Open Buildings" dataset (csv/tif) definitely has it.
                    
                    # NOTE: If Solar API doesn't give height, I might need to use 2.5D Dataset CSV logic OR
                    # assume the user *knows* it does.
                    # "Google Maps Platform Solar API" -> "BuildingInsights" -> Contains "administrativeArea", "statisticalArea", "solarPotential".
                    # `solarPotential` contains `maxArrayPanelsCount`, etc.
                    
                    # Actually, there is `data_layers` endpoint which returns GeoTIFFs (DSM).
                    # DSM = Digital Surface Model (Elevation).
                    # DSM - DEM (Terrain) = Height.
                    # But that requires downloading GeoTIFFs for every request!
                    
                    # Alternative: The user mentioned "Google Open Buildings 2.5D Temporal Dataset" as PRIMARY.
                    # And Solar API as SECONDARY.
                    # IF Solar API `buildingInsights` doesn't give height, I should probably fallback to a strategy where I mock it for now OR warn the user.
                    
                    # Let's look at the `2.5D dataset` option again.
                    # User picked "Solar API".
                    # Let's assume I need to get height.
                    # Maybe I can use the `boundingBox`?
                    # BoundingBox struct: `sw`: {lat, lng}, `ne`: {lat, lng}. No Z.
                    
                    # Wait, look at `solarPotential` -> `roofSegmentStats`.
                    # Maybe `planeHeightAtCenterMeters`? (Hypothetical field, checking docs...)
                    # Docs: `stats` -> `areaMeters2`, `sunshineQuantiles`...
                    
                    # If I cannot get height from Solar API simple JSON, I might be in trouble for "Simple API" approach.
                    # BUT, there used to be a `height` field in some Google Building data.
                    # Let's look at what `requests` content says.
                    # User said: "如果需要实时 API 调用，Google Maps Platform 的 Solar API ... 适合用来交叉验证"
                    # User believes it has it.
                    
                    # Let's implement it such that:
                    # If the JSON contains `height`, use it.
                    # If not, maybe use `roofSegmentStats` to averaging? (No)
                    
                    # ACTUALLY: Google Earth API / Solar API might return `buildingCulling` in `dataLayers`. 
                    # But `buildingInsights` is what was requested.
                    
                    # Strategic Decision:
                    # I will implement the fetcher to get `buildingInsights`. 
                    # I will log the response. 
                    # I will ADDITIONALLY try to infer from `solarPotential` if possible, OR
                    # I will put a PLACEHOLDER 10.0 meters if missing, and add a TODO.
                    # OR, I can use the "Google Geocoding API" or "Places API"? No, they don't have height.
                    
                    # Let's trust the user or my memory that there might be height data or I can calculate it?
                    # No, Solar API is for Solar.
                    # Open Buildings 2.5D is for Height.
                    
                    # Let's implement the code to extract `imageryDate` and `center`.
                    # For height, I will try to find a field.
                    # If not found, I will return `None` (Building valid but no height?) -> Then I can't generate task.
                    
                    # Wait, looking at `solarPotential` -> `wholeRoofStats` -> ???
                    # Okay, I will implement it to allow injecting height if I can't find it, 
                    # OR maybe the user has a modified API or access.
                    # I will extract `name` and `center` at least.
                    
                    # Let's verify `buildingInsights` response structure via search if possible?
                    # "Google Solar API buildingInsights response fields"
                    
                    pass 

        """
        pass
