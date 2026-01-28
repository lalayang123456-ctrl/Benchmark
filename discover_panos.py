"""
Temporary script to discover pano IDs from coordinates.
Finds the pano_id at a given location and explores nearby panoramas via links.

Usage:
    python discover_panos.py

Requires:
    - Google API Key in .env file
    - selenium and webdriver-manager installed
"""

import os
import sys
import json
import time
import random
import requests
from pathlib import Path
from collections import deque
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

# Configuration
API_KEY = "AIzaSyCrPCjmpJ9TT1pLJ5G-AGngabMNwpwSBfs"  # Hardcoded for testing
TARGET_LAT = 52.9497
TARGET_LNG = -1.1906
MAX_PANOS = 10  # Number of panos to collect


def get_pano_from_coords(lat: float, lng: float, api_key: str) -> dict:
    """Get pano_id and metadata from coordinates using Street View Static API."""
    url = "https://maps.googleapis.com/maps/api/streetview/metadata"
    params = {
        "location": f"{lat},{lng}",
        "key": api_key
    }
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "OK":
            return {
                "pano_id": data["pano_id"],
                "lat": data["location"]["lat"],
                "lng": data["location"]["lng"],
                "date": data.get("date", "unknown")
            }
    return None


def get_links_via_selenium(pano_id: str, api_key: str) -> list:
    """Get adjacent panorama links using Selenium and Maps JS API."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    
    # Create HTML page that calls Street View Service
    html_content = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://maps.googleapis.com/maps/api/js?key={api_key}"></script>
    </head>
    <body>
        <div id="result"></div>
        <script>
            const sv = new google.maps.StreetViewService();
            sv.getPanorama({{pano: "{pano_id}"}}, function(data, status) {{
                if (status === "OK") {{
                    const links = data.links || [];
                    const result = links.map(link => ({{
                        panoId: link.pano,
                        heading: link.heading,
                        description: link.description || ""
                    }}));
                    document.getElementById("result").textContent = JSON.stringify(result);
                }} else {{
                    document.getElementById("result").textContent = "ERROR:" + status;
                }}
            }});
        </script>
    </body>
    </html>
    '''
    
    # Write temp HTML file
    temp_html = Path(__file__).parent / "temp_pano_fetch.html"
    with open(temp_html, "w") as f:
        f.write(html_content)
    
    # Setup Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        driver.get(f"file:///{temp_html.absolute()}")
        
        # Wait for result
        wait = WebDriverWait(driver, 10)
        result_elem = wait.until(
            EC.presence_of_element_located((By.ID, "result"))
        )
        
        # Wait a bit more for API call
        time.sleep(2)
        
        result_text = driver.find_element(By.ID, "result").text
        driver.quit()
        
        # Clean up temp file
        temp_html.unlink()
        
        if result_text.startswith("ERROR"):
            print(f"  API Error: {result_text}")
            return []
        
        return json.loads(result_text)
        
    except Exception as e:
        print(f"  Selenium error: {e}")
        if 'driver' in locals():
            driver.quit()
        if temp_html.exists():
            temp_html.unlink()
        return []


def discover_panos(start_lat: float, start_lng: float, max_count: int, api_key: str) -> list:
    """BFS to discover nearby panoramas."""
    print(f"\n=== Discovering panoramas near ({start_lat}, {start_lng}) ===\n")
    
    # Step 1: Get starting pano
    print("Step 1: Finding starting panorama...")
    start_info = get_pano_from_coords(start_lat, start_lng, api_key)
    if not start_info:
        print("ERROR: Could not find panorama at the given coordinates.")
        return []
    
    print(f"  Found: {start_info['pano_id']}")
    print(f"  Location: ({start_info['lat']}, {start_info['lng']})")
    print(f"  Date: {start_info['date']}")
    
    # Step 2: BFS to find nearby panos
    print(f"\nStep 2: Exploring nearby panoramas (target: {max_count})...")
    
    visited = set()
    result = []
    queue = deque([start_info['pano_id']])
    
    while queue and len(result) < max_count:
        pano_id = queue.popleft()
        
        if pano_id in visited:
            continue
        visited.add(pano_id)
        result.append(pano_id)
        
        print(f"  [{len(result)}/{max_count}] Exploring: {pano_id}")
        
        # Get links
        links = get_links_via_selenium(pano_id, api_key)
        print(f"    Found {len(links)} adjacent panoramas")
        
        for link in links:
            link_pano_id = link.get("panoId")
            if link_pano_id and link_pano_id not in visited:
                queue.append(link_pano_id)
        
        # Random delay to avoid rate limiting
        time.sleep(random.uniform(0.5, 1.5))
    
    return result


def update_configs(pano_ids: list, start_pano_id: str):
    """Update task_001.json and geofence_config.json."""
    tasks_dir = Path(__file__).parent / "tasks"
    config_dir = Path(__file__).parent / "config"
    
    # Update task_001.json
    task_file = tasks_dir / "task_001.json"
    task_config = {
        "task_id": "task_001",
        "spawn_point": start_pano_id,
        "spawn_heading": 90,
        "description": "You are on a street in Nottingham. Explore the area and find an interesting landmark.",
        "answer": "",
        "target_pano_ids": [],
        "max_steps": 30,
        "max_time_seconds": 180
    }
    
    with open(task_file, "w") as f:
        json.dump(task_config, f, indent=4)
    print(f"\nUpdated: {task_file}")
    
    # Update geofence_config.json
    geofence_file = config_dir / "geofence_config.json"
    geofence_config = {
        "task_001": pano_ids
    }
    
    with open(geofence_file, "w") as f:
        json.dump(geofence_config, f, indent=4)
    print(f"Updated: {geofence_file}")


def main():
    api_key = API_KEY  # Use hardcoded key for testing
    if not api_key:
        print("ERROR: API_KEY not set.")
        return
    
    # Discover panos
    pano_ids = discover_panos(TARGET_LAT, TARGET_LNG, MAX_PANOS, api_key)
    
    if not pano_ids:
        print("\nNo panoramas found!")
        return
    
    print(f"\n=== Discovered {len(pano_ids)} panoramas ===")
    for i, pano_id in enumerate(pano_ids, 1):
        print(f"  {i}. {pano_id}")
    
    # Update configs
    update_configs(pano_ids, pano_ids[0])
    
    print("\n=== Done! ===")
    print("You can now run the preload API to download these panoramas.")


if __name__ == "__main__":
    main()
