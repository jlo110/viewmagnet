"""
Hook Text Overlays for Video Enhancement

Creates attention-grabbing text overlays on videos to increase retention.
Features:
- White rounded box with serif text and shadow
- Configurable position (top/center/bottom)
- Pixel-based text wrapping for proper sizing
- FFmpeg overlay integration
"""

import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import structlog

logger = structlog.get_logger()

# Font configuration
FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSerif/NotoSerif-Bold.ttf"
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fonts")
FONT_PATH = os.path.join(FONT_DIR, "NotoSerif-Bold.ttf")


class HookPosition(Enum):
    """Position of the hook overlay on the video."""
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


@dataclass
class HookStyle:
    """Style configuration for hook overlays."""
    position: HookPosition = HookPosition.TOP
    font_scale: float = 1.0
    padding_x: int = 30
    padding_y: int = 25
    line_spacing: int = 20
    corner_radius: int = 20
    shadow_offset: Tuple[int, int] = (5, 5)
    shadow_blur: int = 10
    box_color: Tuple[int, int, int, int] = (255, 255, 255, 240)  # Semi-transparent white
    text_color: str = "black"
    shadow_color: Tuple[int, int, int, int] = (0, 0, 0, 100)


@dataclass
class HookResult:
    """Result of hook generation."""
    image_path: str
    width: int
    height: int
    text: str
    position: HookPosition


