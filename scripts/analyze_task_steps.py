import os
import json
from collections import defaultdict

def analyze_tasks(tasks_dir):
    verification_yes_count = 0
    steps_data = defaultdict(list)

    # List all files in the directory
    try:
        files = os.listdir(tasks_dir)
    except FileNotFoundError:
        print(f"Error: Directory not found: {tasks_dir}")
        return

    for filename in files:
        if filename.startswith("vis_") and filename.endswith(".json"):
            file_path = os.path.join(tasks_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if data.get("agent_verification") == "YES":
                    verification_yes_count += 1
                    refined_route = data.get("agent_refined_route", "")
                    
                    if refined_route:
                        # Count steps by splitting '->'
                        steps = refined_route.split("->")
                        # Filter out empty strings if any result from split
                        steps = [s.strip() for s in steps if s.strip()]
                        step_count = len(steps)
                        
                        task_id = data.get("task_id", filename) # Use filename as fallback if task_id is missing
                        steps_data[step_count].append(task_id)
                    else:
                        # Handle case where route is empty but verified YES (should typically count as 0 or 1? User example implies arrows separate steps)
                        # If empty, let's assume 0 steps
                        step_count = 0
                        task_id = data.get("task_id", filename)
                        steps_data[step_count].append(task_id)

            except json.JSONDecodeError:
                print(f"Warning: Could not decode {filename}")
            except Exception as e:
                print(f"Warning: Error processing {filename}: {e}")

    # Write results to file
    output_file = os.path.join(tasks_dir, "..", "analysis_result_utf8.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Total tasks with agent_verification='YES': {verification_yes_count}\n")
        
        if verification_yes_count == 0:
            f.write("No tasks found with agent_verification='YES'.\n")
            return

        # Sort by step count
        sorted_steps = sorted(steps_data.keys())

        f.write("\nAnalysis by Step Count:\n")
        f.write("-" * 30 + "\n")
        
        for count in sorted_steps:
            tasks = steps_data[count]
            num_tasks = len(tasks)
            percentage = (num_tasks / verification_yes_count) * 100
            
            f.write(f"Steps: {count}\n")
            f.write(f"Count: {num_tasks}\n")
            f.write(f"Percentage: {percentage:.2f}%\n")
            f.write(f"Task IDs: {tasks}\n")
            f.write("-" * 30 + "\n")
            
    print(f"Analysis written to {output_file}")

if __name__ == "__main__":
    tasks_directory = r"c:\GitHub\StreetView\VLN_BENCHMARK\tasks"
    analyze_tasks(tasks_directory)
