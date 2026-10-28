"""
Animated Captions - Generate stylized, animated captions for videos.

Features:
- Multiple caption styles (CapCut, TikTok, MrBeast, Hormozi, Minimal)
- Word-by-word animations (bounce, pop, glow, karaoke)
- ASS subtitle format with full styling
- FFmpeg command generation for burning captions
- Web preview with CSS animations
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum
import json

import structlog

logger = structlog.get_logger()


class CaptionStyle(Enum):
    """Pre-designed caption style presets."""
    CAPCUT = "capcut"  # Bold, centered, word-by-word pop
    TIKTOK = "tiktok"  # White with black outline, bouncy
    MRBEAST = "mrbeast"  # Big, bold, yellow/white, impactful
    HORMOZI = "hormozi"  # Clean, white, word highlight in color
    MINIMAL = "minimal"  # Simple, elegant, subtle animations
    GAMING = "gaming"  # Neon glow, cyberpunk vibes
    EDUCATIONAL = "educational"  # Clean, readable, key words highlighted


class AnimationType(Enum):
    """Types of word animations."""
    NONE = "none"  # Static text
    POP = "pop"  # Scale up then settle
    BOUNCE = "bounce"  # Bounce in from below
    FADE = "fade"  # Fade in
    TYPEWRITER = "typewriter"  # Letter by letter
    KARAOKE = "karaoke"  # Words highlight as spoken
    GLOW = "glow"  # Glowing effect
    SHAKE = "shake"  # Shake/vibrate for emphasis


@dataclass
class CaptionWord:
    """A single word with timing and styling."""
    text: str
    start_time: float  # seconds
    end_time: float  # seconds
    is_emphasized: bool = False  # Key word to highlight


@dataclass
class CaptionSegment:
    """A segment of caption (usually a sentence or phrase)."""
    text: str
    words: List[CaptionWord]
    start_time: float
    end_time: float


@dataclass
class StyleConfig:
    """Configuration for caption styling."""
    # Font
    font_name: str = "Montserrat"
    font_size: int = 48
    font_weight: str = "Bold"
    
    # Colors (hex)
    primary_color: str = "#FFFFFF"
    secondary_color: str = "#FFFF00"  # For emphasized words
    outline_color: str = "#000000"
    shadow_color: str = "#000000"
    
    # Outline/Shadow
    outline_width: int = 4
    shadow_offset: int = 3
    
    # Position (0-100, from bottom)
    position_y: int = 15
    
    # Animation
    animation: AnimationType = AnimationType.POP
    animation_duration: float = 0.15  # seconds
    
    # Emphasis detection
    emphasize_key_words: bool = True
    emphasis_words: List[str] = field(default_factory=list)


# Pre-defined style presets
STYLE_PRESETS: Dict[CaptionStyle, StyleConfig] = {
    CaptionStyle.CAPCUT: StyleConfig(
        font_name="Montserrat",
        font_size=52,
        font_weight="ExtraBold",
        primary_color="#FFFFFF",
        secondary_color="#00FF00",
        outline_color="#000000",
        outline_width=5,
        shadow_offset=4,
        position_y=18,
        animation=AnimationType.POP,
        animation_duration=0.12,
    ),
    CaptionStyle.TIKTOK: StyleConfig(
        font_name="Proxima Nova",
        font_size=48,
        font_weight="Bold",
        primary_color="#FFFFFF",
        secondary_color="#FF0050",
        outline_color="#000000",
        outline_width=4,
        shadow_offset=2,
        position_y=20,
        animation=AnimationType.BOUNCE,
        animation_duration=0.15,
    ),
    CaptionStyle.MRBEAST: StyleConfig(
        font_name="Impact",
        font_size=72,
        font_weight="Bold",
        primary_color="#FFFF00",
        secondary_color="#FF0000",
        outline_color="#000000",
        outline_width=6,
        shadow_offset=5,
        position_y=15,
        animation=AnimationType.POP,
        animation_duration=0.1,
    ),
    CaptionStyle.HORMOZI: StyleConfig(
        font_name="Helvetica Neue",
        font_size=44,
        font_weight="Bold",
        primary_color="#FFFFFF",
        secondary_color="#FFD700",
        outline_color="#000000",
        outline_width=3,
        shadow_offset=2,
        position_y=22,
        animation=AnimationType.KARAOKE,
        animation_duration=0.0,
    ),
    CaptionStyle.MINIMAL: StyleConfig(
        font_name="Inter",
        font_size=36,
        font_weight="Medium",
        primary_color="#FFFFFF",
        secondary_color="#FFFFFF",
        outline_color="#00000080",
        outline_width=2,
        shadow_offset=1,
        position_y=10,
        animation=AnimationType.FADE,
        animation_duration=0.2,
    ),
    CaptionStyle.GAMING: StyleConfig(
        font_name="Orbitron",
        font_size=48,
        font_weight="Bold",
        primary_color="#00FFFF",
        secondary_color="#FF00FF",
        outline_color="#000000",
        outline_width=4,
        shadow_offset=3,
        position_y=18,
        animation=AnimationType.GLOW,
        animation_duration=0.15,
    ),
    CaptionStyle.EDUCATIONAL: StyleConfig(
        font_name="Source Sans Pro",
        font_size=40,
        font_weight="SemiBold",
        primary_color="#FFFFFF",
        secondary_color="#4CAF50",
        outline_color="#000000",
        outline_width=3,
        shadow_offset=2,
        position_y=12,
        animation=AnimationType.FADE,
        animation_duration=0.25,
    ),
}


class AnimatedCaptionGenerator:
    """
    Generate animated captions from SRT or transcript data.
    
    Supports multiple output formats:
    - ASS (Advanced SubStation Alpha) for FFmpeg
    - HTML/CSS for web preview
    - JSON for custom renderers
    """
    
    def __init__(self, style: CaptionStyle = CaptionStyle.CAPCUT):
        """Initialize with a style preset."""
        self.style_config = STYLE_PRESETS.get(style, STYLE_PRESETS[CaptionStyle.CAPCUT])
        self.current_style = style
        
        # Words that should be emphasized
        self._emphasis_patterns = [
            r'\b(never|always|every|best|worst|only|first|last)\b',
            r'\b(insane|crazy|incredible|amazing|unbelievable)\b',
            r'\b(money|free|secret|hack|trick|tip)\b',
            r'\b(you|your|now|today|stop|start)\b',
            r'\$[\d,]+',  # Dollar amounts
            r'\b\d+%\b',  # Percentages
            r'\b\d+[xX]\b',  # Multipliers
        ]
    
    def set_style(self, style: CaptionStyle):
        """Change the caption style."""
        self.style_config = STYLE_PRESETS.get(style, STYLE_PRESETS[CaptionStyle.CAPCUT])
        self.current_style = style
    
    def set_custom_style(self, config: StyleConfig):
        """Use a custom style configuration."""
        self.style_config = config
        self.current_style = None
    
    def parse_srt(self, srt_content: str) -> List[CaptionSegment]:
        """Parse SRT file content into caption segments."""
        segments = []
        
        # Split by double newline (SRT block separator)
        blocks = re.split(r'\n\n+', srt_content.strip())
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
            
            # Parse timestamp line
            timestamp_match = re.match(
                r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})',
                lines[1]
            )
            
            if not timestamp_match:
                continue
            
            # Convert to seconds
            start_time = (
                int(timestamp_match.group(1)) * 3600 +
                int(timestamp_match.group(2)) * 60 +
                int(timestamp_match.group(3)) +
                int(timestamp_match.group(4)) / 1000
            )
            end_time = (
                int(timestamp_match.group(5)) * 3600 +
                int(timestamp_match.group(6)) * 60 +
                int(timestamp_match.group(7)) +
                int(timestamp_match.group(8)) / 1000
            )
            
            # Get text (may be multiple lines)
            text = ' '.join(lines[2:])
            
            # Create word-level timing
            words = self._create_word_timing(text, start_time, end_time)
            
            segments.append(CaptionSegment(
                text=text,
                words=words,
                start_time=start_time,
                end_time=end_time,
            ))
        
        return segments
    
    def parse_transcript(self, transcript: List[Dict]) -> List[CaptionSegment]:
        """
        Parse transcript with word-level timing.
        
        Expected format: [{"text": "word", "start": 0.0, "end": 0.5}, ...]
        """
        if not transcript:
            return []
        
        segments = []
        current_words = []
        segment_start = transcript[0].get('start', 0)
        
        for i, word_data in enumerate(transcript):
            text = word_data.get('text', '').strip()
            start = word_data.get('start', 0)
            end = word_data.get('end', start + 0.5)
            
            is_emphasized = self._is_emphasis_word(text)
            
            current_words.append(CaptionWord(
                text=text,
                start_time=start,
                end_time=end,
                is_emphasized=is_emphasized,
            ))
            
            # Split segments at punctuation or every ~8 words
            is_sentence_end = text.endswith(('.', '!', '?', ':'))
            is_long_segment = len(current_words) >= 8
            is_last_word = i == len(transcript) - 1
            
            if is_sentence_end or is_long_segment or is_last_word:
                segment_text = ' '.join(w.text for w in current_words)
                segment_end = end
                
                segments.append(CaptionSegment(
                    text=segment_text,
                    words=current_words.copy(),
                    start_time=segment_start,
                    end_time=segment_end,
                ))
                
                current_words = []
                if i < len(transcript) - 1:
                    segment_start = transcript[i + 1].get('start', end)
        
        return segments
    
    def _create_word_timing(
        self,
        text: str,
        start_time: float,
        end_time: float
    ) -> List[CaptionWord]:
        """Create word-level timing from segment timing."""
        words_text = text.split()
        if not words_text:
            return []
        
        duration = end_time - start_time
        word_duration = duration / len(words_text)
        
        words = []
        for i, word_text in enumerate(words_text):
            word_start = start_time + (i * word_duration)
            word_end = word_start + word_duration
            
            words.append(CaptionWord(
                text=word_text,
                start_time=word_start,
                end_time=word_end,
                is_emphasized=self._is_emphasis_word(word_text),
            ))
        
        return words
    
    def _is_emphasis_word(self, word: str) -> bool:
        """Check if a word should be emphasized."""
        if not self.style_config.emphasize_key_words:
            return False
        
        # Check custom emphasis words
        if word.lower() in [w.lower() for w in self.style_config.emphasis_words]:
            return True
        
        # Check patterns
        for pattern in self._emphasis_patterns:
            if re.search(pattern, word, re.IGNORECASE):
                return True
        
        return False
    
    def generate_ass(self, segments: List[CaptionSegment]) -> str:
        """
        Generate ASS (Advanced SubStation Alpha) subtitle file.
        
        ASS supports advanced styling and can be burned into video with FFmpeg.
        """
        config = self.style_config
        
        # Convert hex colors to ASS format (BGR, &HBBGGRR&)
        def hex_to_ass(hex_color: str) -> str:
            hex_color = hex_color.lstrip('#')
            if len(hex_color) == 8:  # Has alpha
                alpha = hex_color[6:8]
                hex_color = hex_color[:6]
            else:
                alpha = "00"
            r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
            return f"&H{alpha}{b}{g}{r}&"
        
        primary_ass = hex_to_ass(config.primary_color)
        secondary_ass = hex_to_ass(config.secondary_color)
        outline_ass = hex_to_ass(config.outline_color)
        shadow_ass = hex_to_ass(config.shadow_color)
        
        # ASS header
        ass_content = f"""[Script Info]
