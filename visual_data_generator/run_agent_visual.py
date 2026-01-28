"""
Run Agent on Visual Tasks (Optimized)

1. Renders the visual path of a task into images (Parallelized).
2. Packages images and sends them to the Cloud Mist (Yunwu) API (Gemini).
3. Saves the standardized task JSON.
"""

import os
import re
import sys
import json
import time
import base64
import requests
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from visual_data_generator.render_visual_paths import render_task

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE_URL = os.getenv("API_BASE_URL", "https://yunwu.ai/v1")
API_KEY = os.getenv("API_KEY")
MODEL_NAME = "gemini-3-pro-preview" 

# Config switch
OVERWRITE_DESCRIPTION = True  # Set to True to overwrite original description with agent's output

def encode_image(image_path):
    """Encode image to base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def parse_agent_response(content: str) -> dict:
    """Parse JSON response from agent."""
    # Attempt to extract JSON block
    try:
        # Find opening and closing braces
        start = content.find('{')
        end = content.rfind('}') + 1
        if start != -1 and end != -1:
            json_str = content[start:end]
            return json.loads(json_str)
    except Exception as e:
        print(f"[!] JSON Parsing Failed: {e}")
        pass
    
    # Fallback structure if parsing fails
    return {
        "concise_description": content,
        "refined_route": "UNKNOWN",
        "verification": "UNKNOWN"
    }

def run_agent_on_task(task_path: Path):
    """
    Full pipeline: Render -> Agent -> Save Standardized Task
    """
    print(f"[*] Processing Task: {task_path.name}")
    total_start_time = time.time()
    
    # Load original task
    with open(task_path, 'r', encoding='utf-8') as f:
        original_task = json.load(f)
    
    target_name = original_task.get("ground_truth", {}).get("target_name", "the destination")
    orig_desc = original_task.get("description", "")
    orig_route = original_task.get("ground_truth", {}).get("route_description", "")

    # 1. Render Images
    output_base = Path(__file__).parent
    print(f"[*] Rendering visual path...")
    
    images_dir = render_task(task_path, output_base)
    
    if not images_dir or not images_dir.exists():
        print(f"[!] Rendering failed for {task_path}")
        return

    # 2. Prepare Payload
    print("[*] Preparing Agent Payload...")
    
    image_files = sorted(list(images_dir.glob("*.jpg")))
    
    if not image_files:
        print("[!] No images generated.")
        return

    messages_content = []
    
    # Enhanced JSON Prompt
    prompt_text = (
        "You are an expert navigation assistant correcting a route description.\n\n"
        "**Context**:\n"
        "- **Input Text**: A \"Theoretical Walking Route\" from a Map API. It is often TOO DETAILED (e.g., includes small turns into driveways/doorways that Street View doesn't cover).\n"
        "- **Input Images**: The \"Actual Path\" traveled in Street View. This is the GROUND TRUTH.\n\n"
        f"**Rough Description**: \"{orig_desc}\"\n"
        f"**Rough Actions**: \"{orig_route}\"\n\n"
        "**Your Task**: Generate a valid JSON response aligning the text to the images.\n\n"
        "1. \"concise_description\": A precise summary (max 3 sentences).\n"
        "- **CRITICAL**: If the text mentions final turns (e.g., 'Turn left 8m, Turn left 25m') but the images show the path stopping on the main road, **DELETE** those steps from your description. Only describe what is visually traversed.\n"
        "- Use visual landmarks for the turns that actually happen.\n\n"
        "2. \"refined_route\": A standard navigation sequence (e.g., \"Head straight -> Turn Left\").\n"
        "- **PRUNING RULE**: Remove any small actions (like 'Turn right 5m') if they are not visible in the images.\n"
        "- **DISTANCE RULE**: For the long segments that matched the visuals, COPY the distance (meters) from the rough description. Do not invent new distances.\n"
        "- Format: \"Action [Distance if known] -> Action ...\"\n\n"
        f"3. \"verification\": \"YES\" if the destination {target_name} is clearly visible in the last image, else \"NO\".\n\n"
        "Do not output any conversational text, only the JSON block."
    )
    
    messages_content.append({
        "type": "text",
        "text": prompt_text
    })

    # Add Images
    for img_path in image_files:
        b64_image = encode_image(img_path)
        messages_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64_image}"
            }
        })

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": messages_content
            }
        ],
        "temperature": 0.2,
        # "response_format": {"type": "json_object"} # Add if supported by API
    }

    # 3. Call API
    print(f"[*] Calling API ({MODEL_NAME})...")
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    start_time = time.time()
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180 
        )
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        print(f"[!] API Request Failed: {e}")
        return

    duration = time.time() - start_time
    print(f"[*] API Call completed in {duration:.1f}s")

    # 4. Standardize Output
    try:
        agent_raw_content = result['choices'][0]['message']['content']
        print("\n--- Agent Response (Raw) ---")
        print(agent_raw_content)
        print("----------------------------\n")
        
        parsed_data = parse_agent_response(agent_raw_content)
        
        # Create new task object
        new_task = original_task.copy()
        
        # Store agent outputs
        new_task["agent_model"] = MODEL_NAME
        new_task["agent_verification"] = parsed_data.get("verification")
        new_task["agent_refined_route"] = parsed_data.get("refined_route")
        new_task["agent_concise_description"] = parsed_data.get("concise_description")

        # Add timing metrics
        new_task["agent_vlm_duration_seconds"] = round(duration, 3)
        total_duration = time.time() - total_start_time
        new_task["agent_total_duration_seconds"] = round(total_duration, 3)
        
        # Overwrite description if flag is True
        if OVERWRITE_DESCRIPTION:
            new_task["description"] = parsed_data.get("concise_description")
        
        # New filename logic
        original_name = task_path.stem
        new_name = original_name.replace("nav_", "visual_nav_", 1)
        if new_name == original_name:
             new_name = f"visual_{original_name}"
        
        tasks_dir = Path(__file__).parent.parent / "tasks"
        output_file = tasks_dir / f"{new_name}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(new_task, f, indent=2, ensure_ascii=False)
            
        print(f"[SUCCESS] Visual Task saved to: {output_file}")
        print(f"            Verification: {new_task['agent_verification']}")
        print(f"            Refined Route: {new_task['agent_refined_route']}")
        print(f"            VLM Duration: {new_task['agent_vlm_duration_seconds']}s")
        print(f"            Total Duration: {new_task['agent_total_duration_seconds']}s")

        # --- Update ORIGINAL Task Description ---
        # User request: "Navigate to {target_name}. {refined_route}"
        refined_route = parsed_data.get("refined_route", "UNKNOWN")
        new_description = f"Navigate to {target_name}. {refined_route}"
        
        print(f"[*] Updating ORIGINAL task description in: {task_path}")
        # We reload or use original_task. We modify original_task directly.
        original_task["description"] = new_description
        
        # Save back to the original source file
        with open(task_path, 'w', encoding='utf-8') as f:
            json.dump(original_task, f, indent=2, ensure_ascii=False)
        print(f"[SUCCESS] Updated original task description to: {new_description}")
        
        return new_task['agent_verification'] == "YES"
        
    except Exception as e:
        print(f"[!] Failed to parse/save result: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run Agent on Visual Tasks")
    parser.add_argument("task_json", type=Path, help="Path to task JSON file")
    
    args = parser.parse_args()
    
    if not args.task_json.exists():
        print(f"Task file not found: {args.task_json}")
        return
        
    success = run_agent_on_task(args.task_json)
    if success:
        print("[*] Verification Successful")
        sys.exit(0)
    else:
        print("[!] Verification Failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
