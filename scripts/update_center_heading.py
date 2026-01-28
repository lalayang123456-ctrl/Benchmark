"""
Temporary script to update center_heading for all cached panoramas.

This script fetches the centerHeading (north direction offset) for all
panoramas that currently have NULL center_heading values.

Uses parallel processing with ThreadPoolExecutor for faster execution.

Usage:
    python scripts/update_center_heading.py [--dry-run] [--limit N] [--workers W]
"""
import sys
import time
import json
import random
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.cache_manager import cache_manager
from config.settings import settings

# Thread-safe counters
lock = threading.Lock()
progress = {"success": 0, "error": 0, "total": 0}


def get_panos_without_center_heading(limit: int = None):
    """Get all pano_ids that don't have center_heading set."""
    with cache_manager.get_connection() as conn:
        query = '''
            SELECT pano_id FROM metadata 
            WHERE center_heading IS NULL
        '''
        if limit:
            query += f' LIMIT {limit}'
        cursor = conn.execute(query)
        return [row['pano_id'] for row in cursor.fetchall()]


def fetch_center_heading_selenium(pano_id: str, api_key: str) -> float:
    """Fetch centerHeading for a single panorama using Selenium."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    
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
                    const centerHeading = data.tiles ? data.tiles.centerHeading : 0;
                    document.getElementById("result").textContent = JSON.stringify({{
                        centerHeading: centerHeading
                    }});
                }} else {{
                    document.getElementById("result").textContent = "ERROR:" + status;
                }}
            }});
        </script>
    </body>
    </html>
    '''
    
    # Create unique temp file for this thread
    temp_dir = Path(__file__).parent.parent / "temp_images"
    temp_dir.mkdir(exist_ok=True)
    thread_id = threading.current_thread().ident
    temp_html = temp_dir / f"temp_center_heading_{thread_id}.html"
    
    with open(temp_html, "w") as f:
        f.write(html_content)
    
    # Setup Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    
    driver = None
    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        driver.get(f"file:///{temp_html.absolute()}")
        
        # Wait for result
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "result")))
        time.sleep(1.5)
        
        result_text = driver.find_element(By.ID, "result").text
        
        if result_text.startswith("ERROR"):
            return None
        
        data = json.loads(result_text)
        return data.get("centerHeading", 0.0)
        
    finally:
        if driver:
            driver.quit()
        if temp_html.exists():
            temp_html.unlink()


def update_center_heading(pano_id: str, center_heading: float):
    """Update the center_heading for a panorama in the database."""
    with cache_manager.get_connection() as conn:
        conn.execute(
            'UPDATE metadata SET center_heading = ? WHERE pano_id = ?',
            (center_heading, pano_id)
        )


def process_pano(pano_id: str, api_key: str) -> tuple:
    """Process a single panorama. Returns (pano_id, center_heading, error)."""
    try:
        # Add small random delay to avoid rate limiting
        time.sleep(random.uniform(0.1, 0.5))
        
        center_heading = fetch_center_heading_selenium(pano_id, api_key)
        
        if center_heading is not None:
            update_center_heading(pano_id, center_heading)
            return (pano_id, center_heading, None)
        else:
            return (pano_id, None, "Failed to fetch")
            
    except Exception as e:
        return (pano_id, None, str(e))


def main():
    parser = argparse.ArgumentParser(description='Update center_heading for cached panoramas')
    parser.add_argument('--dry-run', action='store_true', help='Only show what would be updated')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of panoramas to update')
    parser.add_argument('--workers', type=int, default=4, help='Number of parallel workers (default: 4)')
    args = parser.parse_args()
    
    api_key = settings.GOOGLE_API_KEY
    if not api_key:
        print("ERROR: No GOOGLE_API_KEY configured in settings")
        return 1
    
    # Get panoramas without center_heading
    pano_ids = get_panos_without_center_heading(args.limit)
    
    if not pano_ids:
        print("All panoramas already have center_heading values!")
        return 0
    
    print(f"Found {len(pano_ids)} panoramas without center_heading")
    print(f"Using {args.workers} parallel workers")
    
    if args.dry_run:
        print("\n[DRY RUN] Would update the following panoramas:")
        for pano_id in pano_ids[:10]:
            print(f"  - {pano_id}")
        if len(pano_ids) > 10:
            print(f"  ... and {len(pano_ids) - 10} more")
        return 0
    
    # Process in parallel
    success_count = 0
    error_count = 0
    start_time = time.time()
    
    print(f"\nStarting parallel update...")
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(process_pano, pano_id, api_key): pano_id 
            for pano_id in pano_ids
        }
        
        # Process results as they complete
        completed = 0
        for future in as_completed(futures):
            completed += 1
            pano_id, center_heading, error = future.result()
            
            if error:
                error_count += 1
                print(f"[{completed}/{len(pano_ids)}] {pano_id}: ERROR - {error}")
            else:
                success_count += 1
                print(f"[{completed}/{len(pano_ids)}] {pano_id}: OK ({center_heading:.1f}°)")
    
    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.1f}s! Updated: {success_count}, Errors: {error_count}")
    print(f"Average: {elapsed/len(pano_ids):.2f}s per panorama")
    
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
