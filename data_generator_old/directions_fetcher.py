"""
Directions Fetcher - Google Directions API Integration

Fetches navigation routes and simplifies instructions (removes street names).
"""

import os
import re
import asyncio
import aiohttp
from typing import List, Dict, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class NavigationStep:
    """Represents a single navigation step."""
    instruction: str
    distance_meters: int
    distance_text: str
    duration_seconds: int
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float


@dataclass
class Route:
    """Represents a complete navigation route."""
    steps: List[NavigationStep]
    total_distance_meters: int
    total_duration_seconds: int
    path_coords: List[Tuple[float, float]]  # List of (lat, lng) along route
    
    @property
    def total_distance_text(self) -> str:
        if self.total_distance_meters < 1000:
            return f"{self.total_distance_meters}m"
        return f"{self.total_distance_meters / 1000:.1f}km"
    
    @property
    def total_duration_text(self) -> str:
        minutes = self.total_duration_seconds // 60
        return f"{minutes} min"


class DirectionsFetcher:
    """Fetch navigation directions and simplify instructions."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API Key not found. Set GOOGLE_API_KEY in .env")
    
    async def get_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str = "WALK"
    ) -> Route:
        """
        Get route from Google Routes API (New).
        
        Args:
            origin_lat: Starting latitude
            origin_lng: Starting longitude
            dest_lat: Destination latitude
            dest_lng: Destination longitude
            mode: Travel mode ("WALK", "DRIVE", "BICYCLE", "TRANSIT")
        
        Returns:
            Route object with steps and metadata
        """
        # Routes API v2 endpoint
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.legs.steps.navigationInstruction,routes.legs.steps.distanceMeters,routes.legs.steps.staticDuration,routes.legs.steps.startLocation,routes.legs.steps.endLocation,routes.legs.distanceMeters,routes.legs.duration"
        }
        
        body = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": origin_lat,
                        "longitude": origin_lng
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": dest_lat,
                        "longitude": dest_lng
                    }
                }
            },
            "travelMode": mode,
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": "METRIC"
        }
        
        # Note: routingPreference is only valid for DRIVE mode
        # WALK and BICYCLE modes don't support this parameter
        if mode == "DRIVE":
            body["routingPreference"] = "TRAFFIC_UNAWARE"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as response:
                data = await response.json()
        
        if "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            raise Exception(f"Routes API error: {error_msg}")
        
        if not data.get("routes"):
            raise Exception("No routes found")
        
        # Parse route from new API format
        route_data = data["routes"][0]
        leg = route_data["legs"][0]
        
        # Extract steps
        steps = []
        path_coords = []
        
        for step_data in leg.get("steps", []):
            # Get instruction
            nav_instruction = step_data.get("navigationInstruction", {})
            html_instruction = nav_instruction.get("instructions", "Continue")
            
            # Simplify instruction (remove street names)
            simplified_instruction = self.simplify_instructions(html_instruction)
            
            # Get locations
            start_loc = step_data.get("startLocation", {}).get("latLng", {})
            end_loc = step_data.get("endLocation", {}).get("latLng", {})
            
            # Get distance and duration
            distance_meters = step_data.get("distanceMeters", 0)
            duration_seconds = int(step_data.get("staticDuration", "0s").rstrip('s'))
            
            step = NavigationStep(
                instruction=simplified_instruction,
                distance_meters=distance_meters,
                distance_text=f"{distance_meters}m" if distance_meters < 1000 else f"{distance_meters/1000:.1f}km",
                duration_seconds=duration_seconds,
                start_lat=start_loc.get("latitude", 0),
                start_lng=start_loc.get("longitude", 0),
                end_lat=end_loc.get("latitude", 0),
                end_lng=end_loc.get("longitude", 0)
            )
            steps.append(step)
            
            # Collect path coordinates
            path_coords.append((step.start_lat, step.start_lng))
        
        # Add final destination
        if steps:
            path_coords.append((steps[-1].end_lat, steps[-1].end_lng))
        
        # Get total distance and duration
        total_distance = leg.get("distanceMeters", 0)
        total_duration = int(leg.get("duration", "0s").rstrip('s'))
        
        route = Route(
            steps=steps,
            total_distance_meters=total_distance,
            total_duration_seconds=total_duration,
            path_coords=path_coords
        )
        
        print(f"[OK] Route planned: {route.total_distance_text}, {route.total_duration_text}, {len(steps)} steps")
        return route
    
    def simplify_instructions(self, html_instruction: str) -> str:
        """
        Remove street names from instructions.
        
        Examples:
        - "Turn right onto King Street" → "Turn right"
        - "Walk northeast on Victoria St for 85m" → "Walk northeast for 85m"
        - "At the traffic lights, turn left" → "At the intersection, turn left"
        
        Args:
            html_instruction: HTML instruction from Directions API
        
        Returns:
            Simplified instruction without street names
        """
        # Remove "on <street>"
        instruction = re.sub(r' on <b>.*?</b>', '', html_instruction)
        # Remove "onto <street>"
        instruction = re.sub(r' onto <b>.*?</b>', '', instruction)
        # Replace specific landmarks with generic terms
        instruction = re.sub(r'at the <b>.*?</b>', 'at the intersection', instruction)
        # Remove HTML tags
        instruction = re.sub(r'<.*?>', '', instruction)
        
        return instruction.strip()
    
    def generate_task_description(self, route: Route, target_name: str = "") -> str:
        """
        Generate natural language task description from route.
        
        Args:
            route: Route object
            target_name: Name of the destination (e.g., "McDonald's")
        
        Returns:
            Natural language description string
        """
        if not route.steps:
            return "Navigate to the target location."
        
        # Build description from steps
        parts = []
        
        # Opening
        if target_name:
            parts.append(f"Navigate to the nearby {target_name}.")
        else:
            parts.append("Navigate to the target location.")
        
        # Add simplified steps
        for i, step in enumerate(route.steps):
            if i == 0:
                parts.append(step.instruction)
            else:
                parts.append(f"then {step.instruction.lower()}")
        
        # Closing
        parts.append("Your destination will be ahead.")
        
        return " ".join(parts)


# Example usage
async def main():
    fetcher = DirectionsFetcher()
    
    # Get route from point A to point B in Barcelona
    route = await fetcher.get_route(
        origin_lat=41.4100,
        origin_lng=2.1800,
        dest_lat=41.4120,
        dest_lng=2.1810
    )
    
    print("\nRoute steps:")
    for i, step in enumerate(route.steps, 1):
        print(f"  {i}. {step.instruction} ({step.distance_text})")
    
    print(f"\nTotal: {route.total_distance_text}, {route.total_duration_text}")
    
    # Generate task description
    description = fetcher.generate_task_description(route, "McDonald's")
    print(f"\nTask description:\n{description}")


if __name__ == "__main__":
    asyncio.run(main())
