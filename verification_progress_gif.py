import os
from typing import Dict, Any, List, Tuple, Optional, Union
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# --- Configuration ---
# Stage names
STAGE_NAMES = {
    'stage1': 'Sponsor',
    'stage2': 'SystemOwner',
    'stage3': 'AccountAdmin',
    'stage4': 'ISSO'
}

# Status colors
COLORS = {
    'default': (255, 255, 255),  # White
    'waiting': (255, 224, 130),  # Yellow
    'validated': (130, 224, 170), # Green
    'denied': (255, 130, 130)     # Red
}
LINE_COLOR = (100, 100, 100)
TEXT_COLOR = (0, 0, 0)
BACKGROUND_COLOR = (240, 240, 240)

# Image dimensions
IMG_WIDTH = 600
IMG_HEIGHT = 400
CIRCLE_RADIUS = 25
LINE_WIDTH = 5  # Thickened connector / rectangle lines

# Animation settings
FRAME_DURATION = 500  # milliseconds per frame
OUTPUT_FILENAME = 'verification_process.gif'
MOVEMENT_STEPS = 30            # Increased interpolation steps for slower movement
MOVEMENT_FRAME_DURATION = 120  # ms per movement frame
STATIC_FRAME_DURATION = 700    # ms for static status frames
TURTLE_Y_OFFSET = -CIRCLE_RADIUS  # raise turtle path so it doesn't cover endpoint color

# --- Drawing Functions ---

def get_font(size=16):
    """Attempts to load a default font, falling back to a basic one."""
    try:
        return ImageFont.truetype("arial.ttf", size)
    except IOError:
        print("Arial font not found. Using default font.")
        return ImageFont.load_default()

def draw_stage(draw, position, color, text):
    """Draws a single verification stage (circle and text)."""
    x, y = position
    # Draw the circle outline
    draw.ellipse(
        (x - CIRCLE_RADIUS, y - CIRCLE_RADIUS, x + CIRCLE_RADIUS, y + CIRCLE_RADIUS),
        fill=color,
        outline=LINE_COLOR,
        width=2
    )
    # Draw the text below the circle
    font = get_font()
    text_width, text_height = draw.textbbox((0,0), text, font=font)[2:]
    draw.text((x - text_width / 2, y + CIRCLE_RADIUS + 5), text, fill=TEXT_COLOR, font=font)

def draw_turtle(draw, position, turtle_image=None, base_image=None):
    """Draws a simple turtle shape or image at a given position.

    Avoids direct use of draw.im (which is an internal ImagingCore object without a public
    Pillow Image API like .mode) by accepting the base PIL Image explicitly. This prevents
    AttributeError: 'ImagingCore' object has no attribute 'mode'.
    """
    x, y = position

    if turtle_image:
        # Resize and ensure RGBA for transparency mask
        turtle_size = (30, 30)
        resized_turtle = turtle_image.resize(turtle_size, Image.Resampling.LANCZOS)
        if resized_turtle.mode != "RGBA":
            resized_turtle = resized_turtle.convert("RGBA")

        paste_x = x - turtle_size[0] // 2
        paste_y = y - turtle_size[1] // 2

        # Determine the image to paste onto
        if base_image is None:
            # Try to retrieve a real Image object from the draw object (fallback logic)
            candidate = getattr(draw, "_image", None)
            if isinstance(candidate, Image.Image):
                base_image = candidate
            else:
                raise ValueError("base_image not provided and underlying image could not be determined.")

        # Paste using alpha channel as mask (works even if base is RGB)
        base_image.paste(resized_turtle, (paste_x, paste_y), resized_turtle)
    else:
        # Fallback simple turtle (circle + head)
        body_radius = 10
        draw.ellipse(
            (x - body_radius, y - body_radius, x + body_radius, y + body_radius),
            fill=(0, 0, 255),
            outline=TEXT_COLOR
        )
        head_radius = 5
        draw.ellipse(
            (x + body_radius, y - head_radius, x + body_radius + head_radius*2, y + head_radius),
            fill=(0, 0, 255),
            outline=TEXT_COLOR
        )

_CACHED_TURTLE = None

