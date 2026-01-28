"""
GPT-4V Agent for VLN Benchmark

This example demonstrates how to use OpenAI's GPT-4V (Vision) model
to navigate through Street View panoramas based on natural language instructions.

Requirements:
    pip install openai requests

Usage:
    1. Set your OpenAI API key as environment variable: OPENAI_API_KEY
    2. Start the VLN Benchmark server: python main.py
    3. Run this script: python gpt4v_agent.py
"""

import os
import base64
import requests
from typing import Optional
from openai import OpenAI


class GPT4VAgent:
    """Agent that uses GPT-4V to navigate based on visual observations."""
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        benchmark_url: str = "http://localhost:8000"
    ):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.benchmark_url = benchmark_url
        self.session_id = None
        self.history = []
        
    def create_session(self, task_id: str, agent_id: str = "gpt4v_agent") -> dict:
        """Create a new evaluation session."""
        response = requests.post(
            f"{self.benchmark_url}/api/session/create",
            json={
                "agent_id": agent_id,
                "task_id": task_id,
                # Use 'human' mode to get panorama_url (full 360° panorama)
                # GPT-4V can understand panoramic images well
                "mode": "human"
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
    
    def get_image_base64(self, image_url: str) -> str:
        """Download image and convert to base64."""
        full_url = f"{self.benchmark_url}{image_url}"
        response = requests.get(full_url)
        response.raise_for_status()
        return base64.b64encode(response.content).decode("utf-8")
    
    def decide_action(self, observation: dict) -> dict:
        """
        Use GPT-4V to decide the next action based on the observation.
        
        Returns:
            Action dict: {"type": "move", "move_id": N} or {"type": "stop", "answer": "..."}
        """
        task_description = observation["task_description"]
        available_moves = observation["available_moves"]
        # Prefer panorama_url (full 360° image from human mode), fallback to current_image
        image_url = observation.get("panorama_url") or observation.get("current_image")
        
        # Build moves description
        moves_text = "\n".join([
            f"  {m['id']}: {m['direction']}" + (f" ({m['distance']:.1f}m)" if m.get('distance') else "")
            for m in available_moves
        ])
        
        # Build prompt
        system_prompt = """You are a navigation agent exploring Street View. Your task is to follow the navigation instructions and reach the destination.

Based on the current view and available moves, decide your next action:
- To move: respond with JSON {"action": "move", "move_id": N} where N is the move number
- To stop (when you believe you've reached the destination): respond with JSON {"action": "stop", "answer": "brief description of where you are"}

Think step by step:
1. What do you see in the current view?
2. What does the task ask you to find/do?
3. Which direction aligns best with the task?

Respond ONLY with valid JSON, no other text."""

        user_prompt = f"""Task: {task_description}

Available moves:
{moves_text}

Based on the current view, which action should I take?"""

        # Build messages
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add conversation history (last 3 turns for context)
        for h in self.history[-3:]:
            messages.append({"role": "user", "content": h["user"]})
            messages.append({"role": "assistant", "content": h["assistant"]})
        
        # Add current observation with image
        if image_url:
            image_base64 = self.get_image_base64(image_url)
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "high"
                        }
                    }
                ]
            })
        else:
            messages.append({"role": "user", "content": user_prompt})
        
        # Call GPT-4V
        response = self.client.chat.completions.create(
            model="gpt-4o",  # or "gpt-4-vision-preview"
            messages=messages,
            max_tokens=200,
            temperature=0.3
        )
        
        assistant_message = response.choices[0].message.content.strip()
        print(f"GPT-4V response: {assistant_message}")
        
        # Parse response
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = assistant_message
            if "```" in json_str:
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            
            import json
            decision = json.loads(json_str.strip())
            
            # Store in history
            self.history.append({
                "user": user_prompt,
                "assistant": assistant_message
            })
            
            # Convert to action format
            if decision.get("action") == "stop":
                return {"type": "stop", "answer": decision.get("answer", "")}
            else:
                return {"type": "move", "move_id": decision.get("move_id", 1)}
                
        except Exception as e:
            print(f"Failed to parse response: {e}")
            # Default: move forward (first option)
            return {"type": "move", "move_id": 1}
    
    def run(self, task_id: str, max_steps: int = 20) -> dict:
        """
        Run the agent on a task.
        
        Returns:
            Result dict with success status and trajectory
        """
        print(f"\n{'='*50}")
        print(f"Starting GPT-4V Agent on task: {task_id}")
        print(f"{'='*50}\n")
        
        # Create session
        observation = self.create_session(task_id)
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
    # API Key (for testing)
    API_KEY = "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"
    
    # Create agent
    agent = GPT4VAgent(api_key=API_KEY)
    
    # Run on a task
    result = agent.run(
        task_id="task_001",
        max_steps=20
    )
    
    print("\nResult:")
    print(f"  Success: {result['success']}")
    print(f"  Reason: {result['done_reason']}")
    print(f"  Steps: {result['total_steps']}")


if __name__ == "__main__":
    main()
