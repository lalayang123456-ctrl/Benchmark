import json
import os
from pathlib import Path

def analyze_verification():
    tasks_dir = Path(__file__).parent.parent / "tasks"
    vis_tasks = list(tasks_dir.glob("vis_*.json"))
    
    yes_tasks = []
    no_tasks = []
    unknown_tasks = []
    
    print(f"Scanning {len(vis_tasks)} visual tasks...")
    
    for task_path in vis_tasks:
        try:
            with open(task_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            verification = data.get("agent_verification", "UNKNOWN")
            
            if isinstance(verification, str):
                verification = verification.upper().strip()
                
            if verification == "YES":
                yes_tasks.append(task_path.name)
            elif verification == "NO":
                no_tasks.append(task_path.name)
            else:
                unknown_tasks.append(f"{task_path.name} ({verification})")
                
        except Exception as e:
            print(f"Error reading {task_path.name}: {e}")

    print("\n" + "="*50)
    print(f"ANALYSIS RESULT")
    print("="*50)
    print(f"Total Visual Tasks: {len(vis_tasks)}")
    print(f"Verified (YES):     {len(yes_tasks)}")
    print(f"Rejected (NO):      {len(no_tasks)}")
    print(f"Unknown/Other:      {len(unknown_tasks)}")
    print("="*50)
    
    print("\nVerified Tasks (YES):")
    for t in sorted(yes_tasks):
        print(f"  - {t}")

    if unknown_tasks:
        print("\nUnknown Status Tasks:")
        for t in sorted(unknown_tasks):
            print(f"  - {t}")

if __name__ == "__main__":
    analyze_verification()
