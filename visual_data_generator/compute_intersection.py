import os

file1_path = r"c:\GitHub\StreetView\VLN_BENCHMARK\visual_data_generator\analysis_result copy.txt"
file2_path = r"c:\GitHub\StreetView\VLN_BENCHMARK\visual_data_generator\analysis_result.txt"

def extract_verified_tasks(file_path):
    tasks = set()
    try:
        encodings = ['utf-16', 'utf-8', 'cp1252']
        content = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeError:
                continue
        
        if content is None:
            print(f"Failed to read {file_path}")
            return set()

        lines = content.splitlines()
        is_in_section = False
        for line in lines:
            line = line.strip()
            if line.startswith("Verified Tasks (YES):"):
                is_in_section = True
                continue
            
            if is_in_section:
                if not line:
                    continue
                if line.startswith("=") or line.endswith(":") or line.startswith("Unknown"):
                    if not line.startswith("- vis_"):
                         is_in_section = False
                         continue

                if line.startswith("- vis_"):
                    # Extraction: remove "- " and any trailing comments
                    # format: "- vis_XXXX_target_....json (optional comment)"
                    parts = line.split()
                    if len(parts) > 1:
                        task = parts[1]
                        tasks.add(task)
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
    return tasks

tasks1 = extract_verified_tasks(file1_path)
tasks2 = extract_verified_tasks(file2_path)

intersection = tasks1.intersection(tasks2)

# Also extract just the task ID (e.g. vis_0001)
def get_id(task_name):
    # Assumes format vis_XXXX_target_...
    parts = task_name.split('_')
    if len(parts) >= 2:
        return f"{parts[0]}_{parts[1]}" # vis_0001
    return task_name

ids1 = {get_id(t) for t in tasks1}
ids2 = {get_id(t) for t in tasks2}
id_intersection = ids1.intersection(ids2)

print(f"File 1 ({os.path.basename(file1_path)}) verified tasks: {len(tasks1)}")
print(f"File 2 ({os.path.basename(file2_path)}) verified tasks: {len(tasks2)}")
print(f"Exact filename intersection count: {len(intersection)}")
print(f"Task ID intersection count: {len(id_intersection)}")
