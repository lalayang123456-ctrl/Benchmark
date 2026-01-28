"""
Render Visual Paths (Optimized)

Reads a task JSON, downloads panoramas for the visual_path,
and renders perspective views for each step using PARALLEL PROCESSING.
"""
import os
import sys
import json
import shutil
import logging
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.image_stitcher import image_stitcher
from engine.observation_generator import get_observation_generator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Max workers for parallel rendering
MAX_WORKERS = 20 

def process_step(step_data):
    """
    Process a single step: Download -> Render -> Save.
    
    Args:
        step_data: Dictionary containing:
            - step: The step object from visual_path
            - output_dir: The target directory for images
            - task_id: Task ID for session context
            
    Returns:
        Result string or error message
    """
    step = step_data['step']
    images_dir = step_data['output_dir']
    task_id = step_data['task_id']
    
    step_index = step.get('step_index')
    pano_id = step.get('pano_id')
    heading = step.get('heading')
    
    if pano_id is None or heading is None:
        return f"[!] Invalid data for step {step_index}"

    # Naming convention: step_001.jpg
    dst_filename = f"step_{step_index:03d}.jpg" 
    dst_path = images_dir / dst_filename
    
    # Skip if already exists
    if dst_path.exists():
        return f"[Skipped] Step {step_index}: Already exists"

    zoom_level = 2
    
    try:
        # 1. Ensure Pano is Downloaded (Stitched)
        # Note: image_stitcher should be thread-safe for reading/checking cache
        pano_path = image_stitcher.download_and_stitch(pano_id, zoom_level)
        
        if not pano_path:
            return f"[!] Step {step_index}: Failed to download/stitch pano {pano_id}"

        # 2. Render Perspective View
        # ObservationGenerator is CPU bound mostly, but ThreadPool is used 
        # because image_stitcher involves I/O.
        obs_gen = get_observation_generator()
        result = obs_gen.generate_observation(
            pano_id=pano_id,
            heading=heading,
            pitch=0,
            zoom=zoom_level,
            session_id=task_id,
            step=step_index
        )
        
        if not result or not result.get('image_path'):
            return f"[!] Step {step_index}: Failed to render view"

        # 3. Copy/Move to Task specific folder
        src_path = Path(result['image_path'])
        shutil.copy2(src_path, dst_path)
        
        return f"[OK] Step {step_index}: {dst_filename}"
        
    except Exception as e:
        return f"[!] Step {step_index}: Exception {str(e)}"


def render_task(task_file: Path, output_base: Path):
    """
    Render visual path for a single task using parallel workers.
    """
    try:
        with open(task_file, 'r', encoding='utf-8') as f:
            task = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load {task_file}: {e}")
        return

    visual_path = task.get('visual_path')
    if not visual_path:
        logger.debug(f"Skipping {task.get('task_id', 'unknown')}: No visual_path found")
        return

    task_id = task.get('task_id', 'unknown')
    logger.info(f"Processing task: {task_id} with {MAX_WORKERS} workers")

    # Create output directories
    images_dir = output_base / "images" / task_id
    images_dir.mkdir(parents=True, exist_ok=True)

    # Prepare work items
    work_items = []
    for step in visual_path:
        work_items.append({
            'step': step,
            'output_dir': images_dir,
            'task_id': task_id
        })
    
    # Execute in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_step, item) for item in work_items]
        
        for future in as_completed(futures):
            result = future.result()
            # Log the result
            if "[!]" in result:
                logger.error(f"  {result}")
            elif "[Skipped]" in result:
                logger.debug(f"  {result}") # Debug level for skips to reduce noise
            else:
                logger.info(f"  {result}")

    logger.info(f"  [Done] Saved images to {images_dir}")
    return images_dir


def main():
    parser = argparse.ArgumentParser(description="Render visual paths from task JSONs.")
    parser.add_argument("task_files", nargs="+", type=Path, help="Task JSON files")
    parser.add_argument("--output", "-o", type=Path, default=Path("visual_tasks_output"), help="Output directory")
    
    args = parser.parse_args()
    
    for task_file in args.task_files:
        if task_file.exists():
            render_task(task_file, args.output)
        else:
            logger.warning(f"File not found: {task_file}")

if __name__ == "__main__":
    main()
