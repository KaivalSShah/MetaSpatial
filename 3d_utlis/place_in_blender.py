import bpy
import json
import math
import os
import argparse
from distutils.util import strtobool  # parse "true"/"false" to bool
import time
bpy.context.preferences.filepaths.save_version = 0  


parser = argparse.ArgumentParser(description="Process room design data in a given range.")
parser.add_argument("--room_name", type=str, required=True, help="Room name to process")
parser.add_argument("--step_number", type=int, required=True, help="Step number to process")
parser.add_argument("--ground_truth", type=lambda x: bool(strtobool(x)), required=True, help="Ground truth or not")
parser.add_argument("--fast_mode", type=lambda x: bool(strtobool(x)), default=False, help="Enable fast mode with lower quality settings")
parser.add_argument("--skip_save", type=lambda x: bool(strtobool(x)), default=False, help="Skip saving blend file")
args = parser.parse_args()

script_dir = os.path.dirname(os.path.abspath(__file__))
room_path = os.path.join(script_dir, "data", args.room_name)
ground_truth = args.ground_truth
fast_mode = args.fast_mode
skip_save = args.skip_save

print(f"Processing room: {args.room_name}")
print(f"Room path: {room_path}")
print(f"Ground truth: {ground_truth}")
print(f"Fast mode: {fast_mode}")
print(f"Skip save: {skip_save}")

# Track timing
times = {}
def time_function(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        func_name = func.__name__
        execution_time = end_time - start_time
        times[func_name] = execution_time
        print(f"Time for {func_name}: {execution_time:.3f} seconds")
        return result
    return wrapper

@time_function
def import_glb(file_path, object_name):
    bpy.ops.import_scene.gltf(filepath=file_path)
    imported_object = bpy.context.view_layer.objects.active
    if imported_object is not None:
        imported_object.name = object_name

@time_function
def create_room(width, depth, height):
    bpy.ops.mesh.primitive_cube_add(size=1, enter_editmode=False, align='WORLD', location=(width / 2, depth / 2, height / 2))
    bpy.ops.transform.resize(value=(width, depth, height))

    room = bpy.context.active_object

    mat = bpy.data.materials.new(name="TransparentMaterial")
    mat.use_nodes = True  

    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Alpha"].default_value = 0.2  

    mat.blend_method = 'BLEND'

    room.data.materials.append(mat)

@time_function
def find_glb_files(directory):
    glb_files = {}
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".glb"):
                key = file.split(".")[0]
                if key not in glb_files:
                    glb_files[key] = os.path.join(root, file)
    return glb_files

@time_function
def get_highest_parent_objects():
    highest_parent_objects = []

    for obj in bpy.data.objects:
        # Check if the object has no parent
        if obj.parent is None:
            highest_parent_objects.append(obj)
    return highest_parent_objects

@time_function
def delete_empty_objects():
    # Iterate through all objects in the scene
    for obj in bpy.context.scene.objects:
        # Check if the object is empty (has no geometry)
        print(obj.name, obj.type)
        if obj.type == 'EMPTY':
            bpy.context.view_layer.objects.active = obj
            bpy.data.objects.remove(obj)

@time_function
def select_meshes_under_empty(empty_object_name):
    # Get the empty object
    empty_object = bpy.data.objects.get(empty_object_name)
    # print(empty_object is not None)
    if empty_object is not None and empty_object.type == 'EMPTY':
        # Iterate through the children of the empty object
        for child in empty_object.children:
            # Check if the child is a mesh
            if child.type == 'MESH':
                # Select the mesh
                child.select_set(True)
                bpy.context.view_layer.objects.active = child
            else:
                select_meshes_under_empty(child.name)

@time_function
def rescale_object(obj, scale):
    # Ensure the object has a mesh data
    if obj.type == 'MESH':
        bbox_dimensions = obj.dimensions
        scale_factors = (
                         scale["length"] / bbox_dimensions.x, 
                         scale["width"] / bbox_dimensions.y, 
                         scale["height"] / bbox_dimensions.z
                        )
        obj.scale = scale_factors

