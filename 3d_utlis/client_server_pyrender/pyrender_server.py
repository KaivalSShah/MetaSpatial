#!/usr/bin/env python
import os
import socket
import json
import sys
import time
import numpy as np
import trimesh
import pyrender
from PIL import Image
import math
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Server configuration
HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 65432        # Port to listen on (non-privileged ports are > 1023)

def normalize(v):
    norm = np.linalg.norm(v)
    if norm == 0: 
       return v
    return v / norm

def look_at(eye, target, up):
    """Creates a view matrix (like OpenGL's gluLookAt)"""
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    zaxis = normalize(eye - target)
    xaxis = normalize(np.cross(normalize(up), zaxis))
    yaxis = np.cross(zaxis, xaxis)

    # Create the 4x4 view matrix
    view_matrix = np.identity(4)
    view_matrix[0, 0:3] = xaxis
    view_matrix[1, 0:3] = yaxis
    view_matrix[2, 0:3] = zaxis
    view_matrix[0, 3] = -np.dot(xaxis, eye)
    view_matrix[1, 3] = -np.dot(yaxis, eye)
    view_matrix[2, 3] = -np.dot(zaxis, eye)
    
    return view_matrix

def create_room(width, depth, height):
    tm = trimesh.creation.box([width, depth, height])
    tm.invert()
    return pyrender.Mesh.from_trimesh(tm, smooth=False)

def euler_to_matrix(rotation_degrees):
    """Convert Euler angles (degrees) to a 4x4 rotation matrix (XYZ order)."""
    rx, ry, rz = map(math.radians, rotation_degrees)
    # Using trimesh's convention which seems to match Blender's default XYZ Euler
    return trimesh.transformations.euler_matrix(rx, ry, rz, 'sxyz') # Check rotation order if needed

def create_transform_matrix(position, rotation_degrees, scale_dims, mesh_bounds):
    """Create a 4x4 transformation matrix from position, rotation, and scale."""
    # 1. Scaling
    current_dims = mesh_bounds[1] - mesh_bounds[0] # max - min
    # Avoid division by zero for flat meshes
    current_dims[current_dims == 0] = 1e-6 
    
    scale_factors = np.array([
        scale_dims.get('length', 1.0) / current_dims[0], # X
        scale_dims.get('width', 1.0) / current_dims[1],  # Y
        scale_dims.get('height', 1.0) / current_dims[2] # Z
    ])
    scale_matrix = trimesh.transformations.scale_matrix(scale_factors)
    
    # Apply scale first to the mesh centered at its local origin before rotation/translation
    # Adjust translation to account for mesh center offset *after* scaling
    scaled_center_offset = mesh_bounds[0] * scale_factors 
    initial_offset_matrix = trimesh.transformations.translation_matrix(-mesh_bounds[0])
    scaled_offset_matrix = trimesh.transformations.translation_matrix(scaled_center_offset)


    # 2. Rotation
    rotation_matrix = euler_to_matrix(rotation_degrees)

    # 3. Translation
    translation_matrix = trimesh.transformations.translation_matrix(position)

    # Combine: Translate * Rotate * Scale (relative to world origin)
    # The order is crucial. Scale is applied in local coords first.
    # T * R * Scale * MESH
    # Pyrender Node Pose = T * R * S
    
    # More robust: Apply scaling relative to object center, then rotate, then translate
    center = (mesh_bounds[0] + mesh_bounds[1]) / 2.0
    to_origin = trimesh.transformations.translation_matrix(-center)
    from_origin = trimesh.transformations.translation_matrix(center)
    
    scale_at_center_matrix = from_origin @ trimesh.transformations.scale_matrix(scale_factors) @ to_origin
    
    # Final matrix: T * R * Scale_At_Center
    final_matrix = translation_matrix @ rotation_matrix @ scale_at_center_matrix

    return final_matrix


