import os
from pathlib import Path

def check_missing():
    tasks_dir = Path(__file__).parent.parent / "tasks"
    
    # 1. Get all nav tasks
    nav_files = sorted(list(tasks_dir.glob("nav_*.json")))
    nav_ids = {}
    for f in nav_files:
        # Pattern: nav_{id}_target_...
        try:
            parts = f.name.split('_')
            if len(parts) >= 2:
                task_id = parts[1]
                nav_ids[task_id] = f.name
        except:
            continue

    # 2. Get all vis tasks
    vis_files = sorted(list(tasks_dir.glob("vis_*.json")))
    vis_ids = set()
    for f in vis_files:
        # Pattern: vis_{id}_target_...
        try:
            parts = f.name.split('_')
            if len(parts) >= 2:
                task_id = parts[1]
                vis_ids.add(task_id)
        except:
            continue

    # 3. Find missing
    missing_ids = []
    missing_files = []
    
    for tid, fname in nav_ids.items():
        if tid not in vis_ids:
            missing_ids.append(tid)
            missing_files.append(fname)

    # 4. Report
    print("="*50)
    print(f"MISSING TASKS REPORT")
    print("="*50)
    print(f"Total Nav Tasks: {len(nav_ids)}")
    print(f"Total Vis Tasks: {len(vis_ids)}")
    print(f"Missing Count:   {len(missing_ids)}")
    print("="*50)
    
    if missing_files:
        print("\nMissing Nav Tasks:")
        for f in sorted(missing_files):
            print(f"  - {f}")
    else:
        print("\nAll nav tasks have corresponding vis tasks!")

if __name__ == "__main__":
    check_missing()