@time_function
def batch_import_assets(objects_in_room, directory_path, glb_file_paths):
    """Import all GLB assets in a single batch for better performance"""
    # collect all files to import
    print("glb_file_paths", glb_file_paths)
    import_list = []
    for item_id, object_in_room in objects_in_room.items():
        if item_id in glb_file_paths:
            import_list.append((glb_file_paths[item_id], item_id))
        else:
            print(f"Warning: No GLB file found for {item_id}")
    
    # Import all files at once to reduce overhead
    for file_path, object_name in import_list:
        bpy.ops.import_scene.gltf(filepath=file_path)
        imported_object = bpy.context.view_layer.objects.active
        if imported_object is not None:
            imported_object.name = object_name

@time_function
def batch_process_meshes(objects_in_room):
    """Process all mesh objects in batched operations for better performance"""
    # Join meshes under empty parents
    parents = get_highest_parent_objects()
    empty_parents = [parent for parent in parents if parent.type == "EMPTY"]
    
    # First batch: Join meshes
    for empty_parent in empty_parents:
        bpy.ops.object.select_all(action='DESELECT')
        select_meshes_under_empty(empty_parent.name)
        bpy.ops.object.join()
        joined_object = bpy.context.view_layer.objects.active
        if joined_object is not None:
            joined_object.name = empty_parent.name + "-joined"
            joined_object.select_set(False)
    
    # Second batch: Clear parent relationships and reset transforms in one operation
    bpy.ops.object.select_all(action='DESELECT')
    MSH_OBJS = [m for m in bpy.context.scene.objects if m.type == 'MESH']
    for obj in MSH_OBJS:
        obj.select_set(True)
    
    if len(MSH_OBJS) > 0:
        bpy.context.view_layer.objects.active = MSH_OBJS[0]
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        
        # Apply all transforms at once for all selected objects
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    
    # Third batch: Position, rotate and scale objects
    bpy.ops.object.select_all(action='DESELECT')
    
    # Create a mapping of positions, rotations and scales for efficient lookup
    transform_map = {}
    for obj in MSH_OBJS:
        key_variants = [
            obj.name,
            obj.name.replace("-joined", ""),
            obj.name.replace(".001", ""),
            obj.name.replace(".002", ""),
        ]
        key = next((k for k in key_variants if k in objects_in_room), None)
        if key is not None:
            item = objects_in_room[key]
            transform_map[obj.name] = {
                "position": (item["position"]["x"], item["position"]["y"], item["position"]["z"]),
                "rotation": (item["rotation"]["z_angle"] / 180.0) * math.pi + math.pi,
                "size": item["size_in_meters"]
            }
    
    # Apply transforms in batches by type
    for obj in MSH_OBJS:
        if obj.name in transform_map:
            transforms = transform_map[obj.name]
            obj.location = transforms["position"]
            
    # Apply rotations
    for obj in MSH_OBJS:
        if obj.name in transform_map:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.transform.rotate(value=transform_map[obj.name]["rotation"], orient_axis='Z')
    
    # Apply scales
    for obj in MSH_OBJS:
        if obj.name in transform_map and obj.type == 'MESH':
            bbox_dimensions = obj.dimensions
            scale = transform_map[obj.name]["size"]
            scale_factors = (
                scale["length"] / bbox_dimensions.x,
                scale["width"] / bbox_dimensions.y,
                scale["height"] / bbox_dimensions.z
            )
            obj.scale = scale_factors

