"""
Parallel VLN Agent Runner

Runs multiple VLN Agents in parallel across different models.
Requirements:
1. Three specific models:
   - claude-sonnet-4-5-20250929-thinking
   - gpt-5-chat-latest
   - gemini-3-pro-preview
2. Each model runs 3 tasks concurrently.
3. Uses shared API configuration.
"""

import os
import sys
import json
import time
import concurrent.futures
from pathlib import Path
from typing import List, Dict
from datetime import datetime

# Add parent directory to path to import vln_agent
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

try:
    from vln_agent import VLNAgent, AgentConfig
except ImportError:
    # Fallback if running from proper package structure
    sys.path.insert(0, str(current_dir.parent))
    from examples.vln_agent import VLNAgent, AgentConfig

# Configuration
MODELS = [
    "claude-sonnet-4-5-20250929-thinking",
    "gpt-5-chat-latest",
    "gemini-3-pro-preview"
]

CONCURRENCY_PER_MODEL = 3

# Define the list of tasks to run
# We'll pick 3 representative tasks for this demonstration
# ideally these should be valid task IDs present in the tasks/ directory
TASK_IDS = [
    "nav_starbucks_20260120_190310_1", 
    "nav_starbucks_20260120_190311_2",
    "nav_starbucks_20260120_190311_3"
]

def run_single_task(model_name: str, task_id: str) -> Dict:
    """Run a single task with a specific model."""
    
    # Create unique agent ID
    timestamp = datetime.now().strftime("%H%M%S")
    agent_id = f"{model_name}_{timestamp}"
    
    print(f"[{model_name}] Starting task: {task_id}")
    
    try:
        # Load config and override model
        config = AgentConfig.from_env()
        config.model_name = model_name
        
        # Create agent
        agent = VLNAgent(config)
        
        # Run task
        result = agent.run(
            task_id=task_id,
            max_steps=30,
            agent_id=agent_id
        )
        
        print(f"[{model_name}] Finished {task_id}: Success={result['success']}")
        
        # Attach model name to result for reporting
        result["model"] = model_name
        result["task_id"] = task_id
        return result
        
    except Exception as e:
        print(f"[{model_name}] Error on {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "model": model_name,
            "task_id": task_id
        }

def run_model_batch(model_name: str, tasks: List[str]) -> List[Dict]:
    """Run a batch of tasks for a specific model with concurrency."""
    print(f"\n--- Starting batch for {model_name} (Concurrency: {CONCURRENCY_PER_MODEL}) ---")
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY_PER_MODEL) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(run_single_task, model_name, task_id): task_id 
            for task_id in tasks
        }
        
        for future in concurrent.futures.as_completed(future_to_task):
            task_id = future_to_task[future]
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                print(f"[{model_name}] Exception in worker: {e}")
                
    return results

def main():
    print(f"Starting Parallel Evaluation")
    print(f"Models: {MODELS}")
    print(f"Tasks: {TASK_IDS}")
    print(f"Concurrency per model: {CONCURRENCY_PER_MODEL}")
    
    start_time = time.time()
    
    # We want to run models in parallel as well
    # So we have: Parallel(Models) -> each doing Parallel(Tasks)
    
    all_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(MODELS)) as executor:
        # Submit the batch run for each model
        # Each model will run the SAME list of tasks (for comparison)
        future_to_model = {
            executor.submit(run_model_batch, model, TASK_IDS): model 
            for model in MODELS
        }
        
        for future in concurrent.futures.as_completed(future_to_model):
            model = future_to_model[future]
            try:
                model_results = future.result()
                all_results.extend(model_results)
                print(f"Model {model} finished all tasks.")
            except Exception as e:
                print(f"Model {model} failed batch: {e}")

    duration = time.time() - start_time
    
    print("\n" + "="*60)
    print(f"EVALUATION COMPLETE ({duration:.1f}s)")
    print("="*60)
    
    # Summary Table
    print(f"{'Model':<40} | {'Task':<35} | {'Success':<8} | {'Steps'}")
    print("-" * 100)
    
    for res in sorted(all_results, key=lambda x: (x['model'], x['task_id'])):
        model = res.get('model', 'unknown')
        task = res.get('task_id', 'unknown')
        success = "YES" if res.get('success') else "NO"
        steps = res.get('total_steps', '-')
        
        print(f"{model:<40} | {task:<35} | {success:<8} | {steps}")

if __name__ == "__main__":
    main()
