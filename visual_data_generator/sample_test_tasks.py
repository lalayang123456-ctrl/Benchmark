import json
import random
import shutil
from pathlib import Path

def sample_and_copy_tasks():
    tasks_dir = Path(__file__).parent.parent / "tasks"
    output_dir = Path(__file__).parent.parent / "tasks_test"
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    vis_tasks = list(tasks_dir.glob("vis_*.json"))
    verified_tasks = []
    
    print(f"Scanning {len(vis_tasks)} visual tasks...")
    
    # 1. Filter for Verified (YES)
    for task_path in vis_tasks:
        try:
            with open(task_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            verification = data.get("agent_verification", "UNKNOWN")
            if isinstance(verification, str) and verification.upper().strip() == "YES":
                verified_tasks.append(task_path)
                
        except Exception as e:
            print(f"Error reading {task_path.name}: {e}")
            
    print(f"Found {len(verified_tasks)} verified tasks.")
    
    if len(verified_tasks) < 20:
        print(f"Warning: Only {len(verified_tasks)} verified tasks found. Copying all of them.")
        selected_tasks = verified_tasks
    else:
        selected_tasks = random.sample(verified_tasks, 20)
        
    print(f"\nSelected {len(selected_tasks)} tasks for copying:")
    
    copied_count = 0
    
    # 2. Copy Loop
    for vis_path in selected_tasks:
        try:
            # Copy VIS task
            shutil.copy2(vis_path, output_dir / vis_path.name)
            
            # Find corresponding NAV task
            # Pattern: vis_{id}_... -> nav_{id}_...
            # We assume IDs are unique enough or we iterate to find match
            task_id_part = vis_path.name.split('_')[1] # e.g. '0009'
            
            # Search for nav task with this ID
            # nav_{id}_target_...
            nav_candidates = list(tasks_dir.glob(f"nav_{task_id_part}_*.json"))
            
            if not nav_candidates:
                print(f"  [!] Missing NAV task for {vis_path.name} (ID: {task_id_part})")
                continue
                
            # Copy NAV task (take the first match if multiple, usually there's only one active)
            # Or better, match exact timestamp if possible, but nav filename structure might differ slightly?
            # User said "id相对应的nav tasks", so copying the matching ID file is correct.
            nav_path = nav_candidates[0]
            shutil.copy2(nav_path, output_dir / nav_path.name)
            
            print(f"  [OK] Copied {vis_path.name} & {nav_path.name}")
            copied_count += 1
            
        except Exception as e:
            print(f"  [!] Error copying {vis_path.name}: {e}")

    print(f"\nSuccessfully copied {copied_count} pairs to {output_dir}")

if __name__ == "__main__":
    sample_and_copy_tasks()
