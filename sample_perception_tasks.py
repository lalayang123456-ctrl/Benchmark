import os
import shutil
import random
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

SOURCE_DIR = 'tasks_perception'
DEST_DIR = 'tasks_perception_1000'
SAMPLE_SIZE = 100

def sample_tasks():
    # 1. Clear destination directory
    if os.path.exists(DEST_DIR):
        logger.info(f"Clearing content of {DEST_DIR}...")
        # Remove all files in the directory
        for filename in os.listdir(DEST_DIR):
            file_path = os.path.join(DEST_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f'Failed to delete {file_path}. Reason: {e}')
    else:
        os.makedirs(DEST_DIR)
        logger.info(f"Created directory: {DEST_DIR}")

    # 2. Get list of all dis and angle tasks
    all_files = os.listdir(SOURCE_DIR)
    dis_tasks = [f for f in all_files if f.startswith('dis_') and f.endswith('.json')]
    angle_tasks = [f for f in all_files if f.startswith('angle_') and f.endswith('.json')]
    
    logger.info(f"Found {len(dis_tasks)} dis tasks and {len(angle_tasks)} angle tasks in source.")

    # 3. Randomly sample
    if len(dis_tasks) < SAMPLE_SIZE:
        logger.warning(f"Not enough dis tasks to sample {SAMPLE_SIZE}. taking all {len(dis_tasks)}.")
        selected_dis = dis_tasks
    else:
        selected_dis = random.sample(dis_tasks, SAMPLE_SIZE)

    if len(angle_tasks) < SAMPLE_SIZE:
        logger.warning(f"Not enough angle tasks to sample {SAMPLE_SIZE}. taking all {len(angle_tasks)}.")
        selected_angle = angle_tasks
    else:
        selected_angle = random.sample(angle_tasks, SAMPLE_SIZE)

    # 4. Copy files
    logger.info(f"Copying {len(selected_dis)} dis tasks...")
    for filename in selected_dis:
        shutil.copy2(os.path.join(SOURCE_DIR, filename), os.path.join(DEST_DIR, filename))

    logger.info(f"Copying {len(selected_angle)} angle tasks...")
    for filename in selected_angle:
        shutil.copy2(os.path.join(SOURCE_DIR, filename), os.path.join(DEST_DIR, filename))

    logger.info("Sampling complete.")
    logger.info(f"Total files in {DEST_DIR}: {len(os.listdir(DEST_DIR))}")

if __name__ == "__main__":
    sample_tasks()
