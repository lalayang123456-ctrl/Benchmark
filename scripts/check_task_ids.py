import json
from pathlib import Path

tasks_dir = Path("c:/GitHub/StreetView/VLN_BENCHMARK/tasks")
mismatches = []
vis_files_count = 0
vis_with_nav_id_count = 0

print(f"Scanning {tasks_dir}...")

for task_file in tasks_dir.glob("*.json"):
    try:
        with open(task_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            task_id = data.get('task_id')
            
            if task_file.name.startswith("vis_"):
                vis_files_count += 1
                if task_id and task_id.startswith("nav_"):
                    vis_with_nav_id_count += 1
                    
            if task_id and task_id != task_file.stem:
                mismatches.append(f"{task_file.name} -> {task_id}")
                
    except Exception as e:
        print(f"Error reading {task_file.name}: {e}")

print(f"Total vis files: {vis_files_count}")
print(f"Vis files with nav_ ID: {vis_with_nav_id_count}")
print(f"Total ID/Filename mismatches: {len(mismatches)}")
print("\nFirst 10 mismatches:")
for m in mismatches[:10]:
    print(m)
