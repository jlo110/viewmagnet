"""
AI Thumbnail Generator - Hybrid approach combining:
1. User-provided base image/face
2. AI-generated/enhanced backgrounds
3. Smart text overlays
4. Data-driven optimization from our patterns
"""
import io
import os
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import httpx
import structlog

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = structlog.get_logger()

# Optimal thumbnail settings based on our analysis
OPTIMAL_SETTINGS = {
    "gaming": {
        "brightness": 0.65,
        "saturation": 1.3,
        "contrast": 1.2,
        "text_color": "#FFFFFF",
        "text_stroke": "#000000",
        "text_position": "bottom-left",
        "style": "vibrant, action-packed, dynamic",
    },
    "tech": {
        "brightness": 0.75,
        "saturation": 1.1,
        "contrast": 1.15,
        "text_color": "#FFFFFF",
        "text_stroke": "#1a1a2e",
        "text_position": "bottom-center",
        "style": "clean, modern, minimalist, professional",
    },
    "education": {
        "brightness": 0.7,
        "saturation": 1.0,
        "contrast": 1.1,
        "text_color": "#FFFFFF",
        "text_stroke": "#2d3436",
        "text_position": "top-center",
        "style": "clear, informative, trustworthy",
    },
    "entertainment": {
        "brightness": 0.6,
        "saturation": 1.25,
        "contrast": 1.2,
        "text_color": "#FFFF00",
        "text_stroke": "#FF0000",
        "text_position": "center",
        "style": "exciting, colorful, expressive",
    },
    "lifestyle": {
        "brightness": 0.72,
        "saturation": 1.15,
        "contrast": 1.1,
        "text_color": "#FFFFFF",
        "text_stroke": "#333333",
        "text_position": "bottom-right",
        "style": "warm, inviting, aesthetic",
    },
    "default": {
        "brightness": 0.7,
        "saturation": 1.1,
        "contrast": 1.15,
        "text_color": "#FFFFFF",
        "text_stroke": "#000000",
        "text_position": "bottom-center",
        "style": "professional, engaging",
    }
}

# Text styles that work
TEXT_STYLES = {
    "bold_impact": {
        "font_size_ratio": 0.12,  # Relative to image height
        "stroke_width": 8,
        "shadow": True,
        "uppercase": True,
    },
    "clean_modern": {
        "font_size_ratio": 0.08,
        "stroke_width": 4,
        "shadow": False,
        "uppercase": False,
    },
    "youtube_style": {
        "font_size_ratio": 0.1,
        "stroke_width": 6,
        "shadow": True,
        "uppercase": True,
    }
}


@dataclass
class ThumbnailConfig:
    """Configuration for thumbnail generation."""
    title: str
    category: str = "default"
    text_style: str = "youtube_style"
    include_face: bool = True
    face_position: str = "right"  # left, right, center
    text_lines: int = 2  # Max lines for title
    width: int = 1280
    height: int = 720
    # Template options
    template: str = "auto"  # auto, mrbeast, minimal, gaming, tech, bold
    # Text customization
    text_color: str = "#FFFFFF"
    text_stroke_color: str = "#000000"
    text_position: str = "bottom-center"  # top-left, top-center, bottom-left, bottom-center, center
    font_size: str = "large"  # small, medium, large, xlarge
    # Background options
    background_style: str = "ai"  # ai, gradient, solid, template


# Professional Templates
TEMPLATES = {
    "mrbeast": {
        "name": "MrBeast Style",
        "description": "Bold, high-energy, face on right, big text",
        "text_color": "#FFFFFF",
        "text_stroke": "#000000",
        "stroke_width": 10,
        "text_position": "left",
        "font_size_ratio": 0.14,
        "face_position": "right",
        "face_size": 0.9,
        "uppercase": True,
        "gradient_colors": ["#1a0a2e", "#4a0080", "#8b00ff"],
        "add_glow": True,
    },
    "minimal": {
        "name": "Minimal Clean",
        "description": "Clean, professional, subtle",
        "text_color": "#FFFFFF",
        "text_stroke": "#333333",
        "stroke_width": 4,
        "text_position": "bottom-center",
        "font_size_ratio": 0.08,
        "face_position": "right",
        "face_size": 0.7,
        "uppercase": False,
        "gradient_colors": ["#0f0f0f", "#1a1a2e", "#2a2a4e"],
        "add_glow": False,
    },
    "gaming": {
        "name": "Gaming/Esports",
        "description": "Neon, cyberpunk, high energy",
        "text_color": "#00ff88",
        "text_stroke": "#000000",
        "stroke_width": 8,
        "text_position": "bottom-left",
        "font_size_ratio": 0.12,
        "face_position": "right",
        "face_size": 0.85,
        "uppercase": True,
        "gradient_colors": ["#0a0a1a", "#1a0a3a", "#0a2a4a", "#00ff88"],
        "add_glow": True,
    },
    "tech": {
        "name": "Tech Review",
        "description": "Sleek, modern, professional",
        "text_color": "#FFFFFF",
        "text_stroke": "#0066ff",
        "stroke_width": 6,
        "text_position": "bottom-center",
        "font_size_ratio": 0.10,
        "face_position": "right",
        "face_size": 0.75,
        "uppercase": True,
        "gradient_colors": ["#0a0a1a", "#0a1a3a", "#1a3a6a", "#3a6aaa"],
        "add_glow": True,
    },
    "bold": {
        "name": "Bold Impact",
        "description": "Maximum attention, huge text",
        "text_color": "#FFFF00",
        "text_stroke": "#FF0000",
        "stroke_width": 12,
        "text_position": "center",
        "font_size_ratio": 0.16,
        "face_position": "right",
        "face_size": 0.8,
        "uppercase": True,
        "gradient_colors": ["#1a0000", "#4a0000", "#8a0000"],
        "add_glow": True,
    },
    "education": {
        "name": "Educational",
        "description": "Trust-building, clear, professional",
        "text_color": "#FFFFFF",
        "text_stroke": "#1a5a8a",
        "stroke_width": 5,
        "text_position": "top-center",
        "font_size_ratio": 0.09,
        "face_position": "right",
        "face_size": 0.7,
        "uppercase": False,
        "gradient_colors": ["#0a1a2a", "#1a3a5a", "#2a5a8a", "#4a8aba"],
        "add_glow": False,
    },
}
    