def process_request(data, room_name):
    """Process a rendering request using Pyrender"""
    start_time = time.time()
    try:
        params = data
        step_number = params.get('step_number', 0) # Default step number
        ground_truth = params.get('ground_truth', False) # Default ground truth
        render_width = params.get('width', 640)
        render_height = params.get('height', 480)

        logging.info(f"Processing request for room: {room_name}, step: {step_number}, ground_truth: {ground_truth}")

        # --- Path Setup ---
        # Assume script is in 3d_utlis/client_server_pyrender
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir)) 
        rooms_folder = os.path.join(project_root, "3d_utlis", "data")
        room_path = os.path.join(rooms_folder, room_name)
        assets_path = os.path.join(room_path, "assets")
        renders_path = os.path.join(room_path, "renders")
        os.makedirs(renders_path, exist_ok=True)
        
        output_dir = renders_path

        # --- Load Scene Graph ---
        scene_graph_file = "scene_graph-backtracked.json" # Add logic for updated if needed based on ground_truth
        scene_graph_path = os.path.join(room_path, scene_graph_file)
        print("scene_graph_path", scene_graph_path)
        if not os.path.exists(scene_graph_path):
            logging.error(f"Scene graph not found at: {scene_graph_path}")
            return json.dumps({"status": "error", "message": "Scene graph not found"})

        with open(scene_graph_path, 'r') as f:
            scene_data = json.load(f)

        # --- Pyrender Scene Setup ---
        logging.info("Setting up Pyrender scene...")
        
        # --- Set up render parameters ---
        radius = 10.0  # Camera distance from center
        
        # Camera target in the middle of the scene
        cam_target = np.array([3.0, 2.0, 1.5])  # Center of the room
        up_vector = np.array([0.0, 0.0, 1.0])  # Z is up
        
        # Function to rescale objects similar to blender_server.py
        def rescale_object(mesh, size_in_meters):
            # Get the current dimensions of the mesh
            bbox_min, bbox_max = mesh.bounds
            dimensions = bbox_max - bbox_min
            
            # Calculate scale factors - handle potential missing dimensions
            scale_factors = np.array([
                size_in_meters.get("length", 1.0) / max(dimensions[0], 0.001),
                size_in_meters.get("width", 1.0) / max(dimensions[1], 0.001),
                size_in_meters.get("height", 1.0) / max(dimensions[2], 0.001)
            ])
            
            # Create scale matrix
            scale_matrix = np.eye(4)
            scale_matrix[0, 0] = scale_factors[0]
            scale_matrix[1, 1] = scale_factors[1]
            scale_matrix[2, 2] = scale_factors[2]
                
            return scale_matrix

        # Store loaded meshes to avoid reloading for each frame
        loaded_meshes = {}
        
        # Process all frames
        for i in range(1):
            # Create a new scene for this frame
            scene = pyrender.Scene(bg_color=[0.1, 0.1, 0.1, 1.0])
            
            # Calculate camera position for this frame
            angle_deg = 0
            angle_rad = np.radians(angle_deg)
            cam_pos = np.array([
                cam_target[0] + radius * np.cos(angle_rad),
                cam_target[1] + radius * np.sin(angle_rad),
                cam_target[2] + 2.0  # Place camera above target
            ])
            
            # Create camera view matrix (LookAt)
            view_matrix = look_at(cam_pos, cam_target, up_vector)
            camera_pose = np.linalg.inv(view_matrix)
            
            # Add camera
            camera = pyrender.PerspectiveCamera(
                yfov=np.radians(40.0),  # ~35mm lens equivalent
                aspectRatio=1.0  # Square aspect ratio (800x800)
            )
            scene.add(camera, pose=camera_pose)
            
            # Add directional light
            light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=5.0)
            # Position it above and behind the camera
            light_position = cam_pos + np.array([0, 0, 2.0])
            light_matrix = look_at(light_position, cam_target, up_vector)
            scene.add(light, pose=np.linalg.inv(light_matrix))
            
            # Add point light in the center of the room
            point_light = pyrender.PointLight(color=[1.0, 1.0, 1.0], intensity=100.0)
            light_pos = np.array([3.0, 2.0, 2.5])
            light_pose = np.eye(4)
            light_pose[:3, 3] = light_pos
            scene.add(point_light, pose=light_pose)
            
            # Add ambient light
            # scene.ambient_light = np.array([0.3, 0.3, 0.3, 1.0])

            logging.info("Loading objects based on scene_graph.json...")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            metaspatial_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
            
            # Construct the base path for this room's assets
            room_assets_path = os.path.join(metaspatial_root, '3d_utlis', 'data', room_name, 'assets')
            logging.info(f"Expecting assets for room '{room_name}' in: {room_assets_path}")
            
            for item in scene_data:
                item_id = item.get("new_object_id")
                if not item_id or item_id in ["south_wall", "north_wall", "east_wall", "west_wall", "middle of the room", "ceiling", "floor"]:
                    logging.debug(f"Skipping non-object item or room geometry: {item_id}")
                    continue
                
                # Construct the expected GLB path
                expected_glb_filename = f"{item_id}.glb"
                absolute_glb_path = os.path.join(room_assets_path, expected_glb_filename)
                absolute_glb_path = absolute_glb_path.replace('\\', '/')
                
                logging.info(f"Processing item: {item_id}, constructed path: {absolute_glb_path}")
                
                if not os.path.exists(absolute_glb_path):
                    logging.warning(f"GLB file not found at constructed path: {absolute_glb_path}")
                    continue  # Skip if file not found
                
                try:
                    # --- Mesh Loading & Caching ---
                    if item_id not in loaded_meshes:
                        logging.info(f"Attempting to load mesh: {absolute_glb_path}")
                        trimesh_scene = trimesh.load(absolute_glb_path, force='scene')
                        logging.info(f"Successfully loaded trimesh scene from: {absolute_glb_path}")
                        
                        mesh_list = list(trimesh_scene.geometry.values())
                        if not mesh_list:
                            logging.warning(f"No geometry found in GLB: {absolute_glb_path}")
                            continue
                        
                        # Combine meshes if multiple exist
                        if len(mesh_list) > 1:
                            logging.info(f"Concatenating {len(mesh_list)} meshes from {item_id}...")
                            try:
                                combined_mesh = trimesh.util.concatenate(mesh_list)
                            except Exception as concat_err:
                                logging.error(f"Error concatenating meshes for {item_id}: {concat_err}")
                                combined_mesh = mesh_list[0]  # Fallback: Use the first mesh
                            logging.info(f"Concatenation complete for {item_id}")
                        else:  # Only one mesh
                            combined_mesh = mesh_list[0]
                        
                        loaded_meshes[item_id] = combined_mesh
                        logging.info(f"Cached mesh for {item_id} (Bounds: {combined_mesh.bounds})")
                    else:
                        logging.info(f"Using cached mesh for {item_id}")
                        combined_mesh = loaded_meshes[item_id]
                    
                    # --- Pyrender Mesh Creation ---
                    logging.info(f"Creating pyrender mesh for {item_id}...")
                    pyrender_mesh = pyrender.Mesh.from_trimesh(combined_mesh, smooth=True)
                    logging.info(f"Pyrender mesh created for {item_id}")
                    
                    # --- Transformations ---
                    # Position: Extract x, y, z from dict, default to 0
                    pos_dict = item.get("position", {})
                    position_vector = [
                        pos_dict.get('x', 0.0),
                        pos_dict.get('y', 0.0),
                        pos_dict.get('z', 0.0)
                    ]
                    
                    # Rotation: Extract z_angle from dict, default to 0
                    # Add PI to match Blender's orientation system
                    rot_dict = item.get("rotation", {})
                    z_angle = rot_dict.get('z_angle', 0.0)
                    rotation_vector_degrees = [0.0, 0.0, z_angle]
                    
                    # Get size_in_meters from the scene graph
                    size_in_meters = item.get("size_in_meters", {"length": 1.0, "width": 1.0, "height": 1.0})
                    
                    logging.info(f"Object {item_id} position: {position_vector}, rotation: {rotation_vector_degrees}, size: {size_in_meters}")
                    
                    # Create transformation matrix (Scale -> Rotate -> Translate)
                    try:
                        # Calculate scale matrix based on actual mesh dimensions vs target dimensions
                        scale_matrix = rescale_object(combined_mesh, size_in_meters)
                        
                        # Create rotation matrix from z-angle
                        rotation_matrix = euler_to_matrix(rotation_vector_degrees)
                        
                        # Create translation matrix from position
                        translation_matrix = trimesh.transformations.translation_matrix(position_vector)
                        
                        # Combine transformations: Scale -> Rotate -> Translate
                        transform_matrix = translation_matrix @ rotation_matrix @ scale_matrix
                        
                        logging.info(f"Created transformation matrix for {item_id}")
                    except Exception as e:
                        logging.error(f"Error creating transformation matrix for {item_id}: {e}")
                        transform_matrix = np.eye(4)  # Fallback identity matrix
                    
                    # --- Add Node to Scene ---
                    logging.info(f"Adding mesh node {item_id} to the scene.")
                    scene.add(pyrender_mesh, pose=transform_matrix)
                    logging.info(f"Mesh node {item_id} added successfully.")
                
                except FileNotFoundError:
                    logging.error(f"GLB file not found error during processing item {item_id} at path: {absolute_glb_path}")
                except Exception as e:
                    logging.error(f"Error processing item {item_id} from {absolute_glb_path}: {e}", exc_info=True)
            
            # Render the scene to an image
            output_file = os.path.join(output_dir, f"pyrender_output_{i}.png")
            r = pyrender.OffscreenRenderer(viewport_width=render_width, viewport_height=render_height)
            color, _ = r.render(scene)
            r.delete()
            
            # Use PIL to save the image
            image = Image.fromarray(color)
            image.save(output_file)
            logging.info(f"Saved render to {output_file}")
            
            # No need to remove nodes as we create a new scene for each frame
        
        end_time = time.time()
        duration = end_time - start_time
        logging.info(f"Request completed in {duration:.2f} seconds")
        
        return json.dumps({"status": "success", "message": f"Rendered {room_name} to {output_file}", "duration": duration})

    except Exception as e:
        logging.error(f"Error processing request: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# --- Main Server Loop ---
def run_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Allow socket reuse
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
            s.listen()
            logging.info(f"Pyrender server listening on {HOST}:{PORT}")

            while True:
                logging.info("Waiting for a connection...")
                conn, addr = s.accept()
                with conn:
                    logging.info(f"Connected by {addr}")
                    data = b""
                    while True:
                        chunk = conn.recv(4096) # Read in chunks
                        if not chunk:
                            break
                        data += chunk
                    
                    if data:
                        logging.info("Received data, processing request...")
                        request_data = json.loads(data.decode('utf-8'))
                        room_name = request_data.get("room_name") # Get room_name
                        if not room_name:
                            logging.error("Request missing 'room_name'")
                            response = json.dumps({"status": "error", "message": "Missing room_name"})
                        else:
                            try:
                                # Pass room_name to process_request
                                response = process_request(request_data, room_name) 
                            except Exception as e:
                                logging.error(f"Error processing request: {e}", exc_info=True)
                                response = json.dumps({"status": "error", "message": str(e)})
                        conn.sendall(response.encode('utf-8'))
                        logging.info("Sent response.")
                    else:
                        logging.warning("Received empty data.")

        except OSError as e:
            logging.error(f"Server failed to start or run: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            logging.info("Server shutting down...")
        finally:
            logging.info("Server stopped.")

if __name__ == "__main__":
    # Add necessary paths for libraries if running directly
    # e.g., if pyrender/trimesh are installed in a venv outside system path
    
    # Check for OSMesa for headless rendering
    # os.environ['PYOPENGL_PLATFORM'] = 'osmesa' 
    # Note: Requires OSMesa library installed on the system
    
    run_server()