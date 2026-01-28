"""
Directions Fetcher - Google Routes API Integration

Fetches navigation routes and simplifies instructions (removes street names).
"""

import os
import re
import asyncio
import aiohttp
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


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
    path_coords: List[Tuple[float, float]] = field(default_factory=list)
    
    @property
    def total_distance_text(self) -> str:
        if self.total_distance_meters >= 1000:
            return f"{self.total_distance_meters / 1000:.1f} km"
        return f"{self.total_distance_meters} m"
    
    @property
    def total_duration_text(self) -> str:
        minutes = self.total_duration_seconds // 60
        return f"{minutes} min"


class DirectionsFetcher:
    """Fetch navigation directions and simplify instructions."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API key is required. Set GOOGLE_API_KEY environment variable.")
        
        self.max_retries = 3
        self.retry_delay = 2.0  # seconds
    
    async def get_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str = "WALK"
    ) -> Optional[Route]:
        """
        Get route from Google Routes API (New).
        
        Args:
            origin_lat: Starting latitude
            origin_lng: Starting longitude
            dest_lat: Destination latitude
            dest_lng: Destination longitude
            mode: Travel mode (WALK, DRIVE, etc.)
        
        Returns:
            Route object with steps and metadata
        """
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        
        # Use same FieldMask as working old implementation
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.legs.steps.navigationInstruction,routes.legs.steps.distanceMeters,routes.legs.steps.staticDuration,routes.legs.steps.startLocation,routes.legs.steps.endLocation,routes.legs.distanceMeters,routes.legs.duration"
        }
        
        body = {
            "origin": {
                "location": {
                    "latLng": {"latitude": origin_lat, "longitude": origin_lng}
                }
            },
            "destination": {
                "location": {
                    "latLng": {"latitude": dest_lat, "longitude": dest_lng}
                }
            },
            "travelMode": mode,
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": "METRIC"
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=body) as response:
                        if response.status == 200:
                            data = await response.json()
                            return self._parse_routes_response(data)
                        else:
                            error_text = await response.text()
                            logger.warning(f"Routes API error (attempt {attempt + 1}): {response.status} - {error_text}")
            except Exception as e:
                logger.warning(f"Routes API exception (attempt {attempt + 1}): {e}")
            
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)
        
        logger.error(f"Routes API failed after {self.max_retries + 1} attempts")
        return None
    
    def _parse_routes_response(self, data: dict) -> Optional[Route]:
        """Parse Routes API response into Route object."""
        routes = data.get("routes", [])
        if not routes:
            logger.warning("No routes found in response")
            return None
        
        route = routes[0]
        legs = route.get("legs", [])
        if not legs:
            logger.warning("No legs found in route")
            return None
        
        leg = legs[0]
        steps = []
        path_coords = []
        
        for step in leg.get("steps", []):
            nav_instruction = step.get("navigationInstruction", {})
            start_loc = step.get("startLocation", {}).get("latLng", {})
            end_loc = step.get("endLocation", {}).get("latLng", {})
            
            instruction_text = nav_instruction.get("instructions", "Continue")
            # Simplify the instruction (remove street names)
            simplified = self.simplify_instructions(instruction_text)
            
            # Get distance directly as integer (not from localizedValues)
            distance_meters = step.get("distanceMeters", 0)
            
            # Parse duration from "30s" format
            duration_str = step.get("staticDuration", "0s")
            duration_seconds = int(duration_str.rstrip("s")) if duration_str.endswith("s") else 0
            
            # Format distance text
            if distance_meters < 1000:
                distance_text = f"{distance_meters}m"
            else:
                distance_text = f"{distance_meters / 1000:.1f}km"
            
            nav_step = NavigationStep(
                instruction=simplified,
                distance_meters=distance_meters,
                distance_text=distance_text,
                duration_seconds=duration_seconds,
                start_lat=start_loc.get("latitude", 0),
                start_lng=start_loc.get("longitude", 0),
                end_lat=end_loc.get("latitude", 0),
                end_lng=end_loc.get("longitude", 0)
            )
            steps.append(nav_step)
            path_coords.append((nav_step.start_lat, nav_step.start_lng))
        
        # Add final destination
        if steps:
            path_coords.append((steps[-1].end_lat, steps[-1].end_lng))
        
        # Parse total distance and duration
        total_distance = leg.get("distanceMeters", 0)
        duration_str = leg.get("duration", "0s")
        total_duration = int(duration_str.rstrip("s")) if duration_str.endswith("s") else 0
        
        return Route(
            steps=steps,
            total_distance_meters=total_distance,
            total_duration_seconds=total_duration,
            path_coords=path_coords
        )
    
    def _parse_distance(self, distance_text: str) -> int:
        """
        Parse distance text to meters.
        
        Handles formats like:
        - "100 m" -> 100
        - "0.1 km" -> 100
        - "1.5 km" -> 1500
        """
        if not distance_text:
            return 0
        
        try:
            text = distance_text.lower().strip()
            
            if "km" in text:
                # Extract number before "km"
                num_str = text.replace("km", "").replace(",", "").strip()
                return int(float(num_str) * 1000)
            elif "m" in text:
                # Extract number before "m"
                num_str = text.replace("m", "").replace(",", "").strip()
                return int(float(num_str))
            else:
                # Try to parse as plain number
                return int(float(distance_text.replace(",", "")))
        except (ValueError, AttributeError):
            logger.debug(f"Could not parse distance: {distance_text}")
            return 0
    
    def _parse_duration(self, duration_text: str) -> int:
        """
        Parse duration text to seconds.
        
        Handles formats like:
        - "1 min" -> 60
        - "5 mins" -> 300
        - "1 hour 30 mins" -> 5400
        """
        if not duration_text:
            return 0
        
        try:
            text = duration_text.lower().strip()
            total_seconds = 0
            
            # Extract hours
            hour_match = re.search(r'(\d+)\s*hour', text)
            if hour_match:
                total_seconds += int(hour_match.group(1)) * 3600
            
            # Extract minutes
            min_match = re.search(r'(\d+)\s*min', text)
            if min_match:
                total_seconds += int(min_match.group(1)) * 60
            
            # Extract seconds (rare)
            sec_match = re.search(r'(\d+)\s*sec', text)
            if sec_match:
                total_seconds += int(sec_match.group(1))
            
            return total_seconds if total_seconds > 0 else 60  # Default to 1 min
        except (ValueError, AttributeError):
            logger.debug(f"Could not parse duration: {duration_text}")
            return 60  # Default to 1 minute
    
    def simplify_instructions(self, instruction: str) -> str:
        """
        Remove street names from instructions.
        
        Examples:
        - "Turn right onto King Street" → "Turn right"
        - "Walk northeast on Victoria St for 85m" → "Walk northeast for 85m"
        - "Head south on Main Road" → "Head south"
        
        Args:
            instruction: Original instruction text
        
        Returns:
            Simplified instruction without street names
        """
        if not instruction:
            return ""
        
        # Remove HTML tags
        instruction = re.sub(r'<[^>]+>', '', instruction)
        
        # Pattern: "... onto [Street Name]"
        instruction = re.sub(r'\s+onto\s+[\w\s\.\'\-]+$', '', instruction, flags=re.IGNORECASE)
        
        # Pattern: "... on [Street Name]" (but preserve "on the left/right")
        instruction = re.sub(r'\s+on\s+(?!the\s+(left|right))[\w\s\.\'\-]+(?=\s+for|\s*$)', '', instruction, flags=re.IGNORECASE)
        
        # Pattern: "Head [direction] on [Street Name]"
        instruction = re.sub(r'(Head\s+\w+)\s+on\s+[\w\s\.\'\-]+', r'\1', instruction, flags=re.IGNORECASE)
        
        # Pattern: "Continue on [Street Name]"
        instruction = re.sub(r'(Continue)\s+on\s+[\w\s\.\'\-]+', r'\1 straight', instruction, flags=re.IGNORECASE)
        
        # Pattern: "toward [Place Name]"
        instruction = re.sub(r'\s+toward\s+[\w\s\.\'\-]+$', '', instruction, flags=re.IGNORECASE)
        
        # Clean up extra spaces
        instruction = re.sub(r'\s+', ' ', instruction).strip()
        
        return instruction
    
    def generate_task_description(self, route: Route, target_name: str = "") -> str:
        """
        Generate natural language task description from route.
        
        Args:
            route: Route object
            target_name: Name of the destination (e.g., "McDonald's")
        
        Returns:
            Natural language description string
        """
        if not route or not route.steps:
            return f"Navigate to {target_name}." if target_name else "Navigate to the destination."
        
        description_parts = []
        
        # Add target introduction
        if target_name:
            description_parts.append(f"Navigate to {target_name}.")
        else:
            description_parts.append("Navigate to the destination.")
        
        # Add step-by-step instructions
        for i, step in enumerate(route.steps):
            if step.instruction:
                step_desc = step.instruction
                if step.distance_text:
                    step_desc += f" for {step.distance_text}"
                description_parts.append(step_desc + ".")
        
        # Add total distance info
        description_parts.append(f"Total distance: approximately {route.total_distance_text}.")
        
        return " ".join(description_parts)
    
    def generate_exploration_description(
        self,
        target_name: str,
        language: str = "en"
    ) -> str:
        """
        Generate task description for exploration tasks.
        
        Evaluation is position-based: success is determined by whether
        the agent stops at a panorama in target_pano_ids.
        
        Args:
            target_name: Name of the POI to find
            language: Language code ('en' or 'zh')
        
        Returns:
            Exploration task description
        """
        if language == "zh":
            return (
                f"你现在位于一个城市街区中。请在这个区域内自由探索，寻找{target_name}。"
                f"如果找到{target_name}，请走到其门前并停下。"
                f"评判标准：当你主动停止时，你所在的位置是否在目标位置附近。"
            )
        else:
            return (
                f"You are in an urban area. Explore this area to find {target_name}. "
                f"If you find it, walk to the front of {target_name} and stop there. "
                f"Success is determined by whether you stop at the target location."
            )


# Example usage
async def main():
    fetcher = DirectionsFetcher()
    
    # Get route from one point to another
    route = await fetcher.get_route(
        origin_lat=47.5065,
        origin_lng=19.0551,
        dest_lat=47.5080,
        dest_lng=19.0570
    )
    
    if route:
        print(f"Route found: {route.total_distance_text}, {route.total_duration_text}")
        print(f"Steps: {len(route.steps)}")
        for i, step in enumerate(route.steps):
            print(f"  {i + 1}. {step.instruction}")
        
        # Generate task description
        description = fetcher.generate_task_description(route, "McDonald's")
        print(f"\nTask description:\n{description}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