@dataclass 
class GeneratedThumbnail:
    """Result of thumbnail generation."""
    image: Image.Image
    score: float  # Predicted performance score
    tips: List[str]
    variations: List[Image.Image]  # Alternative versions


class ThumbnailGenerator:
    """
    Generates optimized YouTube thumbnails using hybrid AI approach.
    """
    
    def __init__(self, replicate_token: Optional[str] = None):
        """Initialize generator."""
        self.replicate_token = replicate_token or os.getenv("REPLICATE_API_TOKEN")
        self._font_cache = {}
        # See HookLab.set_budget_context. Threading user_id through
        # four nested ``_generate_background`` calls would be noisy;
        # this lets the router wire context once.
        self._budget_user_id: Optional[int] = None
        self._budget_plan: str = "free"

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        self._budget_user_id = user_id
        self._budget_plan = plan
    
    def get_templates(self) -> Dict:
        """Get available templates."""
        return TEMPLATES
    
    def _get_template_settings(self, config: ThumbnailConfig) -> Dict:
        """Get settings from template or config."""
        template_name = config.template
        
        # Auto-select template based on category
        if template_name == "auto":
            category_templates = {
                "gaming": "gaming",
                "tech": "tech",
                "education": "education",
                "entertainment": "mrbeast",
                "lifestyle": "minimal",
                "default": "mrbeast",
            }
            template_name = category_templates.get(config.category, "mrbeast")
        
        template = TEMPLATES.get(template_name, TEMPLATES["mrbeast"])
        
        # Override with config if specified
        return {
            "text_color": config.text_color if config.text_color != "#FFFFFF" else template["text_color"],
            "text_stroke": config.text_stroke_color if config.text_stroke_color != "#000000" else template["text_stroke"],
            "stroke_width": template["stroke_width"],
            "text_position": config.text_position if config.text_position != "bottom-center" else template["text_position"],
            "font_size_ratio": template["font_size_ratio"],
            "face_position": config.face_position,
            "face_size": template["face_size"],
            "uppercase": template["uppercase"],
            "gradient_colors": template["gradient_colors"],
            "add_glow": template["add_glow"],
        }
        
    def generate(
        self,
        config: ThumbnailConfig,
        base_image: Optional[bytes] = None,
        face_image: Optional[bytes] = None,
    ) -> GeneratedThumbnail:
        """
        Generate an optimized thumbnail.
        
        Args:
            config: Thumbnail configuration
            base_image: Optional background image bytes
            face_image: Optional face/person image bytes (will be extracted/composed)
            
        Returns:
            GeneratedThumbnail with main image and variations
        """
        settings = OPTIMAL_SETTINGS.get(config.category, OPTIMAL_SETTINGS["default"])
        text_style = TEXT_STYLES.get(config.text_style, TEXT_STYLES["youtube_style"])
        
        # Step 1: Create or process background (ONE AI generation)
        if base_image:
            clean_background = self._process_background(base_image, config, settings)
        else:
            # Generate AI background ONCE
            clean_background = self._generate_background(config, settings)
        
        # Step 2: Apply color optimization to clean background
        clean_background = self._optimize_colors(clean_background, settings)
        
        # Step 3: Generate the MAIN thumbnail with current settings
        main_thumb = self._compose_thumbnail(
            clean_background.copy(), 
            face_image, 
            config, 
            settings, 
            text_style,
            face_position=config.face_position,
            text_position=config.text_position
        )
        
        # Step 4: Generate REAL LAYOUT VARIATIONS (different positions)
        variations = self._generate_layout_variations(
            clean_background, 
            face_image, 
            config, 
            settings, 
            text_style
        )
        
        # Step 5: Score the main thumbnail
        score, tips = self._score_thumbnail(main_thumb, config)
        
        return GeneratedThumbnail(
            image=main_thumb,
            score=score,
            tips=tips,
            variations=variations
        )
    
    def _compose_thumbnail(
        self,
        background: Image.Image,
        face_image: Optional[bytes],
        config: ThumbnailConfig,
        settings: Dict,
        text_style: Dict,
        face_position: str = "right",
        text_position: str = "bottom-center"
    ) -> Image.Image:
        """Compose a complete thumbnail with face and text at specified positions."""
        result = background.copy()
        
        # Create modified settings for this specific layout
        layout_settings = settings.copy()
        layout_settings["face_position"] = face_position
        layout_settings["text_position"] = text_position
        
        # Add face if provided
        if face_image and config.include_face:
            # Create a modified config for this face position
            layout_config = ThumbnailConfig(
                title=config.title,
                category=config.category,
                text_style=config.text_style,
                include_face=True,
                face_position=face_position,
                text_lines=config.text_lines,
                width=config.width,
                height=config.height,
                template=config.template,
                text_color=config.text_color,
                text_stroke_color=config.text_stroke_color,
                text_position=text_position,
            )
            result = self._composite_face_advanced(result, face_image, layout_config, layout_settings)
        
        # Add text overlay
        result = self._add_text_overlay(result, config, layout_settings, text_style)
        
        return result
    
    def _process_background(
        self, 
        image_data: bytes, 
        config: ThumbnailConfig,
        settings: Dict
    ) -> Image.Image:
        """Process and enhance uploaded background."""
        img = Image.open(io.BytesIO(image_data)).convert("RGB")
        
        # Resize to thumbnail dimensions
        img = img.resize((config.width, config.height), Image.Resampling.LANCZOS)
        
        # Slight blur to make text pop
        if config.text_lines > 0:
            # Create gradient mask for selective blur
            img = self._apply_text_area_blur(img, config)
        
        return img
    
    def _generate_background(
        self, 
        config: ThumbnailConfig,
        settings: Dict
    ) -> Image.Image:
        """Generate AI background or use gradient fallback."""
        # Try AI generation if token available
        if self.replicate_token:
            try:
                logger.info("Attempting AI background generation with Replicate...")
                return self._generate_with_ai(config, settings)
            except ImportError:
                logger.warning("Replicate package not installed. Install with: pip install replicate")
            except Exception as e:
                logger.warning(f"AI generation failed: {e}, using gradient fallback")
        else:
            logger.info("No Replicate token found, using gradient background")
        
        # Fallback: Generate attractive gradient background
        return self._generate_gradient_background(config, settings)
    
    def _generate_with_ai(
        self, 
        config: ThumbnailConfig,
        settings: Dict
    ) -> Image.Image:
        """Generate background using Replicate - tries Flux first, then SDXL."""
        import replicate
        
        # Use LLM to generate context-aware background prompt from title
        prompt = self._generate_llm_background_prompt(
            config.title,
            config.face_position,
            user_id=self._budget_user_id,
            plan=self._budget_plan,
        )
        
        negative_prompt = "people, person, human, face, hands, body, man, woman, child, portrait, cartoon, anime, illustration, painting, drawing, text, words, letters, numbers, price tags, dollar signs, currency symbols, labels, signs, watermark, blurry, low quality, boring, flat lighting, stock photo"
        
        logger.info(f"Generating contextual background: {config.title[:40]}...")
        
        # Try Flux first (better quality)
        try:
            output = replicate.run(
                "black-forest-labs/flux-schnell",
                input={
                    "prompt": prompt,
                    "num_outputs": 1,
                    "aspect_ratio": "16:9",
                    "output_format": "png",
                    "output_quality": 90,
                }
            )
            logger.info("Using Flux model")
        except Exception as e:
            logger.warning(f"Flux failed: {e}, trying SDXL...")
            # Fallback to SDXL
            output = replicate.run(
                "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                input={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "width": config.width,
                    "height": config.height,
                    "num_outputs": 1,
                }
            )
        
        # Handle different output types from Replicate
        result = output[0] if isinstance(output, list) else output
        
        # If it's a FileOutput object, read directly
        if hasattr(result, 'read'):
            image_data = result.read()
            img = Image.open(io.BytesIO(image_data)).convert("RGB")
        elif isinstance(result, str):
            response = httpx.get(result)
            img = Image.open(io.BytesIO(response.content)).convert("RGB")
        else:
            response = httpx.get(str(result))
            img = Image.open(io.BytesIO(response.content)).convert("RGB")
        
        # Resize to exact dimensions
        img = img.resize((config.width, config.height), Image.Resampling.LANCZOS)
        return img
    
    def _generate_gradient_background(
        self, 
        config: ThumbnailConfig,
        settings: Dict
    ) -> Image.Image:
        """Generate an attractive gradient background with visual elements."""
        import math
        
        img = Image.new("RGB", (config.width, config.height))
        draw = ImageDraw.Draw(img)
        
        # Category-based color schemes - more vibrant
        color_schemes = {
            "gaming": [("#0f0f1a", "#1a0a2e", "#2d1b4e", "#e94560", "#ff6b9d")],
            "tech": [("#0a0a1a", "#0f1a3a", "#1a2a5a", "#3a4a8a", "#6366f1")],
            "education": [("#0f172a", "#1e3a5f", "#3b82f6", "#60a5fa", "#93c5fd")],
            "entertainment": [("#1a0a0a", "#3a0a2a", "#7c3aed", "#a855f7", "#f472b6")],
            "lifestyle": [("#0a1a1a", "#1a2f2f", "#2dd4bf", "#5eead4", "#99f6e4")],
            "default": [("#0f0f1a", "#1a1a3a", "#3730a3", "#6366f1", "#818cf8")],
        }
        
        colors = color_schemes.get(config.category, color_schemes["default"])[0]
        
        # Create radial gradient from corner
        center_x = config.width * 0.2 if config.face_position == "right" else config.width * 0.8
        center_y = config.height * 0.3
        max_dist = math.sqrt(config.width**2 + config.height**2)
        
        for y in range(config.height):
            for x in range(config.width):
                # Calculate distance from center point
                dist = math.sqrt((x - center_x)**2 + (y - center_y)**2)
                ratio = min(dist / max_dist, 1.0)
                
                # Interpolate between colors
                idx = min(int(ratio * (len(colors) - 1)), len(colors) - 2)
                local_ratio = (ratio * (len(colors) - 1)) - idx
                
                c1 = self._hex_to_rgb(colors[idx])
                c2 = self._hex_to_rgb(colors[idx + 1])
                
                r = int(c1[0] + (c2[0] - c1[0]) * local_ratio)
                g = int(c1[1] + (c2[1] - c1[1]) * local_ratio)
                b = int(c1[2] + (c2[2] - c1[2]) * local_ratio)
                
                draw.point((x, y), fill=(r, g, b))
        
        # Add some visual elements (circles, shapes)
        img = self._add_background_elements(img, config, colors)
        
        return img
    
    def _add_background_elements(
        self, 
        img: Image.Image, 
        config: ThumbnailConfig,
        colors: List[str]
    ) -> Image.Image:
        """Add decorative elements to background."""
        import random
        
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Add glowing circles
        accent_color = self._hex_to_rgb(colors[-1])
        
        # Large glow on opposite side of face
        glow_x = config.width * 0.15 if config.face_position == "right" else config.width * 0.85
        glow_y = config.height * 0.4
        
        for r in range(200, 0, -5):
            alpha = int(30 * (1 - r/200))
            draw.ellipse(
                [glow_x - r, glow_y - r, glow_x + r, glow_y + r],
                fill=(*accent_color, alpha)
            )
        
        # Small accent circles
        random.seed(42)  # Consistent results
        for _ in range(5):
            cx = random.randint(50, config.width - 50)
            cy = random.randint(50, config.height - 50)
            
            # Avoid face area
            if config.face_position == "right" and cx > config.width * 0.5:
                continue
            if config.face_position == "left" and cx < config.width * 0.5:
                continue
                
            radius = random.randint(20, 60)
            for r in range(radius, 0, -2):
                alpha = int(20 * (1 - r/radius))
                draw.ellipse(
                    [cx - r, cy - r, cx + r, cy + r],
                    fill=(*accent_color, alpha)
                )
        
        return img.convert("RGB")
    
    def _composite_face(
        self, 
        background: Image.Image, 
        face_data: bytes,
        config: ThumbnailConfig
    ) -> Image.Image:
        """Composite face/person onto background (basic version)."""
        return self._composite_face_advanced(background, face_data, config, OPTIMAL_SETTINGS["default"])
    
    def _composite_face_advanced(
        self, 
        background: Image.Image, 
        face_data: bytes,
        config: ThumbnailConfig,
        settings: Dict
    ) -> Image.Image:
        """Composite face/person onto background with advanced processing."""
        face_img = Image.open(io.BytesIO(face_data))
        
        # Check if image has alpha channel (PNG with transparency)
        has_transparency = face_img.mode == 'RGBA' and face_img.split()[3].getextrema()[0] < 255
        
        if not has_transparency:
            # Remove background using AI
            face_img = self._remove_background_simple(face_img)
        else:
            face_img = face_img.convert("RGBA")
        
        # Calculate face size - make it prominent
        face_size_ratio = settings.get("face_size", 0.85)
        face_height = int(config.height * face_size_ratio)
        aspect = face_img.width / face_img.height
        face_width = int(face_height * aspect)
        
        # Limit width to not overflow (max 50% of image width)
        if face_width > config.width * 0.5:
            face_width = int(config.width * 0.5)
            face_height = int(face_width / aspect)
        
        face_img = face_img.resize((face_width, face_height), Image.Resampling.LANCZOS)
        
        # ===== FEATHER EDGES =====
        # Create soft edge on the face mask
        if face_img.mode == 'RGBA':
            alpha = face_img.split()[3]
            # Erode slightly then blur for soft edge
            alpha = alpha.filter(ImageFilter.MinFilter(3))
            alpha = alpha.filter(ImageFilter.GaussianBlur(radius=2))
            face_img.putalpha(alpha)
        
        # ===== COLOR GRADING - Match face to background =====
        face_img = self._color_grade_face(face_img, background, config)
        
        # ===== POSITION WITH PADDING (not overflow) =====
        padding = 30  # Keep face fully inside frame
        
        if config.face_position == "right":
            x = config.width - face_width - padding
        elif config.face_position == "left":
            x = padding
        else:  # center
            x = (config.width - face_width) // 2
        
        # Anchor to bottom with padding
        y = config.height - face_height + 20
        
        background = background.convert("RGBA")
        
        # ===== ADD GLOW BEHIND FACE =====
        if face_img.mode == 'RGBA':
            # Get dominant background color for glow
            bg_sample = background.crop((x, y, min(x + face_width, config.width), min(y + face_height, config.height)))
            bg_colors = bg_sample.resize((1, 1)).getpixel((0, 0))
            glow_color = bg_colors[:3] if len(bg_colors) >= 3 else (100, 100, 255)
            
            # Create glow layer
            glow = Image.new('RGBA', (face_width + 60, face_height + 60), (0, 0, 0, 0))
            glow_alpha = face_img.split()[3].resize((face_width, face_height))
            glow_face = Image.new('RGBA', (face_width, face_height), glow_color + (255,))
            glow_face.putalpha(glow_alpha)
            glow.paste(glow_face, (30, 30))
            glow = glow.filter(ImageFilter.GaussianBlur(radius=25))
            
            # Reduce glow opacity
            glow_data = list(glow.getdata())
            glow_data = [(r, g, b, min(a, 80)) for r, g, b, a in glow_data]
            glow.putdata(glow_data)
            
            # Paste glow
            background.paste(glow, (x - 30, y - 30), glow)
        
        # ===== ADD DROP SHADOW =====
        if face_img.mode == 'RGBA':
            shadow = Image.new('RGBA', face_img.size, (0, 0, 0, 0))
            alpha = face_img.split()[3]
            shadow.putalpha(alpha)
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=20))
            
            # Make shadow darker
            shadow_data = list(shadow.getdata())
            shadow_data = [(0, 0, 0, min(a, 150)) for r, g, b, a in shadow_data]
            shadow.putdata(shadow_data)
            
            # Paste shadow offset (down and right)
            background.paste(shadow, (x + 12, y + 12), shadow)
        
        # ===== PASTE FACE =====
        background.paste(face_img, (x, y), face_img if face_img.mode == 'RGBA' else None)
        
        return background.convert("RGB")
    
    def _color_grade_face(
        self, 
        face_img: Image.Image, 
        background: Image.Image,
        config: ThumbnailConfig
    ) -> Image.Image:
        """Apply color grading to face to match background lighting."""
        
        if face_img.mode != 'RGBA':
            face_img = face_img.convert('RGBA')
        
        # Sample background colors to determine lighting
        bg_small = background.resize((10, 10))
        bg_colors = list(bg_small.getdata())
        
        # Calculate average background color
        avg_r = sum(c[0] for c in bg_colors) // len(bg_colors)
        avg_g = sum(c[1] for c in bg_colors) // len(bg_colors)
        avg_b = sum(c[2] for c in bg_colors) // len(bg_colors)
        
        # Determine color temperature (warm vs cool)
        warmth = (avg_r - avg_b) / 255.0  # -1 (cold) to +1 (warm)
        brightness = (avg_r + avg_g + avg_b) / (3 * 255.0)  # 0 to 1
        
        # Split into RGB and Alpha
        r, g, b, a = face_img.split()
        
        # Apply color tint based on background
        # For cold backgrounds (blue), add slight blue tint
        # For warm backgrounds (orange), add slight warm tint
        
        def adjust_channel(channel, factor):
            return channel.point(lambda x: min(255, int(x * factor)))
        
        if warmth < -0.1:  # Cold/blue background
            # Add blue tint, reduce red
            r = adjust_channel(r, 0.95)
            b = adjust_channel(b, 1.08)
        elif warmth > 0.1:  # Warm/orange background
            # Add warm tint
            r = adjust_channel(r, 1.05)
            b = adjust_channel(b, 0.92)
        
        # Adjust brightness to match scene
        if brightness < 0.3:  # Dark background
            r = adjust_channel(r, 0.9)
            g = adjust_channel(g, 0.9)
            b = adjust_channel(b, 0.9)
        elif brightness > 0.7:  # Bright background
            r = adjust_channel(r, 1.05)
            g = adjust_channel(g, 1.05)
            b = adjust_channel(b, 1.05)
        
        # Merge back
        face_img = Image.merge('RGBA', (r, g, b, a))
        
        return face_img
    
    def _remove_background_simple(self, img: Image.Image) -> Image.Image:
        """Remove background using AI (rembg) or fallback to simple method."""
        try:
            from rembg import remove
            logger.info("Using AI background removal (rembg)...")
            
            # Convert to bytes for rembg
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            # Remove background
            output = remove(img_bytes.getvalue())
            result = Image.open(io.BytesIO(output)).convert("RGBA")
            logger.info("Background removed successfully")
            return result
            
        except ImportError:
            logger.warning("rembg not installed, using simple background removal")
        except Exception as e:
            logger.warning(f"AI background removal failed: {e}, using simple method")
        
        # Fallback to simple color-based removal
        return self._remove_background_color_based(img)
    
    def _remove_background_color_based(self, img: Image.Image) -> Image.Image:
        """Simple background removal using edge detection."""
        img = img.convert("RGBA")
        data = img.getdata()
        
        # Get corner colors (likely background)
        width, height = img.size
        corners = [
            img.getpixel((0, 0)),
            img.getpixel((width-1, 0)),
            img.getpixel((0, height-1)),
            img.getpixel((width-1, height-1))
        ]
        
        # Find most common corner color
        bg_color = max(set(corners), key=corners.count)
        
        # Create new image with transparency
        new_data = []
        tolerance = 30
        
        for item in data:
            # Check if pixel is close to background color
            if (abs(item[0] - bg_color[0]) < tolerance and 
                abs(item[1] - bg_color[1]) < tolerance and 
                abs(item[2] - bg_color[2]) < tolerance):
                new_data.append((255, 255, 255, 0))  # Transparent
            else:
                new_data.append(item[:3] + (255,))  # Keep with full opacity
        
        img.putdata(new_data)
        return img
    
    def _optimize_colors(
        self, 
        img: Image.Image, 
        settings: Dict
    ) -> Image.Image:
        """Apply optimal color adjustments."""
        # Brightness
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(settings["brightness"] / 0.5)  # Normalize around 0.5
        
        # Saturation
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(settings["saturation"])
        
        # Contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(settings["contrast"])
        
        return img
    
    def _add_text_overlay(
        self, 
        img: Image.Image, 
        config: ThumbnailConfig,
        settings: Dict,
        text_style: Dict
    ) -> Image.Image:
        """Add optimized text overlay."""
        if not config.title or config.text_lines == 0:
            return img
        
        draw = ImageDraw.Draw(img)
        
        # Prepare text
        text = config.title
        if text_style["uppercase"]:
            text = text.upper()
        
        # Auto-scale font to fit full title
        # Start with template font size and reduce until text fits
        base_font_ratio = text_style["font_size_ratio"]
        
        # Calculate available width for text (avoid face area)
        face_pos = settings.get("face_position", "right")
        face_size = settings.get("face_size", 0.8)
        face_width = int(config.width * face_size * 0.5)  # Face takes ~40-50% of width
        
        if face_pos in ["left", "right"]:
            # Text only on opposite side of face
            max_width = config.width - face_width - 80  # Leave margin
        else:
            max_width = config.width - 100
            
        max_lines = max(config.text_lines, 3)  # Allow at least 3 lines for long titles
        
        # Try progressively smaller fonts until text fits
        for scale in [1.0, 0.85, 0.7, 0.6, 0.5]:
            font_size = int(config.height * base_font_ratio * scale)
            font = self._get_font(font_size)
            lines = self._wrap_text(text, font, max_width, max_lines)
            
            # Check if we got all words
            wrapped_text = " ".join(lines)
            if len(wrapped_text) >= len(text) * 0.95:  # At least 95% of text fits
                break
        
        # Final wrap with chosen font
        lines = self._wrap_text(text, font, max_width, max_lines)
        
        # Calculate position
        text_color = settings["text_color"]
        stroke_color = settings["text_stroke"]
        stroke_width = text_style["stroke_width"]
        
        # Calculate total text height
        line_height = font_size * 1.2
        total_height = len(lines) * line_height
        
        # Get starting position based on settings
        position = settings["text_position"]
        face_pos = settings.get("face_position", "right")
        face_size = settings.get("face_size", 0.8)
        
        # Calculate face area to avoid
        # Face typically takes up face_size * height on one side
        face_width = int(config.width * face_size * 0.5)  # Face takes ~40-50% of width
        
        if "top" in position:
            y_start = 40
        elif "bottom" in position:
            y_start = config.height - total_height - 60
        else:
            y_start = (config.height - total_height) // 2
        
        # Draw each line
        for i, line in enumerate(lines):
            # Calculate x position - AVOID FACE AREA
            bbox = font.getbbox(line)
            text_width = bbox[2] - bbox[0]
            
            # Determine safe text area based on face position
            if face_pos == "right":
                # Face on right - text goes on LEFT side only
                safe_width = config.width - face_width - 50
                if "left" in position or "center" in position:
                    x = 50  # Left align in safe zone
                else:
                    x = min(50, safe_width - text_width)  # Keep in safe zone
            elif face_pos == "left":
                # Face on left - text goes on RIGHT side only
                safe_start = face_width + 50
                if "right" in position:
                    x = config.width - text_width - 50
                else:
                    x = safe_start  # Start after face
            else:
                # Face in center - text at top or bottom, centered
                if "left" in position:
                    x = 50
                elif "right" in position:
                    x = config.width - text_width - 50
                else:
                    x = (config.width - text_width) // 2
            
            y = y_start + i * line_height
            
            # Draw shadow if enabled
            if text_style.get("shadow"):
                shadow_offset = 4
                draw.text(
                    (x + shadow_offset, y + shadow_offset), 
                    line, 
                    font=font, 
                    fill="#000000"
                )
            
            # Draw stroke
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), line, font=font, fill=stroke_color)
            
            # Draw main text
            draw.text((x, y), line, font=font, fill=text_color)
        
        return img
    
    def _generate_layout_variations(
        self, 
        clean_background: Image.Image, 
        face_image: Optional[bytes],
        config: ThumbnailConfig,
        settings: Dict,
        text_style: Dict
    ) -> List[Image.Image]:
        """
        Generate REAL layout variations with different face/text positions.
        Uses the SAME AI background but different compositions.
        """
        variations = []
        
        # Define distinct layout combinations
        # Each variation has different face position + text position
        if face_image and config.include_face:
            # With face: vary both face and text positions
            layouts = [
                {"face_position": "left", "text_position": "bottom-center", "name": "Face Left"},
                {"face_position": "right", "text_position": "top-center", "name": "Face Right Top"},
                {"face_position": "center", "text_position": "bottom-center", "name": "Face Center"},
            ]
        else:
            # No face: just vary text positions
            layouts = [
                {"face_position": "right", "text_position": "top-center", "name": "Top Text"},
                {"face_position": "right", "text_position": "center", "name": "Center Text"},
                {"face_position": "right", "text_position": "bottom-left", "name": "Bottom Left"},
            ]
        
        for layout in layouts:
            try:
                variation = self._compose_thumbnail(
                    clean_background.copy(),
                    face_image,
                    config,
                    settings,
                    text_style,
                    face_position=layout["face_position"],
                    text_position=layout["text_position"]
                )
                variations.append(variation)
            except Exception as e:
                logger.warning(f"Failed to generate variation {layout['name']}: {e}")
                # Fallback: just add a color-adjusted version
                v = clean_background.copy()
                enhancer = ImageEnhance.Color(v)
                v = enhancer.enhance(1.1)
                variations.append(v)
        
        return variations
    
    def _generate_variations(
        self, 
        base: Image.Image, 
        config: ThumbnailConfig,
        settings: Dict
    ) -> List[Image.Image]:
        """Legacy method - kept for compatibility. Use _generate_layout_variations instead."""
        # Simple color variations as fallback
        variations = []
        
        v1 = base.copy()
        enhancer = ImageEnhance.Color(v1)
        v1 = enhancer.enhance(1.2)
        variations.append(v1)
        
        v2 = base.copy()
        r, g, b = v2.split()
        r = r.point(lambda i: min(255, int(i * 1.1)))
        v2 = Image.merge("RGB", (r, g, b))
        variations.append(v2)
        
        return variations
    
    def _score_thumbnail(
        self, 
        img: Image.Image, 
        config: ThumbnailConfig
    ) -> Tuple[float, List[str]]:
        """
        Score thumbnail based on PROVEN SUCCESS PRINCIPLES from viral thumbnails.
        
        Research-backed principles:
        1. FACE: Large, expressive face (40%+ of frame)
        2. CONTRAST: High contrast for visibility at small sizes
        3. COLORS: Bold, saturated colors (especially yellow, red, blue)
        4. TEXT: 3-5 words max, large and readable
        5. SIMPLICITY: 3 elements max (face + text + 1 prop)
        6. BRIGHTNESS: Not too dark (visible in dark mode)
        7. FOCAL POINT: Clear visual hierarchy
        """
        score = 50.0  # Start at 50, earn up to 100
        tips = []
        passed = []
        
        # ===== 1. BRIGHTNESS CHECK (15 points) =====
        brightness = self._calculate_brightness(img)
        if brightness >= 0.35 and brightness <= 0.75:
            score += 15
            passed.append("✅ Good brightness level")
        elif brightness < 0.35:
            tips.append("⚠️ Too dark - may be hard to see in dark mode feeds")
            score += 5
        else:
            tips.append("⚠️ Very bright - ensure text is still readable")
            score += 10
        
        # ===== 2. SATURATION/COLOR VIBRANCY (15 points) =====
        saturation = self._calculate_saturation(img)
        if saturation >= 0.5:
            score += 15
            passed.append("✅ Vibrant colors grab attention")
        elif saturation >= 0.3:
            score += 8
            tips.append("🎨 Boost saturation for more eye-catching colors")
        else:
            tips.append("🎨 Colors look muted - increase saturation significantly")
        
        # ===== 3. CONTRAST CHECK (15 points) =====
        contrast = self._calculate_contrast(img)
        if contrast >= 0.4:
            score += 15
            passed.append("✅ High contrast for small thumbnail visibility")
        elif contrast >= 0.25:
            score += 8
            tips.append("🔲 Increase contrast - thumbnails are viewed at tiny sizes")
        else:
            tips.append("🔲 Low contrast - will look muddy at small sizes")
        
        # ===== 4. TEXT LENGTH (10 points) =====
        word_count = len(config.title.split())
        if word_count <= 5:
            score += 10
            passed.append("✅ Short, punchy title (5 words or less)")
        elif word_count <= 8:
            score += 5
            tips.append("📝 Consider shorter title - 3-5 words is ideal")
        else:
            tips.append("📝 Title too long - top thumbnails use 3-5 words")
        
        # ===== 5. FACE INCLUDED (10 points) =====
        if config.include_face:
            score += 10
            passed.append("✅ Face included - increases CTR by 30%+")
        else:
            tips.append("👤 Add a face - thumbnails with faces get 38% more clicks")
        
        # ===== 6. BOLD TEXT STYLE (5 points) =====
        if config.text_style in ["bold_impact", "youtube_style"]:
            score += 5
            passed.append("✅ Bold text style for readability")
        else:
            tips.append("🔤 Use bolder text - must be readable at 120x68 pixels")
        
        # ===== 7. COLOR TEMPERATURE (5 points) =====
        # Check if using attention-grabbing colors (yellow, red, blue)
        dominant_colors = self._get_dominant_colors(img)
        attention_colors = ["red", "yellow", "blue", "orange"]
        if any(c in dominant_colors for c in attention_colors):
            score += 5
            passed.append("✅ Using attention-grabbing colors")
        else:
            tips.append("🔴 Add red, yellow, or blue - proven attention grabbers")
        
        # ===== 8. TEMPLATE QUALITY (5 points) =====
        if config.template in ["mrbeast", "gaming", "bold"]:
            score += 5
            passed.append("✅ Using high-performance template style")
        
        # ===== CATEGORY-SPECIFIC TIPS =====
        if config.category == "gaming":
            tips.append("🎮 TIP: Show intense emotion or epic moment")
        elif config.category == "tech":
            tips.append("💻 TIP: Feature the product prominently")
        elif config.category == "education":
            tips.append("📚 TIP: Use curiosity gap - hint at transformation")
        elif config.category == "entertainment":
            tips.append("🎬 TIP: Exaggerated expressions perform best")
        
        # Compile final tips (show passed items first, then improvements)
        final_tips = passed[:3] + tips[:3]  # Top 3 of each
        
        return min(100, max(0, score)), final_tips
    
    def _calculate_contrast(self, img: Image.Image) -> float:
        """Calculate contrast level of image."""
        gray = img.convert('L')
        pixels = list(gray.getdata())
        
        if not pixels:
            return 0.5
        
        # Standard deviation of pixel values = contrast measure
        mean = sum(pixels) / len(pixels)
        variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
        std_dev = variance ** 0.5
        
        # Normalize to 0-1 range (max std_dev for image is ~127)
        return min(1.0, std_dev / 80.0)
    
    def _get_dominant_colors(self, img: Image.Image) -> List[str]:
        """Get dominant color names from image."""
        # Resize for speed
        small = img.resize((50, 50))
        pixels = list(small.getdata())
        
        # Count color categories
        colors = {"red": 0, "yellow": 0, "blue": 0, "green": 0, "orange": 0, "purple": 0, "neutral": 0}
        
        for r, g, b in pixels:
            # Classify pixel
            if r > 180 and g < 100 and b < 100:
                colors["red"] += 1
            elif r > 180 and g > 180 and b < 100:
                colors["yellow"] += 1
            elif r > 180 and g > 100 and g < 180 and b < 100:
                colors["orange"] += 1
            elif r < 100 and g < 100 and b > 150:
                colors["blue"] += 1
            elif r < 100 and g > 150 and b < 100:
                colors["green"] += 1
            elif r > 100 and g < 100 and b > 150:
                colors["purple"] += 1
            else:
                colors["neutral"] += 1
        
        # Return colors that make up >10% of image
        total = len(pixels)
        dominant = [c for c, count in colors.items() if count / total > 0.1 and c != "neutral"]
        
        return dominant if dominant else ["neutral"]
    
    def _wrap_text(
        self, 
        text: str, 
        font: ImageFont.FreeTypeFont, 
        max_width: int,
        max_lines: int
    ) -> List[str]:
        """Wrap text to fit within width."""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            test_line = " ".join(current_line)
            bbox = font.getbbox(test_line)
            
            if bbox[2] - bbox[0] > max_width:
                if len(current_line) > 1:
                    current_line.pop()
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []
        
        if current_line:
            lines.append(" ".join(current_line))
        
        return lines[:max_lines]
    
    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get or load font."""
        if size in self._font_cache:
            return self._font_cache[size]
        
        # Try to load a bold font
        font_paths = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        
        for path in font_paths:
            if os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, size)
                    self._font_cache[size] = font
                    return font
                except:
                    pass
        
        # Fallback to default
        font = ImageFont.load_default()
        self._font_cache[size] = font
        return font
    
    def _extract_subject(self, title: str) -> str:
        """Extract main subject from title."""
        # Remove common patterns
        import re
        clean = re.sub(r'\[.*?\]|\(.*?\)', '', title)
        clean = re.sub(r'[!?]', '', clean)
        
        # Get main words
        words = clean.split()[:5]
        return " ".join(words)
    
    def _generate_llm_background_prompt(
        self,
        title: str,
        face_position: str = "right",
        # Budget attribution — see HookLab.set_budget_context for the
        # rationale. Defaults route to the anonymous bucket.
        user_id: Optional[int] = None,
        plan: str = "free",
    ) -> str:
        """Use LLM (Claude with Groq fallback) to generate a context-aware background prompt from video title."""
        try:
            from src.features.llm_client import get_llm_client

            llm_client = get_llm_client()
            
            system_prompt = """You are an expert at creating Stable Diffusion prompts for YouTube thumbnail backgrounds.