def _load_turtle_image():
    """Loads the turtle image once and converts white / near-white background & halo to transparent.

    Strategy:
      1. Classify a pixel as background if:
         - Average brightness > BRIGHT_THRESH (e.g. 200)
         - AND max-min channel difference (color variance) < VARIANCE_THRESH (i.e. close to gray/white)
      2. For very bright pixels (avg > HI_THRESH) => alpha = 0 (fully transparent)
      3. For moderately bright pixels (between BRIGHT & HI) => scale alpha proportionally to preserve anti-aliased edges.

    This avoids a solid white rectangle and reduces jagged edges when pasting over lines.
    """
    global _CACHED_TURTLE
    if _CACHED_TURTLE is not None:
        return _CACHED_TURTLE
    path = './images/turtle.png'
    if not os.path.exists(path):
        return None  # Fallback handled by draw_turtle
    img = Image.open(path).convert('RGBA')
    pixels = img.load()

    BRIGHT_THRESH = 200      # start fading after this
    HI_THRESH = 235          # fully transparent after this
    VARIANCE_THRESH = 22     # how close channels must be to treat as white-ish

    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            mx = max(r, g, b)
            mn = min(r, g, b)
            avg = (r + g + b) / 3
            if avg >= BRIGHT_THRESH and (mx - mn) <= VARIANCE_THRESH:
                if avg >= HI_THRESH:
                    a_new = 0
                else:
                    # Linear fade between BRIGHT_THRESH -> HI_THRESH
                    fade = (avg - BRIGHT_THRESH) / (HI_THRESH - BRIGHT_THRESH)
                    a_new = int(a * (1 - fade))
                pixels[x, y] = (r, g, b, a_new)

    _CACHED_TURTLE = img
    return _CACHED_TURTLE