@time_function
def setup_render():
    """Set up the render settings based on performance mode"""
    scene = bpy.context.scene
    camera = bpy.data.objects.get("Camera")
    
    if camera is None:
        bpy.ops.object.camera_add(location=(2.5, -3, 1.7))
        camera = bpy.context.active_object
        camera.name = "Camera"
        camera.rotation_euler = (math.radians(70), 0, math.radians(45))
    
    camera.data.type = 'PERSP' 
    camera.data.lens = 35  
    camera.data.lens_unit = 'MILLIMETERS'  
    camera.data.shift_x = 0.3 
    camera.data.shift_y = 0.1  
    
    # configurable performance settings
    if fast_mode:
        print("Using fast render settings")
        scene.render.resolution_x = 400
        scene.render.resolution_y = 400
        scene.render.resolution_percentage = 80
        
        # Cycles vs. EEVEE
        if hasattr(scene, 'cycles'):
            print("cycles was chosen")
            scene.cycles.samples = 64
            scene.cycles.max_bounces = 2
            scene.cycles.diffuse_bounces = 1
            scene.cycles.glossy_bounces = 1
            scene.cycles.transparent_max_bounces = 1
            scene.cycles.transmission_bounces = 1
            scene.cycles.volume_bounces = 0
            scene.cycles.use_adaptive_sampling = True
            scene.cycles.adaptive_threshold = 0.1
            
        if hasattr(scene, 'eevee'):
            print("eevee was chose -- more optimized than cycles")
            if hasattr(scene.eevee, 'taa_render_samples'):
                scene.eevee.taa_render_samples = 4
            if hasattr(scene.eevee, 'use_gtao'):
                scene.eevee.use_gtao = False
            if hasattr(scene.eevee, 'use_ssr'):
                scene.eevee.use_ssr = False
            if hasattr(scene.eevee, 'use_bloom'):
                scene.eevee.use_bloom = False
            if hasattr(scene.eevee, 'volumetric_samples'):
                scene.eevee.volumetric_samples = 4
    else:
        # slow render mode
        scene.render.resolution_x = 800
        scene.render.resolution_y = 800
        scene.render.resolution_percentage = 100

    # view_layer = scene.view_layers[0]
    # view_layer.use_pass_ambient_occlusion = False
    # view_layer.use_pass_combined = True  # Keep only the combined pass
    # view_layer.use_pass_diffuse = False
    # view_layer.use_pass_normal = False
    # view_layer.use_pass_z = False

    camera.data.clip_start = 0.1 
    camera.data.clip_end = 100.0
    
    if args.ground_truth:
        scene.render.filepath = os.path.join(room_path, "render_output_groundtruth1.png")
    else:
        scene.render.filepath = os.path.join(room_path, f"render_output_step_{args.step_number}.png")
    
    scene.render.image_settings.file_format = 'PNG'



# RUNNER FUNCTIONS


# Track total execution time
total_start_time = time.time()

# Remove default cube
time_start = time.time()
object_name = 'Cube'
object_to_delete = bpy.data.objects.get(object_name)
if object_to_delete is not None:
    bpy.data.objects.remove(object_to_delete, do_unlink=True)
time_end = time.time()
times["remove_default_cube"] = time_end - time_start

# Load scene data
time_start = time.time()
objects_in_room = {}
file_path = os.path.join(room_path, "scene_graph-backtracked.json")
print(f"Using scene graph file: {file_path}")
with open(file_path, 'r') as file:
    data = json.load(file)
    for item in data:
        if item["new_object_id"] not in ["south_wall", "north_wall", "east_wall", "west_wall", "middle of the room", "ceiling"]:
            objects_in_room[item["new_object_id"]] = item
time_end = time.time()
times["load_json"] = time_end - time_start

# Find GLB files
time_start = time.time()
directory_path = os.path.join(room_path, "assets")
glb_file_paths = find_glb_files(directory_path)
time_end = time.time()
times["find_glb_files"] = time_end - time_start

# Import assets
time_start = time.time()
batch_import_assets(objects_in_room, directory_path, glb_file_paths)
time_end = time.time()
times["import_assets"] = time_end - time_start

# Process meshes
time_start = time.time()
batch_process_meshes(objects_in_room)
time_end = time.time()
times["process_meshes"] = time_end - time_start

# Clean up scene
time_start = time.time()
bpy.ops.object.select_all(action='DESELECT')
delete_empty_objects()
time_end = time.time()
times["delete_empty_objects"] = time_end - time_start

# Create room
time_start = time.time()
create_room(6.0, 4.0, 3)
time_end = time.time()
times["create_room"] = time_end - time_start

# Save file (optional)
if not skip_save:
    time_start = time.time()
    if args.ground_truth:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(room_path, "generated_scene_groundtruth.blend"), check_existing=False)
    else:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(room_path, f"generated_scene_step_{args.step_number}.blend"), check_existing=False)
    time_end = time.time()
    times["save_blend_file"] = time_end - time_start
    print(f"Saved blend file in {times['save_blend_file']:.3f} seconds")

# Setup render and render
time_start = time.time()
setup_render()
print("Rendering now...")
bpy.ops.render.render(write_still=True)
time_end = time.time()
times["rendering"] = time_end - time_start
print(f"Rendering time: {times['rendering']:.3f} seconds")

# Print performance summary
total_time = time.time() - total_start_time
print("\nPerformance summary:")
for operation, operation_time in times.items():
    percentage = (operation_time / total_time) * 100
    print(f"  {operation}: {operation_time:.3f}s ({percentage:.1f}%)")
print(f"Total execution time: {total_time:.3f} seconds")