Your job is to analyze the video title and generate a DRAMATIC, CONTEXTUAL background scene.

=== THUMBNAIL SUCCESS PRINCIPLES (Research-Backed) ===
These are proven factors that make thumbnails get MORE CLICKS:

1. HIGH CONTRAST - Use dramatic lighting with bright highlights and dark shadows
2. BOLD COLORS - Prioritize red, yellow, orange, blue - these grab attention
3. NOT TOO DARK - Background should have bright elements (viewers use dark mode)
4. VISUAL SIMPLICITY - 1-2 key background elements, not cluttered
5. CLEAR FOCAL POINT - Leave space for face on one side, keep other side interesting but not busy
6. EMOTIONAL ATMOSPHERE - Match the emotional tone (exciting, scary, luxurious, epic)

=== RULES ===
1. Background must be RELEVANT to the video topic (not generic)
2. NO people, faces, or human figures - just environment/setting
3. Make it DRAMATIC with bold lighting, colors, and atmosphere
4. Think like a Hollywood set designer for a movie poster
5. Include 1-2 specific visual elements related to the topic
6. Use cinematic lighting (rim lights, spotlights, god rays, lens flares)
7. NEVER include numbers, prices, dollar amounts, text, labels, or signs
8. Always include BRIGHT ACCENT COLORS even in dark scenes (neon, glow, fire, etc.)

