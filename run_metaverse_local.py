#!/usr/bin/env python
# Modified version of metaverse.py for local execution

import os
import json
import sys
import subprocess
import warnings
import time

# Set paths for your local environment
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
ROOMS_FOLDER = os.path.join(PROJECT_ROOT, "3d_utlis", "data")
PLACE_IN_BLENDER_SCRIPT = os.path.join(PROJECT_ROOT, "3d_utlis", "place_in_blender.py")

# Configure OpenAI (but make it optional)
openai_client = None
try:
    from openai import OpenAI
    # api_key = os.environ.get('OPENAI_API_KEY')
    api_key = os.environ.get('OPENAI_API_KEY')
    if api_key:
        print("api key found")
        openai_client = OpenAI(api_key=api_key)
    else:
        warnings.warn("OPENAI_API_KEY not found in environment variables. Skipping OpenAI functionality.")
except ImportError:
    warnings.warn("OpenAI package not found. Skipping OpenAI functionality.")

def run_local_metaverse(room_name, step_number=1, ground_truth="false", fast_mode=False, skip_save=False):
    """
    Run the local version of metaverse_gpt4_reward for a specific room.
    
    Args:
        room_name: Name of the room folder (e.g., "room_97")
        step_number: Step number to process
        ground_truth: Whether to use ground truth or not ("true" or "false")
        fast_mode: Whether to use lower quality settings for faster rendering
        skip_save: Whether to skip saving the blender file
    """
    start_time = time.time()
    try:
        # Check if the room folder exists
        room_path = os.path.join(ROOMS_FOLDER, room_name)
        if not os.path.exists(room_path):
            print(f"Error: Room folder {room_path} does not exist")
            return
            
        # Check if the backtracked JSON file exists
        backtracked_json_path = os.path.join(room_path, "scene_graph-backtracked.json")
        if not os.path.exists(backtracked_json_path):
            print(f"Error: Backtracked JSON file {backtracked_json_path} does not exist")
            return
            
        print(f"Processing room: {room_name}")
        print(f"Using scene graph: {backtracked_json_path}")
        
        # Run place_in_blender.py using the blender Python environment
        # Note: This assumes you have activated the blender conda environment
        blender_cmd = f"python {PLACE_IN_BLENDER_SCRIPT} --room_name {room_name} --step_number {step_number} --ground_truth {ground_truth}"
        
        # Add fast_mode and skip_save if enabled
        if fast_mode:
            blender_cmd += " --fast_mode true"
        if skip_save:
            blender_cmd += " --skip_save true"
            
        print(f"Running: {blender_cmd}")
        
        result = subprocess.run(
            blender_cmd, 
            shell=True, 
            capture_output=True, 
            text=True
        )

        print("BLENDER TIME DELAY OUTPUT")
        print(result.stdout)
        
        if result.returncode != 0:
            print(f"Error running place_in_blender.py: {result.stderr}")
            return
            
        print("Blender processing completed successfully")
        
        # Check for the rendered output
        render_output = os.path.join(room_path, f"render_output_step_{step_number}.png")
        if os.path.exists(render_output):
            print(f"Render output generated: {render_output}")
        else:
            print(f"Warning: Expected render output not found at {render_output}")
            
        end_time = time.time()
        print(f"Total time in run_local_metaverse: {end_time - start_time} seconds")
        
    except Exception as e:
        print(f"Error in run_local_metaverse: {str(e)}")
        
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run local metaverse processing")
    parser.add_argument("--room_name", type=str, required=True, help="Room name to process (e.g., room_97)")
    parser.add_argument("--step_number", type=int, default=1, help="Step number to process")
    parser.add_argument("--ground_truth", type=str, default="false", help="Use ground truth (true/false)")
    parser.add_argument("--fast_mode", action="store_true", help="Use lower quality settings for faster rendering")
    parser.add_argument("--skip_save", action="store_true", help="Skip saving blend file for faster processing")
    
    args = parser.parse_args()
    run_local_metaverse(args.room_name, args.step_number, args.ground_truth, args.fast_mode, args.skip_save)
