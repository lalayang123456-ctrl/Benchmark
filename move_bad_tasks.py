import os
import shutil
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

SOURCE_DIR = 'tasks_perception'
DEST_DIR = 'tasks_perception_bad'
THRESHOLD_DISTANCE = 150.0

def move_bad_tasks():
    # Create destination directory if it doesn't exist
    if not os.path.exists(DEST_DIR):
        os.makedirs(DEST_DIR)
        logger.info(f"Created directory: {DEST_DIR}")

    moved_count = 0
    
    # Iterate through files in source directory
    for filename in os.listdir(SOURCE_DIR):
        # Look for dis tasks only
        if filename.startswith('dis_') and filename.endswith('.json'):
            filepath = os.path.join(SOURCE_DIR, filename)
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Check distance condition
                if 'ground_truth' in data and 'distance_between_pois_m' in data['ground_truth']:
                    distance = data['ground_truth']['distance_between_pois_m']
                    
                    if distance > THRESHOLD_DISTANCE:
                        logger.info(f"Found bad task: {filename} (Distance: {distance}m)")
                        
                        # Move dis task
                        shutil.move(filepath, os.path.join(DEST_DIR, filename))
                        moved_count += 1
                        
                        # Identify and move corresponding angle task
                        # Format: dis_XXXX_TIMESTAMP.json -> angle_XXXX_TIMESTAMP.json
                        angle_filename = filename.replace('dis_', 'angle_', 1)
                        angle_filepath = os.path.join(SOURCE_DIR, angle_filename)
                        
                        if os.path.exists(angle_filepath):
                            shutil.move(angle_filepath, os.path.join(DEST_DIR, angle_filename))
                            logger.info(f"  -> Moved corresponding angle task: {angle_filename}")
                            moved_count += 1
                        else:
                            logger.warning(f"  -> Corresponding angle task not found: {angle_filename}")
                            
            except Exception as e:
                logger.error(f"Error processing {filename}: {e}")

    logger.info(f"\nTotal files moved: {moved_count}")

if __name__ == "__main__":
    move_bad_tasks()