=== EXAMPLES ===
- "I Ate the World's Hottest Pepper" → fiery volcanic hellscape, bright orange lava glow, flames and smoke, dramatic red and orange lighting, intense heat atmosphere
- "I Survived 24 Hours in Antarctica" → frozen tundra, glowing aurora borealis (green/purple), dramatic blue ice, bright sky contrast
- "I Gave Away $1,000,000" → golden vault room, bright spotlights on money piles, glowing gold accents, luxury rich aesthetic
- "I Built a Gaming PC" → epic RGB gaming setup, BRIGHT neon purple and cyan glowing lights, colorful LED strips, dark room with vibrant color pops
- "iPhone 15 Pro Review" → sleek tech lab, bright blue holographic glows, dramatic rim lighting, premium aesthetic"""

            user_prompt = f"""Video title: "{title}"

Generate a Stable Diffusion prompt for a dramatic YouTube thumbnail background.
Output ONLY the prompt, nothing else. Keep it under 100 words.
Remember: NO people, just the environment. Make it DRAMATIC and RELEVANT to this specific video."""

            response = llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.7,
                user_id=user_id,
                plan=plan,
                feature="thumbnail_generator.background_prompt",
            )

            if not response.success:
                logger.warning(f"LLM prompt generation failed: {response.error}, using fallback")
                subject = self._extract_subject(title)
                return f"dramatic cinematic background related to {subject}, bold lighting, professional YouTube thumbnail style, no people, empty scene"
            
            logger.info(f"Background prompt generated using {response.provider}/{response.model}")
            prompt = response.text.strip()
            
            # Add technical quality terms and spacing requirement
            space_side = 'left' if face_position == 'right' else 'right'
            prompt += f". Ultra high quality, 8k, cinematic, dramatic lighting, empty scene, space on {space_side} side for subject"
            
            logger.info(f"LLM generated background prompt: {prompt[:100]}...")
            return prompt
            
        except Exception as e:
            logger.warning(f"LLM prompt generation failed: {e}, using fallback")
            # Fallback to basic prompt
            subject = self._extract_subject(title)
            return f"dramatic cinematic background related to {subject}, bold lighting, professional YouTube thumbnail style, no people, empty scene"
    
    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def _apply_text_area_blur(
        self, 
        img: Image.Image, 
        config: ThumbnailConfig
    ) -> Image.Image:
        """Apply subtle blur to text area for readability."""
        # Create a blurred version
        blurred = img.filter(ImageFilter.GaussianBlur(radius=3))
        
        # Create gradient mask
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        
        # Gradient in text area
        text_y = config.height - 200  # Bottom area
        for y in range(text_y, config.height):
            opacity = int(((y - text_y) / 200) * 128)
            draw.line([(0, y), (config.width, y)], fill=opacity)
        
        # Composite
        return Image.composite(blurred, img, mask)
    
    def _calculate_brightness(self, img: Image.Image) -> float:
        """Calculate average brightness."""
        grayscale = img.convert("L")
        histogram = grayscale.histogram()
        pixels = sum(histogram)
        brightness = sum(i * histogram[i] for i in range(256)) / pixels
        return brightness / 255
    
    def _calculate_saturation(self, img: Image.Image) -> float:
        """Calculate average saturation."""
        hsv = img.convert("HSV")
        s_channel = hsv.split()[1]
        histogram = s_channel.histogram()
        pixels = sum(histogram)
        saturation = sum(i * histogram[i] for i in range(256)) / pixels
        return saturation / 255


# Convenience function
def create_thumbnail(
    title: str,
    category: str = "default",
    base_image: Optional[bytes] = None,
    face_image: Optional[bytes] = None,
) -> GeneratedThumbnail:
    """
    Quick function to create a thumbnail.
    
    Args:
        title: Video title
        category: Content category
        base_image: Optional background image
        face_image: Optional face/person cutout
        
    Returns:
        GeneratedThumbnail
    """
    generator = ThumbnailGenerator()
    config = ThumbnailConfig(title=title, category=category)
    return generator.generate(config, base_image, face_image)

