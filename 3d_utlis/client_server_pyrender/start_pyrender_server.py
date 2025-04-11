#!/usr/bin/env python
"""
Pyrender Server Launcher
This script launches the Pyrender server script.
"""

import subprocess
import os
import sys
import time
import platform

def kill_existing_processes():
    """Kill any existing processes using the server port"""
    try:
        # Try to kill any processes using port 65432
        if platform.system() == "Darwin":  # macOS
            os.system("lsof -i:65432 -t | xargs kill -9 2>/dev/null || true")
        elif platform.system() == "Linux":
            os.system("fuser -k 65432/tcp 2>/dev/null || true")
        elif platform.system() == "Windows":
            os.system("FOR /F \"tokens=5\" %P IN ('netstat -ano | findstr :65432') DO taskkill /F /PID %P 2>NUL")
    except Exception as e:
        print(f"Warning: Error while trying to kill existing processes: {e}")

def start_pyrender_server():
    """Start the Pyrender server script"""
    # First, kill any existing server processes on the port
    kill_existing_processes()
    
    # Get the path to the server script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_script = os.path.join(script_dir, "pyrender_server.py")

    if not os.path.exists(server_script):
        print(f"Error: Server script not found at {server_script}")
        return False

    # Command to run the server script with the current Python interpreter
    cmd = [sys.executable, server_script]
    
    print(f"Starting Pyrender server with command: {' '.join(cmd)}")
    
    # Start the process
    # Use Popen for non-blocking start
    try:
        # Redirect stdout and stderr to DEVNULL if we want it fully backgrounded without console output
        # For debugging, let's keep the output for now
        process = subprocess.Popen(cmd) 
    except Exception as e:
        print(f"Error starting pyrender server: {e}")
        return False
    
    # Give it a moment to start up and potentially fail early
    time.sleep(2)
    
    # Check if the process started successfully
    if process.poll() is None:
        print(f"Pyrender server started successfully (PID: {process.pid})")
        return True
    else:
        print(f"Error: Failed to start Pyrender server. Exit code: {process.poll()}")
        return False

if __name__ == "__main__":
    if start_pyrender_server():
        print("Pyrender server should be running in the background.")
        print("Use pyrender_client.py to send rendering requests.")
    else:
        sys.exit(1)