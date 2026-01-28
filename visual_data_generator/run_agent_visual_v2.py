"""
Run Agent on Visual Tasks V2 (Parallelized & State Aware)

1. Renders the visual path of a task into images.
2. Packages images and sends them to the Cloud Mist (Yunwu) API (Gemini).
3. Saves a NEW visual task JSON (vis_...) without modifying the original.
4. Tracks processed tasks in `visual_gen_state.json` to allow resuming.

Features:
- Parallel Processing (10 workers)
- State Persistence (Resumable)
- Non-destructive (Does not modify input files)
"""

import os
import sys
import json
import time
import base64
import requests
import argparse
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from visual_data_generator.render_visual_paths import render_task

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE_URL = os.getenv("API_BASE_URL", "https://yunwu.ai/v1")
API_KEY = os.getenv("API_KEY")
MODEL_NAME = "gemini-3-pro-preview" 

# Configuration
MAX_WORKERS = 20
STATE_FILE = Path(__file__).parent / "visual_gen_state.json"
TASKS_DIR = Path(__file__).parent.parent / "tasks"

# Thread-safe lock for state file updates
state_lock = Lock()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "visual_gen_v2.log")
    ]
)
logger = logging.getLogger(__name__)

def load_state():
    """Load the set of processed task filenames."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
            return set()
    return set()

def update_state(processed_filename):
    """Thread-safe update of the processed tasks state."""
    with state_lock:
        current_state = load_state()
        current_state.add(str(processed_filename)) # Store just the name
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(current_state), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to update state file: {e}")

def encode_image(image_path):
    """Encode image to base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def parse_agent_response(content: str) -> dict:
    """Parse JSON response from agent."""
    try:
        start = content.find('{')
        end = content.rfind('}') + 1
        if start != -1 and end != -1:
            json_str = content[start:end]
            return json.loads(json_str)
    except Exception as e:
        logger.error(f"JSON Parsing Failed: {e}")
    
    return {
        "concise_description": content,
        "refined_route": "UNKNOWN",
        "verification": "UNKNOWN"
    }