def draw_frame_with_turtle(statuses, turtle_position=None, draw_endpoint=True, show_turtle=True):
    """
    Generates a single frame of the animation based on the current statuses of all stages.

    Args:
        statuses (dict): A dictionary with keys 'stage1' through 'stage4' and 'endpoint',
                         and values representing their current status ('default', 'waiting', etc.).
        turtle_position (tuple, optional): The (x, y) coordinates to draw the turtle.
                                           Defaults to None, in which case the turtle is not drawn.
        draw_endpoint (bool): Whether to draw and color the endpoint in this frame.
    """
    img = Image.new('RGB', (IMG_WIDTH, IMG_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    font = get_font()

    # --- Define positions for all elements ---
    start_pos = (50, IMG_HEIGHT // 2)
    stage1_pos = (150, IMG_HEIGHT // 2)
    stage2_pos = (300, IMG_HEIGHT // 2 - 100)
    stage3_pos = (300, IMG_HEIGHT // 2)
    stage4_pos = (300, IMG_HEIGHT // 2 + 100)
    end_pos = (500, IMG_HEIGHT // 2)

    # --- Draw connecting lines ---
    # Line from start to stage 1
    draw.line([start_pos, stage1_pos], fill=LINE_COLOR, width=LINE_WIDTH)

    # Calculate rectangle bounding box for parallel stages
    # Determine the maximum text width for the parallel stages
    max_text_width = 0
    for stage_name in ['stage2', 'stage3', 'stage4']:
        text_width, text_height = draw.textbbox((0,0), STAGE_NAMES[stage_name], font=font)[2:]
        max_text_width = max(max_text_width, text_width)

    # Adjust rectangle width based on maximum text width and circle radius
    rect_padding = 20 # Padding around circles and text
    vertical_shift = CIRCLE_RADIUS // 2  # Move whole rectangle downward
    min_x = min(stage2_pos[0], stage3_pos[0], stage4_pos[0]) - max_text_width/2 - rect_padding
    max_x = max(stage2_pos[0], stage3_pos[0], stage4_pos[0]) + max_text_width/2 + rect_padding
    min_y = (min(stage2_pos[1], stage3_pos[1], stage4_pos[1]) - CIRCLE_RADIUS - 40) + vertical_shift
    max_y = (max(stage2_pos[1], stage3_pos[1], stage4_pos[1]) + CIRCLE_RADIUS + 20) + vertical_shift
    rectangle_bbox = (min_x, min_y, max_x, max_y)
    # Use the pipeline (stage) center y for straight horizontal connectors, not rectangle midpoint
    pipeline_y = stage1_pos[1]


    # Draw rectangle around parallel stages
    draw.rectangle(rectangle_bbox, outline=LINE_COLOR, width=LINE_WIDTH)

    # Line from stage 1 to the rectangle (connect at rectangle mid height)
    draw.line([stage1_pos, (min_x, pipeline_y)], fill=LINE_COLOR, width=LINE_WIDTH)

    # Line from the rectangle to endpoint
    draw.line([(max_x, pipeline_y), end_pos], fill=LINE_COLOR, width=LINE_WIDTH)


    # --- Draw all points and stages ---
    # Start point
    draw.ellipse(
        (start_pos[0] - 10, start_pos[1] - 10, start_pos[0] + 10, start_pos[1] + 10),
        fill=COLORS['validated'],
        outline=LINE_COLOR
    )
    draw.text((start_pos[0] - 10, start_pos[1] + 15), "Start", fill=TEXT_COLOR, font=font)

    # Stages
    draw_stage(draw, stage1_pos, COLORS[statuses['stage1']], STAGE_NAMES['stage1'])
    draw_stage(draw, stage2_pos, COLORS[statuses['stage2']], STAGE_NAMES['stage2'])
    draw_stage(draw, stage3_pos, COLORS[statuses['stage3']], STAGE_NAMES['stage3'])
    draw_stage(draw, stage4_pos, COLORS[statuses['stage4']], STAGE_NAMES['stage4'])

    # End point
    if draw_endpoint:
        # --- Determine endpoint status and color ---
        parallel_stages_statuses = [statuses['stage2'], statuses['stage3'], statuses['stage4']]
        if any(s=='denied' for s in parallel_stages_statuses):
            endpoint_status = 'denied'
            endpoint_text = 'Denied'
        elif all(s == 'validated' for s in parallel_stages_statuses):
            endpoint_status = 'validated'
            endpoint_text = 'Approved'
        else:
             endpoint_status = 'waiting'
             endpoint_text = 'Processing'

        statuses['endpoint'] = endpoint_status

        draw.ellipse(
            (end_pos[0] - 15, end_pos[1] - 15, end_pos[0] + 15, end_pos[1] + 15),
            fill=COLORS[statuses['endpoint']],
            outline=LINE_COLOR
        )
        draw.text((end_pos[0] - 8, end_pos[1] + 20), endpoint_text, fill=TEXT_COLOR, font=font)
    else:
         # Draw endpoint outline only if not drawing the colored endpoint
         draw.ellipse(
            (end_pos[0] - 15, end_pos[1] - 15, end_pos[0] + 15, end_pos[1] + 15),
            fill=COLORS['default'], # Use default color for outline only
            outline=LINE_COLOR
        )
         draw.text((end_pos[0] - 8, end_pos[1] + 20), 'Processing', fill=TEXT_COLOR, font=font)

    # --- Draw the turtle if position is provided ---
    TURTLE_IMAGE = _load_turtle_image()
    # Debug (optional): print(f"Loaded turtle image size={TURTLE_IMAGE.size} mode={TURTLE_IMAGE.mode}")
    if show_turtle and turtle_position:
        #print(f"turtle_position: {turtle_position}")
        draw_turtle(draw, turtle_position, turtle_image=TURTLE_IMAGE, base_image=img)


    return img

def draw_frame(statuses, draw_endpoint=True):
    """
    Generates a single frame of the animation based on the current statuses of all stages.

    Args:
        statuses (dict): A dictionary with keys 'stage1' through 'stage4' and 'endpoint',
                         and values representing their current status ('default', 'waiting', etc.).
        draw_endpoint (bool): Whether to draw and color the endpoint in this frame.
    """
    img = Image.new('RGB', (IMG_WIDTH, IMG_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    font = get_font()

    # --- Define positions for all elements ---
    start_pos = (50, IMG_HEIGHT // 2)
    stage1_pos = (150, IMG_HEIGHT // 2)
    stage2_pos = (300, IMG_HEIGHT // 2 - 100)
    stage3_pos = (300, IMG_HEIGHT // 2)
    stage4_pos = (300, IMG_HEIGHT // 2 + 100)
    end_pos = (500, IMG_HEIGHT // 2)

    # --- Draw connecting lines ---
    # Line from start to stage 1
    draw.line([start_pos, stage1_pos], fill=LINE_COLOR, width=LINE_WIDTH)

    # Calculate rectangle bounding box for parallel stages
    # Determine the maximum text width for the parallel stages
    max_text_width = 0
    for stage_name in ['stage2', 'stage3', 'stage4']:
        text_width, text_height = draw.textbbox((0,0), STAGE_NAMES[stage_name], font=font)[2:]
        max_text_width = max(max_text_width, text_width)

    # Adjust rectangle width based on maximum text width and circle radius
    rect_padding = 20 # Padding around circles and text
    vertical_shift = CIRCLE_RADIUS // 2  # Move whole rectangle downward
    min_x = min(stage2_pos[0], stage3_pos[0], stage4_pos[0]) - max_text_width/2 - rect_padding
    max_x = max(stage2_pos[0], stage3_pos[0], stage4_pos[0]) + max_text_width/2 + rect_padding
    min_y = (min(stage2_pos[1], stage3_pos[1], stage4_pos[1]) - CIRCLE_RADIUS - 40) + vertical_shift
    max_y = (max(stage2_pos[1], stage3_pos[1], stage4_pos[1]) + CIRCLE_RADIUS + 20) + vertical_shift
    rectangle_bbox = (min_x, min_y, max_x, max_y)
    pipeline_y = stage1_pos[1]


    # Draw rectangle around parallel stages
    draw.rectangle(rectangle_bbox, outline=LINE_COLOR, width=LINE_WIDTH)

    # Line from stage 1 to the rectangle (connect at rectangle mid height)
    draw.line([stage1_pos, (min_x, pipeline_y)], fill=LINE_COLOR, width=LINE_WIDTH)

    # Line from the rectangle to endpoint
    draw.line([(max_x, pipeline_y), end_pos], fill=LINE_COLOR, width=LINE_WIDTH)


    # --- Draw all points and stages ---
    # Start point
    draw.ellipse(
        (start_pos[0] - 10, start_pos[1] - 10, start_pos[0] + 10, start_pos[1] + 10),
        fill=COLORS['validated'],
        outline=LINE_COLOR
    )
    draw.text((start_pos[0] - 10, start_pos[1] + 15), "Start", fill=TEXT_COLOR, font=font)

    # Stages
    draw_stage(draw, stage1_pos, COLORS[statuses['stage1']], STAGE_NAMES['stage1'])
    draw_stage(draw, stage2_pos, COLORS[statuses['stage2']], STAGE_NAMES['stage2'])
    draw_stage(draw, stage3_pos, COLORS[statuses['stage3']], STAGE_NAMES['stage3'])
    draw_stage(draw, stage4_pos, COLORS[statuses['stage4']], STAGE_NAMES['stage4'])

    # End point
    if draw_endpoint:
        # --- Determine endpoint status and color ---
        parallel_stages_statuses = [statuses['stage2'], statuses['stage3'], statuses['stage4']]
        if any(s=='denied' for s in parallel_stages_statuses):
            endpoint_status = 'denied'
            endpoint_text = 'Denied'
        elif all(s == 'validated' for s in parallel_stages_statuses):
            endpoint_status = 'validated'
            endpoint_text = 'Approved'
        else:
             endpoint_status = 'waiting'
             endpoint_text = 'Processing'

        statuses['endpoint'] = endpoint_status

        draw.ellipse(
            (end_pos[0] - 15, end_pos[1] - 15, end_pos[0] + 15, end_pos[1] + 15),
            fill=COLORS[statuses['endpoint']],
            outline=LINE_COLOR
        )
        draw.text((end_pos[0] - 8, end_pos[1] + 20), endpoint_text, fill=TEXT_COLOR, font=font)
    else:
         # Draw endpoint outline only if not drawing the colored endpoint
         draw.ellipse(
            (end_pos[0] - 15, end_pos[1] - 15, end_pos[0] + 15, end_pos[1] + 15),
            fill=COLORS['default'], # Use default color for outline only
            outline=LINE_COLOR
        )
         draw.text((end_pos[0] - 8, end_pos[1] + 20), 'Processing', fill=TEXT_COLOR, font=font)


    return img

# --- Helper path resolution ---
def _resolve_output_paths(requested_name: Optional[str]) -> Tuple[str, str]:
    """Resolve a requested output filename to a filesystem path and a URL path.

    Rules:
      - If name starts with '/images/' or 'images/', store in the project 'images' directory
        and use '/images/<fname>' as the URL.
      - Bare filename (no directory) -> store in project 'images' directory.
      - Any other relative path: create its directory relative to project root and return
        a URL of just the basename (caller can override if needed).

    Returns (fs_path, url_path).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    images_dir = os.path.join(base_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    if not requested_name:
        fname = OUTPUT_FILENAME
        fs_path = os.path.join(images_dir, fname)
        return fs_path, f"/images/{fname}"

    norm = requested_name.replace('\\', '/').lstrip('.')  # normalize slashes

    if norm.startswith('/images/'):
        fname = norm.split('/images/', 1)[1]
        fs_path = os.path.join(images_dir, fname)
        os.makedirs(os.path.dirname(fs_path), exist_ok=True)
        return fs_path, f"/images/{fname}"
    if norm.startswith('images/'):
        fname = norm.split('images/', 1)[1]
        fs_path = os.path.join(images_dir, fname)
        os.makedirs(os.path.dirname(fs_path), exist_ok=True)
        return fs_path, f"/images/{fname}"

    # If it's just a filename (no dir component), put inside images
    if '/' not in norm:
        fs_path = os.path.join(images_dir, norm)
        return fs_path, f"/images/{norm}"

    # General relative path: create dirs relative to project root
    fs_path = os.path.join(base_dir, norm)
    os.makedirs(os.path.dirname(fs_path), exist_ok=True)
    return fs_path, '/' + norm.lstrip('/')

# --- Main Animation Logic ---
def generate_animation_scenario(scenario_steps, output_filename: Optional[str]=None):
    """Generates a GIF based on a provided scenario."""
    frames = []
    current_statuses = {
        'stage1': 'default',
        'stage2': 'default',
        'stage3': 'default',
        'stage4': 'default',
        'endpoint': 'default'
    }

    # Initial state (without colored endpoint)
    frames.append(draw_frame(current_statuses.copy(), draw_endpoint=False))

    # Process each step in the scenario
    for step in scenario_steps:
        stage_to_update, new_status = step
        current_statuses[stage_to_update] = new_status
        # Draw frame without colored endpoint until all steps are processed
        frames.append(draw_frame(current_statuses.copy(), draw_endpoint=False))

    # Add a final frame with the colored endpoint after all stages are updated
    frames.append(draw_frame(current_statuses.copy(), draw_endpoint=True))


    fs_path, url_path = _resolve_output_paths(output_filename or OUTPUT_FILENAME)
    # Save the frames as a GIF (filesystem path)
    frames[0].save(
        fs_path,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION,
        loop=0  # 0 means loop forever
    )
    print(f"Animated GIF saved as '{fs_path}' (url: {url_path})")
    print(f"File path: {os.path.abspath(fs_path)}")
    return url_path

# --- Main Animation Logic ---
def generate_animation_scenario_with_turtle(scenario_steps, show_turtle=True, output_filename: Optional[str]=None):
    """Generates a GIF based on ordered scenario steps (stage, status).

    Movement path: start -> stage1 -> center (rectangle) -> end.
    If show_turtle is False, falls back to non-turtle animation.

    Args:
        scenario_steps (List[Tuple[str,str]]): ordered updates.
        show_turtle (bool): whether to render turtle.
        output_filename (str|None): override output filename.
    """
    frames = []
    current_statuses = {
        'stage1': 'default',
        'stage2': 'default',
        'stage3': 'default',
        'stage4': 'default',
        'endpoint': 'default'
    }

    # Define positions (re-defined for clarity and accessibility in this function)
    global IMG_HEIGHT # Declare IMG_HEIGHT as global to access it
    start_pos = (50, IMG_HEIGHT // 2)
    stage1_pos = (150, IMG_HEIGHT // 2)
    stage2_pos = (300, IMG_HEIGHT // 2 - 100)
    stage3_pos = (300, IMG_HEIGHT // 2)
    stage4_pos = (300, IMG_HEIGHT // 2 + 100)
    end_pos = (500, IMG_HEIGHT // 2)

    # Map stage names to their positions
    stage_positions = {
        'start': start_pos,
        'stage1': stage1_pos,
        'stage2': stage2_pos,
        'stage3': stage3_pos,
        'stage4': stage4_pos,
        'end': end_pos
    }

    # Define turtle movement anchor positions with vertical offset applied
    turtle_start_pos = (start_pos[0], start_pos[1] + TURTLE_Y_OFFSET)
    turtle_stage1_pos = (stage1_pos[0], stage1_pos[1] + TURTLE_Y_OFFSET)
    turtle_center_pos = (stage3_pos[0], stage3_pos[1] + TURTLE_Y_OFFSET)  # center of rectangle
    turtle_end_pos = (end_pos[0], end_pos[1] + TURTLE_Y_OFFSET)

    # Initial turtle position
    turtle_pos = turtle_start_pos

    # Number of intermediate steps for movement animation
    num_movement_frames = MOVEMENT_STEPS

    if not show_turtle:
        # Simple path without turtle
        return generate_animation_scenario(scenario_steps, output_filename=output_filename)

    # Initial state (with turtle at start, without colored endpoint)
    frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=turtle_pos, draw_endpoint=False, show_turtle=show_turtle))
    frame_durations = [STATIC_FRAME_DURATION]

    moved_to_stage1 = False
    moved_to_center = False

    center_pos = turtle_center_pos  # adjusted center position

    for (stage_to_update, new_status) in scenario_steps:
        current_statuses[stage_to_update] = new_status

        # Movement decisions
        if not moved_to_stage1 and current_statuses['stage1'] != 'default':
            # Move start -> stage1
            start_x, start_y = turtle_start_pos
            end_x, end_y = turtle_stage1_pos
            for i in range(1, num_movement_frames + 1):
                interp_x = start_x + (end_x - start_x) * i / num_movement_frames
                interp_y = start_y + (end_y - start_y) * i / num_movement_frames
                frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=(int(interp_x), int(interp_y)), draw_endpoint=False, show_turtle=show_turtle))
                frame_durations.append(MOVEMENT_FRAME_DURATION)
            turtle_pos = turtle_stage1_pos
            moved_to_stage1 = True
            frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=turtle_pos, draw_endpoint=False, show_turtle=show_turtle))
            frame_durations.append(STATIC_FRAME_DURATION)

        # Any parallel stage update triggers move to center (once)
        if moved_to_stage1 and not moved_to_center and stage_to_update in ('stage2','stage3','stage4'):
            start_x, start_y = turtle_pos
            end_x, end_y = center_pos
            for i in range(1, num_movement_frames + 1):
                interp_x = start_x + (end_x - start_x) * i / num_movement_frames
                interp_y = start_y + (end_y - start_y) * i / num_movement_frames
                frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=(int(interp_x), int(interp_y)), draw_endpoint=False, show_turtle=show_turtle))
                frame_durations.append(MOVEMENT_FRAME_DURATION)
            turtle_pos = center_pos
            moved_to_center = True
            frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=turtle_pos, draw_endpoint=False, show_turtle=show_turtle))
            frame_durations.append(STATIC_FRAME_DURATION)

        # Add a status-only frame (no movement) for other updates
    frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=turtle_pos, draw_endpoint=False, show_turtle=show_turtle))
    frame_durations.append(STATIC_FRAME_DURATION)


    # Add final frames for the endpoint transition
    # Determine the final turtle position based on the outcome
    parallel_stages_statuses = [current_statuses['stage2'], current_statuses['stage3'], current_statuses['stage4']]
    if any(s=='denied' for s in parallel_stages_statuses):
        final_turtle_pos = turtle_end_pos # Turtle reaches end, but with denied status
    elif all(s == 'validated' for s in parallel_stages_statuses):
        final_turtle_pos = turtle_end_pos # Turtle reaches end with approved status
    else:
         final_turtle_pos = turtle_pos # Turtle stays at the last updated stage if process is incomplete

    # Add frames for turtle moving to the final endpoint position if it's not already there
    if turtle_pos != final_turtle_pos:
        start_x, start_y = turtle_pos
        end_x, end_y = final_turtle_pos
        for i in range(1, num_movement_frames + 1):
            interp_x = start_x + (end_x - start_x) * i / num_movement_frames
            interp_y = start_y + (end_y - start_y) * i / num_movement_frames
            frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=(int(interp_x), int(interp_y)), draw_endpoint=False, show_turtle=show_turtle))
            frame_durations.append(MOVEMENT_FRAME_DURATION)
        turtle_pos = final_turtle_pos


    # Add a final frame with the colored endpoint and turtle at the final position
    frames.append(draw_frame_with_turtle(current_statuses.copy(), turtle_position=turtle_pos, draw_endpoint=True, show_turtle=show_turtle))
    frame_durations.append(STATIC_FRAME_DURATION)


    # Save the frames as a GIF
    fs_path, url_path = _resolve_output_paths(output_filename or OUTPUT_FILENAME)
    print(f"Saving animated turtle GIF as '{fs_path}' (url: {url_path})")
    frames[0].save(
        fs_path,
        save_all=True,
        append_images=frames[1:],
        duration=frame_durations,
        loop=0
    )
    print(f"Animated turtle GIF saved as '{fs_path}'")
    print(f"File gif path: {os.path.abspath(fs_path)}")
    return url_path


def _parse_timestamp(ts: Union[str, int, float, None]) -> float:
    """Parse numeric or ISO8601 timestamp to POSIX float seconds.

    Supported string examples: '2025-08-15T12:34:56', '2025-08-15T12:34:56.123456',
    '2025-08-15T12:34:56Z', '2025-08-15T12:34:56+00:00'.
    Returns float('inf') if ts is None or cannot be parsed.
    """
    if ts is None:
        return float('inf')
    from datetime import datetime as _dt, timezone as _tz
    if isinstance(ts, _dt):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_tz.utc)
        return ts.timestamp()
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return float('inf')
        # Handle 'Z' suffix (Zulu for UTC)
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                # Assume naive datetimes are in UTC
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return float('inf')
    return float('inf')


def build_scenario_from_statuses(stage_statuses: Dict[str, Dict[str, Any]]) -> List[Tuple[str,str]]:
    """Convert a dict of stage-> {status, timestamp} into ordered scenario steps.

    Timestamp can be numeric (int/float) or ISO8601 string. Naive datetimes are treated as UTC.

    Ordering rules:
      1. stage1 first if status != 'default'
      2. Stages 2,3,4 ordered by ascending timestamp (ignore if status is 'default').
         Missing/unparseable timestamps are treated as +inf (placed last). Ties resolved by stage name.
    """
    scenario: List[Tuple[str,str]] = []
    s1 = stage_statuses.get('stage1')
    if s1 and s1.get('status','default') != 'default':
        scenario.append(('stage1', s1['status']))

    parallel: List[Tuple[float,str,str]] = []  # (timestamp, stage, status)
    for st in ('stage2','stage3','stage4'):
        info = stage_statuses.get(st)
        if not info:
            continue
        status = info.get('status','default')
        if status == 'default':
            continue
        ts_raw = info.get('timestamp')
        sort_ts = _parse_timestamp(ts_raw)
        parallel.append((sort_ts, st, status))
    parallel.sort(key=lambda t: (t[0], t[1]))
    scenario.extend([(st, status) for _, st, status in parallel])
    return scenario


def create_progress_gif(stage_statuses: Dict[str, Dict[str, Any]], show_turtle: bool=True, output_filename: Optional[str]=None) -> str:
    """High-level API for external callers.

    Args:
        stage_statuses: mapping stage -> { 'status': str, 'timestamp': numeric/str }
        show_turtle: whether to draw turtle.
        output_filename: override default output name.
    Returns: output file path.
    """
    print("Creating progress GIF...")
    scenario = build_scenario_from_statuses(stage_statuses)
    if show_turtle:
        return generate_animation_scenario_with_turtle(scenario, show_turtle=True, output_filename=output_filename)
    else:
        # generate_animation_scenario uses global OUTPUT_FILENAME; copy to custom name if provided
        return generate_animation_scenario(scenario, output_filename=output_filename)

if __name__ == '__main__':
    # --- Define the sequence of events for the animation ---
    # This scenario shows a successful verification
    success_scenario = [
        ('stage1', 'validated'),
        ('stage2', 'validated'),
        ('stage3', 'validated'),
        ('stage4', 'validated'),
    ]

    # You can create other scenarios, for example, one with a denial
    denial_scenario = [
        ('stage1', 'validated'),
        ('stage2', 'validated'),
        ('stage3', 'denied'), # This stage is denied
        ('stage4', 'validated'),
    ]

    # generate_animation_scenario(success_scenario)
    # To generate the denial scenario instead, uncomment the line below and comment out the one above
    generate_animation_scenario_with_turtle(denial_scenario)