def download_font_if_needed() -> bool:
    """
    Downloads the serif font for hook text if not present.
    
    Returns:
        True if font is available, False otherwise.
    """
    if not os.path.exists(FONT_DIR):
        os.makedirs(FONT_DIR, exist_ok=True)
    
    if os.path.exists(FONT_PATH):
        return True
    
    logger.info(f"Downloading font from {FONT_URL}...")
    try:
        req = urllib.request.Request(
            FONT_URL,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(FONT_PATH, 'wb') as out_file:
                out_file.write(response.read())
        logger.info("Font downloaded successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to download font: {e}")
        return False


def create_hook_image(
    text: str,
    target_width: int,
    output_path: Optional[str] = None,
    style: Optional[HookStyle] = None
) -> Tuple[str, int, int]:
    """
    Generate a hook overlay image with white box and black serif text.
    
    Args:
        text: The hook text to display
        target_width: Maximum width the box should occupy (e.g., 85% of video width)
        output_path: Path to save the image (auto-generated if None)
        style: HookStyle configuration
    
    Returns:
        Tuple of (image_path, canvas_width, canvas_height)
    """
    download_font_if_needed()
    
    if style is None:
        style = HookStyle()
    
    # Font size calculation (approx 5% of target width)
    base_font_size = int(target_width * 0.05)
    font_size = int(base_font_size * style.font_scale)
    
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception as e:
        logger.warning(f"Could not load font {FONT_PATH}, using default: {e}")
        font = ImageFont.load_default()
    
    # Create dummy image for text measurement
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    
    max_text_width = target_width - (2 * style.padding_x)
    
    # Handle manual newlines and wrap text
    paragraphs = text.split('\n')
    lines = []
    
    for paragraph in paragraphs:
        if not paragraph.strip():
            lines.append("")
            continue
        
        words = paragraph.split()
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            
            if width <= max_text_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    # Single word too long, force it
                    lines.append(word)
                    current_line = []
        
        if current_line:
            lines.append(' '.join(current_line))
    
    # Calculate true dimensions
    max_line_width = 0
    text_heights = []
    
    for line in lines:
        if not line:
            text_heights.append(font_size)
            continue
        
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        max_line_width = max(max_line_width, w)
        text_heights.append(h)
    
    # Box dimensions
    box_width = max(max_line_width + (2 * style.padding_x), int(target_width * 0.3))
    
    if not text_heights:
        total_text_height = font_size
    else:
        total_text_height = sum(text_heights) + (len(text_heights) - 1) * style.line_spacing
    
    box_height = total_text_height + (2 * style.padding_y)
    
    # Create canvas with space for shadow
    canvas_w = box_width + 40
    canvas_h = box_height + 40
    
    img = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw shadow
    shadow_box = [
        (20 + style.shadow_offset[0], 20 + style.shadow_offset[1]),
        (20 + box_width + style.shadow_offset[0], 20 + box_height + style.shadow_offset[1])
    ]
    draw.rounded_rectangle(shadow_box, radius=style.corner_radius, fill=style.shadow_color)
    
    # Blur shadow
    img = img.filter(ImageFilter.GaussianBlur(style.shadow_blur // 2))
    
    # Draw white box on top
    draw_final = ImageDraw.Draw(img)
    main_box = [
        (20, 20),
        (20 + box_width, 20 + box_height)
    ]
    draw_final.rounded_rectangle(main_box, radius=style.corner_radius, fill=style.box_color)
    
    # Draw text
    current_y = 20 + style.padding_y - 2
    for i, line in enumerate(lines):
        if not line:
            current_y += font_size + style.line_spacing
            continue
        
        bbox = draw_final.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = text_heights[i] if i < len(text_heights) else bbox[3] - bbox[1]
        
        # Center text horizontally
        x = 20 + (box_width - line_w) // 2
        
        draw_final.text((x, current_y), line, font=font, fill=style.text_color)
        current_y += line_h + style.line_spacing
    
    # Save image
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix='.png', prefix='hook_')
        os.close(fd)
    
    img.save(output_path, 'PNG')
    logger.info(f"Hook image created: {output_path} ({canvas_w}x{canvas_h})")
    
    return output_path, canvas_w, canvas_h


def add_hook_to_video(
    video_path: str,
    text: str,
    output_path: str,
    position: str = "top",
    font_scale: float = 1.0,
    duration: Optional[float] = None,
    fade_in: float = 0.3,
    fade_out: float = 0.3
) -> bool:
    """
    Overlay hook text onto a video.
    
    Args:
        video_path: Path to input video
        text: Hook text to overlay
        output_path: Path to save output video
        position: 'top', 'center', or 'bottom'
        font_scale: Scale factor for font size
        duration: How long to show the hook (None = full video)
        fade_in: Fade in duration in seconds
        fade_out: Fade out duration in seconds
    
    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")
    
    # Get video dimensions
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=width,height,duration',
            '-of', 'csv=s=x:p=0',
            video_path
        ]
        result = subprocess.check_output(cmd).decode().strip()
        parts = result.split('\n')[0].split('x')
        video_width = int(parts[0])
        video_height = int(parts[1])
    except Exception as e:
        logger.warning(f"FFprobe failed: {e}. Assuming 1080x1920")
        video_width = 1080
        video_height = 1920
    
    # Generate hook image
    target_box_width = int(video_width * 0.9)
    style = HookStyle(
        position=HookPosition(position),
        font_scale=font_scale
    )
    
    hook_filename = None
    try:
        hook_filename, box_w, box_h = create_hook_image(
            text, target_box_width, style=style
        )
        
        # Calculate overlay position
        overlay_x = (video_width - box_w) // 2
        
        if position == "center":
            overlay_y = (video_height - box_h) // 2
        elif position == "bottom":
            overlay_y = int(video_height * 0.70)
        else:  # top
            overlay_y = int(video_height * 0.15)
        
        # Build FFmpeg filter
        # Basic overlay with optional fade
        filter_parts = []
        
        if duration is not None or fade_in > 0 or fade_out > 0:
            # Use enable expression for timing
            enable_expr = []
            if duration is not None:
                enable_expr.append(f"lt(t,{duration})")
            
            overlay_filter = f"[0:v][1:v]overlay={overlay_x}:{overlay_y}"
            if enable_expr:
                overlay_filter += f":enable='{' and '.join(enable_expr)}'"
            filter_parts.append(overlay_filter)
        else:
            filter_parts.append(f"[0:v][1:v]overlay={overlay_x}:{overlay_y}")
        
        filter_complex = filter_parts[0]
        
        logger.info(f"Overlaying hook: '{text[:50]}...' at {overlay_x},{overlay_y}")
        
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', hook_filename,
            '-filter_complex', filter_complex,
            '-c:a', 'copy',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            output_path
        ]
        
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        logger.info(f"Hook added to video: {output_path}")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr.decode() if e.stderr else 'Unknown'}")
        raise
    except Exception as e:
        logger.error(f"Hook generation error: {e}")
        raise
    finally:
        # Cleanup temp image
        if hook_filename and os.path.exists(hook_filename):
            try:
                os.remove(hook_filename)
            except Exception:
                pass


def generate_hook_suggestions(transcript: str, title: str) -> list:
    """
    Generate hook text suggestions based on video content.
    
    Args:
        transcript: Video transcript
        title: Video title
    
    Returns:
        List of suggested hook texts
    """
    suggestions = []
    
    # Extract potential hooks from content
    sentences = transcript.split('.')[:10]  # First 10 sentences
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 10 and len(sentence) < 100:
            # Look for hook patterns
            if any(word in sentence.lower() for word in ['secret', 'never', 'always', 'how', 'why', 'what']):
                suggestions.append(sentence.upper()[:50])
    
    # Add generic hooks based on title
    if suggestions:
        return suggestions[:5]
    
    # Fallback suggestions
    return [
        "WATCH THIS",
        "YOU NEED TO SEE THIS",
        "THIS CHANGES EVERYTHING",
        "WAIT FOR IT...",
        "NO ONE TALKS ABOUT THIS"
    ]