def process_single_task(task_path: Path):
    """
    Process a single task: Render -> API -> Save NEW file -> Update State
    """
    try:
        task_filename = task_path.name
        logger.info(f"[*] Processing: {task_filename}")
        
        # Load original task
        with open(task_path, 'r', encoding='utf-8') as f:
            original_task = json.load(f)
        
        task_id = original_task.get("task_id", "unknown")
        target_name = original_task.get("ground_truth", {}).get("target_name", "the destination")
        orig_desc = original_task.get("description", "")
        orig_route = original_task.get("ground_truth", {}).get("route_description", "")

        # 1. Render Images
        # output_base = Path(__file__).parent
        # images_dir = render_task(task_path, output_base)
        
        # if not images_dir or not images_dir.exists():
        #     logger.error(f"[!] Rendering failed for {task_filename}")
        #     return False

        # 1. Use pre-rendered images from images/{task_id} directory
        images_dir = Path(__file__).parent / "images" / task_id
        
        if not images_dir.exists():
            logger.error(f"[!] Images directory not found for {task_filename}: {images_dir}")
            return False

        # 2. Prepare Payload
        image_files = sorted(list(images_dir.glob("*.jpg")))
        if not image_files:
            logger.error(f"[!] No images generated for {task_filename}")
            return False

        messages_content = []
        prompt_text = (
            "You are an expert Spatial Intelligence Agent. Your task is to correct noisy navigation data by strictly aligning it with the provided Street View images.\n\n"
            
            "### INPUT CONTEXT\n"
            f"- Target Destination: \"{target_name}\"\n"
            f"- Noisy Map Instructions: \"{orig_route}\"\n"
            f"- Noisy Description: \"{orig_desc}\"\n"
            "- Visual Ground Truth: The provided image sequence representing the ACTUAL path traveled.\n\n"
            
            "### CRITICAL RULES (Source of Truth: IMAGES)\n"
            "1. **Image Priority**: The Map API often includes invisible 'micro-turns' (e.g., turning 5m into a doorway) that simply do not happen in the Street View images. If the text says 'Turn' but the images show the camera stopping on the main road, YOU MUST DELETE THE TURN.\n"
            "2. **Pruning**: Only describe actions visually confirmed in the images. If the path ends on the sidewalk, do not invent a path into the building.\n"
            "3. **Format**: Output MUST be a valid, parsable JSON object with no markdown fencing.\n\n"
            
            "### REQUIRED JSON OUTPUT KEYS\n"
            "{\n"
            "  \"concise_description\": \"(String) A high-quality visual navigation instruction (max 3 sentences). Describe landmarks visible in the images. REMOVE any text steps that contradict the images.\",\n"
            "  \"refined_route\": \"(String) The geometric path sequence based ONLY on images. Use format: 'Action [Distance] -> Action'. Example: 'Head Straight 50m -> Stop'.\",\n"
            "  \"verification\": \"(String) 'YES' if the target destination is clearly identifiable in the final image frame, otherwise 'NO'.\"\n"
            "}"
        )
        
        messages_content.append({"type": "text", "text": prompt_text})

        for img_path in image_files:
            b64_image = encode_image(img_path)
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
            })

        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": messages_content}],
            "temperature": 0.2,
        }

        # 3. Call API
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{API_BASE_URL}/chat/completions",
            headers=headers, 
            json=payload,
            timeout=180
        )
        response.raise_for_status()
        result = response.json()
        
        # 4. Standardize Output & Save
        agent_raw_content = result['choices'][0]['message']['content']
        parsed_data = parse_agent_response(agent_raw_content)
        
        # Construct new filename: vis_{id}_target_{timestamp}.json
        # Format: vis_0800_target_20260124_2155_06.json
        current_time_str = datetime.now().strftime("%Y%m%d_%H%M_%S")
        
        # Extract ID from filename assuming standard format nav_XXXX_...
        # If filename is nav_0800_target_....json, we want to replace the timestamp part too? 
        # User request: "nav @[...] 改成 vis_0800_target_当前的如期以及时间"
        # So we should rebuild the name carefully.
        
        parts = task_filename.split('_')
        # parts example: ['nav', '0800', 'target', '20260124', '1631', '12.json'] (approx)
        
        if len(parts) >= 3:
            # Reconstruct prefix: vis_0800_target
            # We assume parts[1] is the ID.
            new_filename = f"vis_{parts[1]}_target_{current_time_str}.json"
        else:
            # Fallback
            new_filename = f"vis_{task_filename.replace('nav_', '').replace('.json', '')}_{current_time_str}.json"

        new_task = original_task.copy()
        new_task["agent_model"] = MODEL_NAME
        new_task["agent_verification"] = parsed_data.get("verification")
        new_task["agent_refined_route"] = parsed_data.get("refined_route")
        new_task["agent_concise_description"] = parsed_data.get("concise_description")
        
        # Update description in the NEW task only
        new_description = parsed_data.get('concise_description', 'UNKNOWN')
        new_task["description"] = new_description

        output_file = TASKS_DIR / new_filename
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(new_task, f, indent=2, ensure_ascii=False)

        logger.info(f"[SUCCESS] Saved to {output_file} (Verification: {new_task['agent_verification']})")
        
        # Mark as done
        update_state(task_filename)
        return True

    except Exception as e:
        logger.error(f"[!] Error processing {task_path.name}: {e}")
        return False

def main():
    if not TASKS_DIR.exists():
        logger.error(f"Tasks directory not found: {TASKS_DIR}")
        return

    # Get list of all nav tasks
    all_tasks = list(TASKS_DIR.glob("nav_*.json"))
    processed_tasks = load_state()
    
    # Filter tasks
    tasks_to_process = [t for t in all_tasks if t.name not in processed_tasks]
    
    logger.info(f"Found {len(all_tasks)} total tasks.")
    logger.info(f"Skipping {len(processed_tasks)} already processed tasks.")
    logger.info(f"Starting processing for {len(tasks_to_process)} tasks with {MAX_WORKERS} workers...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_task, task_path): task_path for task_path in tasks_to_process}
        
        for future in as_completed(futures):
            task_path = futures[future]
            try:
                success = future.result()
                status = "Completed" if success else "Failed"
                # logger handled in function
            except Exception as e:
                logger.error(f"Worker exception for {task_path.name}: {e}")

    logger.info("All tasks processed.")

if __name__ == "__main__":
    main()
