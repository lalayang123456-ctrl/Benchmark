import os
import logging
import aiohttp
import asyncio
from typing import Optional, Dict, List
from dotenv import load_dotenv
from .config import SOLAR_API_BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)

class GroundTruthFetcher:
    """
    Fetches ground truth building data using Google Maps Solar API and Elevation API.
    Calculates building height by subtracting Ground Elevation from Roof Elevation (ASL).
    """
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API Key is required")
            
    async def fetch_building_data(self, lat: float, lng: float) -> Optional[Dict]:
        """
        Fetch building insights and calculate height.
        
        Args:
            lat: Latitude
            lng: Longitude
            
        Returns:
            Dictionary with building data or None.
            {
                "lat": float, 
                "lng": float,
                "height_meters": float,
                "floors_estimated": int,
                "date": str,
                "name": str
            }
        """
        async with aiohttp.ClientSession() as session:
            # 1. Solar API Request
            solar_url = SOLAR_API_BASE_URL
            solar_params = {
                "location.latitude": lat,
                "location.longitude": lng,
                "requiredQuality": "HIGH",
                "key": self.api_key
            }
            
            # 2. Elevation API Request
            elev_url = "https://maps.googleapis.com/maps/api/elevation/json"
            elev_params = {
                "locations": f"{lat},{lng}",
                "key": self.api_key
            }
            
            try:
                # Execute in parallel
                solar_resp_task = session.get(solar_url, params=solar_params)
                elev_resp_task = session.get(elev_url, params=elev_params)
                
                solar_resp, elev_resp = await asyncio.gather(solar_resp_task, elev_resp_task)
                
                # Process Solar Data
                if solar_resp.status != 200:
                    text = await solar_resp.text()
                    if "NOT_FOUND" not in text: # Common if no building
                        logger.warning(f"Solar API Error {solar_resp.status}: {text}")
                    return None
                    
                solar_data = await solar_resp.json()
                
                # Check for roof segments
                solar_potential = solar_data.get("solarPotential", {})
                roof_segments = solar_potential.get("roofSegmentStats", [])
                
                if not roof_segments:
                    return None
                    
                # Find max roof height (ASL)
                # Some segments might not have height, check docs.
                # Assuming 'planeHeightAtCenterMeters' exists.
                max_roof_asl = -9999.0
                has_height = False
                
                for segment in roof_segments:
                    h = segment.get("planeHeightAtCenterMeters")
                    if h is not None:
                        max_roof_asl = max(max_roof_asl, h)
                        has_height = True
                
                if not has_height:
                    logger.warning("No planeHeightAtCenterMeters in roof segments")
                    return None
                
                # Process Elevation Data
                ground_elev = 0.0
                if elev_resp.status == 200:
                    elev_data = await elev_resp.json()
                    if elev_data.get("status") == "OK" and elev_data.get("results"):
                        ground_elev = elev_data["results"][0]["elevation"]
                    else:
                        logger.warning(f"Elevation API error: {elev_data}")
                        # Fallback? If we assume relatively flat, maybe 0? 
                        # No, ASL is absolute. If we miss elevation, height is wrong.
                        return None
                else:
                    return None
                
                # Calculate Height
                height_meters = max_roof_asl - ground_elev
                
                # Sanity check
                if height_meters < 2.0 or height_meters > 1000.0:
                    logger.warning(f"Calculated height {height_meters}m seems invalid (Roof: {max_roof_asl}, Ground: {ground_elev})")
                    return None

                # Extract other metadata
                center = solar_data.get("center", {})
                imagery_date = solar_data.get("imageryDate", {})
                date_str = ""
                if imagery_date:
                    date_str = f"{imagery_date.get('year')}-{imagery_date.get('month'):02d}-{imagery_date.get('day'):02d}"
                
                # Estimate floors (approx 3.5m / floor)
                floors = max(1, int(height_meters / 3.5))
                
                return {
                    "lat": center.get("latitude", lat),
                    "lng": center.get("longitude", lng),
                    "height_meters": round(height_meters, 2),
                    "floors_estimated": floors,
                    "date": date_str,
                    "name": solar_data.get("name", "building"),
                    "ground_elevation": ground_elev,
                    "roof_elevation": max_roof_asl
                }
                
            except Exception as e:
                logger.error(f"GroundTruthFetcher Error: {e}")
                return None