Title: ViewMagnet Animated Captions
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.font_name},{config.font_size},{primary_ass},{secondary_ass},{outline_ass},{shadow_ass},-1,0,0,0,100,100,0,0,1,{config.outline_width},{config.shadow_offset},2,10,10,{config.position_y},1
Style: Emphasis,{config.font_name},{config.font_size},{secondary_ass},{primary_ass},{outline_ass},{shadow_ass},-1,0,0,0,100,100,0,0,1,{config.outline_width},{config.shadow_offset},2,10,10,{config.position_y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        # Generate dialogue lines with animations
        for segment in segments:
            start_str = self._seconds_to_ass_time(segment.start_time)
            end_str = self._seconds_to_ass_time(segment.end_time)
            
            # Build animated text
            if config.animation == AnimationType.KARAOKE:
                # Karaoke style - highlight words as they're spoken
                text_parts = []
                for word in segment.words:
                    word_duration_cs = int((word.end_time - word.start_time) * 100)
                    if word.is_emphasized:
                        text_parts.append(f"{{\\k{word_duration_cs}\\c{secondary_ass}}}{word.text}")
                    else:
                        text_parts.append(f"{{\\k{word_duration_cs}}}{word.text}")
                text = " ".join(text_parts)
            
            elif config.animation == AnimationType.POP:
                # Pop animation using ASS transforms
                text_parts = []
                for i, word in enumerate(segment.words):
                    delay = int(i * config.animation_duration * 1000)
                    if word.is_emphasized:
                        text_parts.append(
                            f"{{\\t({delay},{delay + 100},\\fscx110\\fscy110)\\t({delay + 100},{delay + 200},\\fscx100\\fscy100)\\c{secondary_ass}}}{word.text}"
                        )
                    else:
                        text_parts.append(
                            f"{{\\t({delay},{delay + 100},\\fscx110\\fscy110)\\t({delay + 100},{delay + 200},\\fscx100\\fscy100)}}{word.text}"
                        )
                text = " ".join(text_parts)
            
            elif config.animation == AnimationType.BOUNCE:
                # Bounce from below
                text_parts = []
                for i, word in enumerate(segment.words):
                    delay = int(i * config.animation_duration * 1000)
                    if word.is_emphasized:
                        text_parts.append(
                            f"{{\\move(0,50,0,0,{delay},{delay + 150})\\c{secondary_ass}}}{word.text}"
                        )
                    else:
                        text_parts.append(f"{{\\move(0,30,0,0,{delay},{delay + 150})}}{word.text}")
                text = " ".join(text_parts)
            
            elif config.animation == AnimationType.FADE:
                # Fade in
                fade_ms = int(config.animation_duration * 1000)
                text = f"{{\\fad({fade_ms},0)}}{segment.text}"
            
            elif config.animation == AnimationType.GLOW:
                # Glow effect (using blur)
                text_parts = []
                for word in segment.words:
                    if word.is_emphasized:
                        text_parts.append(f"{{\\blur3\\c{secondary_ass}}}{word.text}{{\\blur0}}")
                    else:
                        text_parts.append(word.text)
                text = " ".join(text_parts)
            
            else:
                # No animation, just text with emphasis
                text_parts = []
                for word in segment.words:
                    if word.is_emphasized:
                        text_parts.append(f"{{\\c{secondary_ass}}}{word.text}{{\\c{primary_ass}}}")
                    else:
                        text_parts.append(word.text)
                text = " ".join(text_parts)
            
            ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n"
        
        return ass_content
    
    def generate_html_preview(self, segments: List[CaptionSegment]) -> str:
        """Generate HTML/CSS preview with animations."""
        config = self.style_config
        
        # CSS animations
        animations_css = """
        @keyframes pop {
            0% { transform: scale(0); opacity: 0; }
            50% { transform: scale(1.2); }
            100% { transform: scale(1); opacity: 1; }
        }
        @keyframes bounce {
            0% { transform: translateY(50px); opacity: 0; }
            60% { transform: translateY(-10px); }
            100% { transform: translateY(0); opacity: 1; }
        }
        @keyframes fade {
            0% { opacity: 0; }
            100% { opacity: 1; }
        }
        @keyframes glow {
            0%, 100% { text-shadow: 0 0 10px currentColor, 0 0 20px currentColor; }
            50% { text-shadow: 0 0 20px currentColor, 0 0 40px currentColor; }
        }
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-5px); }
            75% { transform: translateX(5px); }
        }
        @keyframes typewriter {
            0% { width: 0; }
            100% { width: 100%; }
        }
        """
        
        animation_map = {
            AnimationType.POP: "pop 0.3s ease-out forwards",
            AnimationType.BOUNCE: "bounce 0.4s ease-out forwards",
            AnimationType.FADE: "fade 0.3s ease-out forwards",
            AnimationType.GLOW: "glow 1s ease-in-out infinite",
            AnimationType.SHAKE: "shake 0.5s ease-in-out",
            AnimationType.KARAOKE: "fade 0.2s ease-out forwards",
        }
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Caption Preview</title>
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;800&family=Inter:wght@400;500;600&family=Orbitron:wght@700&display=swap" rel="stylesheet">
    <style>
        {animations_css}
        
        body {{
            margin: 0;
            padding: 0;
            background: #000;
            display: flex;
            justify-content: center;
            align-items: flex-end;
            min-height: 100vh;
            overflow: hidden;
        }}
        
        .caption-container {{
            position: fixed;
            bottom: {config.position_y}%;
            left: 50%;
            transform: translateX(-50%);
            text-align: center;
            max-width: 90%;
        }}
        
        .caption-segment {{
            display: none;
            font-family: '{config.font_name}', sans-serif;
            font-size: {config.font_size}px;
            font-weight: {700 if config.font_weight == 'Bold' else 400};
            color: {config.primary_color};
            text-shadow: 
                -{config.outline_width}px -{config.outline_width}px 0 {config.outline_color},
                {config.outline_width}px -{config.outline_width}px 0 {config.outline_color},
                -{config.outline_width}px {config.outline_width}px 0 {config.outline_color},
                {config.outline_width}px {config.outline_width}px 0 {config.outline_color},
                {config.shadow_offset}px {config.shadow_offset}px 5px rgba(0,0,0,0.5);
        }}
        
        .caption-segment.active {{
            display: block;
        }}
        
        .caption-word {{
            display: inline-block;
            opacity: 0;
            margin: 0 4px;
        }}
        
        .caption-word.visible {{
            animation: {animation_map.get(config.animation, 'fade 0.3s ease-out forwards')};
        }}
        
        .caption-word.emphasis {{
            color: {config.secondary_color};
        }}
        
        .controls {{
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 10px;
        }}
        
        .controls button {{
            padding: 10px 20px;
            font-size: 16px;
            cursor: pointer;
            background: #333;
            color: #fff;
            border: none;
            border-radius: 5px;
        }}
        
        .controls button:hover {{
            background: #555;
        }}
        
        .time-display {{
            color: #fff;
            font-family: monospace;
            font-size: 18px;
            padding: 10px;
        }}
    </style>
</head>
<body>
    <div class="controls">
        <button onclick="play()">▶ Play</button>
        <button onclick="pause()">⏸ Pause</button>
        <button onclick="reset()">⏮ Reset</button>
        <div class="time-display" id="time">0:00</div>
    </div>
    
    <div class="caption-container">
"""
        
        # Add caption segments
        for i, segment in enumerate(segments):
            words_html = []
            for j, word in enumerate(segment.words):
                emphasis_class = 'emphasis' if word.is_emphasized else ''
                delay = j * config.animation_duration
                words_html.append(
                    f'<span class="caption-word {emphasis_class}" '
                    f'data-delay="{delay:.3f}">{word.text}</span>'
                )
            
            html += f"""
        <div class="caption-segment" 
             data-start="{segment.start_time:.3f}" 
             data-end="{segment.end_time:.3f}"
             id="segment-{i}">
            {' '.join(words_html)}
        </div>
"""
        
        html += """
    </div>
    
    <script>
        let currentTime = 0;
        let isPlaying = false;
        let animationFrame = null;
        let lastTimestamp = null;
        
        const segments = document.querySelectorAll('.caption-segment');
        
        function updateCaptions(time) {
            segments.forEach(segment => {
                const start = parseFloat(segment.dataset.start);
                const end = parseFloat(segment.dataset.end);
                
                if (time >= start && time < end) {
                    segment.classList.add('active');
                    
                    // Animate words
                    const words = segment.querySelectorAll('.caption-word');
                    words.forEach(word => {
                        const delay = parseFloat(word.dataset.delay);
                        const wordTime = time - start;
                        
                        if (wordTime >= delay) {
                            word.classList.add('visible');
                        }
                    });
                } else {
                    segment.classList.remove('active');
                    const words = segment.querySelectorAll('.caption-word');
                    words.forEach(word => word.classList.remove('visible'));
                }
            });
            
            // Update time display
            const minutes = Math.floor(time / 60);
            const seconds = Math.floor(time % 60);
            document.getElementById('time').textContent = 
                `${minutes}:${seconds.toString().padStart(2, '0')}`;
        }
        
        function animate(timestamp) {
            if (!lastTimestamp) lastTimestamp = timestamp;
            const delta = (timestamp - lastTimestamp) / 1000;
            lastTimestamp = timestamp;
            
            if (isPlaying) {
                currentTime += delta;
                updateCaptions(currentTime);
            }
            
            animationFrame = requestAnimationFrame(animate);
        }
        
        function play() {
            isPlaying = true;
            lastTimestamp = null;
            if (!animationFrame) {
                animationFrame = requestAnimationFrame(animate);
            }
        }
        
        function pause() {
            isPlaying = false;
        }
        
        function reset() {
            currentTime = 0;
            isPlaying = false;
            updateCaptions(0);
        }
        
        // Start animation loop
        animationFrame = requestAnimationFrame(animate);
    </script>
</body>
</html>
"""
        
        return html
    
    def generate_ffmpeg_command(
        self,
        input_video: str,
        ass_file: str,
        output_video: str,
        video_codec: str = "libx264",
        audio_codec: str = "aac",
    ) -> str:
        """Generate FFmpeg command to burn in captions."""
        
        # Escape paths for shell
        input_escaped = input_video.replace("'", "'\\''")
        ass_escaped = ass_file.replace("'", "'\\''")
        output_escaped = output_video.replace("'", "'\\''")
        
        command = f"""ffmpeg -i '{input_escaped}' \\
  -vf "ass='{ass_escaped}'" \\
  -c:v {video_codec} -preset fast -crf 23 \\
  -c:a {audio_codec} -b:a 128k \\
  '{output_escaped}'"""
        
        return command
    
    def generate_json(self, segments: List[CaptionSegment]) -> str:
        """Export segments as JSON for custom renderers."""
        data = {
            "style": {
                "preset": self.current_style.value if self.current_style else "custom",
                "font_name": self.style_config.font_name,
                "font_size": self.style_config.font_size,
                "primary_color": self.style_config.primary_color,
                "secondary_color": self.style_config.secondary_color,
                "outline_color": self.style_config.outline_color,
                "outline_width": self.style_config.outline_width,
                "animation": self.style_config.animation.value,
                "animation_duration": self.style_config.animation_duration,
            },
            "segments": [
                {
                    "text": seg.text,
                    "start": seg.start_time,
                    "end": seg.end_time,
                    "words": [
                        {
                            "text": word.text,
                            "start": word.start_time,
                            "end": word.end_time,
                            "emphasized": word.is_emphasized,
                        }
                        for word in seg.words
                    ]
                }
                for seg in segments
            ]
        }
        return json.dumps(data, indent=2)
    
    def _seconds_to_ass_time(self, seconds: float) -> str:
        """Convert seconds to ASS timestamp format (H:MM:SS.CC)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centiseconds = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


# ==================== Quick Access Functions ====================

def create_animated_captions(
    srt_content: str,
    style: CaptionStyle = CaptionStyle.CAPCUT,
    output_format: str = "ass"
) -> str:
    """
    Quick function to create animated captions from SRT.
    
    Args:
        srt_content: SRT file content
        style: Caption style preset
        output_format: "ass", "html", or "json"
    
    Returns:
        Formatted caption content
    """
    generator = AnimatedCaptionGenerator(style)
    segments = generator.parse_srt(srt_content)
    
    if output_format == "ass":
        return generator.generate_ass(segments)
    elif output_format == "html":
        return generator.generate_html_preview(segments)
    elif output_format == "json":
        return generator.generate_json(segments)
    else:
        raise ValueError(f"Unknown output format: {output_format}")


def preview_styles(srt_content: str) -> Dict[str, str]:
    """Generate previews for all caption styles."""
    previews = {}
    
    for style in CaptionStyle:
        generator = AnimatedCaptionGenerator(style)
        segments = generator.parse_srt(srt_content)
        previews[style.value] = generator.generate_html_preview(segments)
    
    return previews









