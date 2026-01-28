"""
Gemini Agent for VLN Benchmark

This example demonstrates how to use Google's Gemini models (via google-generativeai)
to navigate through Street View panoramas based on natural language instructions.

Requirements:
    pip install google-generativeai requests pillow

Usage:
    1. Set your Google API key as environment variable: GOOGLE_API_KEY
    2. Start the VLN Benchmark server: python main.py
    3. Run this script: python gemini_agent.py
"""

import os
import io
import requests
from typing import Optional
import google.generativeai as genai
from PIL import Image
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class GeminiAgent:
    """Agent that uses Gemini to navigate based on visual observations."""
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.0-flash",
        benchmark_url: str = "http://localhost:8000"
    ):
        # Configure Gemini
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required in environment variables")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        
        self.benchmark_url = benchmark_url
        self.session_id = None
        self.history = []
        
    def create_session(self, task_id: str, agent_id: str = "gemini_agent") -> dict:
        """Create a new evaluation session."""
        response = requests.post(
            f"{self.benchmark_url}/api/session/create",
            json={
                "agent_id": agent_id,
                "task_id": task_id,
                "mode": "agent"  # Use agent mode (perspective view)
            }
        )
        response.raise_for_status()
        data = response.json()
        self.session_id = data["session_id"]
        return data["observation"]
    
    def execute_action(self, action: dict) -> dict:
        """Execute an action and return the result."""
        response = requests.post(
            f"{self.benchmark_url}/api/session/{self.session_id}/action",
            json=action
        )
        response.raise_for_status()
        return response.json()
    
    def get_image_pil(self, image_url: str) -> Image.Image:
        """Download image and return PIL Image."""
        full_url = f"{self.benchmark_url}{image_url}"
        response = requests.get(full_url)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    
    def decide_action(self, observation: dict) -> dict:
        """
        Use Gemini to decide the next action based on the observation.
        """
        task_description = observation["task_description"]
        available_moves = observation["available_moves"]
        # Prefer panorama_url, fallback to current_image
        image_url = observation.get("panorama_url") or observation.get("current_image")
        
        # Get current orientation
        current_heading = observation.get("heading", 0)
        current_pitch = observation.get("pitch", 0)
        current_fov = observation.get("fov", 90)
        
        # Build moves description
        moves_text = "\n".join([
            f"  {m['id']}: {m['direction']}" + (f" ({m['distance']:.1f}m)" if m.get('distance') else "")
            for m in available_moves
        ])
        
        # Build prompt
        prompt = f"""You are a navigation agent exploring Street View.
Task: {task_description}

Current View:
- Heading: {current_heading}° (0=North, 90=East)
- Pitch: {current_pitch}°

Available moves:
{moves_text}

Analyze the image and the task.
1. What do you see?
2. Does the current view show what you need? If not, consider rotating.
3. Does it align with the task description?
4. What action should you take?

Actions:
- Move: {{"action": "move", "move_id": N}} (N is the move ID)
- Rotate: {{"action": "rotation", "heading": H, "pitch": P}} (H=0-360, P=-85 to 85)
- Stop: {{"action": "stop", "answer": "..."}} (if reached destination)

Format your response as a JSON object:
{{
  "thought": "Your reasoning here...",
  "action": "move" or "rotation" or "stop",
  "move_id": N (integer, required if move),
  "heading": H (float, required if rotation),
  "pitch": P (float, required if rotation),
  "answer": "Your answer" (required if stop)
}}
"""
        
        # Prepare content for Gemini
        content = [prompt]
        
        if image_url:
            try:
                image = self.get_image_pil(image_url)
                content.append(image)
            except Exception as e:
                print(f"Failed to load image: {e}")
        
        import time

        # Call Gemini with retry
        max_retries = 5
        retry_delay = 5  # Start with 5 seconds
        
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(content)
                response_text = response.text
                print(f"Gemini response: {response_text}")
                
                # Parse JSON
                import json
                
                # Clean up markdown code blocks if present
                json_str = response_text
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1]
                    
                decision = json.loads(json_str.strip())
                
                action_type = decision.get("action")
                if action_type == "stop":
                    return {"type": "stop", "answer": decision.get("answer", "")}
                elif action_type == "rotation":
                    return {
                        "type": "rotation",
                        "heading": float(decision.get("heading", current_heading)),
                        "pitch": float(decision.get("pitch", current_pitch))
                    }
                else:
                    return {"type": "move", "move_id": int(decision.get("move_id", 1))}
                    
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    if attempt < max_retries - 1:
                        print(f"Rate limit hit (429). Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                
                print(f"Error calling Gemini or parsing: {e}")
                # If not a rate limit error or retries exhausted, fallback
                if attempt == max_retries - 1:
                    break
        
        # Fallback: move forward
        return {"type": "move", "move_id": 1}

    def run(self, task_id: str, max_steps: int = 20) -> dict:
        """Run the agent on a task."""
        print(f"\n{'='*50}")
        print(f"Starting Gemini Agent on task: {task_id}")
        print(f"{'='*50}\n")
        
        # Create session
        try:
            observation = self.create_session(task_id)
        except requests.exceptions.HTTPError as e:
            print(f"Failed to create session: {e}")
            return {"success": False, "error": str(e)}
            
        print(f"Task: {observation['task_description']}")
        print(f"Session ID: {self.session_id}\n")
        
        trajectory = []
        step = 0
        
        while step < max_steps:
            print(f"\n--- Step {step + 1} ---")
            print(f"Available moves: {len(observation['available_moves'])}")
            for m in observation["available_moves"]:
                print(f"  {m['id']}: {m['direction']}")
            
            # Get agent's decision
            action = self.decide_action(observation)
            print(f"Decision: {action}")
            
            trajectory.append({
                "step": step,
                "observation": observation,
                "action": action
            })
            
            # Execute action
            result = self.execute_action(action)
            
            if result["done"]:
                print(f"\n{'='*50}")
                print(f"Task completed!")
                print(f"Reason: {result['done_reason']}")
                print(f"Total steps: {step + 1}")
                print(f"{'='*50}\n")
                
                return {
                    "success": True,
                    "done_reason": result["done_reason"],
                    "total_steps": step + 1,
                    "trajectory": trajectory
                }
            
            observation = result["observation"]
            step += 1
        
        print(f"\nMax steps ({max_steps}) reached!")
        return {
            "success": False,
            "done_reason": "max_steps",
            "total_steps": step,
            "trajectory": trajectory
        }


def main():
    """Example usage."""
    # API Key should be in environment variable GOOGLE_API_KEY
    agent = GeminiAgent()
    
    # Run on default task
    result = agent.run(
        task_id="task_001",
        max_steps=20
    )
    
    print("\nResult:")
    print(f"  Success: {result['success']}")
    print(f"  Reason: {result.get('done_reason')}")
    print(f"  Steps: {result.get('total_steps')}")


if __name__ == "__main__":
    main()